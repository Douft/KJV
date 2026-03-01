(() => {
    'use strict';

    // Ensure the site favicon is set even when opening chapter pages directly.
    (function ensureFavicon(){
        try {
            if (document.querySelector('link[rel~="icon"]')) return;
            const link = document.createElement('link');
            link.rel = 'icon';
            link.href = '/favicon.svg';
            link.type = 'image/svg+xml';
            document.head.appendChild(link);
        } catch {
            // ignore
        }
    })();

    const introScreen = document.getElementById('intro-screen');
    const mainContainer = document.getElementById('main-container');
    const narration = document.getElementById('narration');
    const harp = document.getElementById('harp');
    const versesContainer = document.querySelector('.verses');
    const verses = Array.from(document.querySelectorAll('.verse'));
    const chapterNav = document.querySelector('.chapter-nav');
    const timingScriptTag = document.querySelector('script[src$="verse-timing-recorder.js"][data-wait-for-first-n]');
    const waitForFirstNToShowVerse = !!timingScriptTag;

    if (!introScreen || !mainContainer || !versesContainer || verses.length === 0) return;

    const qs = new URLSearchParams(window.location.search || '');
    let autoplayEnabled = qs.get('bi_autoplay') === '1';

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

    let started = false;

    function readHighlightTimesFromJsonScript() {
        const el = document.getElementById('highlight-times');
        if (!el) return [];

        const raw = (el.textContent || '').trim();
        if (!raw) return [];

        try {
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) return [];
            return parsed
                .map((n) => (typeof n === 'number' ? n : Number(n)))
                .filter((n) => Number.isFinite(n) && n >= 0);
        } catch {
            return [];
        }
    }

    let highlightTimes = readHighlightTimesFromJsonScript();
    if (highlightTimes.length > 0) {
        highlightTimes = highlightTimes.slice(0, verses.length);
    }

    let currentVerseIndex = -1;
    let waitingForFirstVerseN = false;

    function fitVerseText(verseEl) {
        if (!verseEl || !versesContainer) return;

        verseEl.style.fontSize = '';
        verseEl.style.overflowY = 'hidden';
        verseEl.scrollTop = 0;

        const containerHeight = versesContainer.clientHeight;
        if (containerHeight > 0) {
            verseEl.style.maxHeight = containerHeight + 'px';
        } else {
            verseEl.style.maxHeight = '';
        }

        const computed = window.getComputedStyle(verseEl);
        let fontSizePx = parseFloat(computed.fontSize);
        if (!Number.isFinite(fontSizePx) || fontSizePx <= 0) return;

        const minFontSizePx = 14;
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
                    requestAnimationFrame(() => {
                        fitVerseText(v);
                        if (typeof v.scrollIntoView === 'function') {
                            try {
                                v.scrollIntoView({ block: 'center', behavior: 'smooth' });
                            } catch {
                                v.scrollIntoView();
                            }
                        }
                    });
                });
            } else {
                v.classList.add('hidden');
                v.classList.remove('visible');
                v.classList.remove('highlight');
                v.style.fontSize = '';
                v.style.overflowY = '';
                v.style.maxHeight = '';
                v.scrollTop = 0;
            }
        });

        currentVerseIndex = safeIndex;
    }

    function getVerseIndexForTime(t) {
        for (let i = highlightTimes.length - 1; i >= 0; i--) {
            if (t >= highlightTimes[i]) return i;
        }
        return 0;
    }

    function showAllVersesScrollable() {
        verses.forEach((v) => {
            v.classList.remove('hidden');
            v.classList.add('visible');
            v.classList.remove('highlight');
            v.style.fontSize = '';
            v.style.overflowY = '';
            v.style.maxHeight = '';
            v.scrollTop = 0;
        });

        // Make the verses area behave like a scroll container for full-chapter reading.
        versesContainer.style.overflowY = 'auto';
        versesContainer.style.alignItems = 'flex-start';
        versesContainer.style.justifyContent = 'flex-start';
    }

    // Show intro
    setTimeout(() => introScreen.classList.add('active'), 500);

    function updateIntroHint(text) {
        const hint = introScreen.querySelector('.intro-hint');
        if (!hint) return;
        hint.textContent = text;
    }

    function buildControls() {
        if (!chapterNav) return;
        if (chapterNav.querySelector('[data-doufts-player="1"]')) return;

        const wrap = document.createElement('div');
        wrap.style.display = 'flex';
        wrap.style.justifyContent = 'center';
        wrap.style.gap = '12px';
        wrap.style.flexWrap = 'wrap';
        wrap.style.marginTop = '14px';
        wrap.setAttribute('data-doufts-player', '1');

        const bibleIndex = document.createElement('a');
        bibleIndex.href = '../index.html';
        bibleIndex.className = 'nav-btn';
        bibleIndex.textContent = 'Bible Index';

        const bookIndex = document.createElement('a');
        bookIndex.href = 'index.html';
        bookIndex.className = 'nav-btn';
        bookIndex.textContent = 'Book Index';

        const playPause = document.createElement('a');
        playPause.href = '#';
        playPause.className = 'nav-btn';
        playPause.setAttribute('role', 'button');
        playPause.setAttribute('aria-label', 'Play or pause');

        const autoplayBtn = document.createElement('a');
        autoplayBtn.href = '#';
        autoplayBtn.className = 'nav-btn';
        autoplayBtn.setAttribute('role', 'button');
        autoplayBtn.setAttribute('aria-label', 'Toggle autoplay');

        function syncLabels() {
            if (!narration) {
                playPause.textContent = 'Play';
            } else {
                playPause.textContent = narration.paused ? 'Play' : 'Pause';
            }
            autoplayBtn.textContent = `Autoplay: ${autoplayEnabled ? 'On' : 'Off'}`;
            autoplayBtn.setAttribute('aria-pressed', autoplayEnabled ? 'true' : 'false');
        }

        playPause.addEventListener('click', (e) => {
            e.preventDefault();
            if (!narration) return;

            if (!started) {
                startExperience({ fromAutoplay: false });
                return;
            }

            if (narration.paused) {
                narration.play().catch(() => {
                    // ignore
                });
            } else {
                narration.pause();
            }
        });

        autoplayBtn.addEventListener('click', (e) => {
            e.preventDefault();
            autoplayEnabled = !autoplayEnabled;
            syncLabels();
        });

        if (narration) {
            narration.addEventListener('play', syncLabels);
            narration.addEventListener('pause', syncLabels);
            narration.addEventListener('ended', syncLabels);
        }

        syncLabels();

        wrap.appendChild(bibleIndex);
        wrap.appendChild(bookIndex);
        wrap.appendChild(playPause);
        wrap.appendChild(autoplayBtn);
        chapterNav.insertAdjacentElement('beforebegin', wrap);
    }

    function getNextChapterHref() {
        if (!chapterNav) return null;
        const links = Array.from(chapterNav.querySelectorAll('a.nav-btn'));
        const next = links.find((a) => (a.textContent || '').includes('Next'));
        const href = next && next.getAttribute('href');
        if (!href || href === 'index.html') return null;
        if (next.classList.contains('disabled')) return null;
        return href;
    }

    function startExperience({ fromAutoplay }) {
        if (started) return;
        started = true;

        introScreen.style.transition = 'opacity 2s ease';
        introScreen.style.opacity = '0';
        setTimeout(() => {
            introScreen.style.visibility = 'hidden';
        }, 2000);

        mainContainer.classList.add('active');
        buildControls();

        if (harp) {
            harp.volume = 0.03;
            harp.play().catch(() => {});
        }

        // One verse at a time (no scrolling). If timing data exists, timeupdate will advance;
        // otherwise it stays on verse 1 until you create timings.
        verses.forEach((v) => v.classList.add('hidden'));
        if (waitForFirstNToShowVerse) {
            waitingForFirstVerseN = true;
        } else {
            showVerse(0);
        }

        if (narration) {
            narration.volume = 1;
            narration.play().catch(() => {
                if (fromAutoplay) {
                    // Autoplay policy blocked playback: let the user tap to continue.
                    started = false;
                    introScreen.style.visibility = 'visible';
                    introScreen.style.opacity = '1';
                    mainContainer.classList.remove('active');
                    updateIntroHint('Tap to continue autoplay');
                }
            });
        }
    }

    introScreen.addEventListener('click', () => {
        startExperience({ fromAutoplay: false });
    });

    document.addEventListener('doufts:timing-capture', (e) => {
        if (!waitingForFirstVerseN || !started) return;
        const detail = (e && e.detail) ? e.detail : null;
        const capturedCount = detail && Number.isFinite(Number(detail.capturedCount))
            ? Number(detail.capturedCount)
            : 0;
        if (capturedCount < 1) return;

        waitingForFirstVerseN = false;
        showVerse(0);
    });

    // If coming from an autoplay chain, attempt to start automatically.
    if (autoplayEnabled) {
        updateIntroHint('Autoplay is on…');
        setTimeout(() => {
            startExperience({ fromAutoplay: true });
        }, 100);
    }

    if (narration && highlightTimes.length > 0) {
        narration.addEventListener('timeupdate', () => {
            if (waitingForFirstVerseN) return;
            showVerse(getVerseIndexForTime(narration.currentTime));
        });

        window.addEventListener('resize', () => {
            requestAnimationFrame(refitCurrentVerse);
        });
    }

    if (narration) {
        narration.addEventListener('ended', () => {
            verses.forEach((v) => v.classList.remove('highlight'));

            if (!autoplayEnabled) return;
            const nextHref = getNextChapterHref();
            if (!nextHref) return;

            try {
                const url = new URL(nextHref, window.location.href);
                url.searchParams.set('bi_autoplay', '1');
                window.location.href = url.toString();
            } catch {
                // ignore
            }
        });
    }

    // Ethereal particles (skip when user prefers reduced motion)
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduceMotion) {
        function createParticle() {
            const p = document.createElement('div');
            p.className = 'particle';
            p.style.left = Math.random() * 100 + 'vw';
            p.style.animationDuration = 20 + Math.random() * 20 + 's';
            p.style.animationDelay = Math.random() * 15 + 's';
            document.body.appendChild(p);
            setTimeout(() => p.remove(), 40000);
        }

        setInterval(createParticle, 500);
        for (let i = 0; i < 25; i++) createParticle();
    }
})();
