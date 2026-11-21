# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Roteamento de uma fala para os ouvintes certos (2.5) e filtro de conversa
cruzada (2.7).

Regras (planejamento, seção 4):

1. A fala é transcrita uma vez, no fluxo de STT de quem falou.
2. Para cada idioma de escuta presente na sala, exceto o de quem falou, a fala é
   traduzida e sintetizada uma vez só, não importa quantos ouvintes tenha.
3. Texto e áudio vão só para os ouvintes daquele idioma, nunca para quem falou.
4. Quem ouve o mesmo idioma de quem falou não recebe nada.
"""

import asyncio
import uuid
from typing import Any, Optional

from ..services.pipeline_service import TranslationPipelineService
from ..utils.logger import get_logger
from .models import Participant, Room, RoomManager
from .settings import RoomSettings
from .timing import TimingLog, UtteranceTimer

logger = get_logger(__name__)

_match_codes = TranslationPipelineService._language_match_codes


def crosstalk_reason(
    room: Room,
    speaker: Participant,
    detected_language: Optional[str],
    mode: str,
) -> Optional[str]:
    """Diz por que uma fala deve ser descartada, ou ``None`` para seguir.

    Com as pessoas frente a frente, o microfone de A capta a voz de B. Se o STT
    de A detecta o idioma de fala de outra pessoa da sala, o trecho é dela e já
    está sendo traduzido pelo fluxo dela.
    """
    detected = _match_codes(detected_language)
    if mode == "off" or not detected:
        return None
    own = _match_codes(speaker.speak_language)
    if detected & own:
        return None
    if mode == "strict":
        return "language_mismatch"
    others: set[str] = set()
    for language in room.speak_languages(exclude=speaker.id):
        others |= _match_codes(language)
    if detected & others:
        return "crosstalk"
    return None


def target_groups(room: Room, speaker: Participant) -> dict[str, list[Participant]]:
    """Ouvintes agrupados por idioma de escuta, sem quem falou (regras 2–4)."""
    own = _match_codes(speaker.speak_language)
    groups: dict[str, list[Participant]] = {}
    for participant in room.participants.values():
        if participant.id == speaker.id:
            continue
        if _match_codes(participant.listen_language) & own:
            continue
        groups.setdefault(participant.listen_language, []).append(participant)
    return groups


class RoomRouter:
    """Traduz, sintetiza e entrega as falas de uma sala."""

    def __init__(
        self,
        manager: RoomManager,
        pipeline: TranslationPipelineService,
        settings: Optional[RoomSettings] = None,
        timing_log: Optional[TimingLog] = None,
    ) -> None:
        self.manager = manager
        self.pipeline = pipeline
        self.settings = settings or manager.settings
        self.timing_log = timing_log or TimingLog(self.settings.timing_log_path)

    @staticmethod
    async def _send_to(room: Room, listeners: list[Participant], message: dict) -> int:
        """Envia a quem ainda está na sala; retorna quantos receberam."""
        present = [p for p in listeners if p.id in room.participants]
        sent = await asyncio.gather(*(p.send(message) for p in present))
        return sum(1 for ok in sent if ok)

    async def route_utterance(
        self,
        room: Room,
        speaker: Participant,
        transcript: str,
        detected_language: Optional[str],
        sequence: int,
        timer: UtteranceTimer,
    ) -> dict[str, Any]:
        """Processa uma fala inteira e registra as marcas de tempo."""
        base = {
            "utterance_id": timer.utterance_id,
            "speaker_id": speaker.id,
            "speaker_name": speaker.name,
            "sequence": sequence,
            "source_language": speaker.speak_language,
            "detected_language": detected_language,
            "transcript": transcript,
        }
        timer.info.update(
            {
                "sequence": sequence,
                "source_language": speaker.speak_language,
                "detected_language": detected_language,
                "chars": len(transcript),
            }
        )

        reason = crosstalk_reason(
            room, speaker, detected_language, self.settings.crosstalk_filter
        )
        if reason:
            logger.info(
                f"room utterance ignored room={room.code} speaker={speaker.id} "
                f"detected={detected_language} reason={reason}"
            )
            await speaker.send({"type": "utterance_ignored", "reason": reason, **base})
            timer.info["status"] = f"ignored_{reason}"
            self.timing_log.write(timer.to_record())
            return timer.info

        # Quem falou vê só a própria transcrição (sem tradução nem áudio).
        await speaker.send({"type": "self_transcript", **base})

        groups = target_groups(room, speaker)
        if not groups:
            timer.info["status"] = "no_listeners"
            self.timing_log.write(timer.to_record())
            return timer.info

        await asyncio.gather(
            *(
                self._deliver_group(room, speaker, language, listeners, base, timer)
                for language, listeners in groups.items()
            )
        )
        failed = any(t.get("error") for t in timer.targets.values())
        timer.info["status"] = "partial_failure" if failed else "delivered"
        self.timing_log.write(timer.to_record())
        return timer.info

    async def _deliver_group(
        self,
        room: Room,
        speaker: Participant,
        language: str,
        listeners: list[Participant],
        base: dict[str, Any],
        timer: UtteranceTimer,
    ) -> None:
        target = timer.targets.setdefault(language, {})
        target["listeners"] = [p.id for p in listeners]
        message = {**base, "target_language": language}

        try:
            result = await self.pipeline.translation.translate(
                base["transcript"], speaker.speak_language, language
            )
        except Exception as exc:
            result = None
            error = str(exc)
        else:
            error = None if result.success else (result.error or "Translation failed")
        timer.mark_target(language, "translation_done")
        if error or result is None:
            target["error"] = error
            await self._send_to(
                room,
                listeners,
                {
                    "type": "room_error",
                    "stage": "translation",
                    "error": error,
                    **message,
                },
            )
            return

        translated = result.text
        await self._send_to(
            room,
            listeners,
            {"type": "room_translation", "translated_text": translated, **message},
        )
        timer.mark_target(language, "text_sent")

        output_path = (
            self.pipeline.media_dir
            / f"room_{room.code}_{language}_{uuid.uuid4().hex[:8]}.wav"
        )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tts_result = await self.pipeline.tts.synthesize(
                translated, language, output_path
            )
        except Exception as exc:
            tts_result = None
            tts_error = str(exc)
        else:
            tts_error = (
                None if tts_result.success else (tts_result.error or "TTS failed")
            )
        timer.mark_target(language, "tts_done")
        if tts_result is not None:
            self.manager.register_audio(room, tts_result.audio_path or output_path)
        if tts_error or tts_result is None or not tts_result.audio_url:
            target["error"] = tts_error or "TTS returned no audio"
            await self._send_to(
                room,
                listeners,
                {
                    "type": "room_error",
                    "stage": "tts",
                    "error": target["error"],
                    **message,
                },
            )
            return

        delivered = await self._send_to(
            room,
            listeners,
            {
                "type": "room_tts",
                "audio_url": tts_result.audio_url,
                "translated_text": translated,
                **message,
            },
        )
        timer.mark_target(language, "audio_sent")
        target["delivered_to"] = delivered
