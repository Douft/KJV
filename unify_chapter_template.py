from __future__ import annotations

import argparse
from pathlib import Path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def unify(root: Path, source_book: str, dry_run: bool = False) -> tuple[int, int]:
    source_script = root / source_book / "chapter-template.js"
    if not source_script.exists():
        raise FileNotFoundError(f"Source script not found: {source_script}")

    shared_script = root / "chapter-template.js"
    shared_text = _read_text(source_script)

    if not dry_run:
        _write_text(shared_script, shared_text)

    changed_files = 0
    changed_refs = 0

    for html in sorted(root.glob("*/*.html")):
        original = _read_text(html)
        updated = original.replace('src="chapter-template.js"', 'src="../chapter-template.js"')
        if updated == original:
            continue

        changed_files += 1
        changed_refs += original.count('src="chapter-template.js"')
        if not dry_run:
            _write_text(html, updated)

    return changed_files, changed_refs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Make all chapter pages reference one shared root chapter-template.js."
    )
    parser.add_argument(
        "--source-book",
        default="Genesis",
        help="Book folder whose chapter-template.js becomes the shared root script (default: Genesis)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview counts without writing files",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    changed_files, changed_refs = unify(root=root, source_book=args.source_book, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "UPDATED"
    print(f"{mode}: chapter pages changed={changed_files}, script references changed={changed_refs}")
    print(f"Shared script source: {args.source_book}/chapter-template.js -> chapter-template.js")


if __name__ == "__main__":
    main()
