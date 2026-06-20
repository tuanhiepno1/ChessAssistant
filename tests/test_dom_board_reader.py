from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import chess

from vision.dom_board_reader import DomBoardReader, DomUnavailableError
from ui.main_window import RealtimeWorker


class FakeResponse:
    def __init__(self, pages: list[dict]) -> None:
        self._payload = json.dumps(pages).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class DomBoardReaderPageSelectionTests(unittest.TestCase):
    def _reader_url(self, pages: list[dict], preferred_site: str) -> str:
        with patch("vision.dom_board_reader.urlopen", return_value=FakeResponse(pages)):
            return str(DomBoardReader(preferred_site=preferred_site)._find_chess_page()["url"])

    def _target_reader_url(self, pages: list[dict], target_id: str) -> str:
        with patch("vision.dom_board_reader.urlopen", return_value=FakeResponse(pages)):
            return str(
                DomBoardReader(preferred_site="lichess", target_id=target_id)
                ._find_chess_page()["url"]
            )

    def test_explicit_chesscom_preference_does_not_jump_to_lichess(self) -> None:
        pages = [
            {"type": "page", "url": "https://lichess.org/analysis", "title": "Phân tích bàn cờ • lichess.org"},
            {"type": "page", "url": "chrome-extension://example/offscreen.html", "title": "extension"},
            {"type": "page", "url": "about:blank", "title": "blank"},
            {"type": "page", "url": "https://www.chess.com/play/computer", "title": "Play Chess Online Against the Computer - Chess.com"},
        ]

        selected = self._reader_url(pages, preferred_site="chess.com")

        self.assertEqual(selected, "https://www.chess.com/play/computer")

    def test_preferred_site_still_wins_when_pages_have_similar_recency(self) -> None:
        pages = [
            {"type": "page", "url": "https://www.chess.com/play/computer", "title": "Play Chess Online Against the Computer - Chess.com"},
            {"type": "page", "url": "https://lichess.org/analysis", "title": "Phân tích bàn cờ • lichess.org"},
        ]

        selected = self._reader_url(pages, preferred_site="lichess")

        self.assertEqual(selected, "https://lichess.org/analysis")

    def test_explicit_lichess_preference_wins_even_when_tab_is_old(self) -> None:
        pages = [
            {"type": "page", "url": "https://www.chess.com/play/computer", "title": "Chess.com"},
            {"type": "page", "url": "about:blank", "title": "blank"},
            {"type": "page", "url": "about:blank", "title": "blank"},
            {"type": "page", "url": "about:blank", "title": "blank"},
            {"type": "page", "url": "https://lichess.org/abcdefgh", "title": "Game"},
        ]

        selected = self._reader_url(pages, preferred_site="lichess")

        self.assertEqual(selected, "https://lichess.org/abcdefgh")

    def test_explicit_lichess_never_falls_back_to_chesscom(self) -> None:
        pages = [
            {"type": "page", "url": "https://www.chess.com/play/computer", "title": "Chess.com"},
        ]

        with self.assertRaises(DomUnavailableError):
            self._reader_url(pages, preferred_site="lichess")

    def test_browser_target_id_keeps_reader_on_the_opened_lichess_tab(self) -> None:
        pages = [
            {"id": "old", "type": "page", "url": "https://lichess.org/oldgame1", "title": "Old"},
            {"id": "current", "type": "page", "url": "https://lichess.org/newgame2", "title": "Current"},
        ]

        selected = self._target_reader_url(pages, target_id="current")

        self.assertEqual(selected, "https://lichess.org/newgame2")

    def test_auto_prefers_current_lichess_game_over_older_chesscom_tab(self) -> None:
        pages = [
            {"type": "page", "url": "https://lichess.org/abcdefgh", "title": "Anonymous vs Anonymous"},
            {"type": "page", "url": "https://www.chess.com/play/online", "title": "Play Chess Online - Chess.com"},
        ]

        selected = self._reader_url(pages, preferred_site="auto")

        self.assertEqual(selected, "https://lichess.org/abcdefgh")

    def test_chessbase_play_tab_is_supported(self) -> None:
        pages = [
            {"type": "page", "url": "https://play.chessbase.com/en/Play", "title": "Play chess online"},
            {"type": "page", "url": "https://lichess.org/analysis", "title": "Phân tích bàn cờ • lichess.org"},
        ]

        selected = self._reader_url(pages, preferred_site="chessbase")

        self.assertEqual(selected, "https://play.chessbase.com/en/Play")

    def test_chessclub_play_tab_is_supported(self) -> None:
        pages = [
            {"type": "page", "url": "https://play.chessclub.com/", "title": "ICC Play Area"},
            {"type": "page", "url": "https://www.chess.com/play/online", "title": "Play Chess Online - Chess.com"},
        ]

        selected = self._reader_url(pages, preferred_site="chessclub")

        self.assertEqual(selected, "https://play.chessclub.com/")


class DomBoardReaderTurnTests(unittest.TestCase):
    def test_bottom_clock_respects_white_orientation(self) -> None:
        turn, reliable, _ = DomBoardReader._resolve_turn(
            {"activeClockPosition": "bottom", "blackAtBottom": False}, 0
        )
        self.assertEqual(turn, chess.WHITE)
        self.assertTrue(reliable)

    def test_bottom_clock_respects_black_orientation(self) -> None:
        turn, reliable, _ = DomBoardReader._resolve_turn(
            {"activeClockPosition": "bottom", "blackAtBottom": True}, 0
        )
        self.assertEqual(turn, chess.BLACK)
        self.assertTrue(reliable)

    def test_internal_fen_wins_over_stale_clock_class(self) -> None:
        turn, reliable, source = DomBoardReader._resolve_turn(
            {
                "turnFromFen": "black",
                "activeClockPosition": "bottom",
                "blackAtBottom": False,
            },
            0,
        )
        self.assertEqual(turn, chess.BLACK)
        self.assertTrue(reliable)
        self.assertEqual(source, "FEN nội bộ trang")

    def test_lichess_last_move_wins_over_stale_clock(self) -> None:
        turn, reliable, source = DomBoardReader._resolve_turn(
            {
                "turnFromLastMove": "white",
                "activeClockPosition": "top",
                "blackAtBottom": False,
            },
            7,
        )
        self.assertEqual(turn, chess.WHITE)
        self.assertTrue(reliable)
        self.assertEqual(source, "ô nước đi cuối")

    def test_move_parity_is_explicitly_unreliable_fallback(self) -> None:
        turn, reliable, _ = DomBoardReader._resolve_turn({}, 3)
        self.assertEqual(turn, chess.BLACK)
        self.assertFalse(reliable)

    def test_lichess_san_history_produces_exact_fen_only_when_board_matches(self) -> None:
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "Bc5", "c3", "Nf6", "d4", "exd4"):
            board.push_san(san)

        fen = DomBoardReader._moves_to_exact_fen(
            ["e4", "e5", "Nf3", "Nc6", "Bb5", "Bc5", "c3", "Nf6", "d4", "exd4"],
            board,
        )

        self.assertEqual(fen, board.fen())

    def test_lichess_san_history_is_rejected_when_dom_board_differs(self) -> None:
        observed = chess.Board()
        observed.push_san("d4")

        self.assertIsNone(DomBoardReader._moves_to_exact_fen(["e4"], observed))

    def test_numbered_and_figurine_san_from_other_sites_is_supported(self) -> None:
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6"):
            board.push_san(san)

        fen = DomBoardReader._moves_to_exact_fen(
            ["1. e4 e5", "2. ♘f3 ♞c6"],
            board,
        )

        self.assertEqual(fen, board.fen())

    def test_chessbase_internal_fen_must_match_dom_pieces(self) -> None:
        board = chess.Board()
        board.push_san("e4")

        self.assertEqual(
            DomBoardReader._validated_internal_fen(board.fen(), board),
            board.fen(),
        )
        self.assertIsNone(
            DomBoardReader._validated_internal_fen(chess.Board().fen(), board)
        )


class RealtimeWorkerSchedulingTests(unittest.TestCase):
    def test_reanalyzes_same_observed_fen_when_previous_result_was_discarded(self) -> None:
        self.assertTrue(
            RealtimeWorker._should_analyze("fen-new", "fen-new", False, False)
        )

    def test_skips_same_fen_only_when_it_already_has_a_result(self) -> None:
        self.assertFalse(
            RealtimeWorker._should_analyze("fen-done", "fen-done", True, False)
        )

    def test_force_refresh_always_analyzes(self) -> None:
        self.assertTrue(
            RealtimeWorker._should_analyze("fen-done", "fen-done", True, True)
        )


class ChessBaseOverlayTests(unittest.TestCase):
    def test_chessbase_overlay_uses_native_board_coordinates(self) -> None:
        script = DomBoardReader._chessbase_native_overlay_script("a1", "h8")

        self.assertIn("boardWin.markSquare", script)
        self.assertIn("boardWin.drawArrow", script)
        self.assertIn("(Number(square[1]) - 1) * 8", script)


if __name__ == "__main__":
    unittest.main()
