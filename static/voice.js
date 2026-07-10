/* Voice mode — mic ↔ x.ai realtime agent over /ws/voice (PCM16 mono @ 24kHz).
   Mirrors kaljuvee-chat's pipeline; adapted to the AlpaTrade AG-UI chat DOM
   (.chat-messages / .chat-input-form) with self-contained transcript bubbles. */
(() => {
    const RATE = 24000;
    const $ = (s) => document.querySelector(s);
    const msgHost = () => $(".center-chat .chat-messages") || $(".chat-messages") || $("#messages");
    const formEl  = () => $(".chat-input-form") || $(".chat-form") || $("#chat-form");

    let ws = null, active = false;
    let micCtx = null, playCtx = null, stream = null, node = null, srcNode = null, zeroGain = null;
    let nextTime = 0, playing = [];
    let asstBubble = null, statusEl = null;

    // ── UI ──────────────────────────────────────────────────────────────
    function setStatus(state, label) {
        const p = $("#voice-panel");
        if (p) p.setAttribute("data-state", state);
        if (statusEl) statusEl.textContent = label;
        const btn = $("#voice-btn");
        if (btn) btn.classList.toggle("active", active);
    }
    function showPanel() {
        if ($("#voice-panel")) return;
        const p = document.createElement("div");
        p.id = "voice-panel";
        p.className = "voice-panel";
        p.setAttribute("data-state", "connecting");
        p.innerHTML =
            '<span class="voice-wave"><i></i><i></i><i></i><i></i><i></i></span>' +
            '<span class="voice-status" id="voice-status">Connecting…</span>' +
            '<button class="voice-stop" id="voice-stop">End voice</button>';
        const form = formEl();
        if (form && form.parentElement) form.parentElement.insertBefore(p, form);
        else { p.style.margin = "8px"; (msgHost() || document.body).appendChild(p); }
        statusEl = $("#voice-status");
        $("#voice-stop").onclick = stopVoice;
    }
    function hidePanel() {
        const p = $("#voice-panel");
        if (p) p.remove();
        statusEl = null;
    }

    // ── Transcript bubbles (self-contained; styled inline so they render in any chat DOM) ─
    function addBubble(role, text) {
        const wrap = document.createElement("div");
        wrap.className = `voice-msg voice-${role}`;
        wrap.style.cssText = "display:flex;margin:.4rem 0;" +
            (role === "user" ? "justify-content:flex-end" : "justify-content:flex-start");
        const b = document.createElement("div");
        b.style.cssText = "max-width:80%;padding:.5rem .8rem;border-radius:12px;line-height:1.4;" +
            "font-size:.9rem;white-space:pre-wrap;" +
            (role === "user"
                ? "background:#F59E0B;color:#111;border-top-right-radius:4px"
                : "background:#111A2E;border:1px solid #1E293B;color:#E5E7EB;border-top-left-radius:4px");
        b.textContent = text || "";
        wrap.appendChild(b);
        const m = msgHost();
        if (m) { m.appendChild(wrap); m.scrollTop = m.scrollHeight; }
        return b;
    }

    // ── Audio helpers ─────────────────────────────────────────────────────
    function floatToPCM16(f32) {
        const out = new Int16Array(f32.length);
        for (let i = 0; i < f32.length; i++) {
            let s = Math.max(-1, Math.min(1, f32[i]));
            out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return out;
    }
    function downsample(f32, inRate) {
        if (inRate === RATE) return floatToPCM16(f32);
        const ratio = inRate / RATE, outLen = Math.floor(f32.length / ratio);
        const out = new Int16Array(outLen);
        for (let i = 0; i < outLen; i++) {
            const start = Math.floor(i * ratio), end = Math.floor((i + 1) * ratio);
            let sum = 0, c = 0;
            for (let j = start; j < end && j < f32.length; j++) { sum += f32[j]; c++; }
            let s = c ? sum / c : (f32[start] || 0);
            s = Math.max(-1, Math.min(1, s));
            out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return out;
    }
    function b64FromInt16(int16) {
        const bytes = new Uint8Array(int16.buffer);
        let bin = "";
        for (let i = 0; i < bytes.length; i += 0x8000)
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        return btoa(bin);
    }
    function playPCM16(b64) {
        if (!playCtx) return;
        const bin = atob(b64), bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const int16 = new Int16Array(bytes.buffer), f32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 0x8000;
        const buf = playCtx.createBuffer(1, f32.length, RATE);
        buf.getChannelData(0).set(f32);
        const s = playCtx.createBufferSource();
        s.buffer = buf; s.connect(playCtx.destination);
        const now = playCtx.currentTime;
        if (nextTime < now) nextTime = now;
        s.start(nextTime); nextTime += buf.duration;
        s.onended = () => { playing = playing.filter((x) => x !== s); };
        playing.push(s);
    }
    function stopPlayback() {
        playing.forEach((s) => { try { s.stop(); } catch (e) {} });
        playing = []; nextTime = 0;
    }

    // ── Session lifecycle ─────────────────────────────────────────────────
    async function startVoice() {
        if (active) return;
        showPanel();
        setStatus("connecting", "Requesting microphone…");
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
            });
        } catch (e) {
            setStatus("error", "Microphone blocked — allow access and tap the mic again");
            setTimeout(hidePanel, 3000);
            return;
        }
        active = true;
        micCtx = new (window.AudioContext || window.webkitAudioContext)();
        playCtx = new (window.AudioContext || window.webkitAudioContext)();
        try { await micCtx.resume(); await playCtx.resume(); } catch (e) {}

        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws/voice`);
        ws.onopen = () => setStatus("listening", "Listening…");
        ws.onclose = () => { if (active) stopVoice(); };
        ws.onerror = () => setStatus("error", "Connection error");
        ws.onmessage = (ev) => handle(JSON.parse(ev.data));

        srcNode = micCtx.createMediaStreamSource(stream);
        node = micCtx.createScriptProcessor(4096, 1, 1);
        zeroGain = micCtx.createGain(); zeroGain.gain.value = 0;
        srcNode.connect(node); node.connect(zeroGain); zeroGain.connect(micCtx.destination);
        node.onaudioprocess = (e) => {
            if (!ws || ws.readyState !== 1) return;
            const pcm = downsample(e.inputBuffer.getChannelData(0), micCtx.sampleRate);
            ws.send(JSON.stringify({ type: "audio", audio: b64FromInt16(pcm) }));
        };
    }

    function stopVoice() {
        active = false;
        try { node && node.disconnect(); } catch (e) {}
        try { srcNode && srcNode.disconnect(); } catch (e) {}
        try { stream && stream.getTracks().forEach((t) => t.stop()); } catch (e) {}
        stopPlayback();
        try { micCtx && micCtx.close(); } catch (e) {}
        try { playCtx && playCtx.close(); } catch (e) {}
        try { ws && ws.close(); } catch (e) {}
        ws = micCtx = playCtx = stream = node = srcNode = null;
        asstBubble = null;
        hidePanel();
        const btn = $("#voice-btn"); if (btn) btn.classList.remove("active");
    }

    function handle(m) {
        switch (m.type) {
            case "ready": setStatus("listening", "Listening…"); break;
            case "speech_started": stopPlayback(); setStatus("listening", "Listening…"); break;
            case "speech_stopped": setStatus("thinking", "Thinking…"); break;
            case "user_transcript":
                if (m.text) addBubble("user", m.text);
                asstBubble = null;
                break;
            case "assistant_delta":
                if (!asstBubble) asstBubble = addBubble("assistant", "");
                asstBubble.textContent += m.text || "";
                { const mm = msgHost(); if (mm) mm.scrollTop = mm.scrollHeight; }
                setStatus("speaking", "Speaking…");
                break;
            case "tool": setStatus("thinking", "Checking your positions…"); break;
            case "audio": playPCM16(m.audio); break;
            case "assistant_done": asstBubble = null; break;
            case "done": setStatus("listening", "Listening…"); break;
            case "error":
                setStatus("error", "Voice error");
                addBubble("assistant", "Voice error: " + (m.message || "unknown"));
                break;
        }
    }

    window.toggleVoice = () => { active ? stopVoice() : startVoice(); };
})();
