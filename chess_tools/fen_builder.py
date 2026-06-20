from __future__ import annotations

from dataclasses import dataclass

import chess


PIECE_TO_SYMBOL = {
    "white_pawn": "P",
    "white_knight": "N",
    "white_bishop": "B",
    "white_rook": "R",
    "white_queen": "Q",
    "white_king": "K",
    "black_pawn": "p",
    "black_knight": "n",
    "black_bishop": "b",
    "black_rook": "r",
    "black_queen": "q",
    "black_king": "k",
}

LABEL_ALIASES = {
    "wp": "white_pawn",
    "wn": "white_knight",
    "wb": "white_bishop",
    "wr": "white_rook",
    "wq": "white_queen",
    "wk": "white_king",
    "bp": "black_pawn",
    "bn": "black_knight",
    "bb": "black_bishop",
    "br": "black_rook",
    "bq": "black_queen",
    "bk": "black_king",
    "white-pawn": "white_pawn",
    "white-knight": "white_knight",
    "white-bishop": "white_bishop",
    "white-rook": "white_rook",
    "white-queen": "white_queen",
    "white-king": "white_king",
    "black-pawn": "black_pawn",
    "black-knight": "black_knight",
    "black-bishop": "black_bishop",
    "black-rook": "black_rook",
    "black-queen": "black_queen",
    "black-king": "black_king",
}


@dataclass(frozen=True)
class SquarePiece:
    square_index: int
    label: str


class FenBuilder:
    def build(
        self,
        pieces: list[SquarePiece],
        side_to_move: chess.Color = chess.WHITE,
        castling: str = "-",
        ep_square: str = "-",
        halfmove_clock: int = 0,
        fullmove_number: int = 1,
    ) -> str:
        board = chess.Board.empty()
        for detected in pieces:
            label = normalize_piece_label(detected.label)
            if label is None:
                continue
            try:
                symbol = PIECE_TO_SYMBOL[label]
            except KeyError as exc:
                expected = ", ".join(sorted(PIECE_TO_SYMBOL))
                raise ValueError(
                    f"Nhận diện trả về nhãn quân cờ không được hỗ trợ: {detected.label}. "
                    f"Cac nhan can co: {expected}"
                ) from exc
            board.set_piece_at(detected.square_index, chess.Piece.from_symbol(symbol))

        board.turn = side_to_move
        board.castling_rights = self._parse_castling(castling)
        board.ep_square = None if ep_square == "-" else chess.parse_square(ep_square)
        board.halfmove_clock = halfmove_clock
        board.fullmove_number = fullmove_number
        return board.fen()

    @staticmethod
    def _parse_castling(castling: str) -> int:
        if castling == "-":
            return 0
        rights = 0
        if "K" in castling:
            rights |= chess.BB_H1
        if "Q" in castling:
            rights |= chess.BB_A1
        if "k" in castling:
            rights |= chess.BB_H8
        if "q" in castling:
            rights |= chess.BB_A8
        return rights


def normalize_piece_label(label: str) -> str | None:
    clean = label.strip().lower().replace(" ", "_")
    if clean in {"board", "chessboard", "empty", "blank", "none"}:
        return None
    if clean in PIECE_TO_SYMBOL:
        return clean
    compact = clean.replace("_", "").replace("-", "")
    return LABEL_ALIASES.get(clean) or LABEL_ALIASES.get(compact)
