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
    /** @type {OscillatorNode[]} */
    let oscs = [];
    /** @type {number | null} */
    let lfoTimer = null;

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
        if (lfoTimer !== null) {
            clearInterval(lfoTimer);
            lfoTimer = null;
        }
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
        const c = ensureContext();
        if (!c) return;

        // If already running, just resume.
        if (master && oscs.length > 0) {
            if (c.state === 'suspended') c.resume().catch(() => {});
            return;
        }

        // Ensure we can play after user gesture.
        if (c.state === 'suspended') c.resume().catch(() => {});

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
        // Use a timer to avoid extra nodes.
        let phase = 0;
        lfoTimer = window.setInterval(() => {
            if (!ctx || !filter) return;
            phase += 0.017; // ~0.27 Hz
            const wobble = 120 * Math.sin(phase);
            const base = 620;
            try {
                filter.frequency.setTargetAtTime(base + wobble, ctx.currentTime, 0.18);
            } catch {
                // ignore
            }
        }, 160);

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

        // Cleanup later.
        window.setTimeout(() => {
            cleanup();
        }, 1400);
    }

    // Expose small API.
    window.douftsStartAmbientPad = startAmbientPad;
    window.douftsStopAmbientPad = stopAmbientPad;
})();
