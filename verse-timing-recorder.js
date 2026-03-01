(function () {
    'use strict';

    // Layout safety: many chapter pages use `.verses { display:flex; }` without specifying
    // a direction, and the default `row` will squish each verse side-by-side when a page
    // falls back to showing the full chapter (no timing data).
    // Force vertical stacking for chapter verse containers.
    (function ensureVersesStackVertically() {
        try {
            if (!document.querySelector('.verses .verse')) return;
            if (document.getElementById('douftsVersesLayoutFix')) return;
            const style = document.createElement('style');
            style.id = 'douftsVersesLayoutFix';
            style.textContent = `
                .verses { flex-direction: column; }
            `;
            (document.head || document.documentElement).appendChild(style);
        } catch {
            // ignore
        }
    })();

    function safeJsonParse(raw) {
        try {
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }

    function isFiniteNonNegativeNumber(n) {
        return Number.isFinite(n) && n >= 0;
    }

    function clampNonNegative(n) {
        const x = Number(n);
        if (!Number.isFinite(x) || x < 0) return 0;
        return x;
    }

    function deriveVerseRanges(startTimes, audioDuration) {
        if (!Array.isArray(startTimes) || !startTimes.length) return [];
        const starts = startTimes.map(clampNonNegative);
        const hasDuration = Number.isFinite(audioDuration) && audioDuration > 0;
        const dur = hasDuration ? Number(audioDuration) : null;

        const ranges = [];
        for (let i = 0; i < starts.length; i++) {
            const start = starts[i];
            let end = null;

            if (i < starts.length - 1) {
                end = starts[i + 1];
            } else if (dur != null) {
                end = dur;
            }

            if (end != null) {
                // Guard against out-of-order/invalid timings.
                end = Math.max(start, end);
            }

            const duration = end == null ? null : Math.max(0, end - start);
            ranges.push({ index: i + 1, start, end, duration });
        }
        return ranges;
    }

    // (safeJsonParse moved to top so other helpers can use it)

    /**
     * Attach a verse timing recorder + HUD.
     *
     * @param {Object} options
     * @param {HTMLMediaElement} options.narration
     * @param {NodeListOf<HTMLElement>|HTMLElement[]} options.verses
     * @param {string} options.storageKey
     * @param {number[]} options.defaultHighlightTimes
      * @param {boolean} [options.autoAdvance] When timing mode is on, visually mark the current verse and advance the marker when you capture/undo.
      * @param {boolean} [options.singleVerseView] If true, hides all verses except the active one during timing mode.
      * @param {boolean} [options.scrollIntoViewOnAdvance] If true, scrolls the active verse into view when it changes.
      * @param {(enabled: boolean, state: {capturedTimes: number[], capturedCount: number, totalCount: number}) => void} [options.onTimingModeChange]
      * @param {(evt: {index: number, nextIndex: number, time: number, capturedTimes: number[], capturedCount: number, totalCount: number}) => void} [options.onCapture]
      * @param {(evt: {nextIndex: number, capturedTimes: number[], capturedCount: number, totalCount: number}) => void} [options.onUndo]
      * @param {(times: number[]) => void} [options.onSave]
      * @param {() => void} [options.onClearSaved]
     * @returns {{
     *   getHighlightTimes: () => number[],
     *   setTimingMode: (enabled: boolean, resetCapture?: boolean) => void,
     *   exportCapturedTimes: () => string,
     *   clearSaved: () => void
     * }}
     */
    function attachVerseTimingRecorder(options) {
        const narration = options && options.narration;
        const verses = options && options.verses;
        const storageKey = options && options.storageKey;
        const defaultHighlightTimes = (options && options.defaultHighlightTimes) || [];

        const saveUrl = options && options.saveUrl;
        const bookFolder = options && options.bookFolder;
        const bookOrder = options && options.bookOrder;
        const chapter = options && options.chapter;

        const bookOrderNum = (bookOrder != null && bookOrder !== '') ? Number(bookOrder) : null;
        const chapterNum = (chapter != null && chapter !== '') ? Number(chapter) : null;
        const canSubmitToServer = !!(saveUrl && Number.isFinite(bookOrderNum) && Number.isFinite(chapterNum));

        const autoAdvance = !!(options && options.autoAdvance);
        const singleVerseView = !!(options && options.singleVerseView);
        const scrollIntoViewOnAdvance = options && typeof options.scrollIntoViewOnAdvance === 'boolean'
            ? options.scrollIntoViewOnAdvance
            : true;

        const onTimingModeChange = options && options.onTimingModeChange;
        const onCapture = options && options.onCapture;
        const onUndo = options && options.onUndo;
        const onSave = options && options.onSave;
        const onClearSaved = options && options.onClearSaved;

        if (!narration || !storageKey || !verses) {
            throw new Error('attachVerseTimingRecorder: missing required options');
        }

        const verseList = Array.from(verses);

        function dispatchRecorderEvent(name, detail) {
            try {
                document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
            } catch {
                // ignore
            }
        }

        function loadSavedHighlightTimes() {
            const raw = localStorage.getItem(storageKey);
            if (!raw) return null;
            const parsed = safeJsonParse(raw);
            if (!Array.isArray(parsed)) return null;
            if (parsed.length !== verseList.length) return null;
            if (!parsed.every(isFiniteNonNegativeNumber)) return null;
            return parsed;
        }

        function saveHighlightTimes(times) {
            localStorage.setItem(storageKey, JSON.stringify(times));
        }

        async function submitTimingsToServer(times) {
            if (!canSubmitToServer) {
                return { ok: false, error: 'No server saveUrl/bookOrder/chapter configured.' };
            }
            if (!Array.isArray(times) || times.length !== verseList.length) {
                return { ok: false, error: 'Timings must include every verse.' };
            }
            if (!times.every(isFiniteNonNegativeNumber)) {
                return { ok: false, error: 'Timings must be numbers ≥ 0.' };
            }

            try {
                const audioDuration = (narration && Number.isFinite(narration.duration) && narration.duration > 0)
                    ? Number(narration.duration.toFixed(3))
                    : null;
                const cleaned = times.map((t) => Number(Number(t).toFixed(3)));
                const ranges = deriveVerseRanges(cleaned, audioDuration);

                const payload = {
                    bookFolder: bookFolder || null,
                    bookOrder: bookOrderNum,
                    chapter: chapterNum,
                    verseCount: verseList.length,
                    audioDuration,
                    times: cleaned,
                    ranges
                };

                const r = await fetch(String(saveUrl), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!r || !r.ok) {
                    return { ok: false, error: `Server error (${r ? r.status : 'network'})` };
                }

                // Keep local state in sync so the chapter can immediately use the new timings.
                setHighlightTimes(cleaned, true);
                return { ok: true };
            } catch (e) {
                return { ok: false, error: (e && e.message) ? e.message : 'Network error' };
            }
        }

        function setHighlightTimes(times, persist = false) {
            if (!Array.isArray(times)) return;
            if (times.length !== verseList.length) return;
            if (!times.every(isFiniteNonNegativeNumber)) return;
            highlightTimes = times.slice(0, verseList.length);
            if (persist) {
                saveHighlightTimes(highlightTimes);
            }
        }

        function firstVerseLeadInTime(referenceTimes) {
            const target = 1.0;
            if (!Array.isArray(referenceTimes) || !referenceTimes.length) return target;
            const first = Number(referenceTimes[0]);
            if (!Number.isFinite(first)) return target;
            if (first > target) return target;
            return Math.max(0, Number((first - 0.05).toFixed(3)));
        }

        function buildTimesForPersistence(sourceTimes) {
            const raw = Array.isArray(sourceTimes) ? sourceTimes.slice() : [];
            if (!raw.every(isFiniteNonNegativeNumber)) return null;

            // In recorder single-verse mode, users often capture the boundary where verse 2 starts.
            // To keep chapter highlight-times aligned, inject verse 1 start near 1s and shift right.
            const shouldInjectLeadIn = singleVerseView && autoAdvance;
            if (!shouldInjectLeadIn) {
                return (raw.length === verseList.length) ? raw : null;
            }

            if (raw.length === verseList.length - 1) {
                return [firstVerseLeadInTime(raw), ...raw];
            }

            if (raw.length === verseList.length) {
                return [firstVerseLeadInTime(raw), ...raw.slice(0, verseList.length - 1)];
            }

            return null;
        }

        let highlightTimes = loadSavedHighlightTimes() || defaultHighlightTimes.slice(0, verseList.length);

        let timingMode = false;
        let capturedTimes = [];

        // When timing mode is active, suppress any other timeupdate listeners (e.g. chapter-template auto-advance)
        // so verses don't move while you're recording timings.
        try {
            narration.addEventListener('timeupdate', (e) => {
                if (!timingMode) return;
                if (e && typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
                if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
            }, true);
        } catch {
            // ignore
        }

        // Optional UI helpers for single-page timing.
        const originalDisplay = new WeakMap();
        const originalClassState = new WeakMap();
        let originalClassStateCaptured = false;
        let activeVerseIndex = -1;

        const useClassVisibility = singleVerseView && verseList.every((v) => v && v.classList && v.classList.contains('verse'));

        function ensureTimingStyles() {
            if (document.getElementById('douftsTimingStyles')) return;
            const style = document.createElement('style');
            style.id = 'douftsTimingStyles';
            style.textContent = `
                .doufts-timing-current { outline: 3px solid rgba(255, 215, 0, 0.85); outline-offset: 6px; border-radius: 18px; }
            `;
            document.head.appendChild(style);
        }

        function setActiveVerse(index) {
            if (!autoAdvance && !singleVerseView) return;
            const safeIndex = Math.max(0, Math.min(index, verseList.length - 1));
            if (safeIndex === activeVerseIndex && !singleVerseView) return;

            ensureTimingStyles();

            verseList.forEach((v, i) => {
                v.classList.toggle('doufts-timing-current', i === safeIndex);
                v.setAttribute('data-doufts-timing-current', i === safeIndex ? 'true' : 'false');

                if (!singleVerseView) return;

                if (useClassVisibility) {
                    v.classList.toggle('hidden', i !== safeIndex);
                    v.classList.toggle('visible', i === safeIndex);
                    v.classList.toggle('highlight', i === safeIndex);
                } else {
                    if (!originalDisplay.has(v)) {
                        originalDisplay.set(v, v.style.display);
                    }
                    v.style.display = (i === safeIndex) ? (originalDisplay.get(v) || '') : 'none';
                }
            });

            activeVerseIndex = safeIndex;

            if (scrollIntoViewOnAdvance) {
                const v = verseList[safeIndex];
                if (v && typeof v.scrollIntoView === 'function') {
                    try {
                        v.scrollIntoView({ block: 'center', behavior: 'smooth' });
                    } catch {
                        v.scrollIntoView();
                    }
                }
            }
        }

        function clearActiveVerseUi() {
            verseList.forEach((v) => {
                v.classList.remove('doufts-timing-current');
                v.setAttribute('data-doufts-timing-current', 'false');

                if (!singleVerseView) return;

                if (useClassVisibility) {
                    if (originalClassStateCaptured && originalClassState.has(v)) {
                        const s = originalClassState.get(v);
                        v.classList.toggle('hidden', !!s.hidden);
                        v.classList.toggle('visible', !!s.visible);
                        v.classList.toggle('highlight', !!s.highlight);
                    }
                } else if (originalDisplay.has(v)) {
                    v.style.display = originalDisplay.get(v) || '';
                }
            });
            activeVerseIndex = -1;
        }

        function hideAllVersesInSingleVerseView() {
            if (!singleVerseView) return;

            verseList.forEach((v) => {
                v.classList.remove('doufts-timing-current');
                v.setAttribute('data-doufts-timing-current', 'false');

                if (useClassVisibility) {
                    v.classList.add('hidden');
                    v.classList.remove('visible');
                    v.classList.remove('highlight');
                } else {
                    if (!originalDisplay.has(v)) {
                        originalDisplay.set(v, v.style.display);
                    }
                    v.style.display = 'none';
                }
            });

            activeVerseIndex = -1;
        }

        function refreshActiveVerseForCaptureCount() {
            if (!singleVerseView) {
                const currentIndex = Math.min(capturedTimes.length, verseList.length - 1);
                setActiveVerse(currentIndex);
                return;
            }

            if (capturedTimes.length === 0) {
                setActiveVerse(0);
                return;
            }

            const currentIndex = Math.min(capturedTimes.length, verseList.length - 1);
            setActiveVerse(currentIndex);
        }

        const timingHud = document.createElement('div');
        timingHud.setAttribute('aria-live', 'polite');
        timingHud.style.cssText = [
            'position:fixed',
            'left:12px',
            'right:12px',
            'bottom:12px',
            'z-index:9999',
            'display:none',
            'padding:10px 12px',
            'border-radius:14px',
            'background:rgba(0,0,0,0.55)',
            'backdrop-filter:blur(10px)',
            'color:#fff',
            'font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif',
            'font-size:13px',
            'line-height:1.35',
            'text-align:left',
            'border:1px solid rgba(255,255,255,0.2)'
        ].join(';');
        document.body.appendChild(timingHud);

        let hudStatus = '';
        let hudStatusKind = 'muted';

        function setHudStatus(message, kind) {
            hudStatus = message ? String(message) : '';
            hudStatusKind = kind || 'muted';
            if (timingMode) updateTimingHud();
        }

        function canEnterTimingMode() {
            const main = document.getElementById('main-container');
            if (main && !main.classList.contains('active')) return false;
            return true;
        }

        const timingToggleBtn = (function createTimingToggle() {
            try {
                if (document.getElementById('douftsTimingToggle')) return null;
                const btn = document.createElement('button');
                btn.id = 'douftsTimingToggle';
                btn.type = 'button';
                btn.textContent = 'Timing';
                btn.style.cssText = [
                    'position:fixed',
                    'right:12px',
                    'bottom:96px',
                    'z-index:9999',
                    'padding:10px 12px',
                    'border-radius:999px',
                    'border:1px solid rgba(255,255,255,0.22)',
                    'background:rgba(0,0,0,0.45)',
                    'backdrop-filter:blur(10px)',
                    'color:#fff',
                    'font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif',
                    'font-size:13px',
                    'line-height:1',
                    'cursor:pointer'
                ].join(';');
                btn.addEventListener('click', () => {
                    if (!timingMode && !canEnterTimingMode()) return;
                    setTimingMode(!timingMode, true);
                });
                document.body.appendChild(btn);
                return btn;
            } catch {
                return null;
            }
        })();

        function updateTimingToggleUi() {
            if (!timingToggleBtn) return;
            timingToggleBtn.textContent = timingMode ? 'Timing: ON' : 'Timing';
            timingToggleBtn.style.opacity = timingMode ? '1' : '0.85';
        }

        function updateTimingHud() {
            if (!timingMode) return;
            const nextVerse = Math.min(capturedTimes.length + 1, verseList.length);

            const btnStyle = [
                'padding:8px 10px',
                'border-radius:999px',
                'border:1px solid rgba(255,255,255,0.22)',
                'background:rgba(255,255,255,0.10)',
                'color:#fff',
                'font-size:13px',
                'cursor:pointer'
            ].join(';');

            const statusColor = (hudStatusKind === 'error') ? 'rgba(255,120,120,0.95)'
                : (hudStatusKind === 'ok') ? 'rgba(160,255,180,0.95)'
                    : 'rgba(255,255,255,0.85)';

            const statusHtml = hudStatus
                ? `<div style="margin-top:8px; color:${statusColor}; font-weight:600;">${hudStatus}</div>`
                : '';

            timingHud.innerHTML =
                `<strong>Timing mode</strong> — next: verse ${nextVerse}/${verseList.length} ` +
                `• captured: ${capturedTimes.length}<br>` +
                `<span style="opacity:.9">Keys:</span> ` +
                `<code style="opacity:.9">n</code> record • ` +
                `<code style="opacity:.9">u</code> undo • ` +
                `<code style="opacity:.9">s</code> save • ` +
                `<code style="opacity:.9">e</code> export • ` +
                `<code style="opacity:.9">c</code> clear saved • ` +
                `<code style="opacity:.9">t</code> exit` +
                `<div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">` +
                `<button type="button" data-action="record" style="${btnStyle}">Record</button>` +
                `<button type="button" data-action="undo" style="${btnStyle}">Undo</button>` +
                `<button type="button" data-action="save" style="${btnStyle}">Save</button>` +
                (canSubmitToServer ? `<button type="button" data-action="submit" style="${btnStyle}">Submit</button>` : '') +
                `<button type="button" data-action="export" style="${btnStyle}">Export</button>` +
                `<button type="button" data-action="exit" style="${btnStyle}">Exit</button>` +
                `</div>` +
                statusHtml +
                `<div style="margin-top:8px; opacity:.9">Output (press <code>e</code> to refresh):</div>` +
                `<textarea id="timingOutput" readonly ` +
                `style="width:100%; height:72px; margin-top:6px; resize:vertical; ` +
                `border-radius:10px; border:1px solid rgba(255,255,255,0.2); ` +
                `background:rgba(0,0,0,0.35); color:#fff; padding:8px; ` +
                `font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; ` +
                `font-size:12px; line-height:1.35;">` +
                `${capturedTimes.length ? JSON.stringify(capturedTimes) : ''}` +
                `</textarea>`;
        }

        function captureNow() {
            if (!timingMode) return;
            if (capturedTimes.length >= verseList.length) return;
            capturedTimes.push(Number(narration.currentTime.toFixed(3)));
            setHudStatus('', 'muted');
            updateTimingHud();

            refreshActiveVerseForCaptureCount();

            dispatchRecorderEvent('doufts:timing-capture', {
                capturedCount: capturedTimes.length,
                totalCount: verseList.length,
                time: capturedTimes[capturedTimes.length - 1],
                timingMode: timingMode
            });

            if (typeof onCapture === 'function') {
                const index = capturedTimes.length - 1;
                onCapture({
                    index,
                    nextIndex: capturedTimes.length,
                    time: capturedTimes[index],
                    capturedTimes: capturedTimes.slice(),
                    capturedCount: capturedTimes.length,
                    totalCount: verseList.length
                });
            }

            if (capturedTimes.length === verseList.length) {
                exportCapturedTimes();
            }
        }

        function undoCapture() {
            if (!timingMode) return;
            if (!capturedTimes.length) return;
            capturedTimes.pop();
            setHudStatus('', 'muted');
            updateTimingHud();

            refreshActiveVerseForCaptureCount();

            dispatchRecorderEvent('doufts:timing-undo', {
                capturedCount: capturedTimes.length,
                totalCount: verseList.length,
                timingMode: timingMode
            });

            if (typeof onUndo === 'function') {
                onUndo({
                    nextIndex: capturedTimes.length,
                    capturedTimes: capturedTimes.slice(),
                    capturedCount: capturedTimes.length,
                    totalCount: verseList.length
                });
            }
        }

        function saveCaptureToLocal() {
            if (!timingMode) return;
            const preparedTimes = buildTimesForPersistence(capturedTimes);
            if (!preparedTimes) {
                setHudStatus('Save requires all verses captured.', 'error');
                return;
            }
            saveHighlightTimes(preparedTimes);
            highlightTimes = loadSavedHighlightTimes() || highlightTimes;
            if (typeof onSave === 'function') {
                onSave(highlightTimes.slice());
            }
            setHudStatus('Saved locally (with verse 1 lead-in).', 'ok');
            updateTimingHud();
        }

        async function submitCapture() {
            if (!timingMode) return;
            const preparedTimes = buildTimesForPersistence(capturedTimes);
            if (!preparedTimes) {
                setHudStatus('Submit requires all verses captured.', 'error');
                return;
            }
            setHudStatus('Submitting…', 'muted');
            const res = await submitTimingsToServer(preparedTimes);
            if (res && res.ok) {
                setHudStatus('Submitted to server (with verse 1 lead-in).', 'ok');
            } else {
                setHudStatus(res && res.error ? res.error : 'Submit failed.', 'error');
            }
        }

        timingHud.addEventListener('click', (e) => {
            const t = e && e.target;
            if (!t || !t.closest) return;
            const btn = t.closest('button[data-action]');
            if (!btn) return;
            const action = btn.getAttribute('data-action');
            if (action === 'record') captureNow();
            else if (action === 'undo') undoCapture();
            else if (action === 'save') saveCaptureToLocal();
            else if (action === 'submit') submitCapture();
            else if (action === 'export') exportCapturedTimes();
            else if (action === 'exit') setTimingMode(false, false);
        });

        function setTimingMode(enabled, resetCapture = false) {
            timingMode = !!enabled;
            if (resetCapture) capturedTimes = [];
            timingHud.style.display = timingMode ? 'block' : 'none';
            updateTimingToggleUi();
            if (timingMode) updateTimingHud();

            if (timingMode && singleVerseView && useClassVisibility && !originalClassStateCaptured) {
                verseList.forEach((v) => {
                    originalClassState.set(v, {
                        hidden: v.classList.contains('hidden'),
                        visible: v.classList.contains('visible'),
                        highlight: v.classList.contains('highlight')
                    });
                });
                originalClassStateCaptured = true;
            }

            if (timingMode) {
                refreshActiveVerseForCaptureCount();
            } else {
                clearActiveVerseUi();
                originalClassStateCaptured = false;
            }

            if (typeof onTimingModeChange === 'function') {
                onTimingModeChange(timingMode, {
                    capturedTimes: capturedTimes.slice(),
                    capturedCount: capturedTimes.length,
                    totalCount: verseList.length
                });
            }

            dispatchRecorderEvent('doufts:timing-mode', {
                enabled: timingMode,
                capturedCount: capturedTimes.length,
                totalCount: verseList.length
            });
        }

        function exportCapturedTimes() {
            const exportTimes = buildTimesForPersistence(capturedTimes) || capturedTimes;
            const out = JSON.stringify(exportTimes);
            console.log('Verse highlightTimes:', out);

            try {
                const audioDuration = (narration && Number.isFinite(narration.duration) && narration.duration > 0)
                    ? narration.duration
                    : null;
                const ranges = deriveVerseRanges(exportTimes, audioDuration);
                if (ranges.length) {
                    console.log('Verse ranges (derived):', JSON.stringify({ audioDuration, ranges }));
                }
            } catch {
                // ignore
            }

            setTimingMode(true, false);
            updateTimingHud();

            const ta = document.getElementById('timingOutput');
            if (ta) {
                ta.value = out;
                ta.focus();
                ta.select();
            }

            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(out).catch(() => { });
            }

            return out;
        }

        function clearSaved() {
            localStorage.removeItem(storageKey);
            highlightTimes = defaultHighlightTimes.slice(0, verseList.length);

            if (typeof onClearSaved === 'function') {
                onClearSaved();
            }
        }

        // Hotkeys
        document.addEventListener('keydown', (e) => {
            const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

            const key = e.key.toLowerCase();
            if (key === 't') {
                if (!timingMode) {
                    if (!canEnterTimingMode()) return;
                }
                setTimingMode(!timingMode, true);
                return;
            }

            if (!timingMode) return;

            if (key === 'n') {
                captureNow();
            } else if (key === 'u') {
                undoCapture();
            } else if (key === 'e') {
                exportCapturedTimes();
            } else if (key === 's') {
                saveCaptureToLocal();
            } else if (key === 'c') {
                clearSaved();
                setHudStatus('Cleared saved timings.', 'ok');
                updateTimingHud();
            }
        });

        // If the narration restarts from the beginning, reset capture so it's aligned.
        narration.addEventListener('play', () => {
            if (narration.currentTime < 0.25) {
                setTimingMode(true, true);
            }
        });

        return {
            getHighlightTimes: () => highlightTimes,
            setHighlightTimes,
            setTimingMode,
            exportCapturedTimes,
            clearSaved,
            submitTimingsToServer
        };
    }

    function tryParseDefaultHighlightTimesFromPage(verseCount) {
        const el = document.getElementById('highlight-times');
        if (!el) return null;
        const raw = (el.textContent || '').trim();
        if (!raw) return null;
        const parsed = safeJsonParse(raw);
        if (!Array.isArray(parsed)) return null;
        const times = parsed
            .map((n) => (typeof n === 'number' ? n : Number(n)))
            .filter((n) => Number.isFinite(n) && n >= 0);
        if (!times.length) return null;
        if (times.length !== verseCount) return null;
        return times;
    }

    function buildTimingApiUrl(saveUrl, params) {
        try {
            const u = new URL(saveUrl, window.location.origin);
            Object.keys(params || {}).forEach((k) => {
                if (params[k] == null || params[k] === '') return;
                u.searchParams.set(k, String(params[k]));
            });
            return u.toString();
        } catch {
            return null;
        }
    }

    function parseBookAndChapterFromText(text) {
        if (!text) return null;
        const m = String(text).trim().match(/^([A-Za-z]+)\s+(\d+)/);
        if (!m) return null;
        return { book: m[1], chapter: m[2] };
    }

    function inferStorageKeyFromPage() {
        const fromIntro = parseBookAndChapterFromText(document.getElementById('intro-text') && document.getElementById('intro-text').textContent);
        const fromTitle = parseBookAndChapterFromText(document.title);
        const info = fromIntro || fromTitle;
        if (!info) return null;
        return `doufts:${String(info.book).toLowerCase()}:${info.chapter}:highlightTimes`;
    }

    function getVerseIndexForTime(t, highlightTimes) {
        for (let i = highlightTimes.length - 1; i >= 0; i--) {
            if (t >= highlightTimes[i]) return i;
        }
        return 0;
    }

    function attachDouftsChapterTemplate(options) {
        const introScreen = document.getElementById('intro-screen');
        const mainContainer = document.getElementById('main-container');
        const narration = document.getElementById('narration');
        const harp = document.getElementById('harp');
        const versesContainer = document.querySelector('.verses');
        const verses = document.querySelectorAll('.verse');

        if (!introScreen || !mainContainer || !narration || !verses || !verses.length) {
            throw new Error('attachDouftsChapterTemplate: missing required elements');
        }

        const storageKey = (options && options.storageKey) || inferStorageKeyFromPage();
        if (!storageKey) {
            throw new Error('attachDouftsChapterTemplate: could not infer storageKey (set options.storageKey)');
        }

        const harpVolume = (options && typeof options.harpVolume === 'number') ? options.harpVolume : 0.03;
        const narrationVolume = (options && typeof options.narrationVolume === 'number') ? options.narrationVolume : 1.0;
        const introFadeMs = (options && typeof options.introFadeMs === 'number') ? options.introFadeMs : 250;
        const showVerseDelayMs = (options && typeof options.showVerseDelayMs === 'number') ? options.showVerseDelayMs : 100;
        const fitText = (options && typeof options.fitText === 'boolean') ? options.fitText : true;
        const minFontSizePx = (options && typeof options.minFontSizePx === 'number') ? options.minFontSizePx : 14;

        const fromPage = tryParseDefaultHighlightTimesFromPage(verses.length);
        const defaultHighlightTimes = (options && Array.isArray(options.defaultHighlightTimes) && options.defaultHighlightTimes.length)
            ? options.defaultHighlightTimes
            : (fromPage || [0, ...Array(Math.max(0, verses.length - 1)).fill(1e9)]);

        let timingModeActive = false;
        let highlightTimes = defaultHighlightTimes.slice(0, verses.length);
        let currentVerseIndex = -1;

        function fitVerseText(verseEl) {
            if (!fitText) return;
            if (!verseEl) return;
            if (!versesContainer) return;

            verseEl.style.fontSize = '';
            verseEl.style.overflowY = 'hidden';

            const containerHeight = versesContainer.clientHeight;
            if (containerHeight > 0) {
                verseEl.style.maxHeight = containerHeight + 'px';
            } else {
                verseEl.style.maxHeight = '';
            }

            const computed = window.getComputedStyle(verseEl);
            let fontSizePx = parseFloat(computed.fontSize);
            if (!Number.isFinite(fontSizePx) || fontSizePx <= 0) return;

            let guard = 0;
            while (guard < 40 && verseEl.scrollHeight > verseEl.clientHeight && fontSizePx > minFontSizePx) {
                fontSizePx -= 1;
                verseEl.style.fontSize = fontSizePx + 'px';
                guard++;
            }

            if (verseEl.scrollHeight > verseEl.clientHeight) {
                verseEl.style.overflowY = 'auto';
            }
        }

        function refitCurrentVerse() {
            if (currentVerseIndex < 0) return;
            const v = verses[currentVerseIndex];
            if (!v) return;
            fitVerseText(v);
        }

        function showVerse(index) {
            const safeIndex = Math.max(0, Math.min(index, verses.length - 1));
            if (safeIndex === currentVerseIndex) return;

            verses.forEach((v, i) => {
                if (i === safeIndex) {
                    v.classList.remove('hidden');
                    v.classList.remove('highlight');
                    v.classList.remove('visible');
                    requestAnimationFrame(() => {
                        v.classList.add('visible');
                        v.classList.add('highlight');
                        requestAnimationFrame(() => fitVerseText(v));
                    });
                } else {
                    v.classList.add('hidden');
                    v.classList.remove('visible');
                    v.classList.remove('highlight');
                    v.style.fontSize = '';
                    v.style.overflowY = '';
                    v.style.maxHeight = '';
                }
            });

            currentVerseIndex = safeIndex;
        }

        const saveUrl = options && options.saveUrl;
        const bookFolder = options && options.bookFolder;
        const bookOrder = options && options.bookOrder;
        const chapter = options && options.chapter;

        async function persistTimings(times) {
            if (!saveUrl) return;
            try {
                const audioDuration = (narration && Number.isFinite(narration.duration) && narration.duration > 0)
                    ? Number(narration.duration.toFixed(3))
                    : null;
                const ranges = deriveVerseRanges(times, audioDuration);

                const payload = {
                    bookFolder: bookFolder || null,
                    bookOrder: (bookOrder != null && bookOrder !== '') ? Number(bookOrder) : null,
                    chapter: (chapter != null && chapter !== '') ? Number(chapter) : null,
                    verseCount: verses.length,
                    audioDuration,
                    times,
                    ranges
                };

                const r = await fetch(saveUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                // Ignore errors silently; this is a convenience feature for local tooling.
                if (!r.ok) return;
            } catch {
                // ignore
            }
        }

        const recorderApi = attachVerseTimingRecorder({
            narration,
            verses,
            storageKey,
            defaultHighlightTimes,
            onTimingModeChange: (enabled, state) => {
                timingModeActive = !!enabled;
                if (timingModeActive) {
                    showVerse(Math.min(state.capturedCount || 0, verses.length - 1));
                }
            },
            onCapture: (evt) => {
                if (!timingModeActive) return;
                showVerse(Math.min(evt.nextIndex, verses.length - 1));
            },
            onUndo: (evt) => {
                if (!timingModeActive) return;
                showVerse(Math.min(evt.nextIndex, verses.length - 1));
            },
            onSave: (times) => {
                highlightTimes = times.slice(0, verses.length);
                persistTimings(highlightTimes.slice());
            },
            onClearSaved: () => {
                highlightTimes = defaultHighlightTimes.slice(0, verses.length);
            }
        });

        highlightTimes = recorderApi.getHighlightTimes().slice(0, verses.length);

        // Optional: load timings from local tooling API and seed localStorage/recorder.
        if (saveUrl) {
            const timingUrl = buildTimingApiUrl(saveUrl, {
                bookFolder: bookFolder || undefined,
                bookOrder: bookOrder || undefined,
                chapter: chapter || undefined
            });

            if (timingUrl) {
                fetch(timingUrl)
                    .then((r) => (r && r.ok) ? r.json() : null)
                    .then((data) => {
                        if (!data || !Array.isArray(data.times)) return;
                        if (data.times.length !== verses.length) return;
                        const times = data.times
                            .map((n) => (typeof n === 'number' ? n : Number(n)))
                            .filter((n) => Number.isFinite(n) && n >= 0);
                        if (times.length !== verses.length) return;
                        recorderApi.setHighlightTimes(times, true);
                        highlightTimes = recorderApi.getHighlightTimes().slice(0, verses.length);
                    })
                    .catch(() => { });
            }
        }

        window.addEventListener('resize', () => {
            requestAnimationFrame(refitCurrentVerse);
        });

        // Show intro
        setTimeout(() => introScreen.classList.add('active'), 500);

        introScreen.addEventListener('click', () => {
            introScreen.style.transition = `opacity ${Math.max(0, introFadeMs)}ms ease`;
            introScreen.style.opacity = '0';
            introScreen.style.pointerEvents = 'none';
            setTimeout(() => { introScreen.style.visibility = 'hidden'; }, Math.max(0, introFadeMs) + 30);

            mainContainer.classList.add('active');

            if (harp) {
                harp.volume = harpVolume;
                harp.play().catch(() => { });
            }

            narration.volume = narrationVolume;
            narration.play().catch(() => { });

            verses.forEach(v => v.classList.add('hidden'));
            setTimeout(() => showVerse(0), Math.max(0, showVerseDelayMs));
        });

        narration.addEventListener('timeupdate', () => {
            if (timingModeActive) return;
            // Pull latest timings (covers newly-saved times without a reload).
            highlightTimes = recorderApi.getHighlightTimes().slice(0, verses.length);
            showVerse(getVerseIndexForTime(narration.currentTime, highlightTimes));
        });

        narration.addEventListener('ended', () => {
            verses.forEach(v => v.classList.remove('highlight'));
        });

        return {
            recorderApi,
            showVerse,
            getHighlightTimes: () => recorderApi.getHighlightTimes().slice(0, verses.length)
        };
    }

    function findAutoInitScriptTag() {
        const scripts = Array.from(document.scripts || []);
        // Prefer an explicitly-marked script tag.
        const marked = scripts.filter(s => s && s.dataset && Object.prototype.hasOwnProperty.call(s.dataset, 'douftsAutoinit'));
        if (marked.length) return marked[marked.length - 1];
        return null;
    }

    function parseBooleanish(value, fallback) {
        if (value == null) return fallback;
        const v = String(value).trim().toLowerCase();
        if (v === 'true' || v === '1' || v === 'yes') return true;
        if (v === 'false' || v === '0' || v === 'no') return false;
        return fallback;
    }

    function parseNumberish(value, fallback) {
        if (value == null) return fallback;
        const n = Number(value);
        return Number.isFinite(n) ? n : fallback;
    }

    function attachDouftsTimingRecorderOnlyFromScriptTag(tag) {
        try {
            if (!tag || !tag.dataset) return null;
            const storageKey = tag.dataset.storageKey;
            if (!storageKey) return null;

            const narration = document.getElementById('narration') || document.querySelector('audio');
            const verses = Array.from(document.querySelectorAll('.verse'));
            if (!narration || !verses.length) return null;

            const defaultHighlightTimes = tryParseDefaultHighlightTimesFromPage(verses.length) || [];

            const recorderApi = attachVerseTimingRecorder({
                narration,
                verses,
                storageKey,
                defaultHighlightTimes,
                saveUrl: tag.dataset.saveUrl || undefined,
                bookFolder: tag.dataset.bookFolder || undefined,
                bookOrder: tag.dataset.bookOrder || undefined,
                chapter: tag.dataset.chapter || undefined,
                singleVerseView: true,
                autoAdvance: true
            });

            return { recorderApi };
        } catch {
            return null;
        }
    }

    function autoInitDouftsChapterTemplateFromScriptTag() {
        const tag = findAutoInitScriptTag();
        if (!tag) return null;

        // IMPORTANT: don't auto-init on normal chapter pages.
        // Those pages already have their own per-book `chapter-template.js` controller.
        // Running both causes duplicate event handlers and can contribute to audio glitches.
        //
        // If you want the recorder/template from this file, open the chapter with:
        //   ?doufts_timing=1
        // or set:
        //   data-doufts-autoinit="timing"
        try {
            const v = String(tag.dataset.douftsAutoinit || '').trim().toLowerCase();
            const qs = new URLSearchParams(window.location.search || '');
            const enabledByQuery = qs.get('doufts_timing') === '1' || qs.get('doufts_recorder') === '1';
            const enabledByValue = v === 'timing' || v === 'recorder' || v === 'true' || v === '1';
            const hasPerBookTemplate = !!document.querySelector('script[src$="chapter-template.js"], script[src$="/chapter-template.js"]');

            // Default: if a per-book template exists, do NOT auto-init the full controller.
            // But DO auto-init the timing recorder (HUD + hotkeys) so chapters can be timed.
            if (hasPerBookTemplate && !enabledByQuery && !enabledByValue) {
                return attachDouftsTimingRecorderOnlyFromScriptTag(tag);
            }
        } catch {
            return null;
        }

        const opts = {
            storageKey: tag.dataset.storageKey || undefined,
            saveUrl: tag.dataset.saveUrl || undefined,
            bookFolder: tag.dataset.bookFolder || undefined,
            bookOrder: tag.dataset.bookOrder || undefined,
            chapter: tag.dataset.chapter || undefined,
            harpVolume: parseNumberish(tag.dataset.harpVolume, undefined),
            narrationVolume: parseNumberish(tag.dataset.narrationVolume, undefined),
            introFadeMs: parseNumberish(tag.dataset.introFadeMs, undefined),
            showVerseDelayMs: parseNumberish(tag.dataset.showVerseDelayMs, undefined),
            fitText: parseBooleanish(tag.dataset.fitText, undefined),
            minFontSizePx: parseNumberish(tag.dataset.minFontSizePx, undefined)
        };

        // Strip undefineds so defaults apply.
        Object.keys(opts).forEach(k => { if (opts[k] === undefined) delete opts[k]; });

        return attachDouftsChapterTemplate(opts);
    }

    window.DouftsVerseTimingRecorder = {
        attachVerseTimingRecorder,
        attachDouftsChapterTemplate,
        autoInitDouftsChapterTemplateFromScriptTag
    };

    // Optional: auto-init for your standard chapter template when the script tag includes `data-doufts-autoinit`.
    // Example:
    //   <script src="../verse-timing-recorder.js" data-doufts-autoinit data-storage-key="doufts:matthew:5:highlightTimes"></script>
    //   (No additional inline JS needed.)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            try { autoInitDouftsChapterTemplateFromScriptTag(); } catch (e) { console.warn(e); }
        });
    } else {
        try { autoInitDouftsChapterTemplateFromScriptTag(); } catch (e) { console.warn(e); }
    }
})();
