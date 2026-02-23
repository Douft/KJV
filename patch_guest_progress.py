from __future__ import annotations

from pathlib import Path


def patch_one(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "bi_progress_consent" in text and "bi_last_chapter_path" in text:
        return False

    marker = "let autoplayEnabled = qs.get('bi_autoplay') === '1';"
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError(f"Marker not found in {path}")

    insert = """

    // Guest progress (stored only when user opted in on the Bible index page).
    const PROGRESS_KEYS = {
        consent: 'bi_progress_consent',
        lastPath: 'bi_last_chapter_path'
    };

    function rememberGuestProgress() {
        try {
            if (localStorage.getItem(PROGRESS_KEYS.consent) !== '1') return;
            const parts = (window.location.pathname || '').split('/').filter(Boolean);
            if (parts.length < 2) return;
            const folder = parts[parts.length - 2];
            const file = parts[parts.length - 1];
            if (!folder || !file) return;
            localStorage.setItem(PROGRESS_KEYS.lastPath, `${folder}/${file}`);
        } catch {
            // ignore
        }
    }

    rememberGuestProgress();
"""

    newline = "\r\n" if "\r\n" in text else "\n"
    insert = insert.replace("\n", newline)

    # Insert right after the marker line.
    after = idx + len(marker)
    # Find end of that line
    line_end = text.find("\n", after)
    if line_end == -1:
        line_end = len(text)
    patched = text[:line_end] + insert + text[line_end:]

    path.write_text(patched, encoding="utf-8")
    return True


def main() -> None:
    root = Path(__file__).resolve().parent
    targets = sorted(p for p in root.glob("*/chapter-template.js") if p.is_file())

    changed = 0
    for p in targets:
        if patch_one(p):
            changed += 1

    print(f"Patched {changed} / {len(targets)} chapter-template.js files")


if __name__ == "__main__":
    main()
