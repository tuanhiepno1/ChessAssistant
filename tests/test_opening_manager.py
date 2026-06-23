from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import chess

from books.opening_manager import OpeningManager


class OpeningManagerLifecycleTests(unittest.TestCase):
    def test_reader_is_reused_across_probes(self) -> None:
        reader = Mock()
        reader.find_all.return_value = []
        manager = OpeningManager(enabled=True, path="book.bin")

        with patch("books.opening_manager.chess.polyglot.open_reader", return_value=reader) as open_reader:
            manager.find_moves(chess.Board())
            manager.find_moves(chess.Board())

        open_reader.assert_called_once_with("book.bin")
        self.assertEqual(reader.find_all.call_count, 2)

    def test_changing_path_closes_old_reader_and_opens_new_reader(self) -> None:
        first_reader = Mock()
        first_reader.find_all.return_value = []
        second_reader = Mock()
        second_reader.find_all.return_value = []
        manager = OpeningManager(enabled=True, path="first.bin")

        with patch(
            "books.opening_manager.chess.polyglot.open_reader",
            side_effect=[first_reader, second_reader],
        ) as open_reader:
            manager.find_moves(chess.Board())
            manager.configure(enabled=True, path="second.bin", prefer_book=True)
            manager.find_moves(chess.Board())

        first_reader.close.assert_called_once_with()
        self.assertEqual(open_reader.call_args_list[0].args, ("first.bin",))
        self.assertEqual(open_reader.call_args_list[1].args, ("second.bin",))

    def test_invalid_path_logs_once_and_falls_back(self) -> None:
        manager = OpeningManager(enabled=True, path="missing.bin")

        with (
            patch(
                "books.opening_manager.chess.polyglot.open_reader",
                side_effect=FileNotFoundError("missing"),
            ) as open_reader,
            self.assertLogs("books.opening_manager", level="WARNING") as logs,
        ):
            self.assertEqual(manager.find_moves(chess.Board()), [])
            self.assertEqual(manager.find_moves(chess.Board()), [])

        open_reader.assert_called_once_with("missing.bin")
        self.assertEqual(len(logs.output), 1)

    def test_close_and_disable_release_reader(self) -> None:
        reader = Mock()
        reader.find_all.return_value = []
        manager = OpeningManager(enabled=True, path="book.bin")

        with patch("books.opening_manager.chess.polyglot.open_reader", return_value=reader):
            manager.find_moves(chess.Board())
            manager.close()

        reader.close.assert_called_once_with()
        manager.close()

        second_reader = Mock()
        second_reader.find_all.return_value = []
        with patch("books.opening_manager.chess.polyglot.open_reader", return_value=second_reader):
            manager.find_moves(chess.Board())
            manager.configure(enabled=False, path="book.bin", prefer_book=True)

        second_reader.close.assert_called_once_with()
        self.assertEqual(manager.find_moves(chess.Board()), [])


if __name__ == "__main__":
    unittest.main()
