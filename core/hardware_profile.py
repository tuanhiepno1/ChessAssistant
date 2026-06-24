from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EngineRecommendation:
    threads: int
    hash_mb: int
    time_ms: int
    multipv: int = 1
    skill_level: int = 20
    ponder: bool = False


@dataclass(frozen=True)
class HardwareProfile:
    cpu_name: str
    physical_cores: int
    logical_processors: int
    ram_total_gb: float
    ram_free_gb: float
    gpu_names: tuple[str, ...]
    os_name: str

    @property
    def signature(self) -> str:
        raw = "|".join(
            (
                self.cpu_name,
                str(self.physical_cores),
                str(self.logical_processors),
                f"{self.ram_total_gb:.1f}",
                ",".join(self.gpu_names),
                self.os_name,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def recommend_balanced(self) -> EngineRecommendation:
        physical = max(1, self.physical_cores)
        logical = max(1, self.logical_processors)
        threads = min(physical, max(1, logical - 2))
        if logical >= 12:
            threads = min(threads, 8)
        elif logical >= 8:
            threads = min(threads, 6)
        elif logical >= 4:
            threads = min(threads, 4)
        else:
            threads = 1

        if self.ram_total_gb >= 48:
            hash_mb = 4096
        elif self.ram_total_gb >= 24:
            hash_mb = 2048
        elif self.ram_total_gb >= 12:
            hash_mb = 1024
        elif self.ram_total_gb >= 7:
            hash_mb = 512
        else:
            hash_mb = 256
        hash_mb = self._safe_hash(hash_mb)

        time_ms = 2500 if logical >= 12 else 3000 if logical >= 8 else 4000
        return EngineRecommendation(threads=threads, hash_mb=hash_mb, time_ms=time_ms)

    def recommend_max_strength(self) -> EngineRecommendation:
        logical = max(1, self.logical_processors)
        threads = logical

        if self.ram_total_gb >= 48:
            hash_mb = 8192
        elif self.ram_total_gb >= 24:
            hash_mb = 8000
        elif self.ram_total_gb >= 12:
            hash_mb = 2048
        elif self.ram_total_gb >= 7:
            hash_mb = 1024
        else:
            hash_mb = 512

        hash_mb = self._safe_hash(hash_mb)

        time_ms = 4500 if logical >= 12 else 6000 if logical >= 8 else 8000

        return EngineRecommendation(
            threads=threads,
            hash_mb=hash_mb,
            time_ms=time_ms,
        )

    def recommend_for_ten_minute_game(self) -> EngineRecommendation:
        return self.recommend_max_strength()

    def _safe_hash(self, desired_mb: int) -> int:
        if self.ram_total_gb <= 0:
            return max(128, desired_mb)
        safe_from_total_ram = max(128, int(self.ram_total_gb * 1024 * 0.25))
        return max(128, min(desired_mb, safe_from_total_ram))


def detect_hardware() -> HardwareProfile:
    detected = _detect_windows_hardware() if os.name == "nt" else {}
    logical = _as_int(detected.get("logical_processors"), os.cpu_count() or 1)
    physical = _as_int(detected.get("physical_cores"), max(1, logical // 2))
    total_gb = _as_float(detected.get("ram_total_gb"), 0.0)
    free_gb = _as_float(detected.get("ram_free_gb"), 0.0)
    gpu_names = detected.get("gpu_names")
    if not isinstance(gpu_names, list):
        gpu_names = []

    return HardwareProfile(
        cpu_name=str(detected.get("cpu_name") or platform.processor() or "Không xác định"),
        physical_cores=max(1, physical),
        logical_processors=max(1, logical),
        ram_total_gb=max(0.0, total_gb),
        ram_free_gb=max(0.0, free_gb),
        gpu_names=tuple(str(name) for name in gpu_names if name),
        os_name=str(detected.get("os_name") or platform.platform()),
    )


def apply_recommendation(
    config: Any,
    profile: HardwareProfile,
) -> EngineRecommendation:
    recommendation = profile.recommend_max_strength()
    config.set("hardware.signature", profile.signature)
    config.set("hardware.cpu_name", profile.cpu_name)
    config.set("hardware.physical_cores", profile.physical_cores)
    config.set("hardware.logical_processors", profile.logical_processors)
    config.set("hardware.ram_total_gb", profile.ram_total_gb)
    config.set("hardware.gpu_names", list(profile.gpu_names))
    config.update_default_config({
        "threads": recommendation.threads,
        "hash_mb": recommendation.hash_mb,
        "ponder": recommendation.ponder,
        "multipv": recommendation.multipv,
        "skill_level": recommendation.skill_level,
        "time_ms": recommendation.time_ms,
        "adaptive_time_enabled": True,
    })
    config.set("analysis.game_minutes", 10)
    config.set("book.prefer_book", False)
    config.apply_default_config()
    config.save()
    return recommendation


def _detect_windows_hardware() -> dict[str, Any]:
    script = r"""
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
[pscustomobject]@{
  cpu_name = $cpu.Name
  physical_cores = $cpu.NumberOfCores
  logical_processors = $cpu.NumberOfLogicalProcessors
  ram_total_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
  ram_free_gb = [math]::Round(($os.FreePhysicalMemory * 1KB) / 1GB, 1)
  gpu_names = $gpus
  os_name = $os.Caption + " " + $os.OSArchitecture
} | ConvertTo-Json -Compress
"""
    creationflags = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=creationflags,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            data = json.loads(completed.stdout.strip())
            return data if isinstance(data, dict) else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return {}


def _floor_power_of_two(value: int) -> int:
    return 1 << max(0, int(value).bit_length() - 1)


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
