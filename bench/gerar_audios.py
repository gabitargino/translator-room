"""Gera os áudios do conjunto de frases com as vozes da própria pilha.

PT: Supertonic (porta 7788), alternando vozes femininas e masculinas.
ZH: Piper (porta 5000), voz zh_CN-huayan-medium.

Saída: bench/audio/<id>.wav, 16 kHz, mono, 16 bits, sem silêncio nas pontas
(o silêncio entre falas é acrescentado por quem envia o áudio).

Uso: python bench/gerar_audios.py [--sobrescrever]
Arquivos já existentes são mantidos, para não apagar gravações reais.
"""

from __future__ import annotations

import argparse
import io
import sys

from comum import (
    AUDIO_DIR,
    aparar_silencio,
    ler_frases,
    ler_wav,
    post_json,
    reamostrar,
    salvar_wav,
)

SUPERTONIC = "http://127.0.0.1:7788/v1/tts"
PIPER = "http://127.0.0.1:5000/"
VOZES_PT = ["F1", "M1", "F2", "M2", "F3", "M3", "F4", "M4", "F5", "M5"]


def sintetizar(idioma: str, texto: str, indice: int) -> bytes:
    if idioma == "pt":
        return post_json(
            SUPERTONIC,
            {
                "text": texto,
                "voice": VOZES_PT[indice % len(VOZES_PT)],
                "lang": "pt",
                "steps": 8,
                "speed": 1.0,
                "response_format": "wav",
            },
        )
    if idioma == "zh":
        return post_json(PIPER, {"text": texto, "voice": "zh_CN-huayan-medium"})
    raise ValueError(f"idioma sem voz configurada: {idioma}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--sobrescrever", action="store_true", help="regera arquivos existentes"
    )
    args = ap.parse_args()

    contagem: dict[str, int] = {}
    for frase in ler_frases():
        idioma = frase["idioma"]
        indice = contagem.get(idioma, 0)
        contagem[idioma] = indice + 1
        destino = AUDIO_DIR / f"{frase['id']}.wav"
        if destino.exists() and not args.sobrescrever:
            print(f"mantido  {destino.name}")
            continue
        wav = sintetizar(idioma, frase["texto"], indice)
        amostras, sr = ler_wav(io.BytesIO(wav))
        amostras = aparar_silencio(reamostrar(amostras, sr))
        salvar_wav(destino, amostras)
        print(
            f"gerado   {destino.name}  {len(amostras) / 16000:.2f} s  (origem {sr} Hz)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
