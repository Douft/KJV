(() => {
    'use strict';

    // A tiny, dependency-free ambient pad using the Web Audio API.
    // Starts only after a user gesture (we call it from the intro click).

    /** @type {AudioContext | null} */
    let ctx = null;
    /** @type {GainNode | null} */
    let master = null;
    /** @type {BiquadFilterNode | null} */
    let filter = null;
    /** @type {OscillatorNode | null} */
    let lfoOsc = null;
    /** @type {GainNode | null} */
    let lfoGain = null;
    /** @type {OscillatorNode[]} */
    let oscs = [];

    let startPending = false;

    const STORAGE_KEY_ENABLED = 'bi_bg_music';

    function isAmbientPadEnabled() {
        try {
            const v = localStorage.getItem(STORAGE_KEY_ENABLED);
            if (v == null) return true;
            return v !== '0';
        } catch {
            return true;
        }
    }

    function setAmbientPadEnabled(enabled) {
        try {
            localStorage.setItem(STORAGE_KEY_ENABLED, enabled ? '1' : '0');
        } catch {
            // ignore
        }
    }

    function now() {
        return ctx ? ctx.currentTime : 0;
    }

    function stopOscsAt(t) {
        for (const o of oscs) {
            try {
                o.stop(t);
            } catch {
                // ignore
            }
        }
        oscs = [];
    }

    function cleanup() {
        lfoOsc = null;
        lfoGain = null;
        master = null;
        filter = null;
    }

    function ensureContext() {
        if (ctx) return ctx;
        const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextCtor) return null;
        ctx = new AudioContextCtor();
        return ctx;
    }

    // Keep this very low volume; narration is the main audio.
    const TARGET_GAIN = 0.035;

    function startAmbientPad() {
        if (!isAmbientPadEnabled()) return;

        const c = ensureContext();
        if (!c) return;

        // If already running, just resume.
        if (master && oscs.length > 0) {
            if (c.state === 'suspended') c.resume().catch(() => {});
            return;
        }

        function startGraph() {
            master = c.createGain();
            master.gain.setValueAtTime(0, now());

            filter = c.createBiquadFilter();
            filter.type = 'lowpass';
            filter.frequency.setValueAtTime(650, now());
            filter.Q.setValueAtTime(0.6, now());

            // Gentle chord (A minor-ish): A3, C4, E4 + soft A2.
            // Slight detune for warmth.
            const freqs = [110, 220, 261.626, 329.628];
            const detunes = [-7, 5, -3, 4];

            oscs = freqs.map((f, i) => {
                const o = c.createOscillator();
                o.type = 'sine';
                o.frequency.setValueAtTime(f, now());
                o.detune.setValueAtTime(detunes[i] || 0, now());
                return o;
            });

            // Very slow movement by gently modulating the filter cutoff.
            // Do this in the audio graph (not a JS timer) so it can't "freeze" when the main thread is busy.
            const base = 620;
            filter.frequency.setValueAtTime(base, now());

            lfoOsc = c.createOscillator();
            lfoOsc.type = 'sine';
            lfoOsc.frequency.setValueAtTime(0.27, now());

            lfoGain = c.createGain();
            lfoGain.gain.setValueAtTime(120, now());

            lfoOsc.connect(lfoGain);
            lfoGain.connect(filter.frequency);

            // Connect graph.
            for (const o of oscs) {
                o.connect(filter);
            }
            filter.connect(master);
            master.connect(c.destination);

            // Fade in slowly.
            const t0 = now();
            master.gain.setValueAtTime(0, t0);
            master.gain.linearRampToValueAtTime(TARGET_GAIN, t0 + 2.2);

            for (const o of oscs) {
                o.start(t0);
            }

            try {
                lfoOsc.start(t0);
            } catch {
                // ignore
            }
        }

        if (c.state === 'suspended') {
            if (startPending) return;
            startPending = true;
            c.resume()
                .then(() => {
                    startPending = false;
                    if (!isAmbientPadEnabled()) return;
                    if (master && oscs.length > 0) return;
                    startGraph();
                })
                .catch(() => {
                    startPending = false;
                });
            return;
        }

        startGraph();
    }

    function stopAmbientPad() {
        if (!ctx || !master) {
            cleanup();
            return;
        }

        const t0 = now();
        try {
            master.gain.cancelScheduledValues(t0);
            master.gain.setValueAtTime(master.gain.value, t0);
            master.gain.linearRampToValueAtTime(0, t0 + 1.2);
        } catch {
            // ignore
        }

        // Stop oscillators after fade.
        stopOscsAt(t0 + 1.25);

        if (lfoOsc) {
            try {
                lfoOsc.stop(t0 + 1.25);
            } catch {
                // ignore
            }
        }

        // Cleanup later.
        window.setTimeout(() => {
            cleanup();
        }, 1400);
    }

    // Expose small API.
    window.douftsStartAmbientPad = startAmbientPad;
    window.douftsStopAmbientPad = stopAmbientPad;
    window.douftsIsAmbientPadEnabled = isAmbientPadEnabled;
    window.douftsSetAmbientPadEnabled = (enabled) => {
        setAmbientPadEnabled(!!enabled);
        if (!isAmbientPadEnabled()) stopAmbientPad();
    };

    // Minimal UI: add a small toggle on the intro screen.
    function ensureMusicToggleUi() {
        try {
            const intro = document.getElementById('intro-screen');
            if (!intro) return;
            if (intro.querySelector('[data-doufts-music-toggle="1"]')) return;

            const btn = document.createElement('div');
            btn.className = 'subtitle';
            btn.setAttribute('data-doufts-music-toggle', '1');
            btn.style.cursor = 'pointer';
            btn.style.userSelect = 'none';
            btn.style.marginTop = '10px';

            function sync() {
                btn.textContent = `Music: ${isAmbientPadEnabled() ? 'On' : 'Off'}`;
            }

            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                setAmbientPadEnabled(!isAmbientPadEnabled());
                if (!isAmbientPadEnabled()) stopAmbientPad();
                sync();
            });

            sync();
            intro.appendChild(btn);
        } catch {
            // ignore
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ensureMusicToggleUi);
    } else {
        ensureMusicToggleUi();
    }
})();
