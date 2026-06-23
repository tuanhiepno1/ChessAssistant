from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.config_manager import ConfigManager
from core.hardware_profile import HardwareProfile


class ProfileTests(unittest.TestCase):
    def test_default_time_control_presets_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")

            self.assertEqual(config.get("time_control_presets.RAPID.threads"), 12)
            self.assertEqual(config.get("time_control_presets.CHESSCOM_RAPID_10.threads"), 12)
            self.assertEqual(
                config.get("time_control_presets.CHESSCOM_RAPID_10.realtime_max_time_ms"),
                3000,
            )
            self.assertEqual(config.get("time_control_presets.LICHESS_RAPID_10.site"), "lichess")
            self.assertEqual(config.get("time_control_presets.RAPID.multipv"), 4)
            self.assertEqual(config.get("time_control_presets.BLITZ.multipv"), 2)
            self.assertEqual(config.get("time_control_presets.BULLET.multipv"), 1)
            self.assertEqual(config.get("time_control_presets.RAPID.hard_max_time_ms"), 6000)
            self.assertEqual(config.get("time_control_presets.BLITZ.time_ms"), 1000)
            self.assertEqual(config.get("time_control_presets.BULLET.time_ms"), 400)

    def test_edited_time_control_preset_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = ConfigManager(path)
            config.update_time_control_preset(
                "BLITZ",
                {"threads": 6, "hash_mb": 1536, "time_ms": 750},
            )

            reloaded = ConfigManager(path)

            self.assertEqual(reloaded.get("time_control_presets.BLITZ.threads"), 6)
            self.assertEqual(reloaded.get("time_control_presets.BLITZ.hash_mb"), 1536)
            self.assertEqual(reloaded.get("time_control_presets.BLITZ.time_ms"), 750)

    def test_apply_rapid_time_control_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("engine.threads", 3)
            config.set("engine.hash_mb", 768)

            config.apply_time_control_preset("RAPID")

            self.assertEqual(config.get("engine.threads"), 12)
            self.assertEqual(config.get("engine.hash_mb"), 4096)
            self.assertEqual(config.get("engine.multipv"), 4)
            self.assertTrue(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.adaptive_min_time_ms"), 700)
            self.assertEqual(config.get("analysis.adaptive_probe_time_ms"), 300)
            self.assertEqual(config.get("analysis.adaptive_realtime_max_time_ms"), 3000)
            self.assertEqual(config.get("analysis.adaptive_max_time_ms"), 6000)
            self.assertEqual(config.get("analysis.active_time_control_preset"), "RAPID")

    def test_apply_chesscom_rapid_10_optimized_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("engine.skill_level", 5)
            config.set("engine.multipv", 3)

            config.apply_time_control_preset("CHESSCOM_RAPID_10")

            self.assertEqual(config.get("engine.threads"), 12)
            self.assertEqual(config.get("engine.hash_mb"), 4096)
            self.assertEqual(config.get("engine.skill_level"), 20)
            self.assertEqual(config.get("engine.multipv"), 4)
            self.assertTrue(config.get("analysis.adaptive_time_enabled"))
            self.assertFalse(config.get("engine.ponder"))
            self.assertEqual(config.get("analysis.adaptive_min_time_ms"), 700)
            self.assertEqual(config.get("analysis.adaptive_probe_time_ms"), 300)
            self.assertEqual(config.get("analysis.adaptive_realtime_max_time_ms"), 3000)
            self.assertEqual(config.get("analysis.adaptive_max_time_ms"), 6000)
            self.assertEqual(config.get("analysis.game_minutes"), 10)
            self.assertEqual(config.get("browser.preferred_site"), "chess.com")
            self.assertEqual(
                config.get("analysis.active_time_control_preset"),
                "CHESSCOM_RAPID_10",
            )

    def test_apply_lichess_rapid_10_optimized_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")

            config.apply_time_control_preset("LICHESS_RAPID_10")

            self.assertEqual(config.get("engine.threads"), 12)
            self.assertEqual(config.get("engine.hash_mb"), 4096)
            self.assertEqual(config.get("engine.multipv"), 4)
            self.assertFalse(config.get("engine.ponder"))
            self.assertTrue(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.adaptive_min_time_ms"), 700)
            self.assertEqual(config.get("analysis.adaptive_probe_time_ms"), 300)
            self.assertEqual(config.get("analysis.adaptive_realtime_max_time_ms"), 3000)
            self.assertEqual(config.get("analysis.adaptive_max_time_ms"), 6000)
            self.assertEqual(config.get("analysis.game_minutes"), 10)
            self.assertEqual(config.get("browser.preferred_site"), "lichess")
            self.assertEqual(
                config.get("analysis.active_time_control_preset"),
                "LICHESS_RAPID_10",
            )

    def test_legacy_site_rapid_preset_becomes_shared_rapid_on_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = ConfigManager(path)
            config.apply_time_control_preset("LICHESS_RAPID_10")

            reloaded = ConfigManager(path)

            self.assertEqual(
                reloaded.get("analysis.active_time_control_preset"), "RAPID"
            )
            self.assertEqual(reloaded.get("browser.preferred_site"), "lichess")
            self.assertEqual(reloaded.get("engine.multipv"), 4)

    def test_apply_blitz_time_control_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("BLITZ")

            self.assertEqual(config.get("engine.threads"), 8)
            self.assertEqual(config.get("engine.hash_mb"), 2048)
            self.assertEqual(config.get("engine.multipv"), 2)
            self.assertFalse(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.time_ms"), 1000)
            self.assertEqual(config.get("analysis.adaptive_realtime_max_time_ms"), 1200)
            self.assertEqual(config.get("analysis.active_time_control_preset"), "BLITZ")

    def test_apply_bullet_time_control_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("book.verify_with_engine", True)
            config.apply_time_control_preset("BULLET")

            self.assertEqual(config.get("engine.threads"), 4)
            self.assertEqual(config.get("engine.hash_mb"), 512)
            self.assertEqual(config.get("engine.multipv"), 1)
            self.assertFalse(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.time_ms"), 400)
            self.assertEqual(config.get("analysis.adaptive_realtime_max_time_ms"), 450)
            self.assertTrue(config.get("book.verify_with_engine"))
            self.assertEqual(config.get("analysis.active_time_control_preset"), "BULLET")

    def test_clicking_active_time_control_preset_restores_strong_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("BULLET")

            enabled = config.toggle_time_control_preset("BULLET")

            self.assertFalse(enabled)
            self.assertEqual(config.get("analysis.preset"), "STRONG")
            self.assertEqual(config.get("engine.threads"), 16)
            self.assertEqual(config.get("engine.hash_mb"), 8000)
            self.assertTrue(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("analysis.active_time_control_preset"), "")

    def test_clicking_different_time_control_preset_switches_directly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("BULLET")

            enabled = config.toggle_time_control_preset("BLITZ")

            self.assertTrue(enabled)
            self.assertEqual(config.get("engine.threads"), 8)
            self.assertEqual(config.get("engine.hash_mb"), 2048)
            self.assertEqual(config.get("analysis.active_time_control_preset"), "BLITZ")

    def test_legacy_config_loads_with_default_time_control_presets_without_applying_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "engine": {"stockfish_path": "legacy-stockfish.exe"},
                        "analysis": {"adaptive_time_enabled": False},
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigManager(path)

            self.assertEqual(config.get("engine.stockfish_path"), "legacy-stockfish.exe")
            self.assertFalse(config.get("analysis.adaptive_time_enabled"))
            self.assertEqual(config.get("time_control_presets.RAPID.threads"), 12)

    def test_strong_recommendation_uses_full_16_threads_and_8000_mb(self) -> None:
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

    def test_custom_profile_values_are_applied_without_recalculation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("profiles.STRONG.threads", 16)
            config.set("profiles.STRONG.hash_mb", 8000)
            config.set("profiles.STRONG.time_ms", 4000)
            config.set("profiles.STRONG.multipv", 3)

            config.apply_profile("STRONG")

            self.assertEqual(config.get("engine.threads"), 16)
            self.assertEqual(config.get("engine.hash_mb"), 8000)
            self.assertEqual(config.get("analysis.time_ms"), 4000)
            self.assertEqual(config.get("engine.multipv"), 3)


if __name__ == "__main__":
    unittest.main()
