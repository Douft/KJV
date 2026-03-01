from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TIMINGS_DIR = ROOT / ".timings"

BOOK_FOLDERS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
    "1Samuel", "2Samuel", "1Kings", "2Kings", "1Chronicles", "2Chronicles", "Ezra", "Nehemiah",
    "Esther", "Job", "Psalms", "Proverbs", "Ecclesiastes", "Songs", "Isaiah", "Jeremiah",
    "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi", "Matthew", "Mark", "Luke",
    "John", "Acts", "Romans", "1Corinthians", "2Corinthians", "Galatians", "Ephesians", "Philippians",
    "Colossians", "1Thessalonians", "2Thessalonians", "1Timothy", "2Timothy", "Titus", "Philemon",
    "Hebrews", "James", "1Peter", "2Peter", "1John", "2John", "3John", "Jude", "Revelation",
]


def _get_timing_file(book_order: int, chapter: int) -> Path:
    return TIMINGS_DIR / f"{book_order:02d}" / f"{chapter:03d}.json"


def _default_book_folder(book_order: int) -> str:
    if 1 <= book_order <= len(BOOK_FOLDERS):
        return BOOK_FOLDERS[book_order - 1]
    raise ValueError(f"book_order out of range: {book_order}")


def _load_times(path: Path) -> tuple[dict, list[float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_times = data.get("times")
    if not isinstance(raw_times, list) or not raw_times:
        raise ValueError(f"No valid 'times' list in {path}")

    out: list[float] = []
    for i, value in enumerate(raw_times, start=1):
        try:
            num = float(value)
        except Exception as exc:
            raise ValueError(f"Invalid time at index {i}: {value!r}") from exc
        if not math.isfinite(num) or num < 0:
            raise ValueError(f"Invalid non-negative finite time at index {i}: {value!r}")
        out.append(round(num, 3))

    return data, out


def _replace_highlight_times(html_text: str, times: list[float]) -> tuple[str, bool]:
    pattern = re.compile(
        r'(<script\s+id="highlight-times"\s+type="application/json">)(.*?)(</script>)',
        re.IGNORECASE | re.DOTALL,
    )
    serialized = json.dumps(times)

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}{serialized}{match.group(3)}"

    new_text, count = pattern.subn(repl, html_text, count=1)
    return new_text, count == 1


def _insert_highlight_times(html_text: str, times: list[float]) -> tuple[str, bool]:
    serialized = json.dumps(times)
    block = f'\n    <script id="highlight-times" type="application/json">{serialized}</script>\n\n'

    anchors = [
        '\n    <script src="../chapter-template.js"></script>',
        '\n</body>',
    ]

    for anchor in anchors:
        idx = html_text.find(anchor)
        if idx != -1:
            return html_text[:idx] + block + html_text[idx:], True

    return html_text, False


def _remove_timing_recorder_script_block(html_text: str) -> tuple[str, bool]:
    patterns = [
        re.compile(
            r'\n\s*<!--\s*Timing mode \+ auto-init[^>]*-->\s*\n\s*<script\b(?:(?!</script>).)*?\bsrc="\.\./verse-timing-recorder\.js"(?:(?!</script>).)*?</script>\s*\n?',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'\n\s*<script\b(?:(?!</script>).)*?\bsrc="\.\./verse-timing-recorder\.js"(?:(?!</script>).)*?</script>\s*\n?',
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    updated = html_text
    removed_any = False
    for pattern in patterns:
        updated, count = pattern.subn("\n", updated)
        if count:
            removed_any = True

    return updated, removed_any


def apply_submission(book_order: int, chapter: int, book_folder: str | None, clear_timing_file: bool) -> Path:
    timing_file = _get_timing_file(book_order, chapter)
    if not timing_file.exists():
        raise FileNotFoundError(f"Timing file not found: {timing_file}")

    payload, times = _load_times(timing_file)
    folder = book_folder or payload.get("bookFolder") or _default_book_folder(book_order)
    chapter_file = ROOT / folder / f"{folder}{chapter}.html"
    if not chapter_file.exists():
        raise FileNotFoundError(f"Chapter file not found: {chapter_file}")

    original = chapter_file.read_text(encoding="utf-8")
    updated, replaced = _replace_highlight_times(original, times)
    if not replaced:
        updated, inserted = _insert_highlight_times(original, times)
        if not inserted:
            raise ValueError(f"Could not locate or insert highlight-times script block in {chapter_file}")

    updated, removed_recorder = _remove_timing_recorder_script_block(updated)

    chapter_file.write_text(updated, encoding="utf-8")

    if clear_timing_file:
        timing_file.unlink(missing_ok=True)

    print(f"Applied {len(times)} timings from {timing_file} -> {chapter_file}")
    if removed_recorder:
        print(f"Removed timing recorder script block in {chapter_file}")
    if clear_timing_file:
        print(f"Deleted timing log: {timing_file}")
    return chapter_file


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply saved .timings submission into chapter HTML highlight-times.")
    ap.add_argument("--book-order", type=int, required=True, help="Book order number (1-66)")
    ap.add_argument("--chapter", type=int, required=True, help="Chapter number")
    ap.add_argument("--book-folder", help="Book folder name override (e.g. Genesis, 1Samuel)")
    ap.add_argument(
        "--clear-timing-file",
        action="store_true",
        help="Delete the .timings JSON log after successful apply",
    )
    args = ap.parse_args()

    if args.book_order < 1 or args.book_order > 66:
        raise SystemExit("--book-order must be in the range 1..66")
    if args.chapter < 1:
        raise SystemExit("--chapter must be >= 1")

    apply_submission(
        book_order=args.book_order,
        chapter=args.chapter,
        book_folder=args.book_folder,
        clear_timing_file=bool(args.clear_timing_file),
    )


if __name__ == "__main__":
    main()
