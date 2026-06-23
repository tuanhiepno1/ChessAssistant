from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "engine": {
        "stockfish_path": "",
        "auto_tune": True,
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
        "active_time_control_preset": "",
        "preset": "STRONG",
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
    "profiles": {
        "WEAK": {"threads": 4, "hash_mb": 512, "time_ms": 800, "multipv": 1, "ponder": False},
        "MEDIUM": {"threads": 8, "hash_mb": 2048, "time_ms": 2500, "multipv": 1, "ponder": False},
        "STRONG": {"threads": 16, "hash_mb": 8000, "time_ms": 4500, "multipv": 1, "ponder": False},
    },
    "time_control_presets": {
        "CHESSCOM_RAPID_10": {
            "threads": 12,
            "hash_mb": 4096,
            "multipv": 4,
            "ponder": False,
            "skill_level": 20,
            "contempt": 0,
            "adaptive_time_enabled": True,
            "time_ms": 3000,
            "min_time_ms": 700,
            "probe_time_ms": 300,
            "realtime_max_time_ms": 3000,
            "hard_max_time_ms": 6000,
            "site": "chess.com",
            "game_minutes": 10,
        },
        "LICHESS_RAPID_10": {
            "threads": 12,
            "hash_mb": 4096,
            "multipv": 4,
            "ponder": False,
            "skill_level": 20,
            "contempt": 0,
            "adaptive_time_enabled": True,
            "time_ms": 3000,
            "min_time_ms": 700,
            "probe_time_ms": 300,
            "realtime_max_time_ms": 3000,
            "hard_max_time_ms": 6000,
            "site": "lichess",
            "game_minutes": 10,
        },
        "RAPID": {
            "threads": 12,
            "hash_mb": 4096,
            "multipv": 4,
            "ponder": False,
            "adaptive_time_enabled": True,
            "time_ms": 3000,
            "min_time_ms": 700,
            "probe_time_ms": 300,
            "realtime_max_time_ms": 3000,
            "hard_max_time_ms": 6000,
        },
        "BLITZ": {
            "threads": 8,
            "hash_mb": 2048,
            "multipv": 2,
            "ponder": False,
            "adaptive_time_enabled": False,
            "time_ms": 1000,
            "min_time_ms": 400,
            "probe_time_ms": 200,
            "realtime_max_time_ms": 1200,
            "hard_max_time_ms": 2000,
        },
        "BULLET": {
            "threads": 4,
            "hash_mb": 512,
            "multipv": 1,
            "ponder": False,
            "adaptive_time_enabled": False,
            "time_ms": 400,
            "min_time_ms": 200,
            "probe_time_ms": 150,
            "realtime_max_time_ms": 450,
            "hard_max_time_ms": 800,
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
        self._migrate_profiles()
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

    def apply_profile(self, name: str) -> None:
        profile = self.get(f"profiles.{name}")
        if not isinstance(profile, dict):
            raise ValueError(f"Unknown profile: {name}")

        self.set("analysis.preset", name)
        self.set("engine.auto_tune", False)
        for key in ("threads", "hash_mb", "multipv", "ponder"):
            if key in profile:
                self.set(f"engine.{key}", profile[key])
        if "time_ms" in profile:
            self.set("analysis.time_ms", profile["time_ms"])
        if "tablebase_enabled" in profile:
            self.set("tablebase.enabled", profile["tablebase_enabled"])
        self.save()

    def update_time_control_preset(self, name: str, values: dict[str, Any]) -> None:
        name = name.upper()
        if name not in {"CHESSCOM_RAPID_10", "LICHESS_RAPID_10", "RAPID", "BLITZ", "BULLET"}:
            raise ValueError(f"Unknown time-control preset: {name}")
        current = self.get(f"time_control_presets.{name}", {})
        merged = dict(current) if isinstance(current, dict) else {}
        changed = any(merged.get(key) != value for key, value in values.items())
        merged.update(values)
        self.set(f"time_control_presets.{name}", merged)
        if changed and self.get("analysis.active_time_control_preset", "") == name:
            self.set("analysis.active_time_control_preset", "")
        self.save()

    def apply_time_control_preset(self, name: str) -> None:
        name = name.upper()
        preset = self.get(f"time_control_presets.{name}")
        if not isinstance(preset, dict):
            raise ValueError(f"Unknown time-control preset: {name}")

        if "adaptive_time_enabled" in preset:
            self.set("analysis.adaptive_time_enabled", bool(preset["adaptive_time_enabled"]))
        for key in ("threads", "hash_mb", "multipv", "skill_level", "contempt"):
            if key in preset:
                self.set(f"engine.{key}", int(preset[key]))
        if "ponder" in preset:
            self.set("engine.ponder", bool(preset["ponder"]))
        self.set("engine.auto_tune", False)
        analysis_keys = {
            "time_ms": "analysis.time_ms",
            "min_time_ms": "analysis.adaptive_min_time_ms",
            "probe_time_ms": "analysis.adaptive_probe_time_ms",
            "realtime_max_time_ms": "analysis.adaptive_realtime_max_time_ms",
            "hard_max_time_ms": "analysis.adaptive_max_time_ms",
        }
        for source, target in analysis_keys.items():
            if source in preset:
                self.set(target, int(preset[source]))
        if "game_minutes" in preset:
            self.set("analysis.game_minutes", int(preset["game_minutes"]))
        if "site" in preset:
            self.set("browser.preferred_site", str(preset["site"]))
        self.set("analysis.active_time_control_preset", name)
        self.save()

    def toggle_time_control_preset(self, name: str) -> bool:
        """Apply a time preset, or restore max strength when clicked again."""
        name = name.upper()
        active = str(self.get("analysis.active_time_control_preset", "")).upper()
        if active != name:
            self.apply_time_control_preset(name)
            return True

        self.apply_profile("STRONG")
        self.set("analysis.adaptive_time_enabled", True)
        self.set("analysis.active_time_control_preset", "")
        self.save()
        return False

    def _migrate_profiles(self) -> None:
        preset = str(self.get("analysis.preset", "STRONG"))
        if preset not in {"WEAK", "MEDIUM", "STRONG"}:
            if preset in {"FAST", "BLITZ"}:
                preset = "WEAK"
            elif preset in {"BALANCED10", "RAPID"}:
                preset = "MEDIUM"
            else:
                preset = "STRONG"
            self.set("analysis.preset", preset)

        profiles = self.get("profiles", {})
        if not isinstance(profiles, dict):
            return
        for legacy in (
            "MAX_STRENGTH",
            "BALANCED10",
            "FAST",
            "BLITZ",
            "RAPID10",
            "RAPID",
            "MAX",
        ):
            profiles.pop(legacy, None)

        active = profiles.get(preset)
        if isinstance(active, dict):
            for key in ("threads", "hash_mb", "multipv", "ponder"):
                if key in active:
                    self.set(f"engine.{key}", active[key])
            if "time_ms" in active:
                self.set("analysis.time_ms", active["time_ms"])

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
