# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rotas das salas (2.2, 2.3).

- ``POST /api/rooms``: cria uma sala e devolve o código.
- ``GET /api/rooms/{code}``: estado da sala e participantes.
- ``WS /api/ws/rooms/{code}?name=&speak=&listen=``: conexão do participante.
  O celular envia áudio PCM 16 kHz mono 16 bits (mesmo formato do
  ``/api/ws/translate``) e recebe JSON:

  - ``joined`` (só para quem entrou), ``participant_joined``/``participant_left``
    e ``room_state`` (para todos);
  - ``self_transcript`` ou ``utterance_ignored`` (só para quem falou);
  - ``room_translation`` e depois ``room_tts`` (só para os ouvintes do idioma);
  - ``room_error``/``error``.

  Mensagens de controle aceitas: ``mute``/``pause``, ``unmute``/``resume``,
  ``end``, ``ping`` e ``playback_started`` (com ``utterance_id``).
"""

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..routers import api as api_module
from ..utils.logger import get_logger
from .models import RoomError, get_room_manager
from .routing import RoomRouter
from .session import ParticipantSession

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["rooms"])

WS_CLOSE_CODES = {
    "room_not_found": 4404,
    "room_full": 4409,
    "invalid_language": 4400,
}
STT_DRAIN_SECONDS = 5.0
WORKER_DRAIN_SECONDS = 30.0

_room_router: RoomRouter | None = None


def get_room_router() -> RoomRouter:
    """Roteador ligado ao gerenciador e ao pipeline atuais."""
    global _room_router
    manager = get_room_manager()
    pipeline = api_module.get_pipeline_service()
    if (
        _room_router is None
        or _room_router.manager is not manager
        or _room_router.pipeline is not pipeline
    ):
        _room_router = RoomRouter(manager, pipeline)
    return _room_router


@router.post("/rooms", status_code=201)
async def create_room() -> dict:
    room = get_room_manager().create_room()
    return {
        "room": room.code,
        "state": room.state,
        "ws_url": f"/api/ws/rooms/{room.code}",
    }


@router.get("/rooms/{code}")
async def get_room(code: str) -> dict:
    try:
        return get_room_manager().get_room(code).to_state()
    except RoomError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.websocket("/ws/rooms/{code}")
async def room_websocket(
    websocket: WebSocket,
    code: str,
    name: str | None = None,
    speak: str | None = None,
    listen: str | None = None,
):
    await websocket.accept()
    manager = get_room_manager()
    try:
        room, participant = manager.join(
            code, name, speak, listen, send_func=websocket.send_json
        )
    except RoomError as exc:
        await websocket.send_json(
            {"type": "error", "code": exc.code, "error": exc.message}
        )
        await websocket.close(code=WS_CLOSE_CODES.get(exc.code, 4000))
        return

    room_router = get_room_router()
    pipeline = room_router.pipeline
    session = ParticipantSession(room, participant, room_router, pipeline)
    await participant.send(
        {"type": "joined", "room": room.code, "participant": participant.to_public()}
    )
    await manager.broadcast_state(
        room, {"type": "participant_joined", "participant": participant.to_public()}
    )

    try:
        await pipeline.warm_connections()
    except Exception as exc:
        logger.warning(f"room pipeline warm-up failed: {exc}")

    stt_task = asyncio.create_task(session.run_stt())
    worker_task = asyncio.create_task(session.run_worker())

    async def set_muted(muted: bool) -> None:
        if participant.muted == muted:
            return
        if muted:
            # Fecha a frase pendente antes de parar de mandar áudio.
            session.push_silence(room_router.settings.pause_flush_seconds + 0.2)
        participant.muted = muted
        await manager.broadcast_state(room)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                session.push_audio(message["bytes"])
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            kind = data.get("type") if isinstance(data, dict) else None
            if kind == "end":
                break
            if kind in {"mute", "pause"}:
                await set_muted(True)
            elif kind in {"unmute", "resume"}:
                await set_muted(False)
            elif kind == "ping":
                await participant.send({"type": "pong", "t": time.time()})
            elif kind == "playback_started":
                room_router.timing_log.write(
                    {
                        "event": "playback_started",
                        "utterance_id": str(data.get("utterance_id") or ""),
                        "room": room.code,
                        "listener": participant.id,
                        "t": round(time.time(), 3),
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"room websocket error participant={participant.id}: {exc}")
    finally:
        manager.leave(room.code, participant.id)
        await manager.broadcast_state(
            room, {"type": "participant_left", "participant": participant.to_public()}
        )
        session.end_audio()
        try:
            await asyncio.wait_for(stt_task, timeout=STT_DRAIN_SECONDS)
        except (asyncio.TimeoutError, Exception):
            stt_task.cancel()
        session.finish_utterances()
        try:
            await asyncio.wait_for(worker_task, timeout=WORKER_DRAIN_SECONDS)
        except (asyncio.TimeoutError, Exception):
            worker_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
