from __future__ import annotations

import re
from pathlib import Path

import requests


BASE_URL = "https://tablebase.lichess.ovh/tables/standard/"
SUBDIRS = ("3-4-5-wdl/", "3-4-5-dtz/")
TARGET = Path("tablebase/syzygy")


def list_files(subdir: str) -> list[str]:
    response = requests.get(BASE_URL + subdir, timeout=30)
    response.raise_for_status()
    return sorted(set(re.findall(r'href="([^"]+\.rtb[zw])"', response.text)))


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    head = requests.head(url, timeout=30, allow_redirects=True)
    expected_size = int(head.headers.get("content-length") or 0)
    if target.exists() and expected_size and target.stat().st_size == expected_size:
        print(f"skip {target.name}")
        return

    temp = target.with_suffix(target.suffix + ".part")
    resume_from = temp.stat().st_size if temp.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    with requests.get(url, stream=True, timeout=60, headers=headers) as response:
        response.raise_for_status()
        mode = "ab" if resume_from and response.status_code == 206 else "wb"
        with temp.open(mode) as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)
    temp.replace(target)
    print(f"done {target.name}")


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    total_files = 0
    for subdir in SUBDIRS:
        files = list_files(subdir)
        total_files += len(files)
        print(f"{subdir}: {len(files)} files")
        for name in files:
            download(BASE_URL + subdir + name, TARGET / name)
    print(f"downloaded/verified {total_files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
