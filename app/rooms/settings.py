# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuração das salas, lida de variáveis de ambiente (ROOM_*)."""

import os
from dataclasses import dataclass
from pathlib import Path

CROSSTALK_MODES = ("room", "strict", "off")
STT_LANGUAGE_MODES = ("auto", "fixed")


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(minimum, value)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(minimum, value)


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = os.environ.get(name, "").strip().lower()
    return value if value in choices else default


@dataclass(frozen=True)
class RoomSettings:
    """Parâmetros das salas.

    Attributes:
        empty_ttl_seconds: tempo que uma sala vazia espera alguém voltar antes
            de ser apagada (ROOM_EMPTY_TTL_SECONDS).
        max_participants: limite de pessoas por sala (ROOM_MAX_PARTICIPANTS).
        audio_max_age_seconds: idade máxima de um áudio gerado, mesmo com a
            sala ativa (ROOM_AUDIO_MAX_AGE_SECONDS).
        sweep_interval_seconds: intervalo da limpeza periódica
            (ROOM_SWEEP_INTERVAL_SECONDS).
        crosstalk_filter: ``room`` descarta falas detectadas no idioma de fala
            de outro participante; ``strict`` descarta qualquer idioma diferente
            do declarado; ``off`` desliga o filtro (ROOM_CROSSTALK_FILTER).
        stt_language_mode: ``auto`` deixa o Whisper detectar o idioma (necessário
            para o filtro); ``fixed`` informa o idioma de fala ao STT, que é o
            plano B da 1.3 (ROOM_STT_LANGUAGE_MODE).
        voice_rms_threshold: nível a partir do qual um bloco de áudio conta como
            voz na estimativa do fim da fala (STT_SILENCE_RMS_THRESHOLD).
        pause_flush_seconds: pausa que fecha uma frase no STT
            (STT_PAUSE_FLUSH_SECONDS).
        timing_log_path: arquivo JSONL com as marcas de tempo de cada fala
            (ROOM_TIMING_LOG; vazio desliga o arquivo, o log padrão continua).
    """

    empty_ttl_seconds: float = 120.0
    max_participants: int = 8
    audio_max_age_seconds: float = 600.0
    sweep_interval_seconds: float = 15.0
    crosstalk_filter: str = "room"
    stt_language_mode: str = "auto"
    voice_rms_threshold: float = 0.003
    pause_flush_seconds: float = 0.8
    timing_log_path: Path | None = Path("logs/room-timing.jsonl")

    @classmethod
    def from_env(cls) -> "RoomSettings":
        timing_log = os.environ.get("ROOM_TIMING_LOG")
        if timing_log is None:
            timing_log_path: Path | None = cls.timing_log_path
        else:
            timing_log_path = Path(timing_log.strip()) if timing_log.strip() else None
        return cls(
            empty_ttl_seconds=_env_float("ROOM_EMPTY_TTL_SECONDS", 120.0),
            max_participants=_env_int("ROOM_MAX_PARTICIPANTS", 8, minimum=2),
            audio_max_age_seconds=_env_float("ROOM_AUDIO_MAX_AGE_SECONDS", 600.0),
            sweep_interval_seconds=_env_float(
                "ROOM_SWEEP_INTERVAL_SECONDS", 15.0, minimum=0.1
            ),
            crosstalk_filter=_env_choice(
                "ROOM_CROSSTALK_FILTER", "room", CROSSTALK_MODES
            ),
            stt_language_mode=_env_choice(
                "ROOM_STT_LANGUAGE_MODE", "auto", STT_LANGUAGE_MODES
            ),
            voice_rms_threshold=_env_float("STT_SILENCE_RMS_THRESHOLD", 0.003),
            pause_flush_seconds=_env_float("STT_PAUSE_FLUSH_SECONDS", 0.8),
            timing_log_path=timing_log_path,
        )
