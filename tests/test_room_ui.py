# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Testes da interface da sala (Etapa 3): página, textos PT/ZH, QR code e
reconexão. O comportamento no navegador (som, microfone, tela ligada) é
conferido à mão no celular; aqui ficam as partes que o servidor garante.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.i18n import public_catalog
from app.rooms.models import RoomManager
from app.rooms.web import DEFAULT_SOURCE_URL

from tests.test_rooms import make_settings, receive_until, room_client  # noqa: F401

LOCALES = Path("app/locales")


def catalog(locale: str) -> dict:
    return json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


# ----------------------------------------------------------- 3.1–3.3 ----
class TestRoomPage:
    def test_page_has_three_screens_and_scripts(self, client):
        response = client.get("/sala?ui_locale=pt")
        assert response.status_code == 200
        html = response.text
        for screen in ("screen-home", "screen-setup", "screen-room"):
            assert f'id="{screen}"' in html
        assert "/static/js/audio-recorder.js" in html  # reaproveita o módulo
        assert "/static/js/room-app.js" in html
        assert "window.POLYTALK_I18N" in html
        assert "Criar sala" in html and "Entrar" in html

    def test_alias_and_prefilled_code(self, client):
        response = client.get("/room?code=k7q29&ui_locale=en")
        assert response.status_code == 200
        assert '"initialCode": "K7Q29"' in response.text or (
            'initialCode: "K7Q29"' in response.text
        )
        assert 'value="K7Q29"' in response.text

    def test_language_selects_offer_pt_and_zh(self, client):
        html = client.get("/sala?ui_locale=pt").text
        assert 'id="speak-select"' in html and 'id="listen-select"' in html
        assert '<option value="pt">Português</option>' in html
        assert '<option value="zh">Chinês</option>' in html

    def test_original_page_still_served_and_links_to_room(self, client):
        html = client.get("/?ui_locale=en").text
        assert 'id="source-lang"' in html  # tela original intacta
        assert 'href="/sala"' in html


# ------------------------------------------------------------- 3.8 ----
class TestChineseInterface:
    def test_room_page_in_chinese(self, client):
        response = client.get("/sala?ui_locale=zh")
        assert response.status_code == 200
        assert '<html lang="zh">' in response.text
        assert "创建房间" in response.text
        assert '<option value="zh">中文</option>' in response.text

    def test_accept_language_zh_cn_picks_chinese(self, client):
        response = client.get("/sala", headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        assert '<html lang="zh">' in response.text

    def test_original_page_accepts_chinese(self, client):
        response = client.get("/?ui_locale=zh")
        assert '<html lang="zh">' in response.text
        # O título vem do servidor; o resto é traduzido pelo i18n.js no navegador.
        assert "<title>PolyTalk - 隐私优先的自托管翻译</title>" in response.text

    def test_zh_catalog_covers_every_english_text(self):
        en, zh = catalog("en"), catalog("zh")
        assert set(en["_text"]) <= set(zh["_text"])
        assert set(en["_languages"]) <= set(zh["_languages"])
        top_keys = {k for k in en if not k.startswith("_")}
        assert top_keys <= set(zh)

    def test_room_keys_translated_in_pt_and_zh(self):
        en, pt, zh = catalog("en"), catalog("pt"), catalog("zh")
        room_keys = {k for k in en if k.startswith("room.")}
        assert len(room_keys) >= 40
        assert room_keys <= set(pt) and room_keys <= set(zh)
        # Tudo que é frase precisa estar de fato traduzido.
        same_ok = {"room.code_placeholder", "room.ui_language"}
        for key in room_keys - same_ok:
            assert zh[key] != en[key], f"zh deixa {key} em inglês"
        for key in room_keys - same_ok - {"room.room_code"}:
            assert pt[key] != en[key], f"pt deixa {key} em inglês"

    def test_placeholders_match_across_locales(self):
        import re

        en, pt, zh = catalog("en"), catalog("pt"), catalog("zh")
        for key in (k for k in en if k.startswith("room.")):
            names = set(re.findall(r"\{(\w+)\}", en[key]))
            assert set(re.findall(r"\{(\w+)\}", pt[key])) == names, key
            assert set(re.findall(r"\{(\w+)\}", zh[key])) == names, key

    def test_public_catalog_merges_room_keys(self):
        merged = public_catalog("zh", Config())
        assert merged["room.enter"] == "进入"
        # Idioma sem as chaves da sala cai no inglês.
        assert public_catalog("de", Config())["room.enter"] == "Enter"


# ------------------------------------------------------------ 3.10 ----
class TestLicenseNotice:
    def test_source_link_visible(self, client):
        html = client.get("/sala?ui_locale=pt").text
        assert f'href="{DEFAULT_SOURCE_URL}"' in html
        assert "Código-fonte (AGPL-3.0)" in html

    def test_source_link_configurable(self, client, monkeypatch):
        monkeypatch.setenv("ROOM_SOURCE_URL", "https://example.org/fork")
        html = client.get("/sala").text
        assert 'href="https://example.org/fork"' in html


# ------------------------------------------------------------- 3.9 ----
class TestInviteQr:
    def test_qr_svg_for_existing_room(self, room_client):  # noqa: F811
        client, _, _ = room_client
        code = client.post("/api/rooms").json()["room"]
        response = client.get(f"/api/rooms/{code}/qr.svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.text.lstrip().startswith("<svg")

    def test_qr_unknown_room(self, room_client):  # noqa: F811
        client, _, _ = room_client
        assert client.get("/api/rooms/ZZZZZ/qr.svg").status_code == 404

    def test_join_url_uses_request_host(self, room_client):  # noqa: F811
        client, _, _ = room_client
        created = client.post("/api/rooms").json()
        code = created["room"]
        assert created["join_url"] == f"http://testserver/sala?code={code}"
        assert (
            client.get(f"/api/rooms/{code}").json()["join_url"] == (created["join_url"])
        )

    def test_join_url_public_base_override(self, room_client, monkeypatch):  # noqa: F811
        client, _, _ = room_client
        monkeypatch.setenv("ROOM_PUBLIC_BASE_URL", "https://192.168.0.10:9443/")
        code = client.post("/api/rooms").json()["room"]
        data = client.get(f"http://localhost:9000/api/rooms/{code}").json()
        assert data["join_url"] == f"https://192.168.0.10:9443/sala?code={code}"

    def test_join_url_keeps_tunnel_host(self, room_client, monkeypatch):  # noqa: F811
        """Aberta pelo túnel, o QR leva ao túnel, não ao IP da Wi-Fi."""
        client, _, _ = room_client
        monkeypatch.setenv("ROOM_PUBLIC_BASE_URL", "https://192.168.0.10:9443")
        code = client.post("/api/rooms").json()["room"]
        data = client.get(
            f"http://app/api/rooms/{code}",
            headers={"host": "abc.trycloudflare.com"},
        ).json()
        assert data["join_url"] == f"http://abc.trycloudflare.com/sala?code={code}"

    def test_qr_encodes_join_url(self):
        import segno

        from app.rooms.web import qr_svg

        url = "https://192.168.0.10:9443/sala?code=K7Q29"
        expected = segno.make(url, error="m").svg_inline(
            scale=8, border=2, dark="#111827", light="#ffffff"
        )
        assert qr_svg(url) == expected


# ------------------------------------------------------------- 3.7 ----
class TestRejoin:
    def test_drop_stale_removes_old_participant(self, tmp_path):
        manager = RoomManager(make_settings(tmp_path))
        room = manager.create_room()
        _, old = manager.join(room.code, "Ana", "pt")
        manager.join(room.code, "Bo", "zh")
        stale = manager.drop_stale(room.code.lower(), old.id)
        assert stale is old and old.connected is False
        assert old.id not in room.participants
        assert manager.drop_stale(room.code, old.id) is None
        assert manager.drop_stale(room.code, None) is None
        assert manager.drop_stale("ZZZZZ", old.id) is None

    def test_rejoin_replaces_ghost_without_full_room(self, room_client):  # noqa: F811
        client, manager, _ = room_client  # max_participants=3
        code = client.post("/api/rooms").json()["room"]
        base = f"/api/ws/rooms/{code}"
        with client.websocket_connect(f"{base}?name=Ana&speak=pt") as ghost:
            ana_id = ghost.receive_json()["participant"]["id"]
            with client.websocket_connect(f"{base}?name=Bo&speak=zh") as bo:
                receive_until(bo, "room_state")
                # Ana volta por uma conexão nova enquanto a antiga não caiu.
                with client.websocket_connect(
                    f"{base}?name=Ana&speak=pt&rejoin={ana_id}"
                ) as ana:
                    new_id = ana.receive_json()["participant"]["id"]
                    assert new_id != ana_id
                    joined = receive_until(bo, "participant_joined", "Ana")
                    assert joined["rejoined"] is True
                    state = receive_until(bo, "room_state")
                    assert sorted(p["name"] for p in state["participants"]) == [
                        "Ana",
                        "Bo",
                    ]
                    room = manager.rooms[code]
                    assert new_id in room.participants
                    assert ana_id not in room.participants

                    # A conexão fantasma é encerrada na próxima mensagem dela.
                    ghost.send_json({"type": "ping"})
                    # A fala nova da Ana continua chegando ao Bo.
                    ana.send_bytes("SAY|pt|Voltei".encode())
                    assert receive_until(bo, "room_tts")["speaker_id"] == new_id
                    assert len(room.participants) == 2

    def test_rejoin_with_unknown_id_is_a_normal_join(self, room_client):  # noqa: F811
        client, manager, _ = room_client
        code = client.post("/api/rooms").json()["room"]
        with client.websocket_connect(
            f"/api/ws/rooms/{code}?name=Ana&speak=pt&rejoin=naoexiste"
        ) as ws:
            assert ws.receive_json()["type"] == "joined"
            assert len(manager.rooms[code].participants) == 1


# ------------------------------------------------------- 3.4–3.7 (JS) ----
def test_room_script_has_mobile_safeguards():
    source = Path("app/static/js/room-app.js").read_text(encoding="utf-8")
    assert "class RoomMicrophone extends AudioRecorder" in source  # reaproveita
    assert "unlock()" in source  # 3.4 som liberado no toque
    assert "class PlaybackQueue" in source  # 3.5 fila
    assert "navigator.wakeLock.request('screen')" in source  # 3.6
    assert "rejoin" in source and "scheduleReconnect" in source  # 3.7
    assert "playback_started" in source  # marca de tempo da Etapa 5
