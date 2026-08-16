"""Download TouringPlans wait-time CSVs into data/raw/touringplans/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from wdw.config import (
    METADATA_FILE,
    TOURINGPLANS_DIR,
    TOURINGPLANS_MIRROR_BASE,
    TOURINGPLANS_OFFICIAL_URL,
    attractions,
    ensure_data_dirs,
)


def _download(url: str, dest: Path, timeout: float = 60.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    tmp.replace(dest)


def expected_files() -> list[str]:
    files = [spec["file"] for spec in attractions()]
    files.append(METADATA_FILE)
    return files


def download_touringplans(force: bool = False) -> list[Path]:
    """Fetch the public TouringPlans datasets from the R-package data-raw mirror.

    Official files are published at TouringPlans Crowd Calendar DataSets and
    updated monthly. The GitHub mirror is used because it is a stable, scriptable
    URL. Drop newer official CSVs into the same folder to override.
    """
    ensure_data_dirs()
    saved: list[Path] = []
    for filename in expected_files():
        dest = TOURINGPLANS_DIR / filename
        if dest.exists() and dest.stat().st_size > 0 and not force:
            saved.append(dest)
            continue
        url = f"{TOURINGPLANS_MIRROR_BASE}/{filename}"
        print(f"Downloading {filename} ...")
        _download(url, dest)
        saved.append(dest)
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download TouringPlans WDW wait-time CSVs.",
        epilog=f"Official source: {TOURINGPLANS_OFFICIAL_URL}",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if files exist.")
    args = parser.parse_args(argv)
    try:
        paths = download_touringplans(force=args.force)
    except httpx.HTTPError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        print(
            f"You can also save CSVs manually from {TOURINGPLANS_OFFICIAL_URL} "
            f"into {TOURINGPLANS_DIR}",
            file=sys.stderr,
        )
        return 1
    print(f"Saved {len(paths)} files to {TOURINGPLANS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
