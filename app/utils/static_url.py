# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""URL de arquivo estático com versão, para o navegador não usar CSS/JS antigo."""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def static_url(path: str) -> str:
    """Devolve ``/static/<path>?v=<versão>``.

    A versão é a data de modificação do arquivo: muda quando o arquivo muda, e
    assim o navegador baixa a cópia nova em vez de reaproveitar a antiga do cache.
    """
    url = f"/static/{path.lstrip('/')}"
    try:
        version = (STATIC_DIR / path.lstrip("/")).stat().st_mtime_ns
    except OSError:
        return url
    return f"{url}?v={version:x}"
