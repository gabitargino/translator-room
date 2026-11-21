# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Testes das salas (Etapa 2; testes 6.1, 6.2 e 6.3 do plano).

Rodam sem modelos: STT, tradução e voz são substituídos por versões falsas.
"""

import asyncio
import json
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.rooms import models as room_models
from app.rooms.models import RoomError, RoomManager
from app.rooms.routing import RoomRouter, crosstalk_reason, target_groups
from app.rooms.session import ParticipantSession
from app.rooms.settings import RoomSettings
from app.rooms.timing import TimingLog, UtteranceTimer, VoiceActivityTracker, pcm16_rms
from app.services.base import TranscriptionResult, TranslationResult, TTSResult
from app.services.pipeline_service import TranslationPipelineService


# ---------------------------------------------------------------- fakes ----
class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeWhisper:
    """STT falso: o bloco ``SAY|idioma|texto`` vira uma fala detectada."""

    mock_mode = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def close(self):
        pass

    async def stream_transcribe(
        self,
        audio_generator,
        language=None,
        emit_policy="live",
        candidate_languages=None,
        on_result=None,
    ):
        self.calls.append(
            {
                "language": language,
                "emit_policy": emit_policy,
                "candidate_languages": candidate_languages,
            }
        )
        transcript = ""
        async for chunk in audio_generator:
            if chunk == b"__END_SIGNAL__":
                return
            if not chunk.startswith(b"SAY|"):
                continue
            _, lang, text = chunk.decode("utf-8").split("|", 2)
            transcript = f"{transcript} {text}".strip()
            yield TranscriptionResult(text=transcript, language=lang)


class FakeTranslation:
    mock_mode = True

    def __init__(self, delays: dict[str, float] | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.delays = delays or {}

    async def close(self):
        pass

    async def translate(self, text, source_language, target_language, **kwargs):
        self.calls.append((text, source_language, target_language))
        await asyncio.sleep(self.delays.get(text, 0))
        return TranslationResult(text=f"[{target_language}] {text}", success=True)


class FakeTTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def close(self):
        pass

    async def synthesize(self, text, language, output_path=None):
        self.calls.append((text, language))
        Path(output_path).write_bytes(b"RIFF")
        return TTSResult(
            audio_path=Path(output_path),
            audio_url=f"/media/output/{Path(output_path).name}",
            success=True,
        )


def make_pipeline(tmp_path, translation=None):
    pipeline = TranslationPipelineService(
        whisper_service=FakeWhisper(),
        translation_service=translation or FakeTranslation(),
        tts_service=FakeTTS(),
        warm_connections=False,
    )
    pipeline.media_dir = tmp_path / "media"
    return pipeline


def make_settings(tmp_path, **overrides) -> RoomSettings:
    values = {
        "empty_ttl_seconds": 60.0,
        "max_participants": 3,
        "audio_max_age_seconds": 600.0,
        "timing_log_path": tmp_path / "timing.jsonl",
    }
    values.update(overrides)
    return RoomSettings(**values)


class Inbox:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    def of(self, kind: str) -> list[dict]:
        return [m for m in self.messages if m.get("type") == kind]

    def kinds(self) -> list[str]:
        return [m["type"] for m in self.messages]


def read_timing(tmp_path) -> list[dict]:
    path = tmp_path / "timing.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------- 2.1 / 2.2 ciclo (6.1) ----
class TestRoomLifecycle:
    def test_create_room_has_unambiguous_code(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        room = manager.create_room()
        assert len(room.code) == 5
        assert set(room.code) <= set(room_models.CODE_ALPHABET)
        assert room.state == "empty"
        assert manager.get_room(room.code.lower()) is room

    def test_join_by_code_and_states(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        room = manager.create_room()
        _, a = manager.join(f" {room.code.lower()} ", "Ana", "pt")
        assert room.state == "waiting"
        assert a.listen_language == "pt"  # escuta padrão = idioma de fala
        _, b = manager.join(room.code, "Bo", "zh", "zh")
        assert room.state == "active"
        assert [p["name"] for p in room.to_state()["participants"]] == ["Ana", "Bo"]
        manager.leave(room.code, b.id)
        assert room.state == "waiting"

    def test_invalid_code_is_rejected(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        with pytest.raises(RoomError) as exc:
            manager.join("NOPE1", "Ana", "pt")
        assert exc.value.code == "room_not_found"

    def test_invalid_language_and_full_room(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path, max_participants=2))
        room = manager.create_room()
        with pytest.raises(RoomError) as exc:
            manager.join(room.code, "Ana", "portuguese!")
        assert exc.value.code == "invalid_language"
        manager.join(room.code, "Ana", "pt-BR")
        manager.join(room.code, "Bo", "zh")
        assert (
            room.participants[next(iter(room.participants))].speak_language == "pt_br"
        )
        with pytest.raises(RoomError) as exc:
            manager.join(room.code, "Cy", "en")
        assert exc.value.code == "room_full"

    def test_name_is_cleaned(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        room = manager.create_room()
        _, a = manager.join(room.code, "  " + "x" * 80, "pt")
        _, b = manager.join(room.code, "", "zh")
        assert a.name == "x" * 40
        assert b.name == "Participante"

    def test_empty_room_expires_and_rejoin_before_expiry(self, tmp_path):
        clock = FakeClock()
        manager = RoomManager(make_settings(tmp_path, empty_ttl_seconds=60), clock)
        room = manager.create_room()
        _, a = manager.join(room.code, "Ana", "pt")
        manager.leave(room.code, a.id)
        assert room.state == "empty"
        clock.now += 59
        assert manager.sweep() == []
        manager.join(room.code, "Ana", "pt")  # voltou antes de expirar
        clock.now += 600
        assert manager.sweep() == []  # sala ocupada não expira
        manager.leave(room.code, next(iter(room.participants)))
        clock.now += 60
        assert manager.sweep() == [room.code]
        with pytest.raises(RoomError):
            manager.get_room(room.code)

    def test_created_room_nobody_joined_expires(self, tmp_path):
        clock = FakeClock()
        manager = RoomManager(make_settings(tmp_path, empty_ttl_seconds=10), clock)
        room = manager.create_room()
        clock.now += 10
        assert manager.sweep() == [room.code]


# ----------------------------------------------------- 2.9 áudios ----------
class TestAudioCleanup:
    def test_expired_room_deletes_its_audio(self, tmp_path):
        clock = FakeClock()
        manager = RoomManager(make_settings(tmp_path, empty_ttl_seconds=5), clock)
        room = manager.create_room()
        audio = tmp_path / "room_audio.wav"
        audio.write_bytes(b"RIFF")
        manager.register_audio(room, audio)
        clock.now += 5
        manager.sweep()
        assert not audio.exists()

    def test_old_audio_deleted_while_room_active(self, tmp_path):
        clock = FakeClock()
        manager = RoomManager(make_settings(tmp_path, audio_max_age_seconds=30), clock)
        room = manager.create_room()
        manager.join(room.code, "Ana", "pt")
        old, new = tmp_path / "old.wav", tmp_path / "new.wav"
        old.write_bytes(b"RIFF")
        manager.register_audio(room, old)
        clock.now += 20
        new.write_bytes(b"RIFF")
        manager.register_audio(room, new)
        clock.now += 10
        manager.sweep()
        assert not old.exists() and new.exists()
        assert [p for _, p in room.audio_files] == [new]

    async def test_stop_deletes_everything(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        room = manager.create_room()
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")
        manager.register_audio(room, audio)
        manager.start()
        await manager.stop()
        assert not audio.exists() and manager.rooms == {}


# ----------------------------------------------- 2.5 roteamento (6.2) -------
async def setup_room(tmp_path, people, translation=None, **settings):
    settings = make_settings(tmp_path, **settings)
    manager = RoomManager(settings)
    pipeline = make_pipeline(tmp_path, translation)
    router = RoomRouter(
        manager, pipeline, settings, TimingLog(settings.timing_log_path)
    )
    room = manager.create_room()
    members = {}
    for name, speak, listen in people:
        inbox = Inbox()
        _, participant = manager.join(room.code, name, speak, listen, inbox)
        members[name] = (participant, inbox)
    return manager, router, pipeline, room, members


async def say(router, room, speaker, text, detected=None, sequence=1):
    timer = UtteranceTimer(room.next_utterance_id(), room.code, speaker.id)
    timer.mark("stt_done")
    return await router.route_utterance(
        room, speaker, text, detected or speaker.speak_language, sequence, timer
    )


class TestRouting:
    async def test_each_side_gets_only_the_other_translation(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        (a, inbox_a), (b, inbox_b) = m["A"], m["B"]
        await say(router, room, a, "Onde fica o metrô?")
        await say(router, room, b, "地铁站在哪里？")

        assert [x["translated_text"] for x in inbox_b.of("room_translation")] == [
            "[zh] Onde fica o metrô?"
        ]
        assert [x["translated_text"] for x in inbox_a.of("room_translation")] == [
            "[pt] 地铁站在哪里？"
        ]
        assert [x["target_language"] for x in inbox_b.of("room_tts")] == ["zh"]
        assert [x["target_language"] for x in inbox_a.of("room_tts")] == ["pt"]
        # quem falou só vê a própria transcrição, sem tradução nem áudio
        assert [x["transcript"] for x in inbox_a.of("self_transcript")] == [
            "Onde fica o metrô?"
        ]
        assert all(x["speaker_id"] != a.id for x in inbox_a.of("room_tts"))
        assert all(x["speaker_id"] != b.id for x in inbox_b.of("room_tts"))
        assert pipeline.translation.calls == [
            ("Onde fica o metrô?", "pt", "zh"),
            ("地铁站在哪里？", "zh", "pt"),
        ]

    async def test_translate_once_per_listen_language(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path,
            [("A", "pt", "pt"), ("B", "zh", "zh"), ("C", "zh", "zh")],
        )
        await say(router, room, m["A"][0], "Bom dia")
        assert pipeline.translation.calls == [("Bom dia", "pt", "zh")]
        assert pipeline.tts.calls == [("[zh] Bom dia", "zh")]
        assert len(m["B"][1].of("room_tts")) == 1
        assert len(m["C"][1].of("room_tts")) == 1

    async def test_same_language_listener_gets_nothing(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path,
            [("A", "pt", "pt"), ("B", "zh", "zh"), ("C", "zh", "pt_br")],
        )
        await say(router, room, m["A"][0], "Bom dia")
        assert m["C"][1].of("room_translation") == []
        assert pipeline.translation.calls == [("Bom dia", "pt", "zh")]
        groups = target_groups(room, m["B"][0])
        assert sorted(groups) == ["pt", "pt_br"]

    async def test_no_listeners_is_logged(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(tmp_path, [("A", "pt", "pt")])
        info = await say(router, room, m["A"][0], "Alô?")
        assert info["status"] == "no_listeners"
        assert pipeline.translation.calls == []
        assert read_timing(tmp_path)[0]["status"] == "no_listeners"

    async def test_listener_who_left_is_skipped(self, tmp_path):
        manager, router, _, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        groups = target_groups(room, m["A"][0])
        manager.leave(room.code, m["B"][0].id)
        sent = await router._send_to(room, groups["zh"], {"type": "x"})
        assert sent == 0 and m["B"][1].messages == []

    async def test_translation_failure_reaches_listener_as_error(self, tmp_path):
        class Failing(FakeTranslation):
            async def translate(self, text, source_language, target_language, **kw):
                return TranslationResult(text="", success=False, error="boom")

        _, router, pipeline, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")], translation=Failing()
        )
        info = await say(router, room, m["A"][0], "Oi")
        assert info["status"] == "partial_failure"
        assert m["B"][1].of("room_error")[0]["error"] == "boom"
        assert pipeline.tts.calls == []

    async def test_generated_audio_is_tracked_for_cleanup(self, tmp_path):
        _, router, _, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        await say(router, room, m["A"][0], "Oi")
        paths = [p for _, p in room.audio_files]
        assert len(paths) == 1 and paths[0].exists()
        assert paths[0].name.startswith(f"room_{room.code}_zh_")


# ---------------------------------------- 2.7 conversa cruzada (6.3) --------
class TestCrosstalkFilter:
    async def test_other_participant_language_is_dropped(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        (a, inbox_a), (_, inbox_b) = m["A"], m["B"]
        info = await say(router, room, a, "你好", detected="zh")
        assert info["status"] == "ignored_crosstalk"
        assert inbox_a.of("utterance_ignored")[0]["reason"] == "crosstalk"
        assert inbox_b.messages == []
        assert pipeline.translation.calls == []

    def test_modes(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        room = manager.create_room()
        _, a = manager.join(room.code, "A", "pt")
        manager.join(room.code, "B", "zh")
        assert crosstalk_reason(room, a, "zh", "room") == "crosstalk"
        assert crosstalk_reason(room, a, "zh", "off") is None
        assert crosstalk_reason(room, a, "pt", "room") is None
        assert crosstalk_reason(room, a, None, "room") is None
        # idioma que ninguém fala (ex.: PT curto detectado como galego) passa
        assert crosstalk_reason(room, a, "gl", "room") is None
        assert crosstalk_reason(room, a, "gl", "strict") == "language_mismatch"


# --------------------------------------- 2.4 / 2.6 sessão e ordem ----------
async def run_session(router, room, participant, chunks):
    session = ParticipantSession(room, participant, router, router.pipeline)
    stt = asyncio.create_task(session.run_stt())
    worker = asyncio.create_task(session.run_worker())
    for chunk in chunks:
        session.push_audio(chunk)
        await asyncio.sleep(0)
    session.end_audio()
    await asyncio.wait_for(stt, 2)
    session.finish_utterances()
    await asyncio.wait_for(worker, 5)
    return session


class TestSession:
    async def test_stt_uses_auto_detection_with_declared_language(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        await run_session(router, room, m["A"][0], [b"SAY|pt|Oi"])
        assert pipeline.whisper.calls == [
            {"language": None, "emit_policy": "pause", "candidate_languages": ["pt"]}
        ]

    async def test_fixed_language_mode(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path, [("A", "zh", "zh")], stt_language_mode="fixed"
        )
        await run_session(router, room, m["A"][0], [])
        assert pipeline.whisper.calls[0]["language"] == "zh"

    async def test_fast_sequence_keeps_order(self, tmp_path):
        # A 1ª tradução demora mais que as outras; mesmo assim chega primeiro.
        slow = FakeTranslation(delays={"um": 0.2, "dois": 0.0, "três": 0.05})
        _, router, _, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")], translation=slow
        )
        await run_session(
            router,
            room,
            m["A"][0],
            [b"SAY|pt|um", b"SAY|pt|dois", "SAY|pt|três".encode()],
        )
        inbox_b = m["B"][1]
        assert [x["transcript"] for x in inbox_b.of("room_tts")] == [
            "um",
            "dois",
            "três",
        ]
        assert [x["sequence"] for x in inbox_b.of("room_translation")] == [1, 2, 3]
        assert [k for k in inbox_b.kinds()] == ["room_translation", "room_tts"] * 3

    async def test_muted_audio_is_not_sent_to_stt(self, tmp_path):
        _, router, pipeline, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        m["A"][0].muted = True
        await run_session(router, room, m["A"][0], [b"SAY|pt|segredo"])
        assert pipeline.translation.calls == []


# ------------------------------------------------- 2.10 marcas de tempo ----
def pcm(level: int, seconds: float = 0.1) -> bytes:
    n = int(16000 * seconds)
    return struct.pack(f"<{n}h", *([level] * n))


class TestTiming:
    def test_rms(self):
        assert pcm16_rms(b"") == 0.0
        assert pcm16_rms(pcm(0)) == 0.0
        assert abs(pcm16_rms(pcm(3277)) - 0.1) < 0.001

    def test_speech_end_ignores_short_pauses(self):
        tracker = VoiceActivityTracker(rms_threshold=0.003, pause_seconds=0.8)
        loud, quiet = pcm(3000), pcm(0)
        tracker.feed(loud, 10.0)
        tracker.feed(loud, 10.5)
        tracker.feed(quiet, 10.6)  # pausa curta (0,3 s): não fecha a frase
        tracker.feed(loud, 10.8)
        tracker.feed(loud, 11.2)
        tracker.feed(quiet, 11.3)
        assert tracker.speech_end_before(12.4) == 11.2
        # a pessoa voltou a falar antes de o STT responder
        tracker.feed(loud, 12.5)
        assert tracker.speech_end_before(12.6) == 11.2
        assert VoiceActivityTracker(0.003, 0.8).speech_end_before(5.0) is None

    async def test_timing_record_has_every_stage(self, tmp_path):
        _, router, _, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        a = m["A"][0]
        timer = UtteranceTimer(room.next_utterance_id(), room.code, a.id)
        timer.mark("speech_end", 100.0)
        timer.mark("stt_done", 101.25)
        await router.route_utterance(room, a, "Oi", "pt", 1, timer)
        record = read_timing(tmp_path)[0]
        assert record["status"] == "delivered"
        assert record["stt_seconds"] == 1.25
        assert record["speech_end_estimated"] is True
        zh = record["targets"]["zh"]
        assert set(zh["t"]) == {
            "translation_done",
            "text_sent",
            "tts_done",
            "audio_sent",
        }
        assert zh["delivered_to"] == 1
        assert zh["listeners"] == [m["B"][0].id]

    async def test_session_marks_speech_end_from_audio(self, tmp_path):
        _, router, _, room, m = await setup_room(
            tmp_path, [("A", "pt", "pt"), ("B", "zh", "zh")]
        )
        session = ParticipantSession(room, m["A"][0], router, router.pipeline)
        session.voice.feed(pcm(3000), 1.0)  # voz bem antes do resultado do STT
        stt = asyncio.create_task(session.run_stt())
        worker = asyncio.create_task(session.run_worker())
        session.push_audio(b"SAY|pt|Oi")
        session.end_audio()
        await asyncio.wait_for(stt, 2)
        session.finish_utterances()
        await asyncio.wait_for(worker, 2)
        record = read_timing(tmp_path)[0]
        # 1.0 é velho demais (> 30 s antes do STT): não é usado
        assert record["speech_end_estimated"] is False


# --------------------------------------- 2.3 / 2.8 conexão (WebSocket) -----
@pytest.fixture
def room_client(tmp_path):
    from app.main import app

    settings = make_settings(tmp_path, max_participants=3)
    manager = RoomManager(settings)
    pipeline = make_pipeline(tmp_path)
    room_models.reset_room_manager(manager)
    with patch("app.routers.api.get_pipeline_service", return_value=pipeline):
        with TestClient(app) as client:
            yield client, manager, pipeline
    room_models.reset_room_manager(None)


def receive_until(ws, kind, name=None):
    while True:
        message = ws.receive_json()
        if message["type"] != kind:
            continue
        if name is None or message.get("participant", {}).get("name") == name:
            return message


class TestRoomWebSocket:
    def test_rest_create_and_get(self, room_client):
        client, manager, _ = room_client
        created = client.post("/api/rooms")
        assert created.status_code == 201
        code = created.json()["room"]
        assert created.json()["ws_url"] == f"/api/ws/rooms/{code}"
        state = client.get(f"/api/rooms/{code.lower()}").json()
        assert state["state"] == "empty" and state["participants"] == []
        assert client.get("/api/rooms/ZZZZZ").status_code == 404

    def test_unknown_room_is_refused(self, room_client):
        client, _, _ = room_client
        with client.websocket_connect("/api/ws/rooms/ZZZZZ?speak=pt") as ws:
            message = ws.receive_json()
        assert message == {
            "type": "error",
            "code": "room_not_found",
            "error": "room not found or expired",
        }

    def test_two_clients_pt_zh(self, room_client):
        client, manager, pipeline = room_client
        code = client.post("/api/rooms").json()["room"]
        base = f"/api/ws/rooms/{code}"
        with client.websocket_connect(f"{base}?name=Ana&speak=pt&listen=pt") as a:
            joined = a.receive_json()
            assert joined["type"] == "joined" and joined["room"] == code
            with client.websocket_connect(f"{base}?name=Bo&speak=zh&listen=zh") as b:
                state_b = receive_until(b, "room_state")
                assert state_b["state"] == "active"
                assert {p["name"] for p in state_b["participants"]} == {"Ana", "Bo"}
                # A é avisado da entrada de B (2.8)
                assert receive_until(a, "participant_joined", "Bo")
                assert receive_until(a, "room_state")["state"] == "active"

                a.send_bytes("SAY|pt|Onde fica o metrô?".encode())
                assert receive_until(a, "self_transcript")["transcript"] == (
                    "Onde fica o metrô?"
                )
                t = receive_until(b, "room_translation")
                assert t["translated_text"] == "[zh] Onde fica o metrô?"
                assert receive_until(b, "room_tts")["audio_url"].startswith(
                    f"/media/output/room_{code}_zh_"
                )

                b.send_bytes("SAY|zh|地铁站在哪里？".encode())
                receive_until(b, "self_transcript")
                tts_a = receive_until(a, "room_tts")
                assert tts_a["translated_text"] == "[pt] 地铁站在哪里？"
                assert tts_a["speaker_name"] == "Bo"

                a.send_json({"type": "mute"})
                muted = receive_until(b, "room_state")
                assert {p["name"]: p["status"] for p in muted["participants"]}[
                    "Ana"
                ] == ("muted")
                a.send_json({"type": "ping"})
                assert receive_until(a, "pong")["type"] == "pong"
                b.send_json({"type": "end"})
            left = receive_until(a, "participant_left")
            assert left["participant"]["name"] == "Bo"
            assert receive_until(a, "room_state")["state"] == "waiting"

        room = manager.rooms[code]
        assert room.state == "empty"
        assert sorted(c[2] for c in pipeline.translation.calls) == ["pt", "zh"]
