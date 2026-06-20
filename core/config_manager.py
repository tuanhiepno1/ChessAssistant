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
    },
    "hardware": {
        "signature": "",
    },
    "profiles": {
        "WEAK": {"threads": 4, "hash_mb": 512, "time_ms": 800, "multipv": 1, "ponder": False},
        "MEDIUM": {"threads": 8, "hash_mb": 2048, "time_ms": 2500, "multipv": 1, "ponder": False},
        "STRONG": {"threads": 16, "hash_mb": 8000, "time_ms": 4500, "multipv": 1, "ponder": False},
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
