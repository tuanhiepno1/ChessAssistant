# Architecture

## Design Goals

ChessAssistant is a non-clicking Windows desktop assistant. It observes the screen, reconstructs the chess position, and analyzes it with a UCI engine. The architecture separates GUI, engine, vision, chess state, books, and tablebases so each part can evolve independently.

## Runtime Flow

Phase 1:

1. User enters a FEN in the GUI.
2. `ui.main_window` starts `AnalysisWorker` on a `QThread`.
3. `engine.engine_manager` validates the FEN with `python-chess`.
4. `engine.stockfish` launches/configures the UCI engine.
5. Stockfish analyzes by time, not fixed depth.
6. GUI receives `AnalysisResult` and renders best move, eval, depth, nodes, time, and MultiPV lines.

Future vision flow:

1. `vision.screen_capture` captures the screen with `mss`.
2. `vision.board_detector` finds or crops the calibrated board.
3. `vision.yolo_detector` loads any compatible Ultralytics YOLO model from config.
4. `vision.piece_mapper` maps detections to the 64 board squares.
5. `chess_tools.fen_builder` creates a FEN.
6. `books.opening_manager` may return a book move before engine analysis.
7. `engine.engine_manager` analyzes only uncached FENs.

## Package Boundaries

- `app/`: process entry point.
- `core/`: default engine settings, time-control presets, config persistence.
- `engine/`: UCI engine process lifecycle and analysis result models.
- `vision/`: screen capture, board detection, YOLO detection, square mapping.
- `chess_tools/`: FEN construction and chess analysis orchestration.
- `books/`: Polyglot-compatible opening book integration.
- `tablebase/`: Syzygy probing and path management.
- `ui/`: PySide6 windows, settings, and future overlay.

The chess package is intentionally named `chess_tools`, not `chess`, because the dependency `python-chess` imports as `chess`.

## Performance Model

- UI remains on the Qt main thread.
- Engine work runs on a `QThread`.
- Future vision work should run on a worker thread or async capture loop.
- Engine analysis uses time controls: 500 ms, 1000 ms, 3000 ms, and 10000 ms presets.
- FEN cache avoids repeated engine calls for identical positions and analysis settings.
- Default Ryzen 7 5700X3D tuning uses 16 threads and 8192 MB hash, with 12288 MB only for MAX profile.

## Extension Points

- YOLO version upgrades are isolated in `vision.yolo_detector`; the app depends on the Ultralytics `YOLO` interface, not a hardcoded YOLOv8 class.
- UCI options are filtered against engine-supported options before configuration.
- Opening books and tablebases are separate managers so they can be enabled progressively in Phase 4.
