// SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Sala de tradução para celular (translator-room, Etapa 3).
 *
 * Telas: inicial (3.1) → configuração (3.2) → sala (3.3). O toque em "Entrar"
 * libera o som e o microfone (3.4); as traduções tocam numa fila (3.5); a tela
 * fica ligada (3.6); a conexão volta sozinha se o Wi-Fi oscilar (3.7).
 *
 * Protocolo do servidor: app/rooms/router.py.
 */
(function () {
    'use strict';

    const I18N = window.PolyTalkI18n;
    const PAGE = window.ROOM_PAGE || {};
    const T = (key, params) => (I18N ? I18N.t(key, params) : key);
    const $ = (id) => document.getElementById(id);

    const MAX_CAPTIONS = 40;
    const PING_INTERVAL_MS = 5000;
    const STALE_CONNECTION_MS = 15000; // sem nenhuma mensagem: conexão morta
    const RECONNECT_MAX_DELAY_MS = 8000;
    const PLAYBACK_WATCHDOG_MS = 30000;
    const FATAL_CLOSE = { 4404: 'room_not_found', 4409: 'room_full', 4400: 'invalid_language' };
    const ERROR_KEYS = {
        room_not_found: 'room.not_found',
        room_full: 'room.full',
        invalid_language: 'room.invalid_language'
    };
    const PREFS_KEY = 'translator-room:prefs';

    // ------------------------------------------------------------------
    // Preferências do aparelho (só conveniência: nome e idiomas da última vez)
    // ------------------------------------------------------------------
    const prefs = {
        load() {
            try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') || {}; } catch (e) { return {}; }
        },
        save(value) {
            try { localStorage.setItem(PREFS_KEY, JSON.stringify(value)); } catch (e) { /* modo privado */ }
        }
    };

    function normalizeCode(value) {
        return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    }

    function langLabel(code) {
        return String(code || '').split('_')[0].toUpperCase();
    }

    // ------------------------------------------------------------------
    // Microfone: reaproveita o AudioRecorder do PolyTalk (mesmo PCM 16 kHz,
    // cancelamento de eco e supressão de ruído), mas com um AudioContext criado
    // no toque em "Entrar". No Safari, um contexto criado depois de um await
    // nasce suspenso e o microfone não manda nada.
    // ------------------------------------------------------------------
    class RoomMicrophone extends AudioRecorder {
        async startWithContext(context, onChunk) {
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, sampleRate: 16000 }
            });
            this.audioContext = context;
            if (context.state !== 'running') {
                try { await context.resume(); } catch (e) { /* tenta de novo ao voltar à aba */ }
            }
            const source = context.createMediaStreamSource(this.stream);
            const processor = context.createScriptProcessor(2048, 1, 1);
            this.onChunk = onChunk;
            processor.onaudioprocess = (event) => {
                const input = event.inputBuffer.getChannelData(0);
                const level = this.calculateAudioLevel(input);
                const pcm = new Int16Array(input.length);
                for (let i = 0; i < input.length; i++) {
                    const s = Math.max(-1, Math.min(1, input[i]));
                    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                if (this.onChunk) this.onChunk(pcm.buffer, level);
            };
            source.connect(processor);
            processor.connect(context.destination);
            this.source = source;
            this.processor = processor;
            this.isRecording = true;
        }

        trackEnded() {
            const track = this.stream?.getAudioTracks?.()[0];
            return !track || track.readyState === 'ended';
        }

        async stopKeepingContext() {
            try { this.processor?.disconnect(); this.source?.disconnect(); } catch (e) { /* já parado */ }
            this.stream?.getTracks().forEach((track) => track.stop());
            this.processor = null;
            this.source = null;
            this.isRecording = false;
        }
    }

    // ------------------------------------------------------------------
    // Som: um único <audio> liberado no toque (3.4) e uma fila (3.5)
    // ------------------------------------------------------------------
    function silentWavUrl() {
        const samples = 1600; // 0,1 s a 16 kHz
        const buffer = new ArrayBuffer(44 + samples * 2);
        const view = new DataView(buffer);
        const write = (offset, text) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
        write(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); write(8, 'WAVE');
        write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
        write(36, 'data'); view.setUint32(40, samples * 2, true);
        return URL.createObjectURL(new Blob([buffer], { type: 'audio/wav' }));
    }

    class PlaybackQueue {
        constructor(audio, hooks) {
            this.audio = audio;
            this.hooks = hooks;
            this.items = [];
            this.current = null;
            this.blocked = false;
            this.watchdog = null;
            this.silentUrl = silentWavUrl();
            audio.addEventListener('playing', () => {
                if (this.current && !this.current.started) {
                    this.current.started = true;
                    this.hooks.onStart(this.current);
                }
            });
            audio.addEventListener('ended', () => this.finish());
            audio.addEventListener('error', () => { if (this.current) this.finish(); });
        }

        /** Chamado dentro do toque do usuário: libera a reprodução no celular. */
        unlock() {
            const audio = this.audio;
            audio.muted = false;
            audio.src = this.silentUrl;
            const attempt = audio.play();
            if (attempt && attempt.then) {
                attempt.then(() => {
                    this.blocked = false;
                    this.hooks.onBlocked(false);
                    if (!this.current) audio.pause();
                    this.next();
                }).catch(() => { /* fica para o próximo toque */ });
            }
        }

        get playing() { return Boolean(this.current); }

        push(item) {
            this.items.push(item);
            this.next();
        }

        next() {
            if (this.current || this.blocked || this.items.length === 0) return;
            const item = this.items.shift();
            this.current = item;
            this.hooks.onBusy(true);
            this.audio.src = item.url;
            const attempt = this.audio.play();
            clearTimeout(this.watchdog);
            this.watchdog = setTimeout(() => this.finish(), PLAYBACK_WATCHDOG_MS);
            if (attempt && attempt.catch) {
                attempt.catch((error) => {
                    if (error && error.name === 'NotAllowedError') {
                        // Som bloqueado: devolve à frente da fila e pede um toque.
                        clearTimeout(this.watchdog);
                        this.items.unshift(item);
                        this.current = null;
                        this.blocked = true;
                        this.hooks.onBusy(false);
                        this.hooks.onBlocked(true);
                    } else {
                        this.finish();
                    }
                });
            }
        }

        finish() {
            clearTimeout(this.watchdog);
            const done = this.current;
            this.current = null;
            if (done) this.hooks.onEnd(done);
            if (this.items.length === 0) this.hooks.onBusy(false);
            this.next();
        }

        clear() {
            this.items = [];
            clearTimeout(this.watchdog);
            this.current = null;
            try { this.audio.pause(); } catch (e) { /* nada tocando */ }
            this.hooks.onBusy(false);
        }
    }

    // ------------------------------------------------------------------
    // Tela ligada (3.6)
    // ------------------------------------------------------------------
    class ScreenKeeper {
        constructor(onUnavailable) {
            this.lock = null;
            this.wanted = false;
            this.onUnavailable = onUnavailable;
        }

        async acquire() {
            this.wanted = true;
            if (!('wakeLock' in navigator)) { this.onUnavailable(true); return; }
            if (this.lock || document.visibilityState !== 'visible') return;
            try {
                this.lock = await navigator.wakeLock.request('screen');
                this.onUnavailable(false);
                this.lock.addEventListener('release', () => { this.lock = null; });
            } catch (error) {
                this.onUnavailable(true);
            }
        }

        release() {
            this.wanted = false;
            const lock = this.lock;
            this.lock = null;
            if (lock) lock.release().catch(() => {});
        }
    }

    // ------------------------------------------------------------------
    // Conexão da sala com reconexão automática (3.7)
    // ------------------------------------------------------------------
    class RoomConnection {
        constructor(handlers) {
            this.handlers = handlers;
            this.ws = null;
            this.params = null;
            this.participantId = null;
            this.attempts = 0;
            this.closedByUser = true;
            this.retryTimer = null;
            this.pingTimer = null;
            this.lastMessageAt = 0;
            this.fatal = null;
            // Tempo de ida e volta dos últimos pings, no relógio do celular (5.3).
            this.rttSamples = [];
            window.addEventListener('online', () => this.reconnectNow());
        }

        get open() { return Boolean(this.ws && this.ws.readyState === WebSocket.OPEN); }

        /** Mediana dos últimos RTTs em ms (null antes do primeiro pong). */
        get rttMs() {
            if (this.rttSamples.length === 0) return null;
            const sorted = [...this.rttSamples].sort((a, b) => a - b);
            return sorted[Math.floor(sorted.length / 2)];
        }

        ping() {
            this.sendJson({ type: 'ping', c: performance.now() });
        }

        start(params) {
            this.params = params;
            this.participantId = null;
            this.closedByUser = false;
            this.attempts = 0;
            this.fatal = null;
            this.connect();
            clearInterval(this.pingTimer);
            this.pingTimer = setInterval(() => this.heartbeat(), PING_INTERVAL_MS);
        }

        url() {
            const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
            const query = new URLSearchParams({
                name: this.params.name,
                speak: this.params.speak,
                listen: this.params.listen
            });
            if (this.participantId) query.set('rejoin', this.participantId);
            return `${scheme}://${location.host}/api/ws/rooms/${encodeURIComponent(this.params.code)}?${query}`;
        }

        connect() {
            clearTimeout(this.retryTimer);
            this.retryTimer = null;
            let ws;
            try {
                ws = new WebSocket(this.url());
            } catch (error) {
                this.scheduleReconnect();
                return;
            }
            ws.binaryType = 'arraybuffer';
            this.ws = ws;
            ws.onopen = () => {
                this.lastMessageAt = Date.now();
                this.ping();
            };
            ws.onmessage = (event) => {
                if (ws !== this.ws) return;
                this.lastMessageAt = Date.now();
                let data;
                try { data = JSON.parse(event.data); } catch (e) { return; }
                if (data.type === 'pong' && typeof data.c === 'number') {
                    const rtt = performance.now() - data.c;
                    if (rtt >= 0 && rtt < 5000) {
                        this.rttSamples.push(rtt);
                        if (this.rttSamples.length > 5) this.rttSamples.shift();
                    }
                } else if (data.type === 'joined') {
                    const rejoined = Boolean(this.participantId);
                    this.participantId = data.participant?.id || null;
                    this.attempts = 0;
                    this.handlers.onJoined(data, rejoined);
                } else if (data.type === 'error' && data.code) {
                    this.fatal = data.code;
                }
                this.handlers.onMessage(data);
            };
            ws.onclose = (event) => {
                if (ws !== this.ws) return;
                this.ws = null;
                if (this.closedByUser) return;
                const fatal = this.fatal || FATAL_CLOSE[event.code];
                if (fatal) {
                    this.stop();
                    this.handlers.onFatal(fatal);
                    return;
                }
                this.scheduleReconnect();
            };
        }

        scheduleReconnect() {
            if (this.closedByUser || this.retryTimer) return;
            this.handlers.onConnectionLost();
            const delay = Math.min(RECONNECT_MAX_DELAY_MS, 500 * (2 ** this.attempts));
            this.attempts += 1;
            this.retryTimer = setTimeout(() => this.connect(), delay);
        }

        reconnectNow() {
            if (this.closedByUser || this.open) return;
            if (this.ws && this.ws.readyState === WebSocket.CONNECTING) return;
            this.attempts = 0;
            this.connect();
        }

        /** Descarta a conexão sem esperar o fechamento (Wi-Fi caído não responde). */
        drop() {
            const ws = this.ws;
            this.ws = null;
            if (ws) {
                ws.onopen = ws.onmessage = ws.onclose = null;
                try { ws.close(); } catch (e) { /* já fechada */ }
            }
        }

        heartbeat() {
            if (this.closedByUser) return;
            if (this.open) {
                if (Date.now() - this.lastMessageAt > STALE_CONNECTION_MS) {
                    this.drop();
                    this.scheduleReconnect();
                    return;
                }
                this.ping();
            }
        }

        sendJson(message) {
            if (!this.open) return false;
            this.ws.send(JSON.stringify(message));
            return true;
        }

        sendAudio(buffer) {
            if (!this.open) return false;
            // Evita acumular áudio velho se a rede estiver lenta.
            if (this.ws.bufferedAmount > 256 * 1024) return false;
            this.ws.send(buffer);
            return true;
        }

        stop() {
            this.closedByUser = true;
            clearTimeout(this.retryTimer);
            clearInterval(this.pingTimer);
            this.retryTimer = null;
            const ws = this.ws;
            this.ws = null;
            if (ws) {
                ws.onclose = null;
                try {
                    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'end' }));
                    ws.close();
                } catch (e) { /* já fechada */ }
            }
        }
    }

    // ------------------------------------------------------------------
    // Aplicação
    // ------------------------------------------------------------------
    class RoomApp {
        constructor() {
            this.code = '';
            this.createdHere = false;
            this.joinUrl = '';
            this.inRoom = false;
            this.muted = false;
            this.headphones = true;
            this.me = null;
            this.participants = [];
            this.playingSpeaker = null;
            this.captions = new Map();
            this.audioContext = null;
            this.toastTimer = null;
            this.mic = new RoomMicrophone();
            this.player = new PlaybackQueue($('player'), {
                onStart: (item) => this.onPlaybackStart(item),
                onEnd: () => this.onPlaybackEnd(),
                onBusy: () => this.renderMic(),
                onBlocked: (blocked) => { $('sound-banner').hidden = !blocked; }
            });
            this.screen = new ScreenKeeper((unavailable) => { $('wake-banner').hidden = !unavailable || !this.inRoom; });
            this.conn = new RoomConnection({
                onJoined: (data, rejoined) => this.onJoined(data, rejoined),
                onMessage: (data) => this.onMessage(data),
                onConnectionLost: () => this.setBanner(T('room.reconnecting')),
                onFatal: (code) => this.onFatal(code)
            });
            this.bind();
            this.restorePrefs();
            if (PAGE.initialCode) this.checkRoom(PAGE.initialCode);
        }

        // ----- telas -------------------------------------------------------
        show(name) {
            document.querySelectorAll('[data-screen]').forEach((el) => { el.hidden = el.dataset.screen !== name; });
            window.scrollTo(0, 0);
        }

        showError(id, message) {
            const el = $(id);
            el.textContent = message || '';
            el.hidden = !message;
        }

        toast(message) {
            const el = $('toast');
            el.textContent = message;
            el.hidden = false;
            clearTimeout(this.toastTimer);
            this.toastTimer = setTimeout(() => { el.hidden = true; }, 2500);
        }

        setBanner(message) {
            const el = $('conn-banner');
            el.textContent = message || '';
            el.hidden = !message;
        }

        bind() {
            $('create-btn').addEventListener('click', () => this.createRoom());
            $('join-form').addEventListener('submit', (event) => {
                event.preventDefault();
                this.checkRoom($('code-input').value);
            });
            $('code-input').addEventListener('input', (event) => {
                const el = event.target;
                const value = normalizeCode(el.value);
                if (el.value !== value) el.value = value;
                this.showError('home-error', '');
            });
            $('setup-back').addEventListener('click', () => {
                history.replaceState(null, '', location.pathname + this.localeQuery());
                this.show('home');
            });
            $('speak-select').addEventListener('change', (event) => {
                // Por padrão, ouve no mesmo idioma em que fala.
                const listen = $('listen-select');
                if (listen.dataset.touched !== '1') listen.value = event.target.value;
            });
            $('listen-select').addEventListener('change', (event) => { event.target.dataset.touched = '1'; });
            $('setup-form').addEventListener('submit', (event) => {
                event.preventDefault();
                this.enter();
            });
            $('mute-btn').addEventListener('click', () => this.setMuted(!this.muted));
            $('leave-btn').addEventListener('click', () => this.leave());
            $('invite-btn').addEventListener('click', () => this.openInvite());
            $('invite-close').addEventListener('click', () => { $('invite-sheet').hidden = true; });
            $('invite-sheet').addEventListener('click', (event) => {
                if (event.target === $('invite-sheet')) $('invite-sheet').hidden = true;
            });
            $('copy-link-btn').addEventListener('click', () => this.copyLink());
            $('sound-banner').addEventListener('click', () => {
                this.resumeAudio();
                this.player.unlock();
            });
            document.addEventListener('visibilitychange', () => this.onVisibility());
            window.addEventListener('pagehide', () => { if (this.inRoom) this.conn.stop(); });
        }

        localeQuery() {
            const locale = new URLSearchParams(location.search).get('ui_locale');
            return locale ? `?ui_locale=${encodeURIComponent(locale)}` : '';
        }

        restorePrefs() {
            const saved = prefs.load();
            if (saved.name) $('name-input').value = saved.name;
            const speak = $('speak-select');
            const listen = $('listen-select');
            const uiDefault = (I18N?.locale || 'pt').split('_')[0];
            const pick = (select, value) => {
                if (value && Array.from(select.options).some((o) => o.value === value)) select.value = value;
            };
            pick(speak, saved.speak || uiDefault);
            pick(listen, saved.listen || speak.value);
            if (saved.listen && saved.listen !== saved.speak) listen.dataset.touched = '1';
            if (typeof saved.headphones === 'boolean') $('headphones-check').checked = saved.headphones;
        }

        // ----- 3.1: criar ou entrar ---------------------------------------
        async createRoom() {
            const button = $('create-btn');
            const label = button.textContent;
            button.disabled = true;
            button.textContent = T('room.creating');
            this.showError('home-error', '');
            try {
                const response = await fetch('/api/rooms', { method: 'POST' });
                if (!response.ok) throw new Error(String(response.status));
                const data = await response.json();
                this.createdHere = true;
                this.openSetup(data.room, data.join_url);
            } catch (error) {
                this.showError('home-error', T('room.create_failed'));
            } finally {
                button.disabled = false;
                button.textContent = label;
            }
        }

        async checkRoom(rawCode) {
            const code = normalizeCode(rawCode);
            if (!code) return;
            $('code-input').value = code;
            const button = $('join-btn');
            const label = button.textContent;
            button.disabled = true;
            button.textContent = T('room.checking');
            this.showError('home-error', '');
            try {
                const response = await fetch(`/api/rooms/${encodeURIComponent(code)}`);
                if (response.status === 404) {
                    this.show('home');
                    this.showError('home-error', T('room.not_found'));
                    return;
                }
                if (!response.ok) throw new Error(String(response.status));
                const data = await response.json();
                this.createdHere = false;
                this.openSetup(data.room, data.join_url);
            } catch (error) {
                this.show('home');
                this.showError('home-error', T('room.create_failed'));
            } finally {
                button.disabled = false;
                button.textContent = label;
            }
        }

        // ----- 3.2: configuração -------------------------------------------
        openSetup(code, joinUrl) {
            this.code = code;
            this.joinUrl = joinUrl || `${location.origin}/sala?code=${code}`;
            $('setup-code').textContent = T('room.room_code', { code });
            this.showError('setup-error', '');
            history.replaceState(null, '', `${location.pathname}?code=${code}${this.localeQuery().replace('?', '&')}`);
            this.show('setup');
            if (!$('name-input').value) $('name-input').focus();
        }

        /** 3.4: tudo o que precisa de um toque acontece antes do primeiro await. */
        async enter() {
            const name = $('name-input').value.trim();
            const speak = $('speak-select').value;
            const listen = $('listen-select').value;
            this.headphones = $('headphones-check').checked;
            prefs.save({ name, speak, listen, headphones: this.headphones });
            this.showError('setup-error', '');

            if (!window.isSecureContext || !RoomMicrophone.isSupported()) {
                this.showError('setup-error', T('room.mic_unsupported'));
                return;
            }

            // Dentro do gesto: libera o <audio> e cria o contexto do microfone.
            this.player.unlock();
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!this.audioContext || this.audioContext.state === 'closed') {
                this.audioContext = new Ctx({ sampleRate: 16000 });
            }
            this.audioContext.resume().catch(() => {});
            this.screen.acquire();

            const button = $('enter-btn');
            button.disabled = true;
            try {
                await this.startMic();
            } catch (error) {
                button.disabled = false;
                this.screen.release();
                const denied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
                this.showError('setup-error', denied ? T('room.mic_denied') : T('room.error_generic', { error: error?.message || error }));
                return;
            }
            button.disabled = false;

            this.inRoom = true;
            this.muted = false;
            this.me = null;
            this.participants = [];
            this.captions.clear();
            this.clearCaptions();
            $('room-code').textContent = this.code;
            this.setBanner(T('room.connecting'));
            this.renderPeople();
            this.renderMic();
            this.show('room');
            this.conn.start({ code: this.code, name, speak, listen });
        }

        async startMic() {
            await this.mic.startWithContext(this.audioContext, (buffer, level) => this.onMicChunk(buffer, level));
        }

        onMicChunk(buffer, level) {
            if (!this.inRoom) return;
            const pausedForPlayback = !this.headphones && this.player.playing;
            const live = !this.muted && !pausedForPlayback;
            this.renderLevel(live ? level : 0);
            if (this.muted) return;
            // Sem fone: manda silêncio enquanto a tradução toca, para o STT
            // fechar a frase sem ouvir o próprio alto-falante.
            this.conn.sendAudio(pausedForPlayback ? new ArrayBuffer(buffer.byteLength) : buffer);
        }

        // ----- 3.3: sala ----------------------------------------------------
        onJoined(data, rejoined) {
            this.me = data.participant;
            this.setBanner('');
            if (this.muted) this.conn.sendJson({ type: 'mute' });
            if (rejoined) this.toast(T('room.reconnected'));
        }

        onMessage(data) {
            switch (data.type) {
            case 'room_state':
                this.participants = data.participants || [];
                this.renderPeople(data.state);
                if (this.createdHere && data.state === 'waiting' && !this.inviteShown) {
                    this.inviteShown = true;
                    this.openInvite();
                }
                if (data.state === 'active') $('invite-sheet').hidden = true;
                break;
            case 'participant_joined':
                if (!data.rejoined && data.participant?.id !== this.me?.id) {
                    this.addEvent(T('room.joined_event', { name: data.participant?.name || '' }));
                }
                break;
            case 'participant_left':
                if (data.participant?.id !== this.me?.id) {
                    this.addEvent(T('room.left_event', { name: data.participant?.name || '' }));
                }
                break;
            case 'self_transcript':
                this.addCaption(data.utterance_id + ':self', {
                    who: T('room.you_said'), text: data.transcript, kind: 'self'
                });
                break;
            case 'room_translation':
                this.addCaption(data.utterance_id, {
                    who: data.speaker_name, text: data.translated_text, kind: 'pending'
                });
                break;
            case 'room_tts':
                this.addCaption(data.utterance_id, {
                    who: data.speaker_name, text: data.translated_text, kind: ''
                });
                this.player.push({
                    url: data.audio_url,
                    utteranceId: data.utterance_id,
                    speakerId: data.speaker_id,
                    receivedAt: performance.now()
                });
                break;
            case 'room_error':
                this.addCaption(data.utterance_id + ':err', {
                    who: data.speaker_name, text: T('room.error_stage', { stage: data.stage }), kind: 'error'
                });
                break;
            case 'error':
                if (!data.code) this.toast(T('room.error_generic', { error: data.error || data.stage || '' }));
                break;
            default:
                break; // pong, utterance_ignored
            }
        }

        onFatal(code) {
            const message = code === 'room_not_found' ? T('room.room_closed') : T(ERROR_KEYS[code] || 'room.error_generic', { error: code });
            this.teardown();
            history.replaceState(null, '', location.pathname + this.localeQuery());
            this.show('home');
            this.showError('home-error', message);
        }

        setMuted(muted) {
            this.muted = muted;
            this.conn.sendJson({ type: muted ? 'mute' : 'unmute' });
            this.renderMic();
        }

        leave() {
            this.conn.stop();
            this.teardown();
            history.replaceState(null, '', location.pathname + this.localeQuery());
            this.show('home');
        }

        teardown() {
            this.inRoom = false;
            this.inviteShown = false;
            this.player.clear();
            this.mic.stopKeepingContext();
            this.screen.release();
            this.setBanner('');
            $('wake-banner').hidden = true;
            $('sound-banner').hidden = true;
            $('invite-sheet').hidden = true;
        }

        resumeAudio() {
            if (this.audioContext && this.audioContext.state !== 'running' && this.audioContext.state !== 'closed') {
                this.audioContext.resume().catch(() => {});
            }
        }

        async onVisibility() {
            if (!this.inRoom || document.visibilityState !== 'visible') return;
            this.resumeAudio();
            if (this.screen.wanted) this.screen.acquire();
            this.conn.reconnectNow();
            // Alguns celulares encerram o microfone quando a tela apaga.
            if (this.mic.trackEnded()) {
                try {
                    await this.mic.stopKeepingContext();
                    await this.startMic();
                } catch (error) {
                    this.toast(T('room.mic_denied'));
                }
            }
        }

        onPlaybackStart(item) {
            this.playingSpeaker = item.speakerId;
            this.renderPeople();
            // Marca T6 da Etapa 5: o servidor usa a chegada deste aviso menos
            // metade do RTT; wait_ms (relógio do celular) serve de conferência.
            this.conn.sendJson({
                type: 'playback_started',
                utterance_id: item.utteranceId,
                rtt_ms: this.conn.rttMs,
                wait_ms: item.receivedAt ? Math.round(performance.now() - item.receivedAt) : null
            });
        }

        onPlaybackEnd() {
            this.playingSpeaker = null;
            this.renderPeople();
        }

        // ----- convite (3.9) ------------------------------------------------
        openInvite() {
            $('invite-code').textContent = this.code;
            $('invite-qr').src = `/api/rooms/${encodeURIComponent(this.code)}/qr.svg`;
            $('invite-link').textContent = this.joinUrl;
            $('invite-sheet').hidden = false;
        }

        async copyLink() {
            try {
                await navigator.clipboard.writeText(this.joinUrl);
                this.toast(T('room.link_copied'));
            } catch (error) {
                const range = document.createRange();
                range.selectNodeContents($('invite-link'));
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }
        }

        // ----- desenho ------------------------------------------------------
        renderPeople(state) {
            const list = $('people');
            list.textContent = '';
            this.participants.forEach((p) => {
                const li = document.createElement('li');
                li.className = 'person';
                const isMe = this.me && p.id === this.me.id;
                const isMuted = p.status === 'muted';
                const isPlaying = !isMe && this.playingSpeaker === p.id;
                if (isMuted) li.classList.add('muted');
                if (isPlaying) li.classList.add('playing');

                const dot = document.createElement('span');
                dot.className = 'person-dot';
                const name = document.createElement('span');
                name.className = 'person-name';
                name.textContent = isMe ? `${p.name} (${T('room.you')})` : p.name;
                const lang = document.createElement('span');
                lang.className = 'person-lang';
                lang.textContent = p.listen_language && p.listen_language !== p.speak_language
                    ? `${langLabel(p.speak_language)}→${langLabel(p.listen_language)}`
                    : langLabel(p.speak_language);
                lang.title = I18N?.displayLanguageName(p.speak_language) || p.speak_language;
                const status = document.createElement('span');
                status.className = 'person-status';
                status.textContent = isPlaying ? `🔊 ${T('room.status_playing')}`
                    : (isMuted ? T('room.status_muted') : T('room.status_connected'));

                li.append(dot, name, lang, status);
                list.appendChild(li);
            });
            const waiting = (state || (this.participants.length < 2 ? 'waiting' : 'active')) === 'waiting';
            $('waiting').hidden = !(this.inRoom && waiting && this.participants.length > 0);
        }

        renderMic() {
            const box = $('mic-state');
            const pausedForPlayback = !this.headphones && this.player.playing;
            box.classList.toggle('muted', this.muted);
            box.classList.toggle('paused', !this.muted && pausedForPlayback);
            box.classList.toggle('live', !this.muted && !pausedForPlayback);
            $('mic-label').textContent = this.muted ? T('room.mic_muted')
                : (pausedForPlayback ? T('room.mic_paused_playback') : T('room.mic_active'));
            const button = $('mute-btn');
            button.textContent = this.muted ? T('room.unmute') : T('room.mute');
            button.setAttribute('aria-pressed', String(this.muted));
            if (this.muted || pausedForPlayback) this.renderLevel(0);
        }

        renderLevel(level) {
            // RMS típico de voz: 0,01–0,2. Escala logarítmica para a barra.
            const pct = level > 0 ? Math.max(0, Math.min(100, (Math.log10(level) + 3) * 45)) : 0;
            $('mic-level').style.width = `${pct.toFixed(0)}%`;
        }

        clearCaptions() {
            const list = $('captions');
            list.textContent = '';
            const empty = document.createElement('li');
            empty.className = 'captions-empty';
            empty.id = 'captions-empty';
            empty.textContent = T('room.captions_empty');
            list.appendChild(empty);
        }

        addCaption(key, { who, text, kind }) {
            const list = $('captions');
            $('captions-empty')?.remove();
            let li = this.captions.get(key);
            if (!li) {
                li = document.createElement('li');
                const whoEl = document.createElement('div');
                whoEl.className = 'caption-who';
                const textEl = document.createElement('div');
                textEl.className = 'caption-text';
                li.append(whoEl, textEl);
                list.appendChild(li);
                this.captions.set(key, li);
                while (list.children.length > MAX_CAPTIONS) {
                    const first = list.firstElementChild;
                    for (const [k, v] of this.captions) { if (v === first) this.captions.delete(k); }
                    first.remove();
                }
            }
            li.className = `caption ${kind || ''}`.trim();
            li.children[0].textContent = who || '';
            li.children[1].textContent = text || '';
            list.scrollTop = list.scrollHeight;
        }

        addEvent(text) {
            const key = `event:${Date.now()}:${Math.random()}`;
            this.addCaption(key, { who: '', text, kind: 'event' });
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        window.roomApp = new RoomApp();
    });
}());
