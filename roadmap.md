# Roadmap

_Last updated: 2026-02-24_

## Now

- **Bible chapters: single-verse UX everywhere (Genesis 1 style)**
  - Default to showing **one verse at a time** even when timing metadata is missing.
  - While creating timings, verse changes must be **manual only** (no auto-advance).
  - Once timings exist (provided/entered later), enable **auto-advance based on timings**.
  - Timing mode should not fight playback-driven `timeupdate` handlers.

## Next

- Enter timings for remaining chapters as they are created.
- Decide how/where to persist finalized timings (embedded `highlight-times` JSON vs localStorage vs a server endpoint).launch 

## Later

- (Add future items here as they come up.)

## Tuning log (global rollout notes)

- **2026-02-24: Unified chapter runtime script**
  - All chapter pages now reference the single shared script at `../chapter-template.js`.
  - Per-book `chapter-template.js` files were removed.
  - Server compatibility rewrite added so old requests like `/Book/chapter-template.js` resolve to `/chapter-template.js`.

- **2026-02-24: Timing capture UX refinements**
  - In timing mode, no verse is shown before the first real capture action.
  - First capture now shows verse 1 (no skip to verse 2).
  - Added mobile visibility assist by scrolling active verse into view when shown.

- **2026-02-24: Viewport scale experiment**
  - Chapter pages (non-index files like `Genesis1.html`) were set to:
    - `<meta name="viewport" content="width=device-width, initial-scale=0.67">`
  - Book index pages were then also set to `initial-scale=0.67` (root `index.html` intentionally left at `1.0`).
  - Rollout status:
    - chapter pages scanned `1189`, updated `1188` (Genesis 1 already set)
    - book index pages updated `69`

- **2026-02-24: Ambient music refinement**
  - Updated ambient pad to avoid static single-note/organ hum.
  - Added a very soft moving top-note voice and gentle harmonic drift over time.
  - Goal: keep ambience subtle while restoring audible "gentle notes" motion.
