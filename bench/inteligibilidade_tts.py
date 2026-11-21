"""Estima a inteligibilidade da voz em PT do Supertonic para cada número de passos.

Transcreve com o STT os áudios gerados por medir_tts.py (bench/resultados/
tts-1.6/) e calcula o WER contra o texto sintetizado. Não mede naturalidade, só
se o Whisper entende; a naturalidade precisa ser ouvida por uma pessoa.

Uso: python bench/medir_tts.py --rotulo 1.6 --passos 8,4,2
     python bench/inteligibilidade_tts.py
"""

import asyncio
import json
import struct

from comum import BENCH, ler_frases, ler_wav, reamostrar, aparar_silencio
from medir_stt import transcrever, taxa_erro

URL = "ws://127.0.0.1:8000/v1/stream/transcriptions"


async def main():
    pasta = BENCH / "resultados" / "tts-1.6"
    res = {}
    for passos in (8, 4, 2):
        erros = []
        for f in ler_frases("zh"):
            x, sr = ler_wav(pasta / f"{f['id']}-pt-{passos}p.wav")
            pcm16 = aparar_silencio(reamostrar(x, sr))
            r = await transcrever(
                URL, struct.pack(f"<{len(pcm16)}h", *pcm16), "pt", "fixo", 1.5
            )
            e = taxa_erro(f["referencia"], r["texto"], "pt")
            erros.append(e)
            if e > 0:
                print(
                    f"  {passos}p {f['id']} {e:.0%} {r['texto']!r} | ref {f['referencia']!r}"
                )
        res[passos] = (sum(erros) / len(erros), sum(1 for e in erros if e == 0))
        print(
            f"{passos} passos: WER médio {res[passos][0]:.1%}, exatas {res[passos][1]}/10"
        )
    (BENCH / "resultados" / "tts-1.6-inteligibilidade.json").write_text(
        json.dumps(
            {
                str(k): {"wer_medio": round(v[0], 3), "exatas": v[1]}
                for k, v in res.items()
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


asyncio.run(main())
