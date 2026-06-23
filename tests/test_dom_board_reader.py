from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import Mock, patch

import chess

from vision.dom_board_reader import DomBoardReader, DomUnavailableError
from chess_tools.fen_builder import SquarePiece
from engine.stockfish import EngineLine
from ui.main_window import MainWindow, RealtimeWorker


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

    def test_missing_preferred_site_uses_available_supported_tab(self) -> None:
        pages = [
            {"type": "page", "url": "https://www.chess.com/play/computer", "title": "Chess.com"},
        ]

        selected = self._reader_url(pages, preferred_site="lichess")

        self.assertEqual(selected, "https://www.chess.com/play/computer")

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
    def test_reader_scores_main_board_and_scopes_chesscom_pieces_to_it(self) -> None:
        source = DomBoardReader.read.__code__.co_consts
        script = next(
            value
            for value in source
            if isinstance(value, str) and "const findBoard = () =>" in value
        )

        self.assertIn("const scoreBoard = (el) =>", script)
        self.assertIn("mini-board|miniboard|thumbnail|preview", script)
        self.assertIn("boardEl.querySelectorAll('.piece')", script)
        self.assertIn("side < 140", script)

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

    def test_consecutive_equal_castling_san_is_not_collapsed(self) -> None:
        moves = ["e4", "e5", "Nf3", "Nf6", "Bc4", "Bc5", "O-O", "O-O"]
        board = chess.Board()
        for san in moves:
            board.push_san(san)

        self.assertEqual(
            DomBoardReader._moves_to_exact_fen(moves, board),
            board.fen(),
        )

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

    def test_lichess_unicode_annotation_is_removed_from_san(self) -> None:
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"):
            board.push_san(san)

        fen = DomBoardReader._moves_to_exact_fen(
            ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6½?"],
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
    def test_chesscom_and_lichess_request_four_candidate_moves(self) -> None:
        self.assertEqual(RealtimeWorker._site_multipv("chess.com"), 4)
        self.assertEqual(RealtimeWorker._site_multipv("chesscom"), 4)
        self.assertEqual(RealtimeWorker._site_multipv("lichess"), 4)
        self.assertEqual(RealtimeWorker._site_multipv("chessbase"), 1)
        self.assertEqual(RealtimeWorker._site_multipv("lichess", 2), 2)
        self.assertEqual(RealtimeWorker._site_multipv("chess.com", 1), 1)

    def test_dom_monitor_interrupts_analysis_when_board_changes(self) -> None:
        cancelled = threading.Event()
        manager = Mock()
        manager.cancel_analysis.side_effect = cancelled.set
        expected = object()

        def analyze(*_args: object, **_kwargs: object) -> object:
            self.assertTrue(cancelled.wait(1.0))
            return expected

        manager.analyze_fen.side_effect = analyze
        reader = Mock()
        reader.read.return_value = Mock(
            pieces=[SquarePiece(chess.E4, "white_pawn")]
        )
        worker = RealtimeWorker(
            config=Mock(),
            engine_manager=manager,
            tracker=Mock(),
            template_recognizer=Mock(),
            side_to_move=chess.WHITE,
            last_fen="",
        )

        result, changed = worker._analyze_with_dom_monitor(
            chess.STARTING_FEN,
            reader,
            initial_signature=(),
        )

        self.assertIs(result, expected)
        self.assertTrue(changed)
        manager.cancel_analysis.assert_called_once_with()

    def test_image_fallback_status_explains_dom_failure(self) -> None:
        status = RealtimeWorker._image_status(
            "YOLO đọc 30 quân.",
            "Chưa tìm thấy trang cờ vua.",
        )

        self.assertIn("Fallback hình ảnh vì DOM", status)
        self.assertIn("Chưa tìm thấy trang cờ vua", status)

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

    def test_unreliable_turn_uses_selected_color_after_rematch(self) -> None:
        self.assertEqual(
            RealtimeWorker._turn_hint(chess.WHITE, False, chess.BLACK),
            chess.BLACK,
        )

    def test_verified_turn_can_override_selected_color(self) -> None:
        self.assertEqual(
            RealtimeWorker._turn_hint(chess.WHITE, True, chess.BLACK),
            chess.WHITE,
        )

    def test_force_refresh_uses_deep_non_realtime_analysis(self) -> None:
        manager = Mock()
        expected = object()
        manager.analyze_fen.return_value = expected
        worker = RealtimeWorker(
            config=Mock(),
            engine_manager=manager,
            tracker=Mock(),
            template_recognizer=Mock(),
            side_to_move=chess.WHITE,
            last_fen="",
            force_analysis=True,
        )

        result = worker._analyze(chess.STARTING_FEN)

        self.assertIs(result, expected)
        manager.analyze_fen.assert_called_once_with(
            chess.STARTING_FEN,
            force=True,
            realtime=False,
            multipv_override=1,
        )

    def test_ui_keeps_best_move_when_polling_the_same_position(self) -> None:
        self.assertEqual(
            MainWindow._retained_board_move("same-fen", "same-fen", "e2e4"),
            "e2e4",
        )

    def test_ui_drops_stale_best_move_after_position_changes(self) -> None:
        self.assertEqual(
            MainWindow._retained_board_move("old-fen", "new-fen", "e2e4"),
            "",
        )


class CandidateRoleTests(unittest.TestCase):
    @staticmethod
    def _line(move: str, score_cp: int) -> EngineLine:
        return EngineLine(
            move_uci=move,
            move_san=move,
            score=f"{score_cp / 100:+.2f}",
            depth=18,
            seldepth=22,
            nodes=1000,
            tbhits=0,
            hashfull=1,
            pv=[move],
            score_cp=score_cp,
        )

    def test_natural_central_move_can_be_the_human_choice(self) -> None:
        lines = [self._line("a2a4", 30), self._line("e2e4", 15)]

        selected = MainWindow._human_candidate_index(chess.Board(), lines)

        self.assertEqual(selected, 2)

    def test_large_evaluation_loss_keeps_engine_move_as_human_choice(self) -> None:
        lines = [self._line("e2e4", 80), self._line("g1f3", 0)]

        selected = MainWindow._human_candidate_index(chess.Board(), lines)

        self.assertEqual(selected, 1)

    def test_single_bullet_line_has_no_separate_practical_choice(self) -> None:
        selected = MainWindow._human_candidate_index(
            chess.Board(), [self._line("e2e4", 30)]
        )

        self.assertEqual(selected, 0)


class ChessBaseOverlayTests(unittest.TestCase):
    def test_chessbase_overlay_uses_native_board_coordinates(self) -> None:
        script = DomBoardReader._chessbase_native_overlay_script("a1", "h8")

        self.assertIn("boardWin.markSquare", script)
        self.assertIn("boardWin.drawArrow", script)
        self.assertEqual(DomBoardReader._chessbase_square_index("a1"), 0)
        self.assertEqual(DomBoardReader._chessbase_square_index("a8"), 7)
        self.assertEqual(DomBoardReader._chessbase_square_index("b1"), 8)
        self.assertEqual(DomBoardReader._chessbase_square_index("h8"), 63)


class WebOverlayTests(unittest.TestCase):
    def test_overlay_renders_four_ranked_colored_moves(self) -> None:
        moves = [
            {"uci": "e2e4", "score": "+0.35", "rank": 1, "color": "#4ade80", "role": "E"},
            {"uci": "d2d4", "score": "+0.28", "rank": 2, "color": "#38bdf8", "role": "T"},
            {"uci": "g1f3", "score": "+0.20", "rank": 3, "color": "#facc15"},
            {"uci": "c2c4", "score": "+0.12", "rank": 4, "color": "#fb7185"},
        ]

        script = DomBoardReader._moves_overlay_script(moves, "white")

        self.assertIn('"uci": "c2c4"', script)
        self.assertIn("badge.textContent", script)
        self.assertIn("arrowLine", script)
        self.assertIn("arrowHead", script)
        self.assertIn("midBadge.textContent", script)
        self.assertIn("fromMark.style.borderStyle = 'dashed'", script)
        self.assertIn('"role": "E"', script)
        self.assertIn('"role": "T"', script)
        self.assertIn("move.role ? String(move.role)", script)
        self.assertIn("const rolePriority", script)
        self.assertIn("const renderMoves", script)
        self.assertIn("hasRole ? 50 + priority", script)
        self.assertIn("setProperty('z-index', '2147483647', 'important')", script)
        self.assertIn("moveCount: moves.length", script)

    def test_overlay_connects_two_moves_from_the_same_piece_with_arrows(self) -> None:
        script = DomBoardReader._moves_overlay_script(
            [
                {"uci": "g1f3", "score": "+0.30", "rank": 1, "color": "#4ade80"},
                {"uci": "g1h3", "score": "+0.10", "rank": 2, "color": "#38bdf8"},
            ],
            "white",
        )

        self.assertIn('"uci": "g1f3"', script)
        self.assertIn('"uci": "g1h3"', script)
        self.assertIn("const lineStart", script)
        self.assertIn("const tip", script)

    def test_overlay_tracks_board_resize_and_fullscreen(self) -> None:
        script = DomBoardReader._overlay_script("e2", "e4", "white", "e4")

        self.assertIn("new ResizeObserver(updateOverlay)", script)
        self.assertIn("fullscreenchange", script)
        self.assertIn("__chessAssistantOverlayCleanup", script)

    def test_overlay_falls_back_to_selected_black_perspective(self) -> None:
        script = DomBoardReader._overlay_script("e7", "e5", "black", "e5")

        self.assertIn("let blackAtBottom = data.perspective === 'black'", script)

    def test_overlay_detects_orientation_from_rendered_a1_square(self) -> None:
        script = DomBoardReader._overlay_script("e7", "e5", "black", "e5")

        self.assertIn("board.querySelector?.('[data-square=\"a1\"]')", script)
        self.assertIn("anchorX > rect.left + rect.width / 2", script)

    def test_clear_overlay_removes_generic_and_chessbase_marks(self) -> None:
        reader = DomBoardReader()
        reader._find_chess_page = Mock(return_value={"webSocketDebuggerUrl": "ws://test"})
        reader._evaluate = Mock(return_value={"ok": True})

        reader.clear_best_move()

        expression = reader._evaluate.call_args.args[1]
        self.assertIn("chess-assistant-web-overlay", expression)
        self.assertIn("__chessAssistantOverlayCleanup", expression)
        self.assertIn("undoAttributes", expression)


if __name__ == "__main__":
    unittest.main()
