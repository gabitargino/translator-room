"""Funções compartilhadas pelos scripts de medição da Etapa 1 (só biblioteca padrão)."""

from __future__ import annotations

import csv
import json
import math
import statistics
import struct
import urllib.request
import wave
from pathlib import Path

BENCH = Path(__file__).resolve().parent
AUDIO_DIR = BENCH / "audio"
FRASES = BENCH / "frases.tsv"
SR = 16000


def ler_frases(idioma: str | None = None) -> list[dict[str, str]]:
    with FRASES.open(encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter="\t"))
    return [f for f in linhas if idioma is None or f["idioma"] == idioma]


def post_json(url: str, payload: dict, timeout: float = 120) -> bytes:
    req = urllib.request.Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def ler_wav(caminho) -> tuple[list[int], int]:
    """Lê um WAV PCM 16 bits (caminho ou arquivo em memória); devolve o 1º canal e a taxa."""
    with wave.open(str(caminho) if isinstance(caminho, Path) else caminho, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"{caminho}: esperado PCM 16 bits, veio {sw * 8} bits")
    amostras = struct.unpack(f"<{len(raw) // 2}h", raw)[::ch]
    return list(amostras), sr


def ler_pcm16k(caminho: Path) -> tuple[bytes, float]:
    """Lê um WAV do conjunto (16 kHz mono int16) como bytes PCM e duração."""
    with wave.open(str(caminho), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SR, 1, 2):
            raise ValueError(f"{caminho}: esperado 16 kHz mono 16 bits")
        n = w.getnframes()
        return w.readframes(n), n / SR


def salvar_wav(caminho: Path, amostras: list[int], sr: int = SR) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{len(amostras)}h", *amostras))


def reamostrar(
    x: list[int], sr_in: int, sr_out: int = SR, meia_janela: int = 16
) -> list[int]:
    """Reamostragem por sinc janelado (Hann), com filtro passa-baixa anti-aliasing."""
    if sr_in == sr_out:
        return list(x)
    razao = sr_out / sr_in
    corte = min(1.0, razao)  # fração da Nyquist de entrada
    n_out = int(len(x) * razao)
    out = []
    for i in range(n_out):
        t = i / razao
        centro = int(t)
        acc = 0.0
        for j in range(centro - meia_janela + 1, centro + meia_janela + 1):
            if 0 <= j < len(x):
                d = t - j
                arg = math.pi * d * corte
                s = corte if d == 0 else math.sin(arg) / (math.pi * d)
                janela = 0.5 + 0.5 * math.cos(math.pi * d / meia_janela)
                acc += x[j] * s * janela
        out.append(max(-32768, min(32767, int(round(acc)))))
    return out


def aparar_silencio(
    x: list[int], sr: int = SR, limiar: float = 0.01, margem_s: float = 0.05
) -> list[int]:
    """Remove o silêncio do início e do fim (RMS em quadros de 10 ms)."""
    q = sr // 100
    ativos = []
    for k in range(0, len(x), q):
        bloco = x[k : k + q]
        rms = math.sqrt(sum(v * v for v in bloco) / len(bloco)) / 32768
        ativos.append(rms >= limiar)
    if not any(ativos):
        return x
    ini = ativos.index(True) * q
    fim = (len(ativos) - ativos[::-1].index(True)) * q
    m = int(margem_s * sr)
    return x[max(0, ini - m) : min(len(x), fim + m)]


def percentil(valores: list[float], p: float) -> float:
    """Percentil por posição mais próxima (mesmo critério de tools/benchmarks)."""
    v = sorted(valores)
    return v[round((len(v) - 1) * p)] if v else float("nan")


def resumo(valores: list[float]) -> dict[str, float]:
    if not valores:
        return {"n": 0}
    return {
        "n": len(valores),
        "mediana": statistics.median(valores),
        "p95": percentil(valores, 0.95),
        "min": min(valores),
        "max": max(valores),
    }
