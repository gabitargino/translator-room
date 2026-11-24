# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Página da sala para celular (Etapa 3).

- ``GET /sala`` (e ``/room``): telas de criar/entrar, configuração e sala.
  ``?code=K7Q29`` já abre a entrada nessa sala (link do QR code, 3.9).

A página usa o mesmo sistema de textos do PolyTalk (``app/locales``), com as
chaves ``room.*``. A tela original (``/``) continua igual.
"""

import os
from pathlib import Path

import segno
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import get_config
from ..i18n import preferred_locale, public_catalog, t
from .models import normalize_room_code
from ..utils.static_url import static_url

# Fork público, exigido pela AGPL para quem usa o serviço pela rede (3.10).
DEFAULT_SOURCE_URL = "https://github.com/gabitargino/translator-room"
ROOM_PAGE_LOCALES = ("pt", "zh", "en")
ROOM_LANGUAGES = ("pt", "zh", "en", "es", "fr")

router = APIRouter(tags=["rooms-web"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


templates.env.globals["static_url"] = static_url
def source_url() -> str:
    return os.environ.get("ROOM_SOURCE_URL", "").strip() or DEFAULT_SOURCE_URL


def join_url(request: Request, code: str) -> str:
    """Link que o segundo celular abre ao ler o QR code.

    Usa o endereço pelo qual o criador abriu a página (o IP do notebook na
    Wi-Fi). ``ROOM_PUBLIC_BASE_URL`` substitui esse endereço quando o servidor
    está atrás de um proxy ou foi aberto por ``localhost``.
    """
    base = os.environ.get("ROOM_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/sala?code={normalize_room_code(code)}"


def qr_svg(data: str) -> str:
    qr = segno.make(data, error="m")
    return qr.svg_inline(scale=8, border=2, dark="#111827", light="#ffffff")


@router.get("/sala", response_class=HTMLResponse)
@router.get("/room", response_class=HTMLResponse, include_in_schema=False)
async def room_page(request: Request, code: str | None = None) -> HTMLResponse:
    config = get_config()
    ui_locale = preferred_locale(request, config)
    template = templates.get_template("room.html")
    html = template.render(
        request=request,
        ui_locale=ui_locale,
        ui_locales=ROOM_PAGE_LOCALES,
        room_languages=ROOM_LANGUAGES,
        initial_code=normalize_room_code(code)[:12],
        source_url=source_url(),
        i18n_messages=public_catalog(ui_locale, config),
        t=lambda key, **params: t(key, ui_locale, config, **params),
    )
    return HTMLResponse(content=html)
