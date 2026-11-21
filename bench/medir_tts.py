"""Mede o tempo de síntese de voz das traduções, direto nos serviços de TTS.

O texto sintetizado é a coluna `referencia` de frases.tsv, ou seja, o que o TTS
recebe numa conversa: frase em PT -> voz em ZH (Piper) e frase em ZH -> voz em
PT (Supertonic), com os mesmos parâmetros que o PolyTalk usa (.env).

Para o Supertonic, mede também outros números de passos (`--passos 8,4,2`): menos
passos é mais rápido, mas pode piorar a voz. A qualidade precisa ser ouvida; os
arquivos ficam em bench/resultados/tts-<rotulo>/ (fora do git).

Uso: python bench/medir_tts.py --rotulo padrao [--rodadas 3] [--passos 8,4,2]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import wave

from comum import BENCH, ler_frases, post_json, resumo

SUPERTONIC = "http://127.0.0.1:7788/v1/tts"
PIPER = "http://127.0.0.1:5000/"


def duracao_wav(dados: bytes) -> float:
    with wave.open(io.BytesIO(dados)) as w:
        return w.getnframes() / w.getframerate()


def sintetizar(motor: str, texto: str, passos: int) -> tuple[bytes, float]:
    t = time.perf_counter()
    if motor == "supertonic":
        payload = {
            "text": texto,
            "voice": "F1",
            "lang": "pt",
            "steps": passos,
            "speed": 1.0,
            "response_format": "wav",
        }
        dados = post_json(SUPERTONIC, payload)
    else:
        dados = post_json(PIPER, {"text": texto, "voice": "zh_CN-huayan-medium"})
    return dados, time.perf_counter() - t


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--rotulo", required=True)
    ap.add_argument("--rodadas", type=int, default=3)
    ap.add_argument(
        "--passos", default="8", help="passos do Supertonic, separados por vírgula"
    )
    args = ap.parse_args()

    pasta_audio = BENCH / "resultados" / f"tts-{args.rotulo}"
    pasta_audio.mkdir(parents=True, exist_ok=True)
    variantes = [("piper", "zh", 0)] + [
        ("supertonic", "pt", int(p)) for p in args.passos.split(",")
    ]
    # Aquecimento: a primeira chamada de cada motor pode carregar o modelo.
    sintetizar("piper", "你好", 0)
    sintetizar("supertonic", "Olá", 8)

    medidas = []
    for motor, voz_idioma, passos in variantes:
        origem = "pt" if voz_idioma == "zh" else "zh"
        for rodada in range(1, args.rodadas + 1):
            for f in ler_frases(origem):
                dados, tempo = sintetizar(motor, f["referencia"], passos)
                dur = duracao_wav(dados)
                if rodada == 1:
                    sufixo = f"-{passos}p" if motor == "supertonic" else ""
                    (pasta_audio / f"{f['id']}-{voz_idioma}{sufixo}.wav").write_bytes(
                        dados
                    )
                medidas.append(
                    {
                        "id": f["id"],
                        "motor": motor,
                        "idioma_voz": voz_idioma,
                        "passos": passos or None,
                        "rodada": rodada,
                        "texto": f["referencia"],
                        "tempo": round(tempo, 3),
                        "duracao_audio": round(dur, 3),
                    }
                )
                print(
                    f"[{rodada}] {motor} {passos or ''} {f['id']} {tempo:.2f}s audio={dur:.1f}s"
                )

    res = {}
    for motor, voz_idioma, passos in variantes:
        chave = f"{motor}-{voz_idioma}" + (
            f"-{passos}p" if motor == "supertonic" else ""
        )
        ms = [
            m for m in medidas if m["motor"] == motor and (m["passos"] or 0) == passos
        ]
        res[chave] = {
            "tempo": resumo([m["tempo"] for m in ms]),
            "fator_tempo_real": resumo([m["tempo"] / m["duracao_audio"] for m in ms]),
        }
    print("\n| Voz | Tempo mediana (s) | p95 (s) | Tempo / duração do áudio |")
    print("|---|---|---|---|")
    for k, r in res.items():
        t, f = r["tempo"], r["fator_tempo_real"]
        print(f"| {k} | {t['mediana']:.2f} | {t['p95']:.2f} | {f['mediana']:.2f} |")

    destino = BENCH / "resultados" / f"tts-{args.rotulo}.json"
    saida = {"rotulo": args.rotulo, "resumo": res, "medidas": medidas}
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"\nsalvo em {destino.relative_to(BENCH.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
