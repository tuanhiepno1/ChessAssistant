from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config_manager import ConfigManager
from core.hardware_profile import HardwareProfile


class ProfileTests(unittest.TestCase):
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
