# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuração do HTTPS na rede local (Etapa 4).

O proxy em si foi testado de verdade (bench/testar_sala.py --ca, notas da
Etapa 4); aqui ficam as garantias que um descuido nos arquivos quebraria sem
aviso: o celular sem microfone, o QR code com http ou um certificado novo a
cada recriação do contêiner.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.https.yml"
CADDYFILE = ROOT / "caddy" / "Caddyfile"
CERT_PAGE = ROOT / "caddy" / "index.html"
ENV_EXAMPLE = ROOT / ".env.example"


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def caddyfile() -> str:
    # Sem comentários, para não casar com o texto explicativo.
    lines = CADDYFILE.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def env_example() -> dict[str, str]:
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_proxy_publishes_https_and_certificate_ports():
    proxy = compose()["services"]["https-proxy"]
    assert proxy["image"].startswith("caddy:2.")
    assert "${ROOM_HTTPS_PORT:-9443}:443" in proxy["ports"]
    assert "${ROOM_CERT_PORT:-9080}:80" in proxy["ports"]
    assert "ROOM_LAN_IP=${ROOM_LAN_IP:-127.0.0.1}" in proxy["environment"]
    assert proxy["networks"] == ["polytalk-network"]


def test_local_authority_survives_container_recreation():
    """Se a raiz mudasse, cada celular teria de instalar o certificado de novo."""
    data = compose()
    assert "caddy_data:/data" in data["services"]["https-proxy"]["volumes"]
    assert "caddy_data" in data["volumes"]


def test_app_trusts_forwarded_proto_for_https_join_link():
    env = compose()["services"]["polytalk"]["environment"]
    assert "FORWARDED_ALLOW_IPS=*" in env


def test_caddy_uses_local_authority_and_proxies_to_app():
    text = caddyfile()
    assert re.search(r"^\s*local_certs\s*$", text, re.M)
    assert re.search(r"^\s*tls internal\s*$", text, re.M)
    assert re.search(r"^\s*reverse_proxy polytalk:8000\s*$", text, re.M)
    # Celular abre por IP e não manda SNI: o certificado da Wi-Fi é o padrão.
    assert re.search(r"^\s*default_sni \{\$ROOM_LAN_IP", text, re.M)
    assert "https://{$ROOM_LAN_IP:127.0.0.1}" in text
    assert "https://localhost" in text
    assert "https://127.0.0.1" not in text


def test_certificate_download_serves_only_the_root():
    text = caddyfile()
    assert "handle /certificado.crt" in text
    assert "root * /data/caddy/pki/authorities/local" in text
    assert "rewrite * /root.crt" in text
    assert "root.key" not in text
    assert "application/x-x509-ca-cert" in text


def test_certificate_page_links_download_and_room():
    html = CERT_PAGE.read_text(encoding="utf-8")
    assert 'href="/certificado.crt"' in html
    assert '/sala"' in html and "https://{{.Host}}" in html
    # Passo a passo para os dois celulares (4.5/4.6), em português e chinês.
    assert "Android" in html and "iPhone" in html
    assert "证书" in html


def test_env_example_enables_https_override():
    values = env_example()
    assert "docker-compose.https.yml" in values["COMPOSE_FILE"].split(";")
    for key in ("ROOM_LAN_IP", "ROOM_HTTPS_PORT", "ROOM_CERT_PORT"):
        assert key in values
    assert values["ROOM_HTTPS_PORT"] == "9443"


def test_text_files_read_by_linux_container_keep_lf():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "caddy/* text eol=lf" in attributes
