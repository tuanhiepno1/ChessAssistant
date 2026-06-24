from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import chess

from core.config_manager import ConfigManager
from core.hardware_profile import HardwareProfile
from engine.engine_manager import EngineManager


class ProfileTests(unittest.TestCase):
    def test_only_default_and_three_time_control_presets_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")

            self.assertIsNone(config.get("profiles"))
            self.assertEqual(config.get("default_config.threads"), 16)
            self.assertEqual(
                set(config.get("time_control_presets")),
                {"RAPID", "BLITZ", "BULLET"},
            )
            self.assertEqual(config.get("time_control_presets.RAPID.multipv"), 3)
            self.assertTrue(config.get("time_control_presets.RAPID.ponder"))
            self.assertEqual(config.get("time_control_presets.BLITZ.multipv"), 2)
            self.assertTrue(config.get("time_control_presets.BLITZ.ponder"))
            self.assertEqual(config.get("time_control_presets.BULLET.multipv"), 1)
            self.assertTrue(config.get("time_control_presets.BULLET.ponder"))

    def test_edited_time_control_preset_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = ConfigManager(path)
            config.update_time_control_preset(
                "BLITZ", {"threads": 6, "hash_mb": 1536, "time_ms": 750}
            )

            reloaded = ConfigManager(path)

            self.assertEqual(reloaded.get("time_control_presets.BLITZ.threads"), 6)
            self.assertEqual(reloaded.get("time_control_presets.BLITZ.hash_mb"), 1536)
            self.assertEqual(reloaded.get("time_control_presets.BLITZ.time_ms"), 750)

    def test_apply_rapid_time_control_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")

            config.apply_time_control_preset("RAPID")

            self.assertEqual(config.get("engine.threads"), 8)
            self.assertEqual(config.get("engine.hash_mb"), 2048)
            self.assertEqual(config.get("engine.multipv"), 3)
            self.assertTrue(config.get("engine.ponder"))
            self.assertTrue(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.adaptive_realtime_max_time_ms"), 2000)
            self.assertEqual(config.get("analysis.ponder_miss_quick_time_ms"), 400)
            self.assertEqual(config.get("analysis.ponder_ready_depth"), 8)
            self.assertEqual(config.get("analysis.active_time_control_preset"), "RAPID")

    def test_apply_blitz_time_control_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")

            config.apply_time_control_preset("BLITZ")

            self.assertEqual(config.get("engine.threads"), 6)
            self.assertEqual(config.get("engine.hash_mb"), 1024)
            self.assertEqual(config.get("engine.multipv"), 2)
            self.assertTrue(config.get("engine.ponder"))
            self.assertFalse(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.time_ms"), 1000)

    def test_apply_bullet_time_control_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")

            config.apply_time_control_preset("BULLET")

            self.assertEqual(config.get("engine.threads"), 6)
            self.assertEqual(config.get("engine.hash_mb"), 512)
            self.assertEqual(config.get("engine.multipv"), 1)
            self.assertTrue(config.get("engine.ponder"))
            self.assertFalse(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.time_ms"), 150)
            self.assertEqual(config.get("analysis.ponder_miss_quick_time_ms"), 100)
            self.assertEqual(config.get("analysis.ponder_prediction_time_ms"), 60)

    def test_bullet_skips_opening_book_entirely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("book.enabled", True)
            config.set("book.prefer_book", True)
            config.set("book.verify_with_engine", True)
            config.apply_time_control_preset("BULLET")
            manager = EngineManager(config)
            manager._opening_manager = Mock(prefer_book=True)
            manager._opening_manager.find_moves.return_value = [chess.Move.from_uci("e2e4")]
            manager._verify_book_move = Mock()

            result = manager._try_opening_book(chess.Board())

            self.assertIsNone(result)
            manager._opening_manager.configure.assert_not_called()
            manager._opening_manager.find_moves.assert_not_called()
            manager._verify_book_move.assert_not_called()

    def test_clicking_active_preset_restores_default_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.update_default_config({"threads": 12, "hash_mb": 4096, "time_ms": 3500})
            config.apply_time_control_preset("BULLET")

            enabled = config.toggle_time_control_preset("BULLET")

            self.assertFalse(enabled)
            self.assertEqual(config.get("engine.threads"), 12)
            self.assertEqual(config.get("engine.hash_mb"), 4096)
            self.assertEqual(config.get("analysis.time_ms"), 3500)
            self.assertEqual(config.get("analysis.active_time_control_preset"), "")

    def test_clicking_different_preset_switches_directly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("BULLET")

            enabled = config.toggle_time_control_preset("BLITZ")

            self.assertTrue(enabled)
            self.assertEqual(config.get("analysis.active_time_control_preset"), "BLITZ")
            self.assertEqual(config.get("engine.multipv"), 2)

    def test_legacy_profiles_migrate_strong_and_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({
                    "analysis": {"preset": "MEDIUM"},
                    "engine": {"auto_tune": True},
                    "profiles": {
                        "WEAK": {"threads": 2},
                        "MEDIUM": {"threads": 4},
                        "STRONG": {"threads": 14, "hash_mb": 6000, "time_ms": 3200},
                    },
                }),
                encoding="utf-8",
            )

            config = ConfigManager(path)

            self.assertEqual(config.get("default_config.threads"), 14)
            self.assertEqual(config.get("default_config.hash_mb"), 6000)
            self.assertEqual(config.get("default_config.time_ms"), 3200)
            self.assertIsNone(config.get("profiles"))
            self.assertIsNone(config.get("analysis.preset"))
            self.assertIsNone(config.get("engine.auto_tune"))

    def test_strong_recommendation_uses_full_machine(self) -> None:
        hardware = HardwareProfile(
            cpu_name="Test CPU",
            physical_cores=8,
            logical_processors=16,
            ram_total_gb=31.9,
            ram_free_gb=20.0,
            gpu_names=("Test GPU",),
            os_name="Windows",
        )

        recommendation = hardware.recommend_max_strength()

        self.assertEqual(recommendation.threads, 16)
        self.assertEqual(recommendation.hash_mb, 8000)
        self.assertEqual(recommendation.time_ms, 4500)
        self.assertEqual(recommendation.multipv, 1)


if __name__ == "__main__":
    unittest.main()
