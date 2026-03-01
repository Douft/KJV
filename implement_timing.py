from __future__ import annotations

import argparse
from pathlib import Path

from apply_submitted_timing import BOOK_FOLDERS, TIMINGS_DIR, apply_submission


def _book_order_from_name(book_name: str) -> int:
    normalized = (book_name or '').strip().lower()
    for i, name in enumerate(BOOK_FOLDERS, start=1):
        if name.lower() == normalized:
            return i
    raise ValueError(f"Unknown book name: {book_name}")


def _latest_timing_file() -> Path:
    files = sorted(
        (p for p in TIMINGS_DIR.glob('*/*.json') if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"No timing logs found under {TIMINGS_DIR}")
    return files[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Friendly helper to apply submitted timing logs into chapter HTML files."
    )
    parser.add_argument("--book", help="Book folder/name (e.g. Genesis, 1Samuel)")
    parser.add_argument("--chapter", type=int, help="Chapter number")
    parser.add_argument("--latest", action="store_true", help="Apply the most recently updated timing log")
    parser.add_argument("--clear-log", action="store_true", help="Delete the timing JSON log after successful apply")
    args = parser.parse_args()

    if args.latest:
        latest = _latest_timing_file()
        book_order = int(latest.parent.name)
        chapter = int(latest.stem)
    else:
        if not args.book or not args.chapter:
            raise SystemExit("Use --latest or provide both --book and --chapter")
        book_order = _book_order_from_name(args.book)
        chapter = int(args.chapter)

    chapter_file = apply_submission(
        book_order=book_order,
        chapter=chapter,
        book_folder=None,
        clear_timing_file=bool(args.clear_log),
    )
    print(f"Done: {chapter_file}")


if __name__ == "__main__":
    main()
