from __future__ import annotations

from engine.engine_manager import EngineManager
from engine.stockfish import AnalysisResult


class Analyzer:
    def __init__(self, engine_manager: EngineManager) -> None:
        self.engine_manager = engine_manager

    def analyze_fen(self, fen: str) -> AnalysisResult:
        return self.engine_manager.analyze_fen(fen)

