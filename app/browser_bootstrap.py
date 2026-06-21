from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request
from urllib.request import urlopen


DEVTOOLS_ENDPOINT = "http://127.0.0.1:9222"
DEFAULT_CHESS_URL = "https://www.chess.com/play/computer"
CHESS_COM_URL = "https://www.chess.com/play/online"
LICHESS_URL = "https://lichess.org/"
CHESSBASE_URL = "https://play.chessbase.com/en/Play"
CHESSCLUB_URL = "https://play.chessclub.com/"


@dataclass(frozen=True)
class BrowserLaunchResult:
    ready: bool
    browser_name: str = ""
    message: str = ""


def ensure_chess_browser(timeout_seconds: float = 10.0) -> BrowserLaunchResult:
    if _devtools_ready():
        if not _chess_page_ready():
            _open_chess_tab()
        return BrowserLaunchResult(True, message="Đã kết nối với trình duyệt.")

    browser = _find_browser()
    if browser is None:
        return BrowserLaunchResult(
            False,
            message=(
                "Không tìm thấy trình duyệt tương thích. Hãy cài Cốc Cốc, "
                "Google Chrome, Microsoft Edge hoặc Brave."
            ),
        )

    browser_name, executable, profile_name = browser
    profile_dir = Path(tempfile.gettempdir()) / profile_name
    command = [
        str(executable),
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        DEFAULT_CHESS_URL,
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as exc:
        return BrowserLaunchResult(
            False,
            browser_name=browser_name,
            message=f"Không thể mở {browser_name}: {exc}",
        )

    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    while time.monotonic() < deadline:
        if _devtools_ready():
            return BrowserLaunchResult(
                True,
                browser_name=browser_name,
                message=f"Đã tự động mở {browser_name}.",
            )
        time.sleep(0.25)

    return BrowserLaunchResult(
        False,
        browser_name=browser_name,
        message=f"Đã mở {browser_name} nhưng cổng DOM 9222 chưa sẵn sàng.",
    )


def _devtools_ready() -> bool:
    return _devtools_pages() is not None


def _chess_page_ready() -> bool:
    pages = _devtools_pages()
    if pages is None:
        return False
    return any(
        "chess.com" in str(page.get("url", "")).lower()
        or "lichess.org" in str(page.get("url", "")).lower()
        or "play.chessbase.com" in str(page.get("url", "")).lower()
        or "play.chessclub.com" in str(page.get("url", "")).lower()
        for page in pages
        if isinstance(page, dict)
    )


def _devtools_pages() -> list[dict] | None:
    try:
        with urlopen(f"{DEVTOOLS_ENDPOINT}/json", timeout=0.4) as response:
            pages = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return pages if isinstance(pages, list) else None


def _open_chess_tab() -> None:
    open_chess_url(DEFAULT_CHESS_URL)


def open_chess_url(url: str) -> str | None:
    try:
        request = Request(
            f"{DEVTOOLS_ENDPOINT}/json/new?{quote(url, safe=':/?=&')}",
            method="PUT",
        )
        with urlopen(request, timeout=1.0) as response:
            page = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    target_id = page.get("id") if isinstance(page, dict) else None
    return str(target_id) if target_id else None


def _find_browser() -> tuple[str, Path, str] | None:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("PROGRAMFILES", ""))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", ""))

    candidates = [
        (
            "Cốc Cốc",
            local_app_data / "CocCoc/Browser/Application/browser.exe",
            "ChessAssistantCocCoc",
        ),
        (
            "Cốc Cốc",
            program_files / "CocCoc/Browser/Application/browser.exe",
            "ChessAssistantCocCoc",
        ),
        (
            "Cốc Cốc",
            program_files_x86 / "CocCoc/Browser/Application/browser.exe",
            "ChessAssistantCocCoc",
        ),
        (
            "Google Chrome",
            local_app_data / "Google/Chrome/Application/chrome.exe",
            "ChessAssistantChrome",
        ),
        (
            "Google Chrome",
            program_files / "Google/Chrome/Application/chrome.exe",
            "ChessAssistantChrome",
        ),
        (
            "Google Chrome",
            program_files_x86 / "Google/Chrome/Application/chrome.exe",
            "ChessAssistantChrome",
        ),
        (
            "Microsoft Edge",
            program_files / "Microsoft/Edge/Application/msedge.exe",
            "ChessAssistantEdge",
        ),
        (
            "Microsoft Edge",
            program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
            "ChessAssistantEdge",
        ),
        (
            "Microsoft Edge",
            local_app_data / "Microsoft/Edge/Application/msedge.exe",
            "ChessAssistantEdge",
        ),
        (
            "Brave",
            local_app_data / "BraveSoftware/Brave-Browser/Application/brave.exe",
            "ChessAssistantBrave",
        ),
        (
            "Brave",
            program_files / "BraveSoftware/Brave-Browser/Application/brave.exe",
            "ChessAssistantBrave",
        ),
        (
            "Brave",
            program_files_x86 / "BraveSoftware/Brave-Browser/Application/brave.exe",
            "ChessAssistantBrave",
        ),
    ]
    for browser_name, path, profile_name in candidates:
        if str(path) and path.is_file():
            return browser_name, path, profile_name
    return None
