"""Testa uma sala real com dois participantes simulados (Etapa 2).

Cria uma sala pelo app, conecta A (fala/ouve pt) e B (fala/ouve zh) e manda o
áudio das frases de teste como dois celulares: blocos de 128 ms em tempo real,
com silêncio entre as falas. As frases se alternam (pt-01 por A, zh-01 por B...).

Com ``--cruzada G`` (padrão 0,3, cerca de -10 dB), o microfone de quem está
ouvindo também capta a fala do outro, atenuada por G, como duas pessoas frente a
frente. É o caso que o filtro de conversa cruzada (2.7) precisa descartar.

Para cada frase, confere:

- quem ouve recebe exatamente uma tradução (texto e áudio) no próprio idioma;
- quem falou não recebe nenhuma tradução da própria fala (só ``self_transcript``);
- a fala captada pelo outro microfone foi descartada (``utterance_ignored``).

E mede, a partir do envio do último bloco com fala (fim da fala), a chegada do
texto traduzido e do link do áudio no celular de quem ouve. As marcas que o
servidor gravou em logs/room-timing.jsonl entram no resultado para comparação.

Uso:
    python bench/testar_sala.py --rotulo 2-sala [--rodadas 1] [--cruzada 0.3]
Resultado: bench/resultados/<rotulo>.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import struct
import sys
import time
from datetime import datetime

import websockets

from comum import AUDIO_DIR, BENCH, ler_frases, ler_pcm16k, post_json, resumo
from medir_conversa import BLOCO, BLOCO_S, baixar

SILENCIO = b"\x00\x00" * 2048
TIMING_LOG = BENCH.parent / "logs" / "room-timing.jsonl"


def atenuar(pcm: bytes, ganho: float) -> bytes:
    n = len(pcm) // 2
    amostras = struct.unpack(f"<{n}h", pcm[: n * 2])
    return struct.pack(
        f"<{n}h", *(max(-32768, min(32767, int(a * ganho))) for a in amostras)
    )


class Cliente:
    def __init__(self, nome: str, idioma: str) -> None:
        self.nome = nome
        self.idioma = idioma
        self.microfone: collections.deque[tuple[bytes, bool]] = collections.deque()
        self.eventos: list[dict] = []
        self.novo = asyncio.Event()
        self.fim_da_fala: tuple[float, float] | None = None  # perf, epoch
        self.ws = None
        self.id = None

    async def conectar(self, app: str, sala: str) -> None:
        url = (
            f"ws://{app}/api/ws/rooms/{sala}?name={self.nome}"
            f"&speak={self.idioma}&listen={self.idioma}"
        )
        self.ws = await websockets.connect(url, max_size=None)
        self.tarefas = [
            asyncio.create_task(self._enviar()),
            asyncio.create_task(self._ler()),
        ]
        while self.id is None:
            await self.novo.wait()
            self.novo.clear()

    async def _enviar(self) -> None:
        inicio = time.perf_counter()
        n = 0
        while True:
            bloco, ultimo = (
                self.microfone.popleft() if self.microfone else (SILENCIO, False)
            )
            await self.ws.send(bloco)
            if ultimo:
                self.fim_da_fala = (time.perf_counter(), time.time())
            n += 1
            await asyncio.sleep(max(0.0, inicio + n * BLOCO_S - time.perf_counter()))

    async def _ler(self) -> None:
        try:
            async for m in self.ws:
                if isinstance(m, bytes):
                    continue
                d = json.loads(m)
                d["_t"] = time.perf_counter()
                if d.get("type") == "joined":
                    self.id = d["participant"]["id"]
                self.eventos.append(d)
                self.novo.set()
        except websockets.ConnectionClosed:
            pass

    def falar(self, pcm: bytes, marcar_fim: bool = True) -> None:
        blocos = [pcm[i : i + BLOCO] for i in range(0, len(pcm), BLOCO)]
        for i, b in enumerate(blocos):
            self.microfone.append(
                (b.ljust(BLOCO, b"\x00"), marcar_fim and i == len(blocos) - 1)
            )

    async def fechar(self) -> None:
        try:
            await self.ws.send(json.dumps({"type": "end"}))
            await asyncio.sleep(0.3)
            await self.ws.close()
        finally:
            for t in self.tarefas:
                t.cancel()


def tipos(eventos: list[dict], tipo: str) -> list[dict]:
    return [e for e in eventos if e.get("type") == tipo]


async def testar(args: argparse.Namespace) -> dict:
    frases = ler_frases()
    if args.so:
        ids = set(args.so.split(","))
        frases = [f for f in frases if f["id"] in ids]
    pt = [f for f in frases if f["idioma"] == "pt"]
    zh = [f for f in frases if f["idioma"] == "zh"]
    ordem = [f for par in zip(pt, zh) for f in par] + pt[len(zh) :] + zh[len(pt) :]
    audios = {f["id"]: ler_pcm16k(AUDIO_DIR / f"{f['id']}.wav") for f in ordem}

    sala = json.loads(post_json(f"http://{args.app}/api/rooms", {}))["room"]
    a, b = Cliente("A", "pt"), Cliente("B", "zh")
    await a.conectar(args.app, sala)
    await b.conectar(args.app, sala)
    por_idioma = {"pt": (a, b), "zh": (b, a)}
    await asyncio.sleep(2.0)  # silêncio inicial, como ao abrir o microfone

    medidas = []
    for rodada in range(1, args.rodadas + 1):
        for f in ordem:
            fala, ouve = por_idioma[f["idioma"]]
            pcm, dur = audios[f["id"]]
            n_fala, n_ouve = len(fala.eventos), len(ouve.eventos)
            fala.fim_da_fala = None
            fala.falar(pcm)
            if args.cruzada > 0:
                ouve.falar(atenuar(pcm, args.cruzada), marcar_fim=False)
            while fala.fim_da_fala is None:
                await asyncio.sleep(0.01)
            t_fim, t_fim_epoch = fala.fim_da_fala

            # Espera o áudio chegar a quem ouve e depois um período sem mensagens.
            limite = t_fim + args.tempo_max
            visto = False
            while time.perf_counter() < limite:
                ouve.novo.clear()
                fala.novo.clear()
                espera = args.quieto if visto else 0.5
                try:
                    await asyncio.wait_for(ouve.novo.wait(), espera)
                except asyncio.TimeoutError:
                    if visto:
                        break
                visto = bool(tipos(ouve.eventos[n_ouve:], "room_tts"))

            ev_fala, ev_ouve = fala.eventos[n_fala:], ouve.eventos[n_ouve:]
            textos = tipos(ev_ouve, "room_translation")
            vozes = tipos(ev_ouve, "room_tts")
            med = {
                "id": f["id"],
                "idioma": f["idioma"],
                "rodada": rodada,
                "duracao_fala": round(dur, 3),
                "texto": f["texto"],
                "fim_da_fala_epoch": round(t_fim_epoch, 3),
                "transcrito": " | ".join(e["transcript"] for e in vozes),
                "traduzido": " | ".join(e["translated_text"] for e in vozes),
                "detectado": ",".join(str(e.get("detected_language")) for e in vozes),
                "n_texto_ouvinte": len(textos),
                "n_audio_ouvinte": len(vozes),
                # vazamentos: tradução da própria fala voltando para quem falou
                "n_traducao_para_quem_falou": len(
                    [
                        e
                        for e in tipos(ev_fala, "room_translation")
                        + tipos(ev_fala, "room_tts")
                        if e.get("speaker_id") == fala.id
                    ]
                ),
                "n_self_transcript": len(tipos(ev_fala, "self_transcript")),
                "n_cruzada_descartada": len(tipos(ev_ouve, "utterance_ignored")),
                "cruzada_descartada": [
                    (e.get("detected_language"), e.get("transcript"))
                    for e in tipos(ev_ouve, "utterance_ignored")
                ],
                "erros": [
                    e
                    for e in ev_fala + ev_ouve
                    if e.get("type") in {"error", "room_error"}
                ],
                "texto_s": round(textos[0]["_t"] - t_fim, 3) if textos else None,
                "voz_s": round(vozes[0]["_t"] - t_fim, 3) if vozes else None,
                "utterance_id": vozes[0]["utterance_id"] if vozes else None,
            }
            if vozes:
                med["download_s"] = round(
                    baixar(f"http://{args.app}{vozes[0]['audio_url']}"), 3
                )
                med["audio_s"] = round(med["voz_s"] + med["download_s"], 3)
            ok = (
                med["n_audio_ouvinte"] == 1
                and med["n_traducao_para_quem_falou"] == 0
                and (args.cruzada == 0 or med["n_cruzada_descartada"] >= 1)
            )
            med["ok"] = ok
            medidas.append(med)
            print(
                f"{f['id']} r{rodada}: {'OK ' if ok else 'ERRO'} voz={med['voz_s']}s "
                f"texto={med['texto_s']}s ouvinte={med['n_audio_ouvinte']} "
                f"vazou={med['n_traducao_para_quem_falou']} "
                f"cruzada_descartada={med['n_cruzada_descartada']} | {med['traduzido']}",
                flush=True,
            )
            await asyncio.sleep(args.intervalo)

    await a.fechar()
    await b.fechar()
    return {"sala": sala, "medidas": medidas}


def ler_marcas_servidor(sala: str) -> dict[str, dict]:
    if not TIMING_LOG.exists():
        return {}
    marcas = {}
    for linha in TIMING_LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if r.get("room") == sala and r.get("utterance_id"):
            marcas[r["utterance_id"]] = r
    return marcas


def resumir(medidas: list[dict]) -> dict:
    res = {}
    for idioma, nome in (("pt", "PT→ZH"), ("zh", "ZH→PT")):
        ms = [m for m in medidas if m["idioma"] == idioma]
        res[nome] = {
            "frases": len(ms),
            "ok": sum(m["ok"] for m in ms),
            "vazamentos": sum(m["n_traducao_para_quem_falou"] for m in ms),
            "cruzada_descartada": sum(m["n_cruzada_descartada"] for m in ms),
            **{
                k: resumo([m[k] for m in ms if m.get(k) is not None])
                for k in (
                    "texto_s",
                    "voz_s",
                    "audio_s",
                    "servidor_audio_enviado_s",
                    "erro_fim_da_fala_s",
                )
                if any(m.get(k) is not None for m in ms)
            },
        }
    return res


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--rotulo", required=True)
    ap.add_argument("--app", default="127.0.0.1:9000")
    ap.add_argument("--rodadas", type=int, default=1)
    ap.add_argument("--so", help="ids separados por vírgula")
    ap.add_argument(
        "--cruzada",
        type=float,
        default=0.3,
        help="ganho da fala captada pelo outro microfone (0 = desliga)",
    )
    ap.add_argument("--tempo-max", type=float, default=12.0)
    ap.add_argument("--quieto", type=float, default=1.5)
    ap.add_argument("--intervalo", type=float, default=0.5)
    args = ap.parse_args()

    inicio = datetime.now().isoformat(timespec="seconds")
    res = asyncio.run(testar(args))
    marcas = ler_marcas_servidor(res["sala"])
    for m in res["medidas"]:
        r = marcas.get(m.get("utterance_id") or "")
        if not r:
            continue
        alvo = next(iter(r["targets"].values()), {})
        m["servidor"] = {
            "stt_s": r.get("stt_seconds"),
            **alvo.get("since_speech_end", {}),
        }
        if "audio_sent" in m["servidor"] and m["servidor"]["audio_sent"] is not None:
            m["servidor_audio_enviado_s"] = m["servidor"]["audio_sent"]
        fim_servidor = r.get("t", {}).get("speech_end")
        if fim_servidor:
            # quanto o fim estimado pelo servidor difere do fim real (cliente)
            m["erro_fim_da_fala_s"] = round(fim_servidor - m["fim_da_fala_epoch"], 3)
    saida = {
        "inicio": inicio,
        "args": vars(args),
        "sala": res["sala"],
        "resumo": resumir(res["medidas"]),
        "medidas": res["medidas"],
    }
    destino = BENCH / "resultados" / f"{args.rotulo}.json"
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(saida["resumo"], ensure_ascii=False, indent=2))
    print(f"-> {destino}")
    falhas = [m["id"] for m in res["medidas"] if not m["ok"]]
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
