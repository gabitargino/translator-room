# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Salas de interpretação (translator-room, Etapa 2).

Módulo novo, separado do código original do PolyTalk. Cada participante de uma
sala abre uma conexão própria (um fluxo de STT por pessoa). Cada fala é
traduzida e sintetizada uma vez por idioma de escuta e entregue apenas aos
ouvintes desse idioma, nunca a quem falou.
"""

from .models import Participant, Room, RoomError, RoomManager, get_room_manager
from .settings import RoomSettings

__all__ = [
    "Participant",
    "Room",
    "RoomError",
    "RoomManager",
    "RoomSettings",
    "get_room_manager",
]
