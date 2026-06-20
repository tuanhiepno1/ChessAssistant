from __future__ import annotations

import json
import itertools
import re
from dataclasses import dataclass
from urllib.request import urlopen

import chess
import websocket

from chess_tools.fen_builder import SquarePiece


class DomUnavailableError(RuntimeError):
    pass


class DomReadError(RuntimeError):
    pass


PIECE_CODES = {
    "wp": "white_pawn",
    "wn": "white_knight",
    "wb": "white_bishop",
    "wr": "white_rook",
    "wq": "white_queen",
    "wk": "white_king",
    "bp": "black_pawn",
    "bn": "black_knight",
    "bb": "black_bishop",
    "br": "black_rook",
    "bq": "black_queen",
    "bk": "black_king",
}


@dataclass(frozen=True)
class DomBoardState:
    pieces: list[SquarePiece]
    url: str
    title: str
    turn: chess.Color | None
    turn_reliable: bool
    active_clock_position: str | None
    black_at_bottom: bool
    site: str
    exact_fen: str | None
    move_count: int
    status: str


class DomBoardReader:
    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:9222",
        preferred_site: str = "auto",
        target_id: str = "",
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.preferred_site = preferred_site.lower()
        self.target_id = target_id
        self._message_ids = itertools.count(1)

    def read(self) -> DomBoardState:
        page = self._find_chess_page()
        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise DomReadError("Không tìm thấy WebSocket DevTools của thẻ cờ vua.")

        script = r"""
(() => {
  const pieceCode = (tokens) => {
    const classes = tokens
      .flatMap((name) => String(name || '').trim().toLowerCase().split(/[\s_-]+/))
      .filter(Boolean);
    const compact = classes.find((name) => /^[wb][prnbqk]$/.test(name));
    if (compact) return compact;
    const color = classes.includes('white') ? 'w' : (classes.includes('black') ? 'b' : '');
    const names = { pawn: 'p', knight: 'n', bishop: 'b', rook: 'r', queen: 'q', king: 'k' };
    const kind = Object.keys(names).find((name) => classes.includes(name));
    return color && kind ? color + names[kind] : null;
  };

  const findBoard = () => {
    const cached = window.__chessAssistantMainBoard;
    if (cached && cached.isConnected) {
      const rect = cached.getBoundingClientRect();
      if (rect.width > 250 && rect.height > 250 && Math.abs(rect.width - rect.height) < rect.width * 0.15) {
        return cached;
      }
    }
    const selector = location.hostname.includes('lichess.org')
      ? 'cg-board'
      : (location.hostname.includes('play.chessbase.com')
        ? '#boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas'
        : 'wc-chess-board, chess-board, cg-board, .cg-wrap, .board, .chess-board, #board-single, [data-boardid], #boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas');
    const candidates = Array.from(document.querySelectorAll(selector))
      .map((el) => ({ el, rect: el.getBoundingClientRect() }))
      .filter(({ rect }) => rect.width > 250 && Math.abs(rect.width - rect.height) < rect.width * 0.15)
      // Piece count must not affect selection: captures would otherwise make
      // the reader jump to a fuller mini-board during the game.
      .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
    if (candidates.length) {
      window.__chessAssistantMainBoard = candidates[0].el;
      return candidates[0].el;
    }
    const piece = document.querySelector('.piece, cg-board piece');
    if (!piece) return null;
    let node = piece.parentElement;
    while (node && node !== document.body) {
      const rect = node.getBoundingClientRect();
      if (rect.width > 250 && Math.abs(rect.width - rect.height) < rect.width * 0.12) {
        window.__chessAssistantMainBoard = node;
        return node;
      }
      node = node.parentElement;
    }
    return null;
  };

  const boardEl = findBoard();
  const boardRect = boardEl ? boardEl.getBoundingClientRect() : null;
  const boardClasses = boardEl ? Array.from(boardEl.classList) : [];
  const boardText = boardEl
    ? [boardEl, boardEl.parentElement, boardEl.parentElement?.parentElement]
        .filter(Boolean)
        .map((el) => `${el.className || ''} ${el.getAttribute?.('data-orientation') || ''} ${el.getAttribute?.('orientation') || ''}`)
        .join(' ')
        .toLowerCase()
    : '';
  let blackAtBottom =
    boardText.includes('flipped') ||
    boardText.includes('orientation-black') ||
    boardText.includes('orientation black') ||
    (window.glApp && window.glApp.panelMgr && window.glApp.panelMgr.getKernel &&
      window.glApp.panelMgr.getKernel()?.boardWin?.blackIsBottom === true);

  // data-square is orientation-independent. Its rendered position gives a
  // reliable orientation even when a site renames its flipped CSS class.
  const a1Anchor = boardEl?.querySelector?.('[data-square="a1"]');
  if (a1Anchor && boardRect) {
    const anchorRect = a1Anchor.getBoundingClientRect();
    const anchorX = anchorRect.left + anchorRect.width / 2;
    const anchorY = anchorRect.top + anchorRect.height / 2;
    blackAtBottom = anchorX > boardRect.left + boardRect.width / 2 && anchorY < boardRect.top + boardRect.height / 2;
  }

  const squareFromPoint = (x, y) => {
    if (!boardRect || boardRect.width <= 0 || boardRect.height <= 0) return null;
    const side = Math.min(boardRect.width, boardRect.height);
    const left = boardRect.left + (boardRect.width - side) / 2;
    const top = boardRect.top + (boardRect.height - side) / 2;
    const cell = side / 8;
    const relX = x - left;
    const relY = y - top;
    if (relX < 0 || relY < 0 || relX >= side || relY >= side) return null;
    const col = Math.floor(relX / cell);
    const row = Math.floor(relY / cell);
    if (blackAtBottom) return { file: 8 - col, rank: row + 1 };
    return { file: col + 1, rank: 8 - row };
  };

  const chessComPieces = Array.from(document.querySelectorAll('.piece')).map((el) => {
    const classes = Array.from(el.classList);
    const piece = pieceCode(classes);
    const square = classes.find((name) => /^square-\d\d$/.test(name));
    if (!piece || !square) return null;
    const file = Number(square.slice(7, 8));
    const rank = Number(square.slice(8, 9));
    return { piece, file, rank };
  }).filter(Boolean);

  const piecesFromFen = (fen) => {
    if (!fen || typeof fen !== 'string') return [];
    const boardPart = fen.trim().split(/\s+/)[0];
    if (!boardPart || !boardPart.includes('/')) return [];
    const out = [];
    const rows = boardPart.split('/');
    if (rows.length !== 8) return [];
    const map = { p: 'bp', n: 'bn', b: 'bb', r: 'br', q: 'bq', k: 'bk', P: 'wp', N: 'wn', B: 'wb', R: 'wr', Q: 'wq', K: 'wk' };
    for (let row = 0; row < 8; row++) {
      let file = 1;
      for (const ch of rows[row]) {
        if (/^[1-8]$/.test(ch)) {
          file += Number(ch);
        } else if (map[ch]) {
          out.push({ piece: map[ch], file, rank: 8 - row });
          file += 1;
        } else {
          return [];
        }
      }
      if (file !== 9) return [];
    }
    return out;
  };

  let internalFen = null;
  try {
    internalFen = window.glApp?.panelMgr?.getKernel?.()?.game?.getCurPos?.()?.toFEN?.() || null;
  } catch (err) {
    internalFen = null;
  }
  const internalFenPieces = location.hostname.includes('play.chessbase.com') ? piecesFromFen(internalFen) : [];

  const seenSquares = new Set();
  const directLichessPieces = boardEl ? Array.from(boardEl.querySelectorAll(':scope > piece')) : [];
  const lichessSource = directLichessPieces.length
    ? directLichessPieces
    : (boardEl ? Array.from(boardEl.querySelectorAll('piece')) : []);
  const lichessPieces = lichessSource.map((el) => {
    const classes = Array.from(el.classList);
    if (classes.some((name) => ['ghost', 'fading', 'exploding', 'anim'].includes(name))) return null;
    const piece = pieceCode(classes);
    if (!piece) return null;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (
      rect.width <= 4 ||
      rect.height <= 4 ||
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      Number(style.opacity || '1') <= 0.05
    ) return null;
    const square = squareFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (!square) return null;
    const key = `${square.file}${square.rank}`;
    if (seenSquares.has(key)) return null;
    seenSquares.add(key);
    return { piece, file: square.file, rank: square.rank };
  }).filter(Boolean);

  const chessClubSeenSquares = new Set();
  const chessClubSource = boardEl ? Array.from(boardEl.querySelectorAll('[data-piece]')) : [];
  const chessClubPieces = chessClubSource.map((el) => {
    const piece = pieceCode([el.getAttribute('data-piece'), ...Array.from(el.classList)]);
    if (!piece) return null;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (
      rect.width <= 4 ||
      rect.height <= 4 ||
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      Number(style.opacity || '1') <= 0.05
    ) return null;
    // ChessClub can retain data-square while moving a piece with CSS. The
    // rendered centre is authoritative; the attribute is only a fallback.
    const squareAttr = el.getAttribute('data-square');
    let square = squareFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (!square && squareAttr && /^[a-h][1-8]$/i.test(squareAttr)) {
      square = { file: squareAttr.toLowerCase().charCodeAt(0) - 96, rank: Number(squareAttr[1]) };
    }
    if (!square) return null;
    const key = `${square.file}${square.rank}`;
    if (chessClubSeenSquares.has(key)) return null;
    chessClubSeenSquares.add(key);
    return { piece, file: square.file, rank: square.rank };
  }).filter(Boolean);

  const pieces = internalFenPieces.length ? internalFenPieces : (chessClubPieces.length ? chessClubPieces : (lichessPieces.length ? lichessPieces : chessComPieces));
  let turnFromLastMove = null;
  if (location.hostname.includes('lichess.org') && boardEl) {
    const lastMoveRoot = boardEl.parentElement || boardEl;
    const lastMoveSquares = Array.from(lastMoveRoot.querySelectorAll('square.last-move'))
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return squareFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      })
      .filter(Boolean);
    const occupiedLastMoveSquares = lastMoveSquares
      .map((square) => pieces.find((piece) => piece.file === square.file && piece.rank === square.rank))
      .filter(Boolean);
    if (occupiedLastMoveSquares.length === 1) {
      // The occupied highlighted square is the destination. The other colour
      // moves next, independent of clock markup and move-list rendering.
      turnFromLastMove = occupiedLastMoveSquares[0].piece.startsWith('w') ? 'black' : 'white';
    }
  }
  const moveSelector = location.hostname.includes('lichess.org')
    ? 'l4x kwdb, .analyse__moves move, .moves move'
    : (location.hostname.includes('chess.com')
      ? 'vertical-move-list .node, wc-vertical-move-list .node, .move-list-row .node, .main-line-row .node, .move-text-component'
      : (location.hostname.includes('play.chessclub.com')
        ? '[data-san], .move-list .move, .moves .move, move'
        : 'kwdb, move'));
  const moveNodes = Array.from(document.querySelectorAll(moveSelector));
  const rawMoves = moveNodes
    .map((el) => (el.getAttribute?.('data-san') || el.textContent || '').trim())
    .filter((text) => text && !/^\d+\.*$/.test(text));
  const uniqueMoves = [];
  for (const text of rawMoves) {
    const clean = text.replace(/\s+/g, ' ').trim();
    if (!clean) continue;
    if (uniqueMoves[uniqueMoves.length - 1] !== clean) uniqueMoves.push(clean);
  }
  // Clock markup changes often and differs substantially between the four sites.
  // Keep the selectors site-aware, but also detect the clock whose text changed
  // since the previous poll.  The latter survives renamed active/running classes.
  const clockSelector = location.hostname.includes('lichess.org')
    ? 'rclock, .rclock, [class*="rclock"], [class*="clock"]'
    : (location.hostname.includes('chess.com')
      ? 'wc-chess-clock, .clock-component, [class*="clock"]'
      : (location.hostname.includes('play.chessbase.com')
        ? '[class*="clock"], [id*="clock"], [id*="Clock"]'
        : '[class*="clock"], [id*="clock"], [data-testid*="clock"]'));
  const clockCandidates = Array.from(document.querySelectorAll(clockSelector))
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const ancestry = [el, el.parentElement, el.parentElement?.parentElement]
        .filter(Boolean)
        .map((node) => `${node.className || ''} ${node.id || ''} ${node.getAttribute?.('data-testid') || ''} ${node.getAttribute?.('aria-label') || ''}`)
        .join(' ')
        .toLowerCase();
      const value = (el.textContent || '').replace(/\s+/g, ' ').trim();
      return { el, rect, style, ancestry, value };
    })
    .filter(({ rect, style, value }) =>
      rect.width > 18 && rect.height > 8 &&
      style.display !== 'none' && style.visibility !== 'hidden' &&
      /\d{1,2}\s*[:.]\s*\d{1,2}/.test(value)
    )
    // Nested clock nodes often contain the same text. Prefer the smallest leaf.
    .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
  const distinctClocks = [];
  for (const item of clockCandidates) {
    const y = item.rect.top + item.rect.height / 2;
    if (distinctClocks.some((other) => Math.abs((other.rect.top + other.rect.height / 2) - y) < 6)) continue;
    distinctClocks.push(item);
  }
  const previousClockSample = window.__chessAssistantClockSample || { at: 0, values: {} };
  const currentClockSample = { at: performance.now(), values: {} };
  for (const item of distinctClocks) {
    const position = boardRect && item.rect.top + item.rect.height / 2 > boardRect.top + boardRect.height / 2 ? 'bottom' : 'top';
    currentClockSample.values[position] = item.value;
  }
  window.__chessAssistantClockSample = currentClockSample;
  const changedPositions = Object.keys(currentClockSample.values).filter((position) =>
    previousClockSample.values[position] &&
    previousClockSample.values[position] !== currentClockSample.values[position]
  );
  const classActive = distinctClocks.filter(({ ancestry }) =>
    /(^|[\s_-])(running|active|turn|ticking|is2)([\s_-]|$)/.test(ancestry) &&
    !/(inactive|stopped|paused|expired)/.test(ancestry)
  );
  const activeClock = changedPositions.length === 1
    ? distinctClocks.find((item) => {
        if (!boardRect) return false;
        const position = item.rect.top + item.rect.height / 2 > boardRect.top + boardRect.height / 2 ? 'bottom' : 'top';
        return position === changedPositions[0];
      })?.el || null
    : (classActive.length === 1 ? classActive[0].el : null);
  const clockClasses = activeClock ? Array.from(activeClock.classList) : [];
  const clockHostClasses = activeClock && activeClock.parentElement
    ? Array.from(activeClock.parentElement.classList)
    : [];
  const clockText = [...clockClasses, ...clockHostClasses].join(' ').toLowerCase();
  let activeClockPosition = null;
  if (clockText.includes('bottom') || clockText.includes('lclock') || clockText.includes('clock-bottom')) activeClockPosition = 'bottom';
  if (clockText.includes('top') || clockText.includes('rclock') || clockText.includes('clock-top')) activeClockPosition = 'top';
  if (!activeClockPosition && activeClock && boardRect) {
    const clockRect = activeClock.getBoundingClientRect();
    const clockCenterY = clockRect.top + clockRect.height / 2;
    const boardCenterY = boardRect.top + boardRect.height / 2;
    activeClockPosition = clockCenterY > boardCenterY ? 'bottom' : 'top';
  }
  return {
    url: location.href,
    title: document.title,
    pieces,
    moves: uniqueMoves,
    boardClasses,
    activeClockPosition,
    blackAtBottom,
    internalFen,
    turnFromFen: internalFen && /\s+b\s/.test(internalFen) ? 'black' : (internalFen && /\s+w\s/.test(internalFen) ? 'white' : null),
    turnFromLastMove,
    site: location.hostname.includes('lichess.org') ? 'lichess' : (location.hostname.includes('chess.com') ? 'chess.com' : (location.hostname.includes('play.chessbase.com') ? 'chessbase' : (location.hostname.includes('play.chessclub.com') ? 'chessclub' : 'unknown')))
  };
})()
"""
        payload = self._evaluate(ws_url, script)
        pieces = []
        occupied: set[int] = set()
        for item in payload.get("pieces", []):
            label = PIECE_CODES.get(str(item.get("piece", "")).lower())
            if label is None:
                continue
            file_idx = int(item["file"]) - 1
            rank_idx = int(item["rank"]) - 1
            if 0 <= file_idx <= 7 and 0 <= rank_idx <= 7:
                square = chess.square(file_idx, rank_idx)
                if square in occupied:
                    continue
                occupied.add(square)
                pieces.append(SquarePiece(square_index=square, label=label))
        if not pieces:
            raise DomReadError("DOM không tìm thấy quân cờ trong thẻ hiện tại.")
        if len(pieces) > 32:
            raise DomReadError(f"DOM đọc thừa {len(pieces)} quân; bàn cờ đang có ghost/animation, chờ ổn định.")
        board_snapshot = chess.Board.empty()
        symbols = {
            "white_pawn": "P",
            "white_knight": "N",
            "white_bishop": "B",
            "white_rook": "R",
            "white_queen": "Q",
            "white_king": "K",
            "black_pawn": "p",
            "black_knight": "n",
            "black_bishop": "b",
            "black_rook": "r",
            "black_queen": "q",
            "black_king": "k",
        }
        for piece in pieces:
            symbol = symbols.get(piece.label)
            if symbol:
                board_snapshot.set_piece_at(piece.square_index, chess.Piece.from_symbol(symbol))
        if board_snapshot.king(chess.WHITE) is None or board_snapshot.king(chess.BLACK) is None:
            raise DomReadError("DOM chưa đọc đủ hai vua; bàn cờ có thể đang render/chuyển động hoặc chưa vào ván.")
        move_count = self._move_count(payload.get("moves", []))
        active_clock = payload.get("activeClockPosition")
        site = str(payload.get("site", "unknown"))
        if site == "chessbase":
            exact_fen = self._validated_internal_fen(payload.get("internalFen"), board_snapshot)
        else:
            exact_fen = self._moves_to_exact_fen(payload.get("moves", []), board_snapshot)
        if exact_fen:
            exact_board = chess.Board(exact_fen)
            turn = exact_board.turn
            turn_reliable = True
            turn_source = "danh sách SAN đã kiểm chứng với bàn cờ"
        else:
            turn, turn_reliable, turn_source = self._resolve_turn(payload, move_count)
        status = (
            f"DOM đọc {len(pieces)} quân, {move_count} nước đã đi, "
            f"lượt {'Trắng' if turn == chess.WHITE else 'Đen'} theo {turn_source}."
        )
        return DomBoardState(
            pieces=pieces,
            url=str(payload.get("url", page.get("url", ""))),
            title=str(payload.get("title", "")),
            turn=turn,
            turn_reliable=turn_reliable,
            active_clock_position=str(active_clock) if active_clock in {"top", "bottom"} else None,
            black_at_bottom=bool(payload.get("blackAtBottom", False)),
            site=site,
            exact_fen=exact_fen,
            move_count=move_count,
            status=status,
        )

    def show_best_move(self, move_uci: str, perspective: str, label: str) -> None:
        if len(move_uci) < 4:
            return
        page = self._find_chess_page()
        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise DomReadError("Không tìm thấy WebSocket DevTools của thẻ cờ vua.")

        from_square = move_uci[:2]
        to_square = move_uci[2:4]
        if "play.chessbase.com" in str(page.get("url", "")).lower():
            expression = self._chessbase_native_overlay_script(from_square, to_square)
        else:
            expression = self._overlay_script(from_square, to_square, perspective, label)
        self._evaluate(ws_url, expression)

    def _find_chess_page(self) -> dict:
        try:
            with urlopen(f"{self.endpoint}/json", timeout=0.6) as response:
                pages = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise DomUnavailableError("Không kết nối được cổng DevTools 9222.") from exc
        candidates: list[tuple[int, str, dict]] = []
        for index, page in enumerate(pages):
            url = str(page.get("url", "")).lower()
            title = str(page.get("title", "")).lower()
            page_type = str(page.get("type", "")).lower()
            if page_type != "page":
                continue
            score = 0
            site = ""
            if "lichess.org" in url:
                site = "lichess"
                score += 100
                if self.preferred_site == "lichess":
                    score += 80
                if any(part in url for part in ("/analysis", "/study", "/training", "/practice")):
                    score += 30
                path = url.split("lichess.org", 1)[-1].split("?", 1)[0].strip("/")
                if path and "/" not in path and len(path) >= 6:
                    score += 80
            if "chess.com" in url:
                site = "chess.com"
                score += 100
                if self.preferred_site in {"chess.com", "chesscom"}:
                    score += 80
                if any(part in url for part in ("/game/", "/play/", "/analysis")):
                    score += 60
            if "play.chessbase.com" in url:
                site = "chessbase"
                score += 100
                if self.preferred_site in {"chessbase", "play.chessbase.com"}:
                    score += 80
                if "/play" in url:
                    score += 60
            if "play.chessclub.com" in url:
                site = "chessclub"
                score += 100
                if self.preferred_site in {"chessclub", "icc", "play.chessclub.com"}:
                    score += 80
            if "chess" in title:
                score += 5
            if score:
                if self.target_id and str(page.get("id", "")) == self.target_id:
                    return page
                # Chrome DevTools usually lists the most recently opened/active tabs first.
                # Keep the site preference as a tie-breaker, but do not let a stale
                # chess.com preference hide a newer Lichess board tab.
                candidates.append((score - index * 25, site, page))
        if candidates:
            preferred_aliases = {
                "chesscom": "chess.com",
                "play.chessbase.com": "chessbase",
                "icc": "chessclub",
                "play.chessclub.com": "chessclub",
            }
            preferred = preferred_aliases.get(self.preferred_site, self.preferred_site)
            if preferred != "auto":
                matching = [item for item in candidates if item[1] == preferred]
                if matching:
                    # Once the user explicitly chooses a site, never let an
                    # older tab from another provider win by tab-order score.
                    return max(matching, key=lambda item: item[0])[2]
                raise DomUnavailableError(
                    f"Đang chờ tab {preferred} tải xong; không dùng tạm bàn cờ từ website khác."
                )
            return max(candidates, key=lambda item: item[0])[2]
        raise DomUnavailableError(
            "Chưa tìm thấy trang cờ vua. Ứng dụng đang chờ trình duyệt tải xong."
        )

    def _evaluate(self, ws_url: str, expression: str) -> dict:
        try:
            ws = websocket.create_connection(ws_url, timeout=1.5, suppress_origin=True)
        except Exception as exc:
            raise DomReadError(f"Không kết nối được WebSocket DOM: {exc}") from exc
        try:
            message_id = next(self._message_ids)
            ws.send(
                json.dumps(
                    {
                        "id": message_id,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "returnByValue": True,
                            "awaitPromise": False,
                        },
                    }
                )
            )
            while True:
                message = json.loads(ws.recv())
                if message.get("id") != message_id:
                    continue
                result = message.get("result", {}).get("result", {})
                if "value" in result:
                    return dict(result["value"])
                raise DomReadError("DevTools không trả về dữ liệu bàn cờ.")
        finally:
            ws.close()

    @staticmethod
    def _move_count(moves: object) -> int:
        if not isinstance(moves, list):
            return 0
        count = 0
        for move in moves:
            text = str(move).strip()
            if not text:
                continue
            if text in {"...", "1-0", "0-1", "1/2-1/2", "*"}:
                continue
            count += 1
        return count

    @staticmethod
    def _moves_to_exact_fen(moves: object, observed: chess.Board) -> str | None:
        if not isinstance(moves, list) or not moves:
            return None
        figurines = str.maketrans({
            "♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N",
            "♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N",
        })
        san_moves: list[str] = []
        for raw_move in moves:
            text = str(raw_move).translate(figurines).replace("\u00a0", " ").strip()
            if not text:
                continue
            for token in text.split():
                token = re.sub(r"^\d+\.(?:\.\.)?", "", token).strip()
                token = re.sub(r"[!?]+$", "", token)
                if not token or token.startswith("$") or token in {
                    "...", "1-0", "0-1", "1/2-1/2", "*",
                }:
                    continue
                san_moves.append(token)
        if not san_moves:
            return None

        board = chess.Board()
        try:
            for san in san_moves:
                board.push_san(san)
        except (ValueError, AssertionError):
            return None
        if board.board_fen() != observed.board_fen():
            return None
        return board.fen()

    @staticmethod
    def _validated_internal_fen(fen: object, observed: chess.Board) -> str | None:
        if not isinstance(fen, str):
            return None
        try:
            board = chess.Board(fen)
        except ValueError:
            return None
        return board.fen() if board.board_fen() == observed.board_fen() else None

    @staticmethod
    def _resolve_turn(payload: dict, move_count: int) -> tuple[chess.Color, bool, str]:
        active_clock = payload.get("activeClockPosition")
        turn_from_fen = str(payload.get("turnFromFen", "")).lower()
        # ChessBase exposes an exact FEN from its game object. It is stronger
        # evidence than CSS clock state, especially while a clock is paused.
        if turn_from_fen in {"white", "black"}:
            return (
                chess.WHITE if turn_from_fen == "white" else chess.BLACK,
                True,
                "FEN nội bộ trang",
            )
        turn_from_last_move = str(payload.get("turnFromLastMove", "")).lower()
        if turn_from_last_move in {"white", "black"}:
            return (
                chess.WHITE if turn_from_last_move == "white" else chess.BLACK,
                True,
                "ô nước đi cuối",
            )
        if active_clock in {"top", "bottom"}:
            bottom_color = chess.BLACK if bool(payload.get("blackAtBottom", False)) else chess.WHITE
            turn = bottom_color if active_clock == "bottom" else not bottom_color
            return turn, True, "đồng hồ đang chạy"
        return (
            chess.WHITE if move_count % 2 == 0 else chess.BLACK,
            False,
            "chẵn/lẻ danh sách nước",
        )

    @staticmethod
    def _chessbase_native_overlay_script(from_square: str, to_square: str) -> str:
        data = json.dumps({"from": from_square, "to": to_square})
        return f"""
(() => {{
  const data = {data};
  const toIndex = (square) => {{
    if (!/^[a-h][1-8]$/.test(square || '')) return null;
    return (Number(square[1]) - 1) * 8 + square.charCodeAt(0) - 97;
  }};
  const from = toIndex(data.from);
  const to = toIndex(data.to);
  const boardWin = window.glApp?.panelMgr?.getKernel?.()?.boardWin;
  if (!boardWin || from === null || to === null) return {{ok: false}};

  // Remove the old pixel overlay from earlier versions. ChessBase's native
  // board renderer owns zoom, padding, orientation and high-DPI conversion.
  document.getElementById('chess-assistant-web-overlay')?.remove();
  boardWin.undoAttributes?.();
  // Arguments 4/5 keep the attributes across ChessBase's frequent canvas
  // redraws and render them immediately. Calling redraw() here used to erase
  // the temporary marks before the browser presented the frame.
  boardWin.markSquare(from, 'hsla(0, 75%, 50%, 0.70)', undefined, true, false);
  boardWin.markSquare(to, 'hsla(135, 65%, 42%, 0.72)', undefined, true, false);
  boardWin.drawArrow?.(from, to, 'hsla(135, 70%, 38%, 0.88)', undefined, true);
  return {{ok: true}};
}})()
"""

    @staticmethod
    def _overlay_script(from_square: str, to_square: str, perspective: str, label: str) -> str:
        payload = {
            "from": from_square,
            "to": to_square,
            "perspective": perspective,
            "label": label,
        }
        data = json.dumps(payload)
        return f"""
(() => {{
  const data = {data};
  const files = {{a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8}};
  const parseSquare = (sq) => [files[sq[0]], Number(sq[1])];
  const [fromFile, fromRank] = parseSquare(data.from);
  const [toFile, toRank] = parseSquare(data.to);
  if (!fromFile || !toFile || !fromRank || !toRank) return {{ok: false}};

  const findBoard = () => {{
    const cached = window.__chessAssistantMainBoard;
    if (cached && cached.isConnected) {{
      const rect = cached.getBoundingClientRect();
      if (rect.width > 250 && rect.height > 250 && Math.abs(rect.width - rect.height) < rect.width * 0.15) return cached;
    }}
    const selector = location.hostname.includes('lichess.org')
      ? 'cg-board'
      : (location.hostname.includes('play.chessbase.com')
        ? '#boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas'
        : 'wc-chess-board, chess-board, cg-board, .cg-wrap, .board, .chess-board, #board-single, [data-boardid], #boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas');
    const candidates = Array.from(document.querySelectorAll(selector))
      .map((el) => ({{ el, rect: el.getBoundingClientRect() }}))
      .filter((item) => item.rect.width > 250 && Math.abs(item.rect.width - item.rect.height) < item.rect.width * 0.15)
      .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
    if (candidates.length) {{
      window.__chessAssistantMainBoard = candidates[0].el;
      return candidates[0].el;
    }}
    const piece = document.querySelector('.piece, [data-piece], cg-board piece');
    if (!piece) return null;
    let node = piece.parentElement;
    while (node && node !== document.body) {{
      const rect = node.getBoundingClientRect();
      if (rect.width > 250 && Math.abs(rect.width - rect.height) < rect.width * 0.12) {{
        window.__chessAssistantMainBoard = node;
        return node;
      }}
      node = node.parentElement;
    }}
    return null;
  }};

  const board = findBoard();
  if (!board) return {{ok: false, reason: 'board not found'}};
  const rect = board.getBoundingClientRect();
  const side = Math.min(rect.width, rect.height);
  const left = rect.left + (rect.width - side) / 2;
  const top = rect.top + (rect.height - side) / 2;
  const square = side / 8;
  const boardText = [board, board.parentElement, board.parentElement?.parentElement]
    .filter(Boolean)
    .map((el) => `${{el.className || ''}} ${{el.getAttribute?.('data-orientation') || ''}} ${{el.getAttribute?.('orientation') || ''}}`)
    .join(' ')
    .toLowerCase();
  let blackAtBottom =
    boardText.includes('flipped') ||
    boardText.includes('orientation-black') ||
    boardText.includes('orientation black');
  try {{
    const chessBaseOrientation = window.glApp?.panelMgr?.getKernel?.()?.boardWin?.blackIsBottom;
    if (typeof chessBaseOrientation === 'boolean') blackAtBottom = chessBaseOrientation;
  }} catch (err) {{
    // Keep the DOM orientation fallback.
  }}

  const center = (file, rank) => {{
    let col;
    let row;
    if (blackAtBottom) {{
      col = 8 - file;
      row = rank - 1;
    }} else {{
      col = file - 1;
      row = 8 - rank;
    }}
    return {{
      x: left + (col + 0.5) * square,
      y: top + (row + 0.5) * square
    }};
  }};

  const start = center(fromFile, fromRank);
  const end = center(toFile, toRank);
  const old = document.getElementById('chess-assistant-web-overlay');
  if (old) old.remove();

  const overlay = document.createElement('div');
  overlay.id = 'chess-assistant-web-overlay';
  overlay.style.position = 'fixed';
  overlay.style.left = '0';
  overlay.style.top = '0';
  overlay.style.width = '100vw';
  overlay.style.height = '100vh';
  overlay.style.pointerEvents = 'none';
  overlay.style.zIndex = '2147483647';

  const makeSquare = (point, color) => {{
    const mark = document.createElement('div');
    mark.style.position = 'fixed';
    mark.style.left = `${{point.x - square * 0.5}}px`;
    mark.style.top = `${{point.y - square * 0.5}}px`;
    mark.style.width = `${{square}}px`;
    mark.style.height = `${{square}}px`;
    mark.style.boxSizing = 'border-box';
    mark.style.border = `${{Math.max(4, square * 0.075)}}px solid ${{color}}`;
    mark.style.background = 'transparent';
    mark.style.boxShadow = '0 0 0 2px rgba(255,255,255,0.55), 0 0 12px rgba(0,0,0,0.28)';
    return mark;
  }};

  const fromMark = makeSquare(start, '#dc2626');
  const toMark = makeSquare(end, '#16a34a');

  overlay.appendChild(fromMark);
  overlay.appendChild(toMark);
  document.documentElement.appendChild(overlay);
  return {{ok: true}};
}})()
"""
