# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Modelo de dados e ciclo de vida das salas (subtarefas 2.1, 2.2, 2.8 e 2.9).

As salas ficam na memória do processo. Por isso o app precisa rodar com um único
worker (APP_WORKERS=1): com vários, cada processo teria as próprias salas.
"""

import asyncio
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ..utils.logger import get_logger
from .settings import RoomSettings

logger = get_logger(__name__)

# Sem 0/O e 1/I/L, para ditar o código em voz alta sem confusão.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5
NAME_MAX_CHARS = 40
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,4})?$")

SendFunc = Callable[[dict], Awaitable[None]]

STATE_EMPTY = "empty"  # ninguém conectado; expira após empty_ttl_seconds
STATE_WAITING = "waiting"  # uma pessoa, esperando a outra
STATE_ACTIVE = "active"  # duas ou mais pessoas


class RoomError(Exception):
    """Erro previsível de sala, com um código estável para o cliente."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_room_code(code: str | None) -> str:
    return (code or "").strip().upper()


def validate_language(value: str | None, field_name: str) -> str:
    language = (value or "").strip()
    if not _LANGUAGE_RE.match(language):
        raise RoomError(
            "invalid_language", f"{field_name} must be a language code like pt or zh"
        )
    return language.replace("-", "_").lower()


def clean_name(value: str | None) -> str:
    name = " ".join((value or "").split())[:NAME_MAX_CHARS]
    return name or "Participante"


@dataclass
class Participant:
    """Uma pessoa conectada à sala.

    ``speak_language`` vai para o STT e para o filtro de conversa cruzada;
    ``listen_language`` decide quais traduções a pessoa recebe.
    """

    name: str
    speak_language: str
    listen_language: str
    send_func: Optional[SendFunc] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    joined_at: float = field(default_factory=time.time)
    muted: bool = False
    connected: bool = True
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def send(self, message: dict) -> bool:
        """Envia uma mensagem JSON; serializa envios vindos de tarefas diferentes."""
        if not self.connected or self.send_func is None:
            return False
        async with self._send_lock:
            try:
                await self.send_func(message)
                return True
            except Exception as exc:  # conexão caiu no meio do envio
                logger.debug(f"room send failed participant={self.id}: {exc}")
                self.connected = False
                return False

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "speak_language": self.speak_language,
            "listen_language": self.listen_language,
            "status": "muted" if self.muted else "connected",
            "joined_at": round(self.joined_at, 3),
        }


@dataclass
class Room:
    code: str
    created_at: float
    participants: dict[str, Participant] = field(default_factory=dict)
    empty_since: Optional[float] = None
    audio_files: list[tuple[float, Path]] = field(default_factory=list)
    utterance_counter: int = 0

    @property
    def state(self) -> str:
        count = len(self.participants)
        if count == 0:
            return STATE_EMPTY
        if count == 1:
            return STATE_WAITING
        return STATE_ACTIVE

    def next_utterance_id(self) -> str:
        self.utterance_counter += 1
        return f"{self.code}-{self.utterance_counter}"

    def speak_languages(self, exclude: Optional[str] = None) -> set[str]:
        return {
            p.speak_language for pid, p in self.participants.items() if pid != exclude
        }

    def to_state(self) -> dict[str, Any]:
        return {
            "type": "room_state",
            "room": self.code,
            "state": self.state,
            "participants": [p.to_public() for p in self.participants.values()],
        }


class RoomManager:
    """Cria, encontra e expira salas; guarda e apaga os áudios gerados."""

    def __init__(
        self,
        settings: Optional[RoomSettings] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings or RoomSettings.from_env()
        self.clock = clock
        self.rooms: dict[str, Room] = {}
        self._sweeper: Optional[asyncio.Task] = None

    # ----- ciclo de vida (2.2) -------------------------------------------
    def create_room(self) -> Room:
        for _ in range(100):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                break
        else:  # pragma: no cover - 31^5 códigos
            raise RoomError("no_code", "could not allocate a room code")
        now = self.clock()
        # Até o criador conectar, a sala conta como vazia e pode expirar.
        room = Room(code=code, created_at=now, empty_since=now)
        self.rooms[code] = room
        logger.info(f"room created code={code}")
        return room

    def get_room(self, code: str | None) -> Room:
        room = self.rooms.get(normalize_room_code(code))
        if room is None:
            raise RoomError("room_not_found", "room not found or expired")
        return room

    def join(
        self,
        code: str | None,
        name: str | None,
        speak_language: str | None,
        listen_language: str | None = None,
        send_func: Optional[SendFunc] = None,
    ) -> tuple[Room, Participant]:
        room = self.get_room(code)
        speak = validate_language(speak_language, "speak_language")
        listen = (
            validate_language(listen_language, "listen_language")
            if listen_language
            else speak
        )
        if len(room.participants) >= self.settings.max_participants:
            raise RoomError("room_full", "room is full")
        participant = Participant(
            name=clean_name(name),
            speak_language=speak,
            listen_language=listen,
            send_func=send_func,
            joined_at=self.clock(),
        )
        room.participants[participant.id] = participant
        room.empty_since = None
        logger.info(
            f"room join code={room.code} participant={participant.id} "
            f"speak={speak} listen={listen} count={len(room.participants)}"
        )
        return room, participant

    def leave(self, code: str, participant_id: str) -> Optional[Room]:
        room = self.rooms.get(normalize_room_code(code))
        if room is None:
            return None
        participant = room.participants.pop(participant_id, None)
        if participant is None:
            return room
        participant.connected = False
        if not room.participants:
            room.empty_since = self.clock()
        logger.info(
            f"room leave code={room.code} participant={participant_id} "
            f"count={len(room.participants)}"
        )
        return room

    async def broadcast(self, room: Room, message: dict) -> None:
        participants = list(room.participants.values())
        await asyncio.gather(*(p.send(message) for p in participants))

    async def broadcast_state(self, room: Room, event: Optional[dict] = None) -> None:
        """Avisa a sala da entrada/saída e manda a lista atualizada (2.8)."""
        if event:
            await self.broadcast(room, event)
        await self.broadcast(room, room.to_state())

    # ----- áudios gerados (2.9) ----------------------------------------
    def register_audio(self, room: Room, path: Optional[Path]) -> None:
        if path is not None:
            room.audio_files.append((self.clock(), Path(path)))

    @staticmethod
    def _delete_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"could not delete room audio {path}: {exc}")

    def _delete_room(self, room: Room) -> None:
        for _, path in room.audio_files:
            self._delete_file(path)
        room.audio_files.clear()
        self.rooms.pop(room.code, None)

    def sweep(self) -> list[str]:
        """Apaga salas vazias vencidas e áudios antigos. Retorna as salas apagadas."""
        now = self.clock()
        expired: list[str] = []
        for room in list(self.rooms.values()):
            if (
                not room.participants
                and room.empty_since is not None
                and now - room.empty_since >= self.settings.empty_ttl_seconds
            ):
                expired.append(room.code)
                self._delete_room(room)
                logger.info(f"room expired code={room.code}")
                continue
            max_age = self.settings.audio_max_age_seconds
            kept: list[tuple[float, Path]] = []
            for created, path in room.audio_files:
                if now - created >= max_age:
                    self._delete_file(path)
                else:
                    kept.append((created, path))
            room.audio_files = kept
        return expired

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.sweep_interval_seconds)
            try:
                self.sweep()
            except Exception as exc:  # pragma: no cover - defensivo
                logger.error(f"room sweep failed: {exc}")

    def start(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None
        for room in list(self.rooms.values()):
            self._delete_room(room)


_manager: Optional[RoomManager] = None


def get_room_manager() -> RoomManager:
    global _manager
    if _manager is None:
        _manager = RoomManager()
    return _manager


def reset_room_manager(manager: Optional[RoomManager] = None) -> None:
    """Troca o gerenciador global (usado nos testes)."""
    global _manager
    _manager = manager
