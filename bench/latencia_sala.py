"""Tabela de latência por direção a partir do log da sala (Etapa 5, 5.4).

Lê logs/room-timing.jsonl (uma linha por fala e uma por aviso de reprodução),
junta cada fala com o aviso ``playback_started`` do celular de quem ouviu e
calcula mediana, p95 e máximo de T0 → T6 (fim da fala → início do áudio
traduzido) por direção, além da mediana de cada etapa intermediária.
As definições das marcas estão em app/rooms/latency.py.

Uso:
    python bench/latencia_sala.py                      # última sala do log
    python bench/latencia_sala.py --sala ABCDE --rotulo 6-sessao-5min
    python bench/latencia_sala.py --todas              # todas as salas
Resultado: bench/resultados/<rotulo>.json e <rotulo>.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RAIZ = BENCH.parent
sys.path.insert(0, str(RAIZ))

from app.rooms.latency import analyze, collect, markdown_table  # noqa: E402


def ler_log(caminho: Path) -> list[dict]:
    registros = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        try:
            registros.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return registros


def ultima_sala(registros: list[dict]) -> str | None:
    for r in reversed(registros):
        if r.get("room"):
            return r["room"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--log", type=Path, default=RAIZ / "logs" / "room-timing.jsonl")
    ap.add_argument("--sala", help="código da sala (padrão: a última do log)")
    ap.add_argument("--todas", action="store_true", help="junta todas as salas")
    ap.add_argument("--rotulo", help="nome do resultado (padrão: 5-latencia-<sala>)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console do Windows (cp1252)

    if not args.log.exists():
        print(f"log não encontrado: {args.log}", file=sys.stderr)
        return 2
    registros = ler_log(args.log)
    sala = None if args.todas else (args.sala or ultima_sala(registros))
    linhas = collect(registros, room=sala)
    if not linhas:
        print(f"nenhuma fala entregue para a sala {sala}", file=sys.stderr)
        return 1
    resultado = analyze(linhas)
    tabela = markdown_table(resultado)

    rotulo = args.rotulo or f"5-latencia-{sala or 'todas'}"
    saida = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "log": str(args.log),
        "sala": sala,
        "definicoes": {
            "T0": "fim da fala estimado no servidor (último bloco com voz antes da pausa)",
            "T5": "link do áudio enviado ao celular de quem ouve",
            "T6": "aviso playback_started do celular: chegada no servidor − RTT/2",
        },
        "resumo": resultado,
        "falas": linhas,
    }
    destino = BENCH / "resultados" / f"{rotulo}.json"
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (BENCH / "resultados" / f"{rotulo}.md").write_text(
        f"# Latência – sala {sala or 'todas'}\n\n{tabela}", encoding="utf-8"
    )
    print(tabela)
    print(f"-> {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
