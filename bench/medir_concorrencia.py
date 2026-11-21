"""Mede a latência com duas falas simultâneas (dois fluxos de STT ao mesmo tempo).

Abre duas sessões `mode=conversation` independentes, A e B, como dois
participantes com o microfone aberto. Em cada passo, as duas começam a falar no
mesmo instante: A fala a frase pt-N e B fala a zh-N. Assim, as duas disputam o
STT, o tradutor e a voz. O relógio de cada sessão parte do fim da própria fala.

Uso: python bench/medir_concorrencia.py --rotulo 2-falas [--rodadas 1]
Comparar com uma medição de uma sessão só (medir_conversa.py), com a mesma
configuração.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
import time

import websockets

from comum import AUDIO_DIR, BENCH, ler_frases, ler_pcm16k, resumo
from medir_conversa import BLOCO, BLOCO_S, baixar, config_stt

SILENCIO = b"\x00\x00" * 2048


async def sessao(
    nome: str, frases: list[dict], barreira: asyncio.Barrier, args
) -> list[dict]:
    url = (
        f"ws://{args.app}/api/ws/translate?source_language=pt"
        f"&target_language=zh&mode=conversation"
    )
    fila: collections.deque[tuple[bytes, bool]] = collections.deque()
    eventos: list[dict] = []
    fim = {"t": None}
    medidas = []
    async with websockets.connect(url, max_size=None) as ws:

        async def enviar() -> None:
            inicio, n = time.perf_counter(), 0
            while True:
                bloco, ultimo = fila.popleft() if fila else (SILENCIO, False)
                await ws.send(bloco)
                if ultimo:
                    fim["t"] = time.perf_counter()
                n += 1
                await asyncio.sleep(
                    max(0.0, inicio + n * BLOCO_S - time.perf_counter())
                )

        async def ler() -> None:
            try:
                async for m in ws:
                    if isinstance(m, str):
                        d = json.loads(m)
                        d["_t"] = time.perf_counter()
                        eventos.append(d)
            except websockets.ConnectionClosed:
                pass

        tarefas = [asyncio.create_task(enviar()), asyncio.create_task(ler())]
        await asyncio.sleep(2.0)
        for rodada in range(1, args.rodadas + 1):
            for f in frases:
                await barreira.wait()  # as duas sessões começam a falar juntas
                pcm, dur = ler_pcm16k(AUDIO_DIR / f"{f['id']}.wav")
                n0 = len(eventos)
                fim["t"] = None
                blocos = [pcm[i : i + BLOCO] for i in range(0, len(pcm), BLOCO)]
                for i, b in enumerate(blocos):
                    fila.append((b.ljust(BLOCO, b"\x00"), i == len(blocos) - 1))
                while fim["t"] is None:
                    await asyncio.sleep(0.01)
                t_fim = fim["t"]
                while time.perf_counter() < t_fim + args.tempo_max:
                    if any(e.get("type") == "tts" for e in eventos[n0:]):
                        break
                    await asyncio.sleep(0.02)
                janela = eventos[n0:]
                med = {
                    "sessao": nome,
                    "id": f["id"],
                    "idioma": f["idioma"],
                    "rodada": rodada,
                }
                for tipo, k in (
                    ("transcription", "transcricao"),
                    ("conversation_turn", "traducao"),
                    ("tts", "voz"),
                ):
                    evs = [e for e in janela if e.get("type") == tipo]
                    med[k] = round(evs[0]["_t"] - t_fim, 3) if evs else None
                tts = [e for e in janela if e.get("type") == "tts"]
                med["audio"] = None
                if tts:
                    u = tts[0]["audio_url"]
                    u = f"http://{args.app}{u}" if u.startswith("/") else u
                    med["audio"] = round(
                        med["voz"] + await asyncio.to_thread(baixar, u), 3
                    )
                turnos = [e for e in janela if e.get("type") == "conversation_turn"]
                med["transcrito"] = " | ".join(e.get("transcript", "") for e in turnos)
                med["traduzido"] = " | ".join(
                    e.get("translated_text", "") for e in turnos
                )
                medidas.append(med)
                print(
                    f"[{rodada}] {nome} {f['id']} "
                    + "  ".join(
                        f"{k}={med[k]:.2f}" if med[k] is not None else f"{k}=—"
                        for k in ("transcricao", "traducao", "voz", "audio")
                    )
                    + f"  {med['transcrito']!r}"
                )
                await asyncio.sleep(args.intervalo)
        await ws.send(json.dumps({"type": "end"}))
        for t in tarefas:
            t.cancel()
    return medidas


async def medir(args) -> list[dict]:
    pt, zh = ler_frases("pt"), ler_frases("zh")
    n = min(len(pt), len(zh))
    barreira = asyncio.Barrier(2)
    a, b = await asyncio.gather(
        sessao("A", pt[:n], barreira, args), sessao("B", zh[:n], barreira, args)
    )
    return a + b


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--rotulo", required=True)
    ap.add_argument("--app", default="127.0.0.1:9000")
    ap.add_argument("--rodadas", type=int, default=1)
    ap.add_argument(
        "--intervalo", type=float, default=2.5, help="silêncio após a voz (s)"
    )
    ap.add_argument("--tempo-max", type=float, default=20.0)
    args = ap.parse_args()

    stt = config_stt()
    medidas = asyncio.run(medir(args))
    res = {}
    for idioma, direcao in (("pt", "pt→zh"), ("zh", "zh→pt")):
        ms = [m for m in medidas if m["idioma"] == idioma]
        res[direcao] = {
            k: resumo([m[k] for m in ms if m[k] is not None])
            for k in ("transcricao", "traducao", "voz", "audio")
        }
        res[direcao]["falhas"] = sum(1 for m in ms if m["audio"] is None)
    print(
        "\n| Direção | Até a transcrição | Até a tradução | Até o áudio (mediana / p95) | Falhas |"
    )
    print("|---|---|---|---|---|")
    for d, r in res.items():
        print(
            f"| {d} | {r['transcricao'].get('mediana', 0):.2f} | "
            f"{r['traducao'].get('mediana', 0):.2f} | "
            f"{r['audio'].get('mediana', 0):.2f} / {r['audio'].get('p95', 0):.2f} | "
            f"{r['falhas']} |"
        )
    destino = BENCH / "resultados" / f"{args.rotulo}.json"
    saida = {
        "rotulo": args.rotulo,
        "config_stt": stt,
        "resumo": res,
        "medidas": medidas,
    }
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"\nsalvo em {destino.relative_to(BENCH.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
