"""Mede a precisão e o tempo do STT com o conjunto de frases (direto no serviço).

Cada frase é enviada numa conexão nova ao WebSocket do STT
(`/v1/stream/transcriptions`), com `emit_policy=pause` como no modo conversation,
seguida de silêncio para fechar a frase. O áudio vai sem esperar o tempo real,
porque aqui interessa o reconhecimento, não a espera de silêncio.

Modos de idioma:
    fixo  o idioma da frase é informado (cada participante declara o seu)
    auto  detecção restrita a pt/zh, como o modo conversation faz hoje

Métricas:
    zh  CER (erro por caractere) após normalizar: tradicional -> simplificado
        (se o pacote opencc estiver instalado), algarismos -> numerais chineses, 两 -> 二,
        sem pontuação nem espaços
    pt  WER (erro por palavra) após normalizar: minúsculas, sem pontuação,
        "R$ 12,50" -> "12 reais e 50 centavos", algarismos -> extenso (até 99)

Uso:
    python bench/medir_stt.py --rotulo small-cpu [--idioma fixo|auto|ambos]
Resultado em bench/resultados/stt-<rotulo>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import unicodedata

import websockets

from comum import AUDIO_DIR, BENCH, SR, ler_frases, ler_pcm16k, resumo

try:  # pip install opencc-python-reimplemented
    from opencc import OpenCC

    _T2S = OpenCC("t2s").convert
except ImportError:  # pragma: no cover - dependência opcional
    _T2S = None

BLOCO = 2048 * 2
UNIDADES = (
    "zero um dois três quatro cinco seis sete oito nove dez onze doze treze "
    "catorze quinze dezesseis dezessete dezoito dezenove"
).split()
DEZENAS = "_ _ vinte trinta quarenta cinquenta sessenta setenta oitenta noventa".split()
ZH_DIG = "零一二三四五六七八九"


def pt_extenso(n: int) -> str:
    if n < 20:
        return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return DEZENAS[d] + (f" e {UNIDADES[u]}" if u else "")
    return str(n)


def zh_numeral(n: int) -> str:
    if n < 10:
        return ZH_DIG[n]
    if n < 100:
        d, u = divmod(n, 10)
        return ("" if d == 1 else ZH_DIG[d]) + "十" + (ZH_DIG[u] if u else "")
    if n < 1000:
        c, r = divmod(n, 100)
        return (
            ZH_DIG[c]
            + "百"
            + ("" if r == 0 else ("零" if r < 10 else "") + zh_numeral(r))
        )
    return str(n)


def normalizar(texto: str, idioma: str) -> str:
    if idioma == "zh":
        if _T2S:
            texto = _T2S(texto)
        texto = re.sub(r"\d+", lambda m: zh_numeral(int(m.group())), texto)
        texto = texto.replace("两", "二")  # 两百 = 二百 = 200
        return "".join(c for c in texto if unicodedata.category(c)[0] in "LN")
    texto = texto.lower()
    texto = re.sub(
        r"r\$\s*(\d+),(\d{2})",
        lambda m: f"{int(m[1])} reais e {int(m[2])} centavos",
        texto,
    )
    texto = re.sub(r"\d+", lambda m: pt_extenso(int(m.group())), texto)
    texto = "".join(c if unicodedata.category(c)[0] in "LN" else " " for c in texto)
    return " ".join(texto.split())


def distancia(a: list[str], b: list[str]) -> int:
    ant = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        atual = [i]
        for j, y in enumerate(b, 1):
            atual.append(min(ant[j] + 1, atual[j - 1] + 1, ant[j - 1] + (x != y)))
        ant = atual
    return ant[-1]


def taxa_erro(ref: str, hip: str, idioma: str) -> float:
    r, h = normalizar(ref, idioma), normalizar(hip, idioma)
    ur, uh = (list(r), list(h)) if idioma == "zh" else (r.split(), h.split())
    return distancia(ur, uh) / max(1, len(ur))


async def transcrever(
    url: str, pcm: bytes, idioma: str, modo: str, silencio_s: float
) -> dict:
    alvo = f"{url}?language={idioma}" if modo == "fixo" else url
    async with websockets.connect(alvo, max_size=None) as ws:
        controle = {"emit_policy": "pause"}
        if modo == "auto":
            controle["candidate_languages"] = ["pt", "zh"]
        await ws.send(json.dumps(controle))
        for i in range(0, len(pcm), BLOCO):
            await ws.send(pcm[i : i + BLOCO])
        for _ in range(int(silencio_s * SR * 2 / BLOCO) + 1):
            await ws.send(b"\x00" * BLOCO)
        t0 = time.perf_counter()
        resultado = {"texto": "", "idioma": None, "tempo": None, "inferencia": None}
        try:
            while True:
                espera = 2.0 if resultado["texto"] else 30.0
                m = json.loads(await asyncio.wait_for(ws.recv(), espera))
                if m.get("error"):
                    resultado["erro"] = m["error"]
                    break
                if m.get("text"):
                    resultado["texto"] = m["text"]
                    resultado["idioma"] = m.get("language")
                    resultado["tempo"] = round(time.perf_counter() - t0, 3)
                    metricas = m.get("metrics") or {}
                    resultado["inferencia"] = metricas.get("inference_seconds")
        except asyncio.TimeoutError:
            pass
    return resultado


def config_stt() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["docker", "exec", "polytalk-stt", "printenv"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout
    except Exception:  # noqa: BLE001 - informativo
        return {}
    return dict(x.split("=", 1) for x in out.splitlines() if x.startswith("STT_"))


async def medir(args: argparse.Namespace) -> list[dict]:
    modos = ["fixo", "auto"] if args.idioma == "ambos" else [args.idioma]
    medidas = []
    for rodada in range(1, args.rodadas + 1):
        for f in ler_frases():
            pcm, dur = ler_pcm16k(AUDIO_DIR / f"{f['id']}.wav")
            for modo in modos:
                r = await transcrever(args.url, pcm, f["idioma"], modo, args.silencio)
                erro = taxa_erro(f["texto"], r["texto"], f["idioma"])
                medidas.append(
                    {
                        "id": f["id"],
                        "idioma": f["idioma"],
                        "modo": modo,
                        "rodada": rodada,
                        "duracao_fala": round(dur, 3),
                        "referencia": f["texto"],
                        **r,
                        "taxa_erro": round(erro, 3),
                    }
                )
                print(
                    f"[{rodada}] {f['id']} {modo:4} det={r['idioma']} "
                    f"t={r['tempo']}s inf={r['inferencia']} erro={erro:.0%}  {r['texto']!r}"
                )
    return medidas


def resumir(medidas: list[dict]) -> dict:
    saida = {}
    for modo in sorted({m["modo"] for m in medidas}):
        for idioma in ("pt", "zh"):
            ms = [m for m in medidas if m["modo"] == modo and m["idioma"] == idioma]
            if not ms:
                continue
            saida[f"{idioma}-{modo}"] = {
                "taxa_erro_media": round(sum(m["taxa_erro"] for m in ms) / len(ms), 3),
                "frases_exatas": sum(1 for m in ms if m["taxa_erro"] == 0),
                "idioma_errado": sum(1 for m in ms if m["idioma"] != idioma),
                "sem_texto": sum(1 for m in ms if not m["texto"]),
                "tempo": resumo([m["tempo"] for m in ms if m["tempo"] is not None]),
                "inferencia": resumo(
                    [m["inferencia"] for m in ms if m["inferencia"] is not None]
                ),
                "n": len(ms),
            }
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--rotulo", required=True)
    ap.add_argument("--url", default="ws://127.0.0.1:8000/v1/stream/transcriptions")
    ap.add_argument("--idioma", choices=["fixo", "auto", "ambos"], default="ambos")
    ap.add_argument("--rodadas", type=int, default=1)
    ap.add_argument(
        "--silencio", type=float, default=2.0, help="silêncio após a fala (s)"
    )
    args = ap.parse_args()
    if _T2S is None:
        print(
            "aviso: opencc ausente; o chinês tradicional conta como erro",
            file=sys.stderr,
        )

    stt = config_stt()
    medidas = asyncio.run(medir(args))
    res = resumir(medidas)
    print(
        "\n| Idioma/modo | Erro médio | Exatas | Idioma errado | Tempo mediana (s) | p95 (s) |"
    )
    print("|---|---|---|---|---|---|")
    for k, r in res.items():
        t = r["tempo"]
        print(
            f"| {k} | {r['taxa_erro_media']:.1%} | {r['frases_exatas']}/{r['n']} | "
            f"{r['idioma_errado']} | {t.get('mediana', float('nan')):.2f} | "
            f"{t.get('p95', float('nan')):.2f} |"
        )
    destino = BENCH / "resultados" / f"stt-{args.rotulo}.json"
    destino.parent.mkdir(exist_ok=True)
    saida = {"rotulo": args.rotulo, "opencc": _T2S is not None, "config_stt": stt}
    saida |= {"resumo": res, "medidas": medidas}
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"\nsalvo em {destino.relative_to(BENCH.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
