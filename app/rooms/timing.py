# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Marcas de tempo por fala (subtarefa 2.10), base da Etapa 5.

Eventos registrados, em segundos desde a época (time.time()):

- ``speech_end``: fim da fala estimado no servidor, a partir do último bloco de
  áudio com voz recebido antes da pausa que fechou a frase;
- ``stt_done``: chegada da transcrição final do STT;
- por idioma de escuta: ``translation_done``, ``text_sent``, ``tts_done`` e
  ``audio_sent`` (link do áudio enviado aos ouvintes);
- ``playback_started``: informado pelo celular do ouvinte quando o áudio começa
  a tocar (linha separada, chega depois).

Cada fala gera uma linha JSON no arquivo ROOM_TIMING_LOG e no log padrão
(prefixo ``room_timing``), com as marcas e as durações já calculadas.
"""

import json
import math
import sys
import threading
import time
from array import array
from collections import deque
from pathlib import Path
from typing import Any, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


def pcm16_rms(chunk: bytes) -> float:
    """RMS normalizado (0–1) de PCM 16 bits, igual ao cálculo do serviço STT."""
    usable = len(chunk) - (len(chunk) % BYTES_PER_SAMPLE)
    if usable <= 0:
        return 0.0
    samples = array("h")
    samples.frombytes(chunk[:usable])
    if sys.byteorder == "big":
        samples.byteswap()
    square_sum = sum(s * s for s in samples)
    return math.sqrt(square_sum / len(samples)) / 32768.0


class VoiceActivityTracker:
    """Guarda os trechos com voz recebidos de um participante.

    Serve só para estimar o fim da fala; quem decide onde a frase termina
    continua sendo o STT.
    """

    def __init__(
        self, rms_threshold: float, pause_seconds: float, max_segments: int = 64
    ) -> None:
        self.rms_threshold = rms_threshold
        # Uma pausa menor que isso não fecha frase no STT; com folga para a
        # granularidade dos blocos de áudio.
        self.min_gap = max(0.0, pause_seconds * 0.75)
        self.segments: deque[list[float]] = deque(maxlen=max_segments)
        self._in_voice = False

    def feed(self, chunk: bytes, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        voiced = pcm16_rms(chunk) >= self.rms_threshold
        if voiced:
            if self._in_voice and self.segments:
                self.segments[-1][1] = now
            else:
                self.segments.append([now, now])
                self._in_voice = True
        else:
            self._in_voice = False
        return voiced

    def speech_end_before(self, t: float) -> Optional[float]:
        """Último fim de trecho com voz antes de ``t`` seguido de pausa real.

        Um trecho só conta como fim de frase se depois dele houve pelo menos
        ``min_gap`` sem voz (até o trecho seguinte ou até ``t``). O trecho ainda
        aberto (a pessoa está falando agora) nunca conta.
        """
        segments = list(self.segments)
        if self._in_voice and segments:
            segments = segments[:-1]
        for index in range(len(segments) - 1, -1, -1):
            end = segments[index][1]
            if end > t:
                continue
            following = [s[0] for s in self.segments if s[0] > end]
            gap_until = min(following[0], t) if following else t
            if gap_until - end >= self.min_gap:
                return end
        return None


class UtteranceTimer:
    """Marcas de tempo de uma fala."""

    def __init__(self, utterance_id: str, room: str, speaker_id: str) -> None:
        self.utterance_id = utterance_id
        self.room = room
        self.speaker_id = speaker_id
        self.marks: dict[str, float] = {}
        self.targets: dict[str, dict[str, Any]] = {}
        self.info: dict[str, Any] = {}

    def mark(self, event: str, when: Optional[float] = None) -> float:
        when = time.time() if when is None else when
        self.marks[event] = when
        return when

    def mark_target(
        self, language: str, event: str, when: Optional[float] = None
    ) -> float:
        when = time.time() if when is None else when
        self.targets.setdefault(language, {})[event] = when
        return when

    def _base(self) -> Optional[float]:
        return self.marks.get("speech_end") or self.marks.get("stt_done")

    def to_record(self) -> dict[str, Any]:
        base = self._base()

        def rel(value: Optional[float]) -> Optional[float]:
            if value is None or base is None:
                return None
            return round(value - base, 3)

        targets = {}
        for language, data in self.targets.items():
            marks = {k: v for k, v in data.items() if isinstance(v, float)}
            extra = {k: v for k, v in data.items() if not isinstance(v, float)}
            targets[language] = {
                **extra,
                "t": {k: round(v, 3) for k, v in marks.items()},
                "since_speech_end": {k: rel(v) for k, v in marks.items()},
            }
        stt_done = self.marks.get("stt_done")
        return {
            "utterance_id": self.utterance_id,
            "room": self.room,
            "speaker": self.speaker_id,
            **self.info,
            "speech_end_estimated": "speech_end" in self.marks,
            "t": {k: round(v, 3) for k, v in self.marks.items()},
            "stt_seconds": rel(stt_done),
            "targets": targets,
        }


class TimingLog:
    """Escreve uma linha JSON por evento (arquivo opcional + log padrão)."""

    def __init__(self, path: Optional[Path]) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        logger.info(f"room_timing {line}")
        if self.path is None:
            return
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            logger.warning(f"could not write room timing log {self.path}: {exc}")
