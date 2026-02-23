from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BIBLICAL_INDEX_HTML = SCRIPT_DIR / "index.html"


@dataclass(frozen=True)
class Book:
    name: str
    folder: str


def stable_hue(seed: str) -> int:
    # Keep hues in a calmer range.
    n = zlib.adler32(seed.encode("utf-8"))
    return 185 + (n % 120)  # 185..304


def parse_books_from_global_index(html_text: str) -> list[Book]:
    # Extract from the JS list in BiblicalInspiration/index.html
    # Example:
    #   { name: '1 Samuel', folder: '1Samuel', chapters: 31 },
    book_pat = re.compile(r"\{\s*name:\s*'([^']+)'\s*,\s*folder:\s*'([^']+)'", re.M)
    books: list[Book] = []
    for m in book_pat.finditer(html_text):
        books.append(Book(name=m.group(1), folder=m.group(2)))
    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[Book] = []
    for b in books:
        if b.folder in seen:
            continue
        seen.add(b.folder)
        out.append(b)
    return out


def find_existing_chapters(book_dir: Path, folder: str) -> list[int]:
    pat = re.compile(rf"^{re.escape(folder)}(\d+)\.html$")
    chapters: set[int] = set()
    for p in book_dir.glob(f"{folder}*.html"):
        m = pat.match(p.name)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n > 0:
            chapters.add(n)
    return sorted(chapters)


def render_book_index(*, title: str, folder: str, chapters: list[int], bg_hue: int) -> str:
    chapter_links = "\n".join(
        f'            <a class="chapter-link" href="{folder}{ch}.html">Chapter {ch}</a>' for ch in chapters
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} Index</title>
    <meta name="description" content="Index of {title} chapters (KJV).">
    <link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400&family=Great+Vibes&display=swap" rel="stylesheet">
    <style>
        body {{
            margin: 0;
            padding: 0;
            min-height: 100vh;
            font-family: 'Alegreya', serif;
            color: #f5f0e8;
            --bg-hue: {bg_hue};
            --bg-hue2: calc(var(--bg-hue) + 22);
            --cross-x: 50%;
            --cross-y: 44%;
            --cross-w: 18px;
            --cross-h: 14px;
            --cross-mark-w: 240px;
            --cross-mark-h: 360px;
            --cross-mark-y: 40%;
            background-image:
                radial-gradient(720px 520px at var(--cross-x) var(--cross-y), rgba(255, 215, 0, 0.18), transparent 60%),
                radial-gradient(1100px 700px at 15% 25%, hsla(var(--bg-hue), 75%, 70%, 0.45), transparent 60%),
                radial-gradient(900px 640px at 85% 30%, hsla(var(--bg-hue2), 70%, 65%, 0.38), transparent 62%),
                radial-gradient(700px 520px at 30% 85%, hsla(calc(var(--bg-hue) + 55), 70%, 60%, 0.28), transparent 60%),
                linear-gradient(to bottom, hsl(var(--bg-hue), 55%, 55%), hsl(calc(var(--bg-hue) + 10), 55%, 45%), hsl(calc(var(--bg-hue) + 25), 55%, 60%));
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
            display: flex;
            justify-content: center;
            align-items: center;
            position: relative;
            overflow: hidden;
        }}

        body::before {{
            content: '';
            position: absolute;
            inset: 0;
            background: rgba(10, 40, 80, 0.28);
            backdrop-filter: blur(5px);
            z-index: 0;
        }}

        /* Draw a bounded upright cross (not a full-screen plus) */
        body::after {{
            content: '';
            position: fixed;
            left: var(--cross-x);
            top: var(--cross-mark-y);
            transform: translate(-50%, -50%);
            width: var(--cross-mark-w);
            height: var(--cross-mark-h);
            pointer-events: none;
            z-index: 0;
            opacity: 0.95;
            background:
                radial-gradient(closest-side at 50% 42%, rgba(255, 215, 0, 0.18), transparent 70%),
                linear-gradient(90deg,
                    transparent calc(50% - var(--cross-w)),
                    rgba(255, 240, 190, 0.10) calc(50% - var(--cross-w)),
                    rgba(255, 215, 0, 0.34) 50%,
                    rgba(255, 240, 190, 0.10) calc(50% + var(--cross-w)),
                    transparent calc(50% + var(--cross-w))
                ),
                linear-gradient(180deg,
                    transparent calc(34% - var(--cross-h)),
                    rgba(255, 240, 190, 0.10) calc(34% - var(--cross-h)),
                    rgba(255, 215, 0, 0.30) 34%,
                    rgba(255, 240, 190, 0.10) calc(34% + var(--cross-h)),
                    transparent calc(34% + var(--cross-h))
                );
            filter: drop-shadow(0 0 24px rgba(255, 215, 0, 0.20));
        }}

        #container {{
            position: relative;
            z-index: 1;
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            max-width: 90vw;
            width: 950px;
            padding: 70px 40px;
            border-radius: 40px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25), inset 0 0 80px rgba(255, 255, 255, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.35);
            text-align: center;
            max-height: 92vh;
            overflow-y: auto;
            overflow-x: hidden;
            animation: gentleGlow 12s ease-in-out infinite alternate;
            box-sizing: border-box;
        }}

        @keyframes gentleGlow {{
            from {{ box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25), inset 0 0 80px rgba(255, 255, 255, 0.25); }}
            to {{ box-shadow: 0 15px 60px rgba(255, 215, 0, 0.35), inset 0 0 100px rgba(255, 255, 255, 0.4); }}
        }}

        h1 {{
            font-family: 'Great Vibes', cursive;
            font-size: clamp(3.2rem, 11vw, 5.5rem);
            color: #ffd700;
            margin: 0 0 18px;
            text-shadow: 0 0 25px rgba(255, 255, 255, 0.9), 3px 3px 10px rgba(0,0,0,0.5);
        }}

        .subtitle {{
            font-style: italic;
            margin: 0 auto 20px;
            font-size: clamp(1.2rem, 4vw, 1.6rem);
            color: #fff8d0;
            text-shadow: 0 0 15px rgba(255, 255, 255, 0.7);
            max-width: 46ch;
        }}

        .chapter-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin: 0 auto;
            max-width: 720px;
        }}

        .chapter-link {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 56px;
            padding: 12px 14px;
            border-radius: 16px;
            text-decoration: none;
            color: #ffefb0;
            border: 1px solid rgba(255, 215, 0, 0.5);
            background: rgba(255, 255, 255, 0.12);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: all 0.35s ease;
            font-size: clamp(1rem, 2.8vw, 1.2rem);
        }}

        .chapter-link:hover {{
            color: #ffffff;
            text-shadow: 0 0 18px #ffd700;
            border-color: rgba(255, 215, 0, 0.95);
            transform: translateY(-1px);
        }}

        @media (max-width: 768px) {{
            #container {{
                width: 95vw;
                padding: 34px 20px;
                border-radius: 30px;
            }}
            .chapter-grid {{
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }}
        }}

        @media (max-width: 480px) {{
            #container {{
                padding: 28px 16px;
            }}
            .chapter-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
        }}
    </style>
</head>
<body>
    <div id="container">
        <h1>{title}</h1>
        <p class="subtitle">Select a chapter to read and listen (KJV).</p>

        <div style="display:flex; justify-content:center; margin: 0 auto 22px; max-width: 720px;">
            <a class="chapter-link" href="../index.html" style="min-height:46px; width: 100%; max-width: 260px;">Bible Index</a>
        </div>

        <div class="chapter-grid" aria-label="{title} chapter index">
{chapter_links}
        </div>

        <p class="subtitle" style="margin-top: 26px;">
            Verses: <a href="https://biblehub.com/" target="_blank" rel="noopener">BibleHub (KJV)</a>. Audio: <a href="https://mp3bible.ca/" target="_blank" rel="noopener">mp3bible.ca</a>. Thank you.
        </p>
    </div>
</body>
</html>
"""


def main() -> int:
    if not BIBLICAL_INDEX_HTML.exists():
        raise SystemExit(f"Missing global index: {BIBLICAL_INDEX_HTML}")

    books = parse_books_from_global_index(BIBLICAL_INDEX_HTML.read_text(encoding="utf-8"))
    book_by_folder = {b.folder: b for b in books}

    # Only regenerate in folders directly under BiblicalInspiration/.
    exclude = {"audio", "tool", ".timings", "_archive", "__pycache__", ".cache"}
    regenerated = 0
    for book_dir in sorted(SCRIPT_DIR.iterdir()):
        if not book_dir.is_dir() or book_dir.name in exclude:
            continue

        folder = book_dir.name
        book = book_by_folder.get(folder)
        title = book.name if book else folder
        chapters = find_existing_chapters(book_dir, folder)

        out_html = render_book_index(title=title, folder=folder, chapters=chapters, bg_hue=stable_hue(folder))
        (book_dir / "index.html").write_text(out_html, encoding="utf-8")
        regenerated += 1

    print(f"Regenerated {regenerated} book index pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
