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
    turn_source: str
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
    const selector = location.hostname.includes('lichess.org')
      ? 'main.round cg-board, main.analyse cg-board, main.study cg-board, cg-board'
      : (location.hostname.includes('play.chessbase.com')
        ? '#boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas'
        : 'wc-chess-board, chess-board, cg-board, .cg-wrap, .board, .chess-board, #board-single, [data-boardid], #boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas');
    const contextText = (el) => {
      const nodes = [];
      let node = el;
      for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) nodes.push(node);
      return nodes
        .map((item) => `${item.tagName || ''} ${item.id || ''} ${item.className || ''} ${item.getAttribute?.('data-testid') || ''}`)
        .join(' ')
        .toLowerCase();
    };
    const scoreBoard = (el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const side = Math.min(rect.width, rect.height);
      if (
        side < 140 ||
        Math.abs(rect.width - rect.height) > side * 0.18 ||
        style.display === 'none' ||
        style.visibility === 'hidden'
      ) return null;
      const context = contextText(el);
      let score = side * side;
      if (el === cached) score += 50000;
      if (/\b(round|analyse|analysis|game|live|board-layout|board-main)\b/.test(context)) score += 500000;
      if (/\b(mini|mini-board|miniboard|thumbnail|preview|advert|advertisement|promo)\b/.test(context)) score -= 1000000;
      if (el.matches?.('wc-chess-board, chess-board, cg-board, #board-single, #boardRoot0 canvas')) score += 100000;
      return { el, rect, score };
    };
    const candidates = Array.from(document.querySelectorAll(selector))
      .map(scoreBoard)
      .filter(Boolean)
      // Piece count must not affect selection: captures would otherwise make
      // the reader jump to a fuller mini-board during the game.
      .sort((a, b) => b.score - a.score);
    if (candidates.length) {
      window.__chessAssistantMainBoard = candidates[0].el;
      return candidates[0].el;
    }
    const piece = document.querySelector('.piece, cg-board piece');
    if (!piece) return null;
    let node = piece.parentElement;
    while (node && node !== document.body) {
      const rect = node.getBoundingClientRect();
      if (rect.width > 140 && Math.abs(rect.width - rect.height) < rect.width * 0.12) {
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

  const chessComSource = boardEl
    ? Array.from(boardEl.querySelectorAll('.piece'))
    : Array.from(document.querySelectorAll('.piece'));
  const chessComPieces = chessComSource.map((el) => {
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
  const firstMoveNodes = (selectors) => {
    for (const selector of selectors) {
      const nodes = Array.from(document.querySelectorAll(selector));
      if (nodes.length) return nodes;
    }
    return [];
  };
  const moveNodes = location.hostname.includes('lichess.org')
    ? firstMoveNodes(['l4x kwdb', '.analyse__moves move', '.moves move'])
    : (location.hostname.includes('chess.com')
      ? firstMoveNodes([
          'vertical-move-list .node',
          'wc-vertical-move-list .node',
          '.move-list-row .node',
          '.main-line-row .node',
          '.move-text-component'
        ])
      : (location.hostname.includes('play.chessclub.com')
        ? firstMoveNodes(['[data-san]', '.move-list .move', '.moves .move', 'move'])
        : firstMoveNodes(['kwdb', 'move'])));
  const rawMoves = moveNodes
    .map((el) => (el.getAttribute?.('data-san') || el.textContent || '').trim())
    .filter((text) => text && !/^\d+\.*$/.test(text));
  // querySelectorAll already returns each DOM node once even when it matches
  // multiple selectors. Never collapse equal adjacent SAN: O-O O-O and many
  // repeated manoeuvres are valid consecutive moves by opposite colours.
  const uniqueMoves = rawMoves
    .map((text) => text.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  // Clock markup changes often and differs substantially between the four sites.
  // Keep the selectors site-aware, but also detect the clock whose text changed
  // since the previous poll.  The latter survives renamed active/running classes.
  const clockSelector = location.hostname.includes('lichess.org')
    ? 'rclock, .rclock'
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
  const lichessRunningClock = location.hostname.includes('lichess.org')
    ? distinctClocks.find(({ el }) => el.classList.contains('running'))?.el || null
    : null;
  const chessComActiveClock = location.hostname.includes('chess.com')
    ? document.querySelector('.clock-player-turn, .clock-component.clock-player-turn')
    : null;
  const chessClubActiveClock = location.hostname.includes('play.chessclub.com')
    ? document.querySelector('[data-testid*="clock"].running, [data-testid*="clock"].active, .clock.running, .clock.active')
    : null;
  const activeClock = lichessRunningClock || chessComActiveClock || chessClubActiveClock || (classActive.length === 1
    ? classActive[0].el
    : (changedPositions.length === 1
      ? distinctClocks.find((item) => {
        if (!boardRect) return false;
        const position = item.rect.top + item.rect.height / 2 > boardRect.top + boardRect.height / 2 ? 'bottom' : 'top';
        return position === changedPositions[0];
      })?.el || null
      : null));
  const clockClasses = activeClock ? Array.from(activeClock.classList) : [];
  const clockHostClasses = activeClock && activeClock.parentElement
    ? Array.from(activeClock.parentElement.classList)
    : [];
  const clockText = [...clockClasses, ...clockHostClasses].join(' ').toLowerCase();
  let activeClockPosition = null;
  if (clockText.includes('rclock-bottom') || clockText.includes('clock-bottom')) {
    activeClockPosition = 'bottom';
  } else if (clockText.includes('rclock-top') || clockText.includes('clock-top')) {
    activeClockPosition = 'top';
  } else if (clockClasses.includes('lclock') || clockHostClasses.includes('lclock')) {
    activeClockPosition = 'bottom';
  } else if (clockClasses.includes('rclock') || clockHostClasses.includes('rclock')) {
    activeClockPosition = 'top';
  }
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
            turn_source=turn_source,
            active_clock_position=str(active_clock) if active_clock in {"top", "bottom"} else None,
            black_at_bottom=bool(payload.get("blackAtBottom", False)),
            site=site,
            exact_fen=exact_fen,
            move_count=move_count,
            status=status,
        )

    def show_best_move(self, move_uci: str, perspective: str, label: str) -> None:
        self.show_moves(
            [{"uci": move_uci, "label": label, "score": "", "rank": 1, "color": "#4ade80"}],
            perspective,
        )

    def show_moves(self, moves: list[dict[str, object]], perspective: str) -> None:
        valid_moves = [move for move in moves[:4] if len(str(move.get("uci", ""))) >= 4]
        if not valid_moves:
            return
        page = self._find_chess_page()
        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise DomReadError("Không tìm thấy WebSocket DevTools của thẻ cờ vua.")

        first_uci = str(valid_moves[0]["uci"])
        from_square = first_uci[:2]
        to_square = first_uci[2:4]
        if "play.chessbase.com" in str(page.get("url", "")).lower():
            expression = self._chessbase_native_overlay_script(from_square, to_square)
        else:
            expression = self._moves_overlay_script(valid_moves, perspective)
        self._evaluate(ws_url, expression)

    def clear_best_move(self) -> None:
        page = self._find_chess_page()
        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise DomReadError("Không tìm thấy WebSocket DevTools của thẻ cờ vua.")
        expression = r"""
(() => {
  window.__chessAssistantOverlayCleanup?.();
  document.getElementById('chess-assistant-web-overlay')?.remove();
  if (location.hostname.includes('play.chessbase.com')) {
    window.glApp?.panelMgr?.getKernel?.()?.boardWin?.undoAttributes?.();
  }
  return {ok: true};
})()
"""
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
                # A remembered preference must not force image recognition
                # when another supported chess tab is already available.
                return max(candidates, key=lambda item: item[0])[2]
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
                # Lichess can render symbolic NAGs as Unicode suffixes. Some
                # fonts expose ?! as the observed "½?" sequence.
                token = re.sub(r"[!?‼⁇⁉⁈½□⟳]+$", "", token)
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
        data = json.dumps({
            "from": DomBoardReader._chessbase_square_index(from_square),
            "to": DomBoardReader._chessbase_square_index(to_square),
        })
        return f"""
(() => {{
  const data = {data};
  const from = data.from;
  const to = data.to;
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
    def _chessbase_square_index(square: str) -> int | None:
        if not re.fullmatch(r"[a-h][1-8]", square or ""):
            return None
        return (ord(square[0]) - ord("a")) * 8 + int(square[1]) - 1

    @staticmethod
    def _overlay_script(from_square: str, to_square: str, perspective: str, label: str) -> str:
        return DomBoardReader._moves_overlay_script(
            [{"uci": from_square + to_square, "label": label, "score": "", "rank": 1, "color": "#4ade80"}],
            perspective,
        )

    @staticmethod
    def _moves_overlay_script(moves: list[dict[str, object]], perspective: str) -> str:
        payload = {"moves": moves[:4], "perspective": perspective}
        data = json.dumps(payload, ensure_ascii=False)
        return f"""
(() => {{
  const data = {data};
  const files = {{a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8}};
  const parseSquare = (sq) => [files[sq[0]], Number(sq[1])];
  const moves = data.moves.map((move, index) => {{
    const uci = String(move.uci || '');
    const [fromFile, fromRank] = parseSquare(uci.slice(0, 2));
    const [toFile, toRank] = parseSquare(uci.slice(2, 4));
    return {{...move, rank: Number(move.rank || index + 1), fromFile, fromRank, toFile, toRank}};
  }}).filter((move) => move.fromFile && move.toFile && move.fromRank && move.toRank);
  if (!moves.length) return {{ok: false}};

  const findBoard = () => {{
    const cached = window.__chessAssistantMainBoard;
    const selector = location.hostname.includes('lichess.org')
      ? 'main.round cg-board, main.analyse cg-board, main.study cg-board, cg-board'
      : (location.hostname.includes('play.chessbase.com')
        ? '#boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas'
        : 'wc-chess-board, chess-board, cg-board, .cg-wrap, .board, .chess-board, #board-single, [data-boardid], #boardRoot0 canvas, .boardRoot canvas, .boardHolder canvas');
    const contextText = (el) => {{
      const nodes = [];
      let node = el;
      for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) nodes.push(node);
      return nodes
        .map((item) => `${{item.tagName || ''}} ${{item.id || ''}} ${{item.className || ''}} ${{item.getAttribute?.('data-testid') || ''}}`)
        .join(' ')
        .toLowerCase();
    }};
    const scoreBoard = (el) => {{
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const side = Math.min(rect.width, rect.height);
      if (
        side < 140 ||
        Math.abs(rect.width - rect.height) > side * 0.18 ||
        style.display === 'none' ||
        style.visibility === 'hidden'
      ) return null;
      const context = contextText(el);
      let score = side * side;
      if (el === cached) score += 50000;
      if (/\\b(round|analyse|analysis|game|live|board-layout|board-main)\\b/.test(context)) score += 500000;
      if (/\\b(mini|mini-board|miniboard|thumbnail|preview|advert|advertisement|promo)\\b/.test(context)) score -= 1000000;
      if (el.matches?.('wc-chess-board, chess-board, cg-board, #board-single, #boardRoot0 canvas')) score += 100000;
      return {{ el, rect, score }};
    }};
    const candidates = Array.from(document.querySelectorAll(selector))
      .map(scoreBoard)
      .filter(Boolean)
      .sort((a, b) => b.score - a.score);
    if (candidates.length) {{
      window.__chessAssistantMainBoard = candidates[0].el;
      return candidates[0].el;
    }}
    const piece = document.querySelector('.piece, [data-piece], cg-board piece');
    if (!piece) return null;
    let node = piece.parentElement;
    while (node && node !== document.body) {{
      const rect = node.getBoundingClientRect();
      if (rect.width > 140 && Math.abs(rect.width - rect.height) < rect.width * 0.12) {{
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
  // ChessClub does not consistently expose an orientation class. Start from
  // the user-selected perspective, then prefer orientation evidence from the
  // rendered board when the site provides it.
  let blackAtBottom = data.perspective === 'black';
  if (
    boardText.includes('flipped') ||
    boardText.includes('orientation-black') ||
    boardText.includes('orientation black')
  ) blackAtBottom = true;
  if (
    boardText.includes('orientation-white') ||
    boardText.includes('orientation white')
  ) blackAtBottom = false;
  try {{
    const chessBaseOrientation = window.glApp?.panelMgr?.getKernel?.()?.boardWin?.blackIsBottom;
    if (typeof chessBaseOrientation === 'boolean') blackAtBottom = chessBaseOrientation;
  }} catch (err) {{
    // Keep the DOM orientation fallback.
  }}

  // data-square is orientation-independent. Its rendered position is the
  // strongest signal on ChessClub, where the flipped state may have no class.
  const a1Anchor = board.querySelector?.('[data-square="a1"]');
  if (a1Anchor) {{
    const anchorRect = a1Anchor.getBoundingClientRect();
    const anchorX = anchorRect.left + anchorRect.width / 2;
    const anchorY = anchorRect.top + anchorRect.height / 2;
    blackAtBottom = anchorX > rect.left + rect.width / 2 && anchorY < rect.top + rect.height / 2;
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

  const old = document.getElementById('chess-assistant-web-overlay');
  window.__chessAssistantOverlayCleanup?.();
  if (old) old.remove();

  const overlay = document.createElement('div');
  overlay.id = 'chess-assistant-web-overlay';
  overlay.style.position = 'fixed';
  overlay.style.left = '0';
  overlay.style.top = '0';
  overlay.style.width = '100vw';
  overlay.style.height = '100vh';
  overlay.style.pointerEvents = 'none';
  overlay.style.setProperty('z-index', '2147483647', 'important');
  overlay.style.isolation = 'isolate';

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '100%');
  svg.style.position = 'fixed';
  svg.style.inset = '0';
  svg.style.overflow = 'visible';
  svg.style.zIndex = '0';
  svg.style.filter = 'drop-shadow(0 2px 2px rgba(0,0,0,.75))';
  overlay.appendChild(svg);

  const makeSquare = (point, color, opacity = 1) => {{
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
    mark.style.opacity = String(opacity);
    return mark;
  }};

  const rolePriority = (move) => {{
    const role = String(move.role || '');
    if (role.includes('E') && role.includes('T')) return 4;
    if (role.includes('E')) return 3;
    if (role.includes('T')) return 2;
    return 0;
  }};
  // Paint ordinary candidates first. E/T candidates are appended last, so
  // their SVG arrows remain on top when several paths overlap.
  const renderMoves = [...moves].sort((a, b) => rolePriority(a) - rolePriority(b));
  const marks = renderMoves.map((move) => {{
    const color = String(move.color || '#cbd5e1');
    const priority = rolePriority(move);
    const hasRole = priority > 0;
    const start = center(move.fromFile, move.fromRank);
    const end = center(move.toFile, move.toRank);
    // The source is deliberately neutral: several candidate moves can start
    // from the same piece. The colored arrow is the unambiguous pairing.
    const fromMark = makeSquare(start, '#f8fafc', 0.72);
    fromMark.style.borderStyle = 'dashed';
    fromMark.style.zIndex = String(hasRole ? 30 + priority : 10);
    const toMark = makeSquare(end, color);
    toMark.style.zIndex = String(hasRole ? 32 + priority : 12);
    const arrowOutline = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    arrowOutline.setAttribute('stroke', 'rgba(2,6,23,.9)');
    arrowOutline.setAttribute('stroke-linecap', 'round');
    arrowOutline.setAttribute('opacity', hasRole ? '1' : '.48');
    const arrowLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    arrowLine.setAttribute('stroke', color);
    arrowLine.setAttribute('stroke-linecap', 'round');
    arrowLine.setAttribute('opacity', hasRole ? '1' : '.52');
    const arrowHead = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    arrowHead.setAttribute('fill', color);
    arrowHead.setAttribute('stroke', 'rgba(2,6,23,.9)');
    arrowHead.setAttribute('stroke-width', '2');
    arrowHead.setAttribute('opacity', hasRole ? '1' : '.58');
    svg.appendChild(arrowOutline);
    svg.appendChild(arrowLine);
    svg.appendChild(arrowHead);

    const midBadge = document.createElement('div');
    midBadge.style.position = 'fixed';
    midBadge.style.width = `${{Math.max(22, square * 0.30)}}px`;
    midBadge.style.height = `${{Math.max(22, square * 0.30)}}px`;
    midBadge.style.boxSizing = 'border-box';
    midBadge.style.borderRadius = '999px';
    midBadge.style.background = '#08111f';
    midBadge.style.color = color;
    midBadge.style.border = `2px solid ${{color}}`;
    midBadge.style.font = `900 ${{Math.max(12, square * 0.18)}}px/1 system-ui, sans-serif`;
    midBadge.style.display = 'flex';
    midBadge.style.alignItems = 'center';
    midBadge.style.justifyContent = 'center';
    midBadge.style.filter = 'drop-shadow(0 2px 3px rgba(0,0,0,.8))';
    midBadge.style.zIndex = String(hasRole ? 40 + priority : 20);
    midBadge.style.opacity = hasRole ? '1' : '.72';
    midBadge.textContent = String(move.rank);
    const badge = document.createElement('div');
    badge.style.position = 'fixed';
    badge.style.minWidth = `${{Math.max(22, square * 0.32)}}px`;
    badge.style.height = `${{Math.max(22, square * 0.32)}}px`;
    badge.style.padding = '0 5px';
    badge.style.boxSizing = 'border-box';
    badge.style.borderRadius = '999px';
    badge.style.background = color;
    badge.style.color = '#08111f';
    badge.style.border = '2px solid white';
    badge.style.font = `800 ${{Math.max(12, square * 0.18)}}px/1 system-ui, sans-serif`;
    badge.style.display = 'flex';
    badge.style.alignItems = 'center';
    badge.style.justifyContent = 'center';
    badge.style.whiteSpace = 'nowrap';
    badge.style.filter = 'drop-shadow(0 2px 3px rgba(0,0,0,.65))';
    badge.style.zIndex = String(hasRole ? 50 + priority : 22);
    badge.style.opacity = hasRole ? '1' : '.76';
    badge.textContent = [
      `#${{move.rank}}`,
      move.role ? String(move.role) : '',
      move.score ? String(move.score) : '',
    ].filter(Boolean).join(' · ');
    overlay.appendChild(fromMark);
    overlay.appendChild(toMark);
    overlay.appendChild(midBadge);
    overlay.appendChild(badge);
    return {{move, priority, hasRole, fromMark, toMark, arrowOutline, arrowLine, arrowHead, midBadge, badge}};
  }});
  document.documentElement.appendChild(overlay);

  const updateOverlay = () => {{
    if (!board.isConnected || !overlay.isConnected) return;
    const currentRect = board.getBoundingClientRect();
    const currentSide = Math.min(currentRect.width, currentRect.height);
    if (currentSide <= 0) return;
    const currentLeft = currentRect.left + (currentRect.width - currentSide) / 2;
    const currentTop = currentRect.top + (currentRect.height - currentSide) / 2;
    const currentSquare = currentSide / 8;
    const currentText = [board, board.parentElement, board.parentElement?.parentElement]
      .filter(Boolean)
      .map((el) => `${{el.className || ''}} ${{el.getAttribute?.('data-orientation') || ''}} ${{el.getAttribute?.('orientation') || ''}}`)
      .join(' ')
      .toLowerCase();
    let currentBlackAtBottom = data.perspective === 'black';
    if (currentText.includes('flipped') || currentText.includes('orientation-black') || currentText.includes('orientation black')) currentBlackAtBottom = true;
    if (currentText.includes('orientation-white') || currentText.includes('orientation white')) currentBlackAtBottom = false;
    const currentA1 = board.querySelector?.('[data-square="a1"]');
    if (currentA1) {{
      const anchor = currentA1.getBoundingClientRect();
      currentBlackAtBottom =
        anchor.left + anchor.width / 2 > currentRect.left + currentRect.width / 2 &&
        anchor.top + anchor.height / 2 < currentRect.top + currentRect.height / 2;
    }}
    const currentCenter = (file, rank) => {{
      const col = currentBlackAtBottom ? 8 - file : file - 1;
      const row = currentBlackAtBottom ? rank - 1 : 8 - rank;
      return {{
        x: currentLeft + (col + 0.5) * currentSquare,
        y: currentTop + (row + 0.5) * currentSquare,
      }};
    }};
    const placeMark = (mark, point) => {{
      mark.style.left = `${{point.x - currentSquare * 0.5}}px`;
      mark.style.top = `${{point.y - currentSquare * 0.5}}px`;
      mark.style.width = `${{currentSquare}}px`;
      mark.style.height = `${{currentSquare}}px`;
      mark.style.borderWidth = `${{Math.max(4, currentSquare * 0.075)}}px`;
    }};
    marks.forEach((item) => {{
      const start = currentCenter(item.move.fromFile, item.move.fromRank);
      const end = currentCenter(item.move.toFile, item.move.toRank);
      placeMark(item.fromMark, start);
      placeMark(item.toMark, end);
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const ux = dx / distance;
      const uy = dy / distance;
      const lineStart = {{x: start.x + ux * currentSquare * 0.24, y: start.y + uy * currentSquare * 0.24}};
      const tip = {{x: end.x - ux * currentSquare * 0.18, y: end.y - uy * currentSquare * 0.18}};
      const headLength = Math.max(13, currentSquare * 0.24);
      const headWidth = Math.max(8, currentSquare * 0.15);
      const base = {{x: tip.x - ux * headLength, y: tip.y - uy * headLength}};
      const px = -uy;
      const py = ux;
      const setLine = (line) => {{
        line.setAttribute('x1', String(lineStart.x));
        line.setAttribute('y1', String(lineStart.y));
        line.setAttribute('x2', String(base.x));
        line.setAttribute('y2', String(base.y));
      }};
      setLine(item.arrowOutline);
      setLine(item.arrowLine);
      item.arrowOutline.setAttribute(
        'stroke-width', String(Math.max(item.hasRole ? 10 : 7, currentSquare * (item.hasRole ? 0.17 : 0.12)))
      );
      item.arrowLine.setAttribute(
        'stroke-width', String(Math.max(item.hasRole ? 6 : 4, currentSquare * (item.hasRole ? 0.105 : 0.072)))
      );
      item.arrowHead.setAttribute(
        'points',
        `${{tip.x}},${{tip.y}} ${{base.x + px * headWidth}},${{base.y + py * headWidth}} ` +
        `${{base.x - px * headWidth}},${{base.y - py * headWidth}}`
      );
      const midX = lineStart.x + (base.x - lineStart.x) * 0.52;
      const midY = lineStart.y + (base.y - lineStart.y) * 0.52;
      const midSize = Math.max(22, currentSquare * 0.30);
      item.midBadge.style.left = `${{midX - midSize / 2}}px`;
      item.midBadge.style.top = `${{midY - midSize / 2}}px`;
      item.midBadge.style.width = `${{midSize}}px`;
      item.midBadge.style.height = `${{midSize}}px`;
      item.midBadge.style.fontSize = `${{Math.max(12, currentSquare * 0.18)}}px`;
      const badgeHeight = Math.max(22, currentSquare * 0.32);
      item.badge.style.left = `${{end.x - currentSquare * 0.46}}px`;
      item.badge.style.top = `${{end.y - currentSquare * 0.46}}px`;
      item.badge.style.height = `${{badgeHeight}}px`;
      item.badge.style.minWidth = `${{badgeHeight}}px`;
      item.badge.style.fontSize = `${{Math.max(12, currentSquare * 0.18)}}px`;
    }});
  }};

  const resizeObserver = typeof ResizeObserver === 'function'
    ? new ResizeObserver(updateOverlay)
    : null;
  resizeObserver?.observe(board);
  window.addEventListener('resize', updateOverlay, {{ passive: true }});
  document.addEventListener('fullscreenchange', updateOverlay);
  window.__chessAssistantOverlayCleanup = () => {{
    resizeObserver?.disconnect();
    window.removeEventListener('resize', updateOverlay);
    document.removeEventListener('fullscreenchange', updateOverlay);
    window.__chessAssistantOverlayCleanup = null;
  }};
  updateOverlay();
  return {{ok: true, moveCount: moves.length}};
}})()
"""
