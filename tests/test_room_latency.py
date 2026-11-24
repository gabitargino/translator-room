# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Medição de latência da sala (Etapa 5)."""

from pathlib import Path

import pytest

from app.rooms.latency import (
    analyze,
    collect,
    markdown_table,
    percentile,
    playback_record,
)
from tests.test_rooms import read_timing, receive_until, room_client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def utterance(uid, source, target, listener, speech_end, offsets, room="ABCDE"):
    """Linha de fala como a do UtteranceTimer.to_record()."""
    marks = {k: speech_end + v for k, v in offsets.items()}
    return {
        "utterance_id": uid,
        "room": room,
        "speaker": "s",
        "source_language": source,
        "status": "delivered",
        "speech_end_estimated": True,
        "t": {"speech_end": speech_end, "stt_done": speech_end + 1.2},
        "targets": {target: {"listeners": [listener], "t": marks}},
    }


SENT = {"translation_done": 1.5, "text_sent": 1.5, "tts_done": 1.8, "audio_sent": 1.8}


class TestPlaybackRecord:
    def test_t6_is_arrival_minus_half_rtt(self):
        record = playback_record("R-1", "R", "l1", 1000.0, rtt_ms=40, wait_ms=120)
        assert record["event"] == "playback_started"
        assert record["t"] == 1000.0
        assert record["t_playback"] == pytest.approx(999.98)
        assert record["rtt_ms"] == 40 and record["wait_ms"] == 120
        assert record["clock"] == "server_arrival_minus_half_rtt"

    @pytest.mark.parametrize("bad", [None, "x", -5, float("nan"), 999999])
    def test_invalid_rtt_falls_back_to_arrival(self, bad):
        record = playback_record("R-1", "R", "l1", 1000.0, rtt_ms=bad)
        assert record["t_playback"] == 1000.0
        assert record["clock"] == "server_arrival"
        assert "rtt_ms" not in record


class TestAnalysis:
    def test_percentile_interpolates(self):
        assert percentile([1.0], 0.95) == 1.0
        assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
        assert percentile(list(range(1, 21)), 0.95) == pytest.approx(19.05)

    def test_collect_joins_playback_by_utterance_and_listener(self):
        records = [
            utterance("R-1", "pt", "zh", "b", 100.0, SENT),
            utterance("R-2", "zh", "pt", "a", 200.0, SENT),
            playback_record("R-1", "ABCDE", "b", 102.1, rtt_ms=20),
            # aviso de outro ouvinte não conta para b
            playback_record("R-2", "ABCDE", "x", 202.0),
            {"event": "playback_started", "utterance_id": "R-9", "room": "ABCDE"},
            "linha inválida",
        ]
        rows = collect(records)
        assert [r["direction"] for r in rows] == ["pt→zh", "zh→pt"]
        first, second = rows
        assert first["since_speech_end"]["playback"] == pytest.approx(2.09)
        assert first["stages"] == {
            "silencio_e_stt": 1.2,
            "traducao": 0.3,
            "voz": 0.3,
            "envio": 0.0,
            "celular": pytest.approx(0.29),
        }
        assert first["rtt_ms"] == 20
        assert "playback" not in second["since_speech_end"]

    def test_collect_filters_room_and_skips_ignored(self):
        ignored = utterance("Z-1", "pt", "zh", "b", 1.0, SENT, room="ZZZZZ")
        ignored["targets"] = {}
        records = [
            utterance("R-1", "pt", "zh", "b", 100.0, SENT),
            utterance("Z-2", "pt", "zh", "b", 1.0, SENT, room="ZZZZZ"),
            ignored,
        ]
        assert [r["utterance_id"] for r in collect(records, room="ABCDE")] == ["R-1"]
        assert [r["utterance_id"] for r in collect(records, room="ZZZZZ")] == ["Z-2"]

    def test_analyze_per_direction_and_table(self):
        records = []
        for i, total in enumerate([1.5, 2.0, 2.5, 3.5]):
            uid = f"R-{i}"
            records += [
                utterance(uid, "pt", "zh", "b", 100.0 * i, SENT),
                playback_record(uid, "ABCDE", "b", 100.0 * i + total),
            ]
        records.append(utterance("R-9", "zh", "pt", "a", 900.0, SENT))
        result = analyze(collect(records))
        pt = result["pt→zh"]
        assert pt["falas"] == 4
        assert pt["ate_inicio_do_audio_s"]["n"] == 4
        assert pt["ate_inicio_do_audio_s"]["mediana"] == 2.25
        assert pt["ate_inicio_do_audio_s"]["max"] == 3.5
        assert pt["dentro_da_meta_3s"] == 3
        assert pt["etapas_mediana_s"]["traducao"] == 0.3
        zh = result["zh→pt"]
        assert zh["ate_inicio_do_audio_s"] == {"n": 0}
        assert zh["ate_link_enviado_s"]["mediana"] == 1.8

        table = markdown_table(result)
        assert "| PT→ZH | 4 | 4 | 2,25 |" in table
        assert "| 3/4 |" in table
        assert "| ZH→PT | 1 | 0 | – |" in table


class TestRoomWebSocketLatency:
    def test_pong_echoes_client_clock_and_playback_is_logged(
        self,
        room_client,  # noqa: F811
        tmp_path,
    ):
        client, _, _ = room_client
        code = client.post("/api/rooms").json()["room"]
        base = f"/api/ws/rooms/{code}"
        with client.websocket_connect(f"{base}?name=Ana&speak=pt&listen=pt") as a:
            receive_until(a, "joined")
            with client.websocket_connect(f"{base}?name=Bo&speak=zh&listen=zh") as b:
                receive_until(b, "room_state")
                b.send_json({"type": "ping", "c": 1234.5})
                assert receive_until(b, "pong")["c"] == 1234.5

                a.send_bytes("SAY|pt|Bom dia".encode())
                tts = receive_until(b, "room_tts")
                b.send_json(
                    {
                        "type": "playback_started",
                        "utterance_id": tts["utterance_id"],
                        "rtt_ms": 30,
                        "wait_ms": 210,
                    }
                )
                b.send_json({"type": "ping"})  # garante que o aviso foi lido
                assert receive_until(b, "pong")["c"] is None
                b.send_json({"type": "end"})
            a.send_json({"type": "end"})

        records = read_timing(tmp_path)
        playback = [r for r in records if r.get("event") == "playback_started"]
        assert len(playback) == 1
        assert playback[0]["rtt_ms"] == 30 and playback[0]["wait_ms"] == 210
        assert playback[0]["t_playback"] == pytest.approx(playback[0]["t"] - 0.015)

        rows = collect(records, room=code)
        assert rows and rows[0]["direction"] == "pt→zh"
        assert "playback" in rows[0]["since_speech_end"]


def test_client_sends_rtt_and_wait():
    source = (ROOT / "app" / "static" / "js" / "room-app.js").read_text(
        encoding="utf-8"
    )
    assert "rtt_ms: this.conn.rttMs" in source
    assert "receivedAt: performance.now()" in source
    assert "type: 'ping', c: performance.now()" in source
