# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sessão de um participante: o fluxo de STT dele (2.4) e a fila das falas que
garante a ordem (2.6).

A conexão do celular só empurra áudio para ``push_audio``. Duas tarefas rodam
em paralelo:

- ``run_stt`` manda o áudio ao STT e põe cada fala transcrita numa fila;
- ``run_worker`` tira as falas da fila uma por vez e as roteia. Como só existe um
  worker por participante, as falas de uma pessoa chegam aos ouvintes na ordem
  em que foram ditas, mesmo que uma tradução demore mais que a seguinte.
"""

import asyncio
import time
from typing import AsyncGenerator, Optional

from ..services.pipeline_service import TranslationPipelineService
from ..utils.logger import get_logger
from .models import Participant, Room
from .routing import RoomRouter
from .timing import SAMPLE_RATE, BYTES_PER_SAMPLE, UtteranceTimer, VoiceActivityTracker

logger = get_logger(__name__)

END_SIGNAL = b"__END_SIGNAL__"
# Sem nova voz por mais que isso, o fim estimado é velho demais para ser desta fala.
MAX_SPEECH_END_AGE_SECONDS = 30.0


class ParticipantSession:
    def __init__(
        self,
        room: Room,
        participant: Participant,
        room_router: RoomRouter,
        pipeline: TranslationPipelineService,
    ) -> None:
        self.room = room
        self.participant = participant
        self.router = room_router
        self.pipeline = pipeline
        self.settings = room_router.settings
        self.audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self.utterances: asyncio.Queue[Optional[tuple]] = asyncio.Queue()
        self.voice = VoiceActivityTracker(
            self.settings.voice_rms_threshold, self.settings.pause_flush_seconds
        )
        self.sequence = 0
        self.transcript = ""
        self._audio_closed = False

    # ----- entrada de áudio ------------------------------------------------
    def push_audio(self, chunk: bytes, now: Optional[float] = None) -> None:
        if self._audio_closed or self.participant.muted or not chunk:
            return
        self.voice.feed(chunk, now)
        self.audio_queue.put_nowait(chunk)

    def push_silence(self, seconds: float) -> None:
        """Silêncio para o STT fechar a frase pendente (usado ao silenciar)."""
        if self._audio_closed:
            return
        size = int(seconds * SAMPLE_RATE) * BYTES_PER_SAMPLE
        self.audio_queue.put_nowait(b"\x00" * size)

    def end_audio(self) -> None:
        if not self._audio_closed:
            self._audio_closed = True
            self.audio_queue.put_nowait(None)

    async def _audio_generator(self) -> AsyncGenerator[bytes, None]:
        while True:
            chunk = await self.audio_queue.get()
            if chunk is None:
                yield END_SIGNAL
                return
            yield chunk

    # ----- STT (2.4) --------------------------------------------------------
    def _stt_kwargs(self) -> dict:
        speak = self.participant.speak_language
        if self.settings.stt_language_mode == "fixed":
            return {"language": speak, "candidate_languages": [speak]}
        # Detecção automática: o idioma detectado alimenta o filtro da 2.7.
        return {"language": None, "candidate_languages": [speak]}

    async def run_stt(self) -> None:
        try:
            async for result in self.pipeline.whisper.stream_transcribe(
                self._audio_generator(), emit_policy="pause", **self._stt_kwargs()
            ):
                if not result.success:
                    await self.participant.send(
                        {"type": "error", "stage": "stt", "error": result.error}
                    )
                    continue
                stt_done = time.time()
                current = result.text.strip()
                new_text = TranslationPipelineService._extract_new_transcript_text(
                    current, self.transcript
                )
                self.transcript = current or self.transcript
                if len(new_text.strip()) < 2:
                    continue
                self.sequence += 1
                timer = UtteranceTimer(
                    self.room.next_utterance_id(), self.room.code, self.participant.id
                )
                timer.mark("stt_done", stt_done)
                speech_end = self.voice.speech_end_before(stt_done)
                if (
                    speech_end is not None
                    and stt_done - speech_end <= MAX_SPEECH_END_AGE_SECONDS
                ):
                    timer.mark("speech_end", speech_end)
                if result.metrics:
                    timer.info["stt_metrics"] = {
                        k: result.metrics.get(k)
                        for k in (
                            "audio_duration_seconds",
                            "inference_seconds",
                            "queue_wait_seconds",
                        )
                        if k in result.metrics
                    }
                self.utterances.put_nowait(
                    (new_text, result.language, self.sequence, timer)
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"room STT failed participant={self.participant.id}: {exc}")
            await self.participant.send(
                {"type": "error", "stage": "stt", "error": str(exc)}
            )

    # ----- roteamento em ordem (2.5, 2.6) -----------------------------------
    async def run_worker(self) -> None:
        while True:
            item = await self.utterances.get()
            if item is None:
                return
            text, detected, sequence, timer = item
            try:
                await self.router.route_utterance(
                    self.room, self.participant, text, detected, sequence, timer
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # uma fala com erro não para as próximas
                logger.error(
                    f"room routing failed utterance={timer.utterance_id}: {exc}"
                )

    def finish_utterances(self) -> None:
        self.utterances.put_nowait(None)
