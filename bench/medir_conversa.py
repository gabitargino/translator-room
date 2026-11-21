"""Mede a latência do modo conversation do PolyTalk com o conjunto de frases.

Abre uma sessão `mode=conversation` (pt <-> zh) e envia o áudio como o navegador:
blocos de 2048 amostras (128 ms) em tempo real, com silêncio entre as falas. As
frases são alternadas (pt-01, zh-01, pt-02, ...), como numa conversa.

Para cada frase, o relógio parte do envio do último bloco com fala (fim da fala) e
marca a chegada de cada mensagem do servidor:

    transcricao  mensagem `transcription`      espera de silêncio + STT
    traducao     mensagem `conversation_turn`  + tradução
    voz          mensagem `tts`                + síntese de voz
    audio        arquivo de áudio baixado      + envio (= "início do áudio")

Uso:
    python bench/medir_conversa.py --rotulo padrao [--rodadas 2] [--so pt-01,zh-03]
O resultado vai para bench/resultados/<rotulo>.json, com a configuração do STT
lida do container (se o Docker estiver acessível).
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import random
import struct
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

import websockets

from comum import AUDIO_DIR, BENCH, ler_frases, ler_pcm16k, resumo

BLOCO = 2048 * 2  # bytes: 2048 amostras int16, como o ScriptProcessor do navegador
BLOCO_S = 2048 / 16000
ETAPAS = ("transcricao", "traducao", "voz", "audio")


def bloco_silencio(ruido_dbfs: float | None, rng: random.Random) -> bytes:
    if ruido_dbfs is None:
        return b"\x00\x00" * 2048
    amp = 32768 * 10 ** (ruido_dbfs / 20)
    amostras = (max(-32768, min(32767, int(rng.gauss(0, amp)))) for _ in range(2048))
    return b"".join(a.to_bytes(2, "little", signed=True) for a in amostras)


def config_stt() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["docker", "exec", "polytalk-stt", "printenv"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout
    except Exception:  # noqa: BLE001 - a configuração é só informativa
        return {}
    return dict(x.split("=", 1) for x in out.splitlines() if x.startswith("STT_"))


def esticar_pausa(pcm: bytes, alvo_s: float) -> tuple[bytes, bool]:
    """Estica a maior pausa interna da frase (ex.: na vírgula) até `alvo_s`.

    Procura, entre 15% e 85% da frase, o trecho mais longo de quadros de 10 ms com
    RMS abaixo de 1% da escala. Se tiver pelo menos 50 ms, insere silêncio no meio
    dele até a pausa somar `alvo_s`. Simula quem hesita no meio da frase.
    """
    q = 160 * 2  # 10 ms em bytes
    quadros = [pcm[i : i + q] for i in range(0, len(pcm) - q + 1, q)]
    baixos = []
    for b in quadros:
        n = len(b) // 2
        soma = sum(v * v for (v,) in struct.iter_unpack("<h", b))
        baixos.append((soma / n) ** 0.5 / 32768 < 0.01)
    ini_ok, fim_ok = int(len(quadros) * 0.15), int(len(quadros) * 0.85)
    melhor, atual = (0, 0), None
    for i in range(ini_ok, fim_ok):
        if baixos[i]:
            atual = (atual[0], i + 1) if atual else (i, i + 1)
            if atual[1] - atual[0] > melhor[1] - melhor[0]:
                melhor = atual
        else:
            atual = None
    tamanho = melhor[1] - melhor[0]
    if tamanho < 5:
        return pcm, False
    meio = (melhor[0] + tamanho // 2) * q
    extra = max(0, int(alvo_s * 100) - tamanho) * q
    return pcm[:meio] + b"\x00" * extra + pcm[meio:], True


def baixar(url: str) -> float:
    """Baixa o áudio e devolve quanto tempo o download levou."""
    t = time.perf_counter()
    with urllib.request.urlopen(url, timeout=30) as r:
        r.read()
    return time.perf_counter() - t


async def medir(args: argparse.Namespace) -> dict:
    frases = ler_frases()
    if args.so:
        ids = set(args.so.split(","))
        frases = [f for f in frases if f["id"] in ids]
    pt = [f for f in frases if f["idioma"] == "pt"]
    zh = [f for f in frases if f["idioma"] == "zh"]
    ordem = [f for par in zip(pt, zh) for f in par] + pt[len(zh) :] + zh[len(pt) :]
    audios = {f["id"]: ler_pcm16k(AUDIO_DIR / f"{f['id']}.wav") for f in ordem}
    pausas: dict[str, bool] = {}
    if args.pausa_interna:
        for k, (pcm, _) in audios.items():
            novo, ok = esticar_pausa(pcm, args.pausa_interna)
            audios[k] = (novo, len(novo) / 32000)
            pausas[k] = ok

    rng = random.Random(1)
    silencio = bloco_silencio(args.ruido_dbfs, rng)
    fila: collections.deque[tuple[bytes, bool]] = collections.deque()
    eventos: list[dict] = []
    novo_evento = asyncio.Event()
    fim_da_fala = {"t": None}
    url = (
        f"ws://{args.app}/api/ws/translate?source_language=pt"
        f"&target_language=zh&mode=conversation"
    )

    async with websockets.connect(url, max_size=None) as ws:

        async def enviar() -> None:
            inicio = time.perf_counter()
            n = 0
            while True:
                bloco, ultimo = fila.popleft() if fila else (silencio, False)
                await ws.send(bloco)
                if ultimo:
                    fim_da_fala["t"] = time.perf_counter()
                n += 1
                atraso = inicio + n * BLOCO_S - time.perf_counter()
                await asyncio.sleep(max(0.0, atraso))

        async def ler() -> None:
            try:
                async for m in ws:
                    if isinstance(m, bytes):
                        continue
                    d = json.loads(m)
                    d["_t"] = time.perf_counter()
                    eventos.append(d)
                    novo_evento.set()
            except websockets.ConnectionClosed:
                pass

        tarefas = [asyncio.create_task(enviar()), asyncio.create_task(ler())]
        await asyncio.sleep(2.0)  # silêncio inicial, como ao abrir o microfone

        medidas = []
        for rodada in range(1, args.rodadas + 1):
            for f in ordem:
                pcm, dur = audios[f["id"]]
                n0 = len(eventos)
                fim_da_fala["t"] = None
                blocos = [pcm[i : i + BLOCO] for i in range(0, len(pcm), BLOCO)]
                for i, b in enumerate(blocos):
                    fila.append((b.ljust(BLOCO, b"\x00"), i == len(blocos) - 1))
                while fim_da_fala["t"] is None:
                    await asyncio.sleep(0.01)
                t_fim = fim_da_fala["t"]

                # Espera a voz e depois um período sem mensagens novas.
                limite = t_fim + args.tempo_max
                visto_tts = False
                while time.perf_counter() < limite:
                    novo_evento.clear()
                    try:
                        await asyncio.wait_for(
                            novo_evento.wait(), args.quieto if visto_tts else 0.5
                        )
                    except asyncio.TimeoutError:
                        if visto_tts:
                            break
                    visto_tts = any(e.get("type") == "tts" for e in eventos[n0:])

                janela = eventos[n0:]
                med = {
                    "id": f["id"],
                    "idioma": f["idioma"],
                    "rodada": rodada,
                    "duracao_fala": round(dur, 3),
                    "texto": f["texto"],
                    "pausa_interna": pausas.get(f["id"], False),
                }
                tipos = {
                    "transcription": "transcricao",
                    "conversation_turn": "traducao",
                    "tts": "voz",
                }
                for tipo, nome in tipos.items():
                    evs = [e for e in janela if e.get("type") == tipo]
                    med[nome] = round(evs[-1]["_t"] - t_fim, 3) if evs else None
                    med[f"n_{nome}"] = len(evs)
                turnos = [e for e in janela if e.get("type") == "conversation_turn"]
                med["transcrito"] = " | ".join(e.get("transcript", "") for e in turnos)
                med["traduzido"] = " | ".join(
                    e.get("translated_text", "") for e in turnos
                )
                med["idioma_detectado"] = ",".join(
                    str(e.get("detected_language")) for e in turnos
                )
                med["idioma_destino"] = ",".join(
                    str(e.get("target_language")) for e in turnos
                )
                med["erros"] = [
                    e.get("error") for e in janela if e.get("type") == "error"
                ]
                tts = [e for e in janela if e.get("type") == "tts"]
                med["audio"] = None
                if tts:
                    audio_url = tts[-1]["audio_url"]
                    if audio_url.startswith("/"):
                        audio_url = f"http://{args.app}{audio_url}"
                    # O download acontece depois da espera por silêncio nas
                    # mensagens; o arquivo é estático, então soma-se o tempo dele
                    # à chegada da mensagem `tts`.
                    med["download"] = round(
                        await asyncio.to_thread(baixar, audio_url), 3
                    )
                    med["audio"] = round(med["voz"] + med["download"], 3)
                medidas.append(med)
                print(
                    f"[{rodada}] {f['id']} {dur:4.1f}s  "
                    + "  ".join(
                        f"{k}={med[k]:.2f}" if med[k] is not None else f"{k}=—"
                        for k in ETAPAS
                    )
                    + f"  turnos={med['n_traducao']}  {med['transcrito']!r} -> {med['traduzido']!r}"
                )
                await asyncio.sleep(args.intervalo)

        await ws.send(json.dumps({"type": "end"}))
        for t in tarefas:
            t.cancel()

    return {"medidas": medidas}


def resumir(medidas: list[dict]) -> dict:
    saida = {}
    for idioma, direcao in (("pt", "pt→zh"), ("zh", "zh→pt")):
        ms = [m for m in medidas if m["idioma"] == idioma]
        partes = {}
        for k in ETAPAS:
            partes[k] = resumo([m[k] for m in ms if m[k] is not None])
        # Tempo de cada parte isolada (diferença entre mensagens consecutivas).
        for k, (a, b) in {
            "so_traducao": ("transcricao", "traducao"),
            "so_voz": ("traducao", "voz"),
            "so_envio": ("voz", "audio"),
        }.items():
            partes[k] = resumo(
                [m[b] - m[a] for m in ms if m[a] is not None and m[b] is not None]
            )
        partes["falhas"] = sum(1 for m in ms if m["audio"] is None)
        partes["frases_divididas"] = sum(1 for m in ms if m["n_traducao"] > 1)
        partes["direcao_errada"] = sum(
            1
            for m in ms
            if m["idioma_destino"]
            and m["idioma_destino"].split(",")[-1] != ("zh" if idioma == "pt" else "pt")
        )
        saida[direcao] = partes
    return saida


def imprimir(res: dict) -> None:
    print("\n| Direção | Parte | Mediana (s) | p95 (s) | n |")
    print("|---|---|---|---|---|")
    for direcao, partes in res.items():
        for k in ("transcricao", "so_traducao", "so_voz", "so_envio", "audio"):
            r = partes[k]
            if r.get("n"):
                print(
                    f"| {direcao} | {k} | {r['mediana']:.2f} | {r['p95']:.2f} | {r['n']} |"
                )
        print(
            f"| {direcao} | falhas / divididas / direção errada | "
            f"{partes['falhas']} / {partes['frases_divididas']} / {partes['direcao_errada']} | | |"
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--rotulo",
        required=True,
        help="nome da configuração medida (vira o nome do arquivo)",
    )
    ap.add_argument("--app", default="127.0.0.1:9000")
    ap.add_argument("--rodadas", type=int, default=2)
    ap.add_argument("--so", help="ids separados por vírgula")
    ap.add_argument(
        "--intervalo", type=float, default=1.0, help="silêncio extra entre frases (s)"
    )
    ap.add_argument(
        "--quieto", type=float, default=1.5, help="espera sem mensagens após a voz (s)"
    )
    ap.add_argument(
        "--tempo-max", type=float, default=20.0, help="limite por frase (s)"
    )
    ap.add_argument(
        "--pausa-interna",
        type=float,
        default=0.0,
        help="estica a pausa da vírgula para este total (s); 0 = áudio original",
    )
    ap.add_argument(
        "--ruido-dbfs",
        type=float,
        default=None,
        help="ruído gaussiano no silêncio (ex.: -55); padrão: silêncio digital",
    )
    args = ap.parse_args()

    stt = config_stt()
    inicio = datetime.now().isoformat(timespec="seconds")
    dados = asyncio.run(medir(args))
    res = resumir(dados["medidas"])
    imprimir(res)
    saida = {
        "rotulo": args.rotulo,
        "inicio": inicio,
        "rodadas": args.rodadas,
        "ruido_dbfs": args.ruido_dbfs,
        "pausa_interna": args.pausa_interna,
        "config_stt": stt,
        "resumo": res,
        **dados,
    }
    destino = BENCH / "resultados" / f"{args.rotulo}.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"\nsalvo em {destino.relative_to(BENCH.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
