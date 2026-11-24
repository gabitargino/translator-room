# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Latência da sala a partir do log de marcas de tempo (Etapa 5).

Definições (5.1), todas no relógio do servidor:

- **T0, fim da fala** (``speech_end``): fim do último bloco de áudio com voz
  (RMS ≥ limiar do STT) recebido do celular de quem fala antes da pausa que
  fechou a frase. Quando não dá para estimar, usa-se T1 e a fala é marcada.
- **T1, frase fechada** (``stt_done``): chegada da transcrição final do STT.
- **T2/T3** (``translation_done``/``text_sent``): tradução pronta e enviada.
- **T4** (``tts_done``): áudio sintetizado.
- **T5** (``audio_sent``): link do áudio enviado ao celular de quem ouve.
- **T6, início do áudio traduzido** (``playback``): evento ``playing`` do
  ``<audio>`` no celular de quem ouve.

Compensação de relógio (5.3): o relógio do celular nunca é usado. O celular
mede no próprio relógio monotônico o tempo de ida e volta de um ``ping``
(``rtt_ms``) e informa esse valor junto com o aviso ``playback_started``. O
servidor estima T6 = chegada do aviso − RTT/2. O erro máximo é a assimetria da
rede (metade do RTT, tipicamente < 20 ms em Wi-Fi local).

O celular também manda ``wait_ms``: quanto tempo passou, no relógio dele, entre
receber o ``room_tts`` e o áudio começar a tocar (download + decodificação +
fila de reprodução). Serve para conferir a estimativa: T5 + RTT/2 + wait ≈ T6.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Optional

MAX_RTT_MS = 5000.0
MAX_WAIT_MS = 120000.0

# Durações parciais (de → até) mostradas na tabela, além do total T0 → T6.
STAGES = (
    ("silencio_e_stt", "speech_end", "stt_done"),
    ("traducao", "stt_done", "translation_done"),
    ("voz", "translation_done", "tts_done"),
    ("envio", "tts_done", "audio_sent"),
    ("celular", "audio_sent", "playback"),
)


def _number(value: Any, limit: float) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number < 0 or number > limit:
        return None
    return number


def playback_record(
    utterance_id: str,
    room: str,
    listener: str,
    arrival: float,
    rtt_ms: Any = None,
    wait_ms: Any = None,
) -> dict[str, Any]:
    """Linha de log do aviso ``playback_started`` com T6 já estimado (5.2, 5.3)."""
    rtt = _number(rtt_ms, MAX_RTT_MS)
    wait = _number(wait_ms, MAX_WAIT_MS)
    playback = arrival - (rtt / 2000.0 if rtt is not None else 0.0)
    record: dict[str, Any] = {
        "event": "playback_started",
        "utterance_id": utterance_id,
        "room": room,
        "listener": listener,
        "t": round(arrival, 3),
        "t_playback": round(playback, 3),
        "clock": "server_arrival_minus_half_rtt"
        if rtt is not None
        else "server_arrival",
    }
    if rtt is not None:
        record["rtt_ms"] = round(rtt, 1)
    if wait is not None:
        record["wait_ms"] = round(wait, 1)
    return record


def percentile(values: list[float], fraction: float) -> float:
    """Percentil com interpolação linear (igual ao bench/comum.py)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mediana": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def collect(
    records: Iterable[dict[str, Any]], room: Optional[str] = None
) -> list[dict[str, Any]]:
    """Junta falas e avisos de reprodução: uma linha por (fala, ouvinte).

    Cada linha traz a direção (``pt→zh``), as marcas absolutas e as durações
    desde o fim da fala. Falas descartadas ou sem ouvintes ficam de fora.
    """
    utterances: dict[str, dict[str, Any]] = {}
    playbacks: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if room and record.get("room") != room:
            continue
        key = str(record.get("utterance_id") or "")
        if not key:
            continue
        if record.get("event") == "playback_started":
            # Fica com o primeiro aviso (reconexões podem repetir).
            playbacks.setdefault((key, str(record.get("listener"))), record)
        elif "targets" in record:
            utterances[key] = record

    rows = []
    for key, record in utterances.items():
        marks = record.get("t") or {}
        base = marks.get("speech_end") or marks.get("stt_done")
        if base is None:
            continue
        source = record.get("source_language") or "?"
        for language, target in (record.get("targets") or {}).items():
            target_marks = target.get("t") or {}
            for listener in target.get("listeners") or [None]:
                points = {**marks, **target_marks}
                playback = playbacks.get((key, str(listener)))
                if playback:
                    points["playback"] = playback.get("t_playback", playback.get("t"))
                row = {
                    "utterance_id": key,
                    "room": record.get("room"),
                    "direction": f"{source}→{language}",
                    "listener": listener,
                    "speech_end_estimated": bool(record.get("speech_end_estimated")),
                    "status": record.get("status"),
                    "rtt_ms": playback.get("rtt_ms") if playback else None,
                    "wait_ms": playback.get("wait_ms") if playback else None,
                    "since_speech_end": {
                        name: round(value - base, 3)
                        for name, value in points.items()
                        if isinstance(value, (int, float)) and name != "speech_end"
                    },
                    "stages": {},
                }
                for name, start, end in STAGES:
                    first = points.get(start)
                    if start == "speech_end" and first is None:
                        first = base
                    last = points.get(end)
                    if first is not None and last is not None:
                        row["stages"][name] = round(last - first, 3)
                rows.append(row)
    rows.sort(key=lambda r: (r["room"] or "", r["utterance_id"]))
    return rows


def analyze(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Mediana, p95 e máximo por direção (5.4)."""
    result: dict[str, dict[str, Any]] = {}
    for direction in sorted({r["direction"] for r in rows}):
        selected = [r for r in rows if r["direction"] == direction]
        total = [
            r["since_speech_end"]["playback"]
            for r in selected
            if "playback" in r["since_speech_end"]
        ]
        sent = [
            r["since_speech_end"]["audio_sent"]
            for r in selected
            if "audio_sent" in r["since_speech_end"]
        ]
        result[direction] = {
            "falas": len(selected),
            "fim_da_fala_estimado": sum(r["speech_end_estimated"] for r in selected),
            "ate_inicio_do_audio_s": summarize(total),
            "ate_link_enviado_s": summarize(sent),
            "dentro_da_meta_3s": sum(1 for v in total if v <= 3.0),
            "etapas_mediana_s": {
                name: summarize(
                    [r["stages"][name] for r in selected if name in r["stages"]]
                ).get("mediana")
                for name, _, _ in STAGES
            },
            "rtt_ms_mediana": summarize(
                [r["rtt_ms"] for r in selected if r["rtt_ms"] is not None]
            ).get("mediana"),
        }
    return result


def _fmt(value: Any) -> str:
    if value is None:
        return "–"
    return f"{value:.2f}".replace(".", ",")


def markdown_table(result: dict[str, dict[str, Any]]) -> str:
    """Tabela pronta para o relatório."""
    lines = [
        "| Direção | Falas | Com T6 | Mediana T0→T6 (s) | p95 (s) | Máx. (s) "
        "| ≤ 3 s | Mediana T0→T5 (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for direction, data in result.items():
        total = data["ate_inicio_do_audio_s"]
        sent = data["ate_link_enviado_s"]
        within = f"{data['dentro_da_meta_3s']}/{total['n']}" if total.get("n") else "–"
        lines.append(
            f"| {direction.upper()} | {data['falas']} | {total.get('n', 0)} "
            f"| {_fmt(total.get('mediana'))} | {_fmt(total.get('p95'))} "
            f"| {_fmt(total.get('max'))} | {within} | {_fmt(sent.get('mediana'))} |"
        )
    lines += [
        "",
        "| Direção | Silêncio + STT | Tradução | Voz | Envio | Celular (rede, download, início) | RTT (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for direction, data in result.items():
        stages = data["etapas_mediana_s"]
        rtt = data["rtt_ms_mediana"]
        lines.append(
            f"| {direction.upper()} | "
            + " | ".join(_fmt(stages.get(name)) for name, _, _ in STAGES)
            + f" | {'–' if rtt is None else round(rtt)} |"
        )
    return "\n".join(lines) + "\n"


def session_summary(
    records: Iterable[dict[str, Any]], room: Optional[str] = None
) -> dict[str, Any]:
    """Resumo da sessão de validação (6.6) a partir do mesmo log.

    Conta o que a pessoa não deveria precisar fazer (tocar em silenciar,
    reconectar) e o que não deveria acontecer (tradução voltando para quem
    falou), além da duração e do destino de cada fala.
    """
    selected = [
        r
        for r in records
        if isinstance(r, dict) and (room is None or r.get("room") == room)
    ]
    utterances = [r for r in selected if "targets" in r and "event" not in r]
    status: dict[str, int] = {}
    for r in utterances:
        key = str(r.get("status") or "?")
        status[key] = status.get(key, 0) + 1
    self_delivery = sum(
        1
        for r in utterances
        for target in (r.get("targets") or {}).values()
        if r.get("speaker") in (target.get("listeners") or [])
    )
    times = [
        (r.get("t") or {}).get("speech_end") or (r.get("t") or {}).get("stt_done")
        for r in utterances
    ]
    times = [t for t in times if isinstance(t, (int, float))]
    joins = [r for r in selected if r.get("event") == "participant_joined"]
    controls = [r for r in selected if r.get("event") == "control"]
    return {
        "duracao_s": round(max(times) - min(times), 1) if len(times) > 1 else 0.0,
        "falas": len(utterances),
        "por_status": dict(sorted(status.items())),
        "traducao_para_quem_falou": self_delivery,
        "participantes": len(
            {r.get("participant") for r in joins if not r.get("rejoined")}
        ),
        "reconexoes": sum(1 for r in joins if r.get("rejoined")),
        "toques_silenciar": sum(1 for r in controls if r.get("kind") == "mute"),
        "toques_reativar": sum(1 for r in controls if r.get("kind") == "unmute"),
        "avisos_de_reproducao": sum(
            1 for r in selected if r.get("event") == "playback_started"
        ),
    }


def session_markdown(summary: dict[str, Any]) -> str:
    minutes, seconds = divmod(int(round(summary["duracao_s"])), 60)
    status = ", ".join(f"{k}: {v}" for k, v in summary["por_status"].items()) or "–"
    rows = [
        ("Duração (primeira → última fala)", f"{minutes} min {seconds:02d} s"),
        ("Falas transcritas", summary["falas"]),
        ("Destino das falas", status),
        ("Tradução entregue a quem falou", summary["traducao_para_quem_falou"]),
        ("Participantes", summary["participantes"]),
        ("Reconexões", summary["reconexoes"]),
        (
            "Toques em silenciar / reativar",
            f"{summary['toques_silenciar']} / {summary['toques_reativar']}",
        ),
        ("Avisos de reprodução (T6)", summary["avisos_de_reproducao"]),
    ]
    lines = ["| Sessão | Valor |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return "\n".join(lines) + "\n"
