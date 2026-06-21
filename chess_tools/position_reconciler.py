from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_tools.fen_builder import FenBuilder, SquarePiece


@dataclass(frozen=True)
class ReconciledPosition:
    fen: str
    accepted: bool
    plies_advanced: int
    status: str


class PositionReconciler:
    """Turns a piece snapshot into a position that is consistent with game history."""

    def reconcile(
        self,
        pieces: list[SquarePiece],
        last_fen: str = "",
        turn_hint: chess.Color = chess.WHITE,
        source: str = "Nhận diện",
        max_plies: int = 2,
        allow_resync: bool = False,
        allow_piece_increase_resync: bool = False,
    ) -> ReconciledPosition:
        observed = chess.Board(FenBuilder().build(pieces, side_to_move=turn_hint))
        self._require_kings(observed, source)

        if last_fen:
            previous = chess.Board(last_fen)
            if observed.board_fen() == previous.board_fen():
                return ReconciledPosition(
                    fen=previous.fen(),
                    accepted=True,
                    plies_advanced=0,
                    status=f"{source}: thế cờ không đổi; giữ nguyên lượt đã xác nhận.",
                )

            restarted = self._find_new_game_position(previous, observed)
            if restarted is not None:
                return ReconciledPosition(
                    fen=restarted.fen(),
                    accepted=True,
                    plies_advanced=0,
                    status=(
                        f"{source}: phát hiện ván/rematch mới và dựng lại lịch sử "
                        "từ thế cờ ban đầu."
                    ),
                )

            matched = self._find_successor(previous, observed.board_fen(), max_plies=max_plies)
            if matched is not None:
                board, plies, moves = matched
                move_text = " ".join(move.uci() for move in moves)
                skipped = " (đã bắt kịp 2 nửa-nước)" if plies == 2 else ""
                return ReconciledPosition(
                    fen=board.fen(),
                    accepted=True,
                    plies_advanced=plies,
                    status=f"{source}: xác nhận chuỗi nước hợp lệ {move_text}{skipped}.",
                )

            repaired = self._find_successor_without_one_extra_piece(
                previous,
                observed,
                # Ghost recovery is a hot realtime path. One or two missed
                # plies covers animation without a combinatorial 3-ply scan
                # for every possible extra square.
                max_plies=min(max_plies, 2),
            )
            if repaired is not None:
                board, plies, moves, removed_square = repaired
                move_text = " ".join(move.uci() for move in moves)
                return ReconciledPosition(
                    fen=board.fen(),
                    accepted=True,
                    plies_advanced=plies,
                    status=(
                        f"{source}: bỏ quân DOM animation tại {chess.square_name(removed_square)}; "
                        f"xác nhận chuỗi nước hợp lệ {move_text}."
                    ),
                )

            if (
                len(observed.piece_map()) > len(previous.piece_map())
                and not allow_piece_increase_resync
            ):
                return ReconciledPosition(
                    fen=previous.fen(),
                    accepted=False,
                    plies_advanced=0,
                    status=(
                        f"{source}: số quân tăng từ {len(previous.piece_map())} lên "
                        f"{len(observed.piece_map())} nhưng không tìm được quân animation duy nhất; "
                        "đã giữ FEN trước."
                    ),
                )

            initial = chess.Board()
            if observed.board_fen() == initial.board_fen():
                return ReconciledPosition(
                    fen=initial.fen(),
                    accepted=True,
                    plies_advanced=0,
                    status=f"{source}: phát hiện ván mới và đặt lại lịch sử về thế cờ ban đầu.",
                )

            if allow_resync:
                resynced = observed.copy(stack=False)
                inferred_turn = self._infer_turn_from_delta(previous, observed)
                resynced.turn = inferred_turn if inferred_turn is not None else turn_hint
                resynced.castling_rights = chess.BB_EMPTY
                resynced.ep_square = None
                resynced.halfmove_clock = 0
                resynced.fullmove_number = max(1, previous.fullmove_number)
                if resynced.is_valid():
                    return ReconciledPosition(
                        fen=resynced.fen(),
                        accepted=True,
                        plies_advanced=-1,
                        status=(
                            f"{source}: đã bỏ lỡ nhiều hơn {max_plies} nửa-nước; "
                            "đã tự đồng bộ lại từ bàn cờ ổn định và màu quân vừa di chuyển."
                        ),
                    )

            return ReconciledPosition(
                fen=previous.fen(),
                accepted=False,
                plies_advanced=0,
                status=(
                    f"{source}: ảnh/DOM mới không nối tiếp thế cờ trước trong {max_plies} nửa-nước; "
                    "đã bỏ qua để tránh lệch FEN/lượt."
                ),
            )

        board = self._choose_initial_turn(observed, turn_hint)
        initial = chess.Board()
        if board.board_fen() == initial.board_fen():
            board = initial
        return ReconciledPosition(
            fen=board.fen(),
            accepted=True,
            plies_advanced=0,
            status=f"{source}: khởi tạo thế cờ, lượt {'Trắng' if board.turn else 'Đen'}.",
        )

    @staticmethod
    def _require_kings(board: chess.Board, source: str) -> None:
        if board.king(chess.WHITE) is None or board.king(chess.BLACK) is None:
            raise RuntimeError(f"{source} chưa đọc đủ hai vua.")

    @staticmethod
    def _choose_initial_turn(board: chess.Board, turn_hint: chess.Color) -> chess.Board:
        candidates: list[chess.Board] = []
        for turn in (turn_hint, not turn_hint):
            candidate = board.copy(stack=False)
            candidate.turn = turn
            if candidate.is_valid():
                candidates.append(candidate)
        if not candidates:
            raise RuntimeError("Thế cờ nhận diện không hợp lệ với cả hai lượt đi.")
        return candidates[0]

    @staticmethod
    def _find_successor(
        previous: chess.Board,
        target_board_fen: str,
        max_plies: int,
    ) -> tuple[chess.Board, int, list[chess.Move]] | None:
        frontier: list[tuple[chess.Board, list[chess.Move]]] = [(previous.copy(stack=False), [])]
        for depth in range(1, max(1, max_plies) + 1):
            next_frontier: list[tuple[chess.Board, list[chess.Move]]] = []
            matches: list[tuple[chess.Board, list[chess.Move]]] = []
            for board, path in frontier:
                for move in board.legal_moves:
                    candidate = board.copy(stack=False)
                    candidate.push(move)
                    candidate_path = [*path, move]
                    if candidate.board_fen() == target_board_fen:
                        matches.append((candidate, candidate_path))
                    elif depth < max_plies:
                        next_frontier.append((candidate, candidate_path))
            if matches:
                unique = {match[0].fen(): match for match in matches}
                if len(unique) == 1:
                    board, path = next(iter(unique.values()))
                    return board, depth, path
                return None
            frontier = next_frontier
        return None

    @classmethod
    def _find_successor_without_one_extra_piece(
        cls,
        previous: chess.Board,
        observed: chess.Board,
        max_plies: int,
    ) -> tuple[chess.Board, int, list[chess.Move], chess.Square] | None:
        """Remove one DOM ghost only when it yields one unique legal history."""
        matches: dict[str, tuple[chess.Board, int, list[chess.Move], chess.Square]] = {}
        for square, piece in observed.piece_map().items():
            if piece.piece_type == chess.KING:
                continue
            candidate = observed.copy(stack=False)
            candidate.remove_piece_at(square)
            matched = cls._find_successor(
                previous,
                candidate.board_fen(),
                max_plies=max_plies,
            )
            if matched is None:
                continue
            board, plies, moves = matched
            matches[board.fen()] = (board, plies, moves, square)
        if len(matches) != 1:
            return None
        return next(iter(matches.values()))

    @classmethod
    def _find_new_game_position(
        cls,
        previous: chess.Board,
        observed: chess.Board,
    ) -> chess.Board | None:
        """Recognize a rematch even when one or two opening plies were missed."""
        previous_count = len(previous.piece_map())
        observed_count = len(observed.piece_map())
        if not previous.is_game_over() and observed_count <= previous_count:
            return None
        if observed_count < 31:
            return None

        initial = chess.Board()
        if observed.board_fen() == initial.board_fen():
            return initial
        matched = cls._find_successor(initial, observed.board_fen(), max_plies=2)
        return matched[0] if matched is not None else None

    @staticmethod
    def _infer_turn_from_delta(
        previous: chess.Board,
        observed: chess.Board,
    ) -> chess.Color | None:
        """Infer the next turn from the colour that physically moved.

        This deliberately ignores previous.turn, clock CSS and move-list DOM.
        It covers normal moves, captures, en-passant, promotion and castling.
        """
        changed = [
            square
            for square in chess.SQUARES
            if previous.piece_at(square) != observed.piece_at(square)
        ]
        if not 2 <= len(changed) <= 4:
            return None

        possible_movers: list[chess.Color] = []
        for color in (chess.WHITE, chess.BLACK):
            sources = [
                square
                for square in changed
                if (piece := previous.piece_at(square)) is not None
                and piece.color == color
                and observed.piece_at(square) != piece
            ]
            destinations = [
                square
                for square in changed
                if (piece := observed.piece_at(square)) is not None
                and piece.color == color
                and previous.piece_at(square) != piece
            ]
            if sources and destinations:
                possible_movers.append(color)

        if len(possible_movers) != 1:
            return None
        return not possible_movers[0]
