from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "engine": {
        "stockfish_path": "",
        "threads": 12,
        "hash_mb": 4096,
        "ponder": False,
        "multipv": 1,
        "skill_level": 20,
        "contempt": 0,
        "uci_options": {},
    },
    "analysis": {
        "time_ms": 4500,
        "adaptive_time_enabled": True,
        "adaptive_min_time_ms": 700,
        "adaptive_max_time_ms": 6000,
        "adaptive_probe_time_ms": 300,
        "adaptive_realtime_max_time_ms": 4200,
        "ponder_max_time_ms": 10000,
        "ponder_hit_settle_ms": 25,
        "ponder_miss_quick_time_ms": 650,
        "ponder_prediction_time_ms": 200,
        "ponder_completion_time_ms": 650,
        "ponder_stop_timeout_ms": 200,
        "ponder_refinement_time_ms": 2000,
        "ponder_ready_depth": 8,
        "active_time_control_preset": "",
        "game_minutes": 10,
        "cache_enabled": True,
    },
    "book": {
        "enabled": False,
        "path": "",
        "prefer_book": False,
        "verify_with_engine": True,
        "max_eval_loss_cp": 10,
        "verify_time_ms": 300,
    },
    "tablebase": {
        "enabled": False,
        "syzygy_path": "",
        "max_pieces": 5,
    },
    "vision": {
        "yolo_model_path": "models/chess_piece_model.pt",
        "confidence_threshold": 0.5,
        "board_position": None,
        "perspective": "white",
    },
    "browser": {
        "preferred_site": "auto",
        "web_overlay_enabled": True,
    },
    "hardware": {
        "signature": "",
    },
    "default_config": {
        "threads": 16,
        "hash_mb": 8000,
        "multipv": 1,
        "ponder": False,
        "skill_level": 20,
        "contempt": 0,
        "adaptive_time_enabled": True,
        "time_ms": 4500,
        "min_time_ms": 700,
        "probe_time_ms": 300,
        "realtime_max_time_ms": 4200,
        "hard_max_time_ms": 6000,
    },
    "time_control_presets": {
        "RAPID": {
            "threads": 16,
            "hash_mb": 4096,
            "multipv": 3,
            "ponder": True,
            "adaptive_time_enabled": True,
            "time_ms": 3000,
            "min_time_ms": 700,
            "probe_time_ms": 300,
            "realtime_max_time_ms": 2000,
            "hard_max_time_ms": 6000,
            "ponder_max_time_ms": 10000,
            "ponder_hit_settle_ms": 25,
            "ponder_miss_quick_time_ms": 400,
            "ponder_prediction_time_ms": 200,
            "ponder_completion_time_ms": 650,
            "ponder_stop_timeout_ms": 200,
            "ponder_refinement_time_ms": 2000,
            "ponder_ready_depth": 8,
        },
        "BLITZ": {
            "threads": 8,
            "hash_mb": 512,
            "multipv": 2,
            "ponder": True,
            "adaptive_time_enabled": False,
            "time_ms": 1000,
            "min_time_ms": 400,
            "probe_time_ms": 200,
            "realtime_max_time_ms": 1200,
            "hard_max_time_ms": 2000,
            "ponder_max_time_ms": 5000,
            "ponder_hit_settle_ms": 20,
            "ponder_miss_quick_time_ms": 250,
            "ponder_prediction_time_ms": 120,
            "ponder_completion_time_ms": 350,
            "ponder_stop_timeout_ms": 150,
            "ponder_refinement_time_ms": 1000,
            "ponder_ready_depth": 7,
        },
        "BULLET": {
            "threads": 6,
            "hash_mb": 256,
            "multipv": 1,
            "ponder": False,
            "adaptive_time_enabled": False,
            "time_ms": 120,
            "min_time_ms": 80,
            "probe_time_ms": 80,
            "realtime_max_time_ms": 150,
            "hard_max_time_ms": 300,
            "ponder_max_time_ms": 0,
            "ponder_hit_settle_ms": 0,
            "ponder_miss_quick_time_ms": 80,
            "ponder_prediction_time_ms": 0,
            "ponder_completion_time_ms": 80,
            "ponder_stop_timeout_ms": 100,
            "ponder_refinement_time_ms": 0,
            "ponder_ready_depth": 1,
        },
    },
}


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class ConfigManager:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = self._load()
        self._migrate_legacy_profiles()
        self._restore_active_time_control_preset()
        self.save()

    @property
    def settings(self) -> dict[str, Any]:
        return self._settings

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULT_SETTINGS)
        with self.path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        return _deep_merge(DEFAULT_SETTINGS, loaded)

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self._settings, file, indent=2)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._settings
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        node = self._settings
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def update_default_config(self, values: dict[str, Any]) -> None:
        current = self.get("default_config", {})
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(values)
        self.set("default_config", merged)
        self.save()

    def apply_default_config(self) -> None:
        default = self.get("default_config", {})
        if not isinstance(default, dict):
            raise ValueError("Default engine configuration is invalid.")
        self._apply_engine_values(default)
        self.set("analysis.active_time_control_preset", "")
        self.save()

    def update_time_control_preset(self, name: str, values: dict[str, Any]) -> None:
        name = name.upper()
        if name not in {"RAPID", "BLITZ", "BULLET"}:
            raise ValueError(f"Unknown time-control preset: {name}")
        current = self._time_control_preset_with_defaults(name)
        merged = dict(current) if isinstance(current, dict) else {}
        changed = any(merged.get(key) != value for key, value in values.items())
        merged.update(values)
        self.set(f"time_control_presets.{name}", merged)
        if changed and self.get("analysis.active_time_control_preset", "") == name:
            self.set("analysis.active_time_control_preset", "")
        self.save()

    def apply_time_control_preset(self, name: str) -> None:
        name = name.upper()
        preset = self._time_control_preset_with_defaults(name)
        if not isinstance(preset, dict):
            raise ValueError(f"Unknown time-control preset: {name}")
        self.set(f"time_control_presets.{name}", preset)

        self._apply_engine_values(preset)
        if "game_minutes" in preset:
            self.set("analysis.game_minutes", int(preset["game_minutes"]))
        if "site" in preset:
            self.set("browser.preferred_site", str(preset["site"]))
        self.set("analysis.active_time_control_preset", name)
        self.save()

    def _apply_engine_values(self, values: dict[str, Any]) -> None:
        if "adaptive_time_enabled" in values:
            self.set("analysis.adaptive_time_enabled", bool(values["adaptive_time_enabled"]))
        for key in ("threads", "hash_mb", "multipv", "skill_level", "contempt"):
            if key in values:
                self.set(f"engine.{key}", int(values[key]))
        if "ponder" in values:
            self.set("engine.ponder", bool(values["ponder"]))
        analysis_keys = {
            "time_ms": "analysis.time_ms",
            "min_time_ms": "analysis.adaptive_min_time_ms",
            "probe_time_ms": "analysis.adaptive_probe_time_ms",
            "realtime_max_time_ms": "analysis.adaptive_realtime_max_time_ms",
            "hard_max_time_ms": "analysis.adaptive_max_time_ms",
            "ponder_max_time_ms": "analysis.ponder_max_time_ms",
            "ponder_hit_settle_ms": "analysis.ponder_hit_settle_ms",
            "ponder_miss_quick_time_ms": "analysis.ponder_miss_quick_time_ms",
            "ponder_prediction_time_ms": "analysis.ponder_prediction_time_ms",
            "ponder_completion_time_ms": "analysis.ponder_completion_time_ms",
            "ponder_stop_timeout_ms": "analysis.ponder_stop_timeout_ms",
            "ponder_refinement_time_ms": "analysis.ponder_refinement_time_ms",
            "ponder_ready_depth": "analysis.ponder_ready_depth",
        }
        for source, target in analysis_keys.items():
            if source in values:
                self.set(target, int(values[source]))

    def toggle_time_control_preset(self, name: str) -> bool:
        """Apply a time preset, or restore max strength when clicked again."""
        name = name.upper()
        active = str(self.get("analysis.active_time_control_preset", "")).upper()
        if active != name:
            self.apply_time_control_preset(name)
            return True

        self.apply_default_config()
        return False

    def _time_control_preset_with_defaults(self, name: str) -> dict[str, Any] | None:
        default_presets = DEFAULT_SETTINGS.get("time_control_presets", {})
        default = default_presets.get(name)
        current = self.get(f"time_control_presets.{name}")
        if not isinstance(default, dict):
            return current if isinstance(current, dict) else None
        if not isinstance(current, dict):
            return copy.deepcopy(default)
        return _deep_merge(default, current)

    def _migrate_legacy_profiles(self) -> None:
        profiles = self.get("profiles", {})
        default = self.get("default_config", {})
        if isinstance(profiles, dict) and isinstance(profiles.get("STRONG"), dict):
            # Existing users keep their customized Strong values as the sole
            # default configuration during the one-time migration.
            legacy_strong = profiles["STRONG"]
            if isinstance(default, dict):
                migrated = dict(default)
                migrated.update(legacy_strong)
                self.set("default_config", migrated)
        self._settings.pop("profiles", None)
        analysis = self._settings.get("analysis")
        if isinstance(analysis, dict):
            analysis.pop("preset", None)
        engine = self._settings.get("engine")
        if isinstance(engine, dict):
            engine.pop("auto_tune", None)
        presets = self._settings.get("time_control_presets")
        if isinstance(presets, dict):
            presets.pop("CHESSCOM_RAPID_10", None)
            presets.pop("LICHESS_RAPID_10", None)
        self._migrate_bullet_preset()

    def _migrate_bullet_preset(self) -> None:
        """Ensure the BULLET preset always matches the latest code defaults.

        The BULLET preset is performance-tuned in code; stale saved values
        from a previous version must not prevent the new tuning from taking
        effect.  Only engine-critical keys are migrated — site selection and
        game_minutes are left untouched so the user's website preference
        persists across updates.
        """
        default_bullet = DEFAULT_SETTINGS.get("time_control_presets", {}).get("BULLET")
        if not isinstance(default_bullet, dict):
            return
        saved_bullet = self.get("time_control_presets.BULLET")
        # Only migrate if the user has a saved BULLET preset whose engine
        # values differ from the current code defaults.  A fresh install
        # or first-time Bullet selection has no saved preset at all.
        if not isinstance(saved_bullet, dict):
            return
        saved_threads = int(saved_bullet.get("threads", 0))
        saved_time_ms = int(saved_bullet.get("time_ms", 0))
        default_threads = int(default_bullet.get("threads", 0))
        default_time_ms = int(default_bullet.get("time_ms", 0))
        if saved_threads == default_threads and saved_time_ms == default_time_ms:
            return  # Already up to date.

        # Preserve site preference if the user explicitly chose one.
        site = saved_bullet.get("site")
        game_minutes = saved_bullet.get("game_minutes")

        self.set(
            "time_control_presets.BULLET",
            copy.deepcopy(default_bullet),
        )
        if site is not None:
            self.set("time_control_presets.BULLET.site", site)
        if game_minutes is not None:
            self.set("time_control_presets.BULLET.game_minutes", game_minutes)

    def _restore_active_time_control_preset(self) -> None:
        active = str(self.get("analysis.active_time_control_preset", "")).upper()
        if active in {"CHESSCOM_RAPID_10", "LICHESS_RAPID_10"}:
            # These legacy presets now share the canonical Rapid engine
            # settings. Keep the remembered website, but remove duplicate UI
            # state after upgrading an existing settings file.
            active = "RAPID"
            self.set("analysis.active_time_control_preset", active)
        if active in {"RAPID", "BLITZ", "BULLET"}:
            self.apply_time_control_preset(active)
        else:
            self.apply_default_config()
