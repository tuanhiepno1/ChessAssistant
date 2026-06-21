from __future__ import annotations

import unittest

import chess

from chess_tools.fen_builder import SquarePiece
from chess_tools.position_reconciler import PositionReconciler


PIECE_NAMES = {
    "P": "white_pawn",
    "N": "white_knight",
    "B": "white_bishop",
    "R": "white_rook",
    "Q": "white_queen",
    "K": "white_king",
    "p": "black_pawn",
    "n": "black_knight",
    "b": "black_bishop",
    "r": "black_rook",
    "q": "black_queen",
    "k": "black_king",
}


def snapshot(board: chess.Board) -> list[SquarePiece]:
    return [
        SquarePiece(square, PIECE_NAMES[piece.symbol()])
        for square, piece in board.piece_map().items()
    ]


class PositionReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reconciler = PositionReconciler()

    def test_initial_position_overrides_bad_turn_hint_and_keeps_castling(self) -> None:
        board = chess.Board()
        result = self.reconciler.reconcile(snapshot(board), turn_hint=chess.BLACK)

        self.assertEqual(result.fen, board.fen())

    def test_one_ply_transition_determines_turn_and_preserves_ep(self) -> None:
        previous = chess.Board()
        for move in ("e2e4", "a7a6", "e4e5"):
            previous.push_uci(move)
        observed = previous.copy()
        observed.push_uci("d7d5")

        result = self.reconciler.reconcile(
            snapshot(observed),
            last_fen=previous.fen(),
            turn_hint=chess.BLACK,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.plies_advanced, 1)
        reconciled = chess.Board(result.fen)
        self.assertEqual(reconciled.turn, chess.WHITE)
        self.assertEqual(reconciled.ep_square, chess.D6)

    def test_two_ply_transition_recovers_a_missed_scan(self) -> None:
        previous = chess.Board()
        observed = previous.copy()
        observed.push_uci("e2e4")
        observed.push_uci("e7e5")

        result = self.reconciler.reconcile(
            snapshot(observed),
            last_fen=previous.fen(),
            turn_hint=chess.BLACK,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.plies_advanced, 2)
        self.assertEqual(chess.Board(result.fen).turn, chess.WHITE)

    def test_impossible_snapshot_is_rejected_without_changing_fen(self) -> None:
        previous = chess.Board()
        previous.push_uci("e2e4")
        impossible = previous.copy()
        impossible.remove_piece_at(chess.A2)

        result = self.reconciler.reconcile(
            snapshot(impossible),
            last_fen=previous.fen(),
            turn_hint=chess.WHITE,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.fen, previous.fen())

    def test_unchanged_snapshot_keeps_confirmed_turn(self) -> None:
        previous = chess.Board()
        previous.push_uci("e2e4")

        result = self.reconciler.reconcile(
            snapshot(previous),
            last_fen=previous.fen(),
            turn_hint=chess.WHITE,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.plies_advanced, 0)
        self.assertEqual(result.fen, previous.fen())

    def test_reliable_snapshot_resyncs_after_more_than_two_missed_plies(self) -> None:
        previous = chess.Board()
        observed = previous.copy()
        for move in ("e2e4", "e7e5", "g1f3", "b8c6"):
            observed.push_uci(move)

        result = self.reconciler.reconcile(
            snapshot(observed),
            last_fen=previous.fen(),
            turn_hint=chess.WHITE,
            allow_resync=True,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.plies_advanced, -1)
        reconciled = chess.Board(result.fen)
        self.assertEqual(reconciled.board_fen(), observed.board_fen())
        self.assertEqual(reconciled.turn, chess.WHITE)
        self.assertEqual(reconciled.castling_rights, chess.BB_EMPTY)

    def test_resync_recovers_turn_from_black_piece_move_when_clock_hint_is_wrong(self) -> None:
        previous = chess.Board()
        previous.push_uci("e2e4")
        # Simulate a stale resync that incorrectly says White is still to move.
        previous.turn = chess.WHITE
        observed = previous.copy(stack=False)
        observed.remove_piece_at(chess.E7)
        observed.set_piece_at(chess.E5, chess.Piece(chess.PAWN, chess.BLACK))

        result = self.reconciler.reconcile(
            snapshot(observed),
            last_fen=previous.fen(),
            turn_hint=chess.BLACK,
            allow_resync=True,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.plies_advanced, -1)
        self.assertEqual(chess.Board(result.fen).turn, chess.WHITE)

    def test_delta_turn_inference_supports_capture(self) -> None:
        previous = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 b - - 0 1")
        observed = previous.copy(stack=False)
        observed.remove_piece_at(chess.D5)
        observed.remove_piece_at(chess.E4)
        observed.set_piece_at(chess.E4, chess.Piece(chess.PAWN, chess.BLACK))

        self.assertEqual(
            self.reconciler._infer_turn_from_delta(previous, observed),
            chess.WHITE,
        )

    def test_lichess_animation_piece_is_removed_by_unique_legal_history(self) -> None:
        previous = chess.Board()
        actual = previous.copy()
        actual.push_uci("e2e4")
        with_ghost = actual.copy(stack=False)
        # Lichess can retain the animated source piece while the real piece is
        # already rendered at its destination.
        with_ghost.set_piece_at(chess.E2, chess.Piece(chess.PAWN, chess.WHITE))

        result = self.reconciler.reconcile(
            snapshot(with_ghost),
            last_fen=previous.fen(),
            turn_hint=chess.WHITE,
            allow_resync=True,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.fen, actual.fen())
        self.assertIn("animation", result.status)

    def test_unrepairable_piece_count_increase_cannot_replace_tracked_game(self) -> None:
        previous = chess.Board("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")
        wrong_board = chess.Board("4k3/8/8/8/8/3P4/3PP3/4K3 w - - 0 1")

        result = self.reconciler.reconcile(
            snapshot(wrong_board),
            last_fen=previous.fen(),
            turn_hint=chess.WHITE,
            allow_resync=True,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.fen, previous.fen())

    def test_chessclub_can_resync_after_render_adds_missing_pieces(self) -> None:
        previous = chess.Board("4k3/8/8/8/8/8/P7/4K3 w - - 0 1")
        observed = chess.Board("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1")

        result = self.reconciler.reconcile(
            snapshot(observed),
            last_fen=previous.fen(),
            turn_hint=chess.WHITE,
            source="ChessClub",
            allow_resync=True,
            allow_piece_increase_resync=True,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(chess.Board(result.fen).board_fen(), observed.board_fen())
        self.assertEqual(chess.Board(result.fen).turn, chess.WHITE)

    def test_rematch_is_detected_after_white_already_played_first_move(self) -> None:
        previous = chess.Board("8/8/8/8/8/4k3/8/4K3 w - - 0 70")
        observed = chess.Board()
        observed.push_uci("e2e4")

        result = self.reconciler.reconcile(
            snapshot(observed),
            last_fen=previous.fen(),
            turn_hint=chess.BLACK,
            source="ChessClub",
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.fen, observed.fen())
        self.assertEqual(chess.Board(result.fen).turn, chess.BLACK)
        self.assertIn("rematch", result.status)


if __name__ == "__main__":
    unittest.main()
