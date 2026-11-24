# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later
<#
.SYNOPSIS
    translator-room: abre a sala por um túnel da Cloudflare, sem certificado
    para instalar nos celulares.

.DESCRIPTION
    Sobe um "Quick Tunnel" (cloudflared, sem conta) até o app em
    http://127.0.0.1:9000 e mostra o endereço https://....trycloudflare.com.
    O certificado é público e válido, então o celular abre a página e libera o
    microfone sem aviso. O QR code da sala já sai com o endereço do túnel.

    Cuidados:
    - O endereço muda toda vez que o túnel sobe e fica público enquanto o
      script estiver rodando (qualquer um com o link entra). Ctrl+C encerra.
    - O áudio passa pela internet (notebook -> Cloudflare -> celular), o que
      soma latência; a medição oficial continua sendo a da rede local (Caddy).
    - Precisa do cloudflared:  winget install --id Cloudflare.cloudflared

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\tunel-cloudflare.ps1
#>
[CmdletBinding()]
param(
    [string]$AppUrl = 'http://127.0.0.1:9000'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    throw 'cloudflared não encontrado. Instale com: winget install --id Cloudflare.cloudflared'
}

try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "$AppUrl/api/health" | Out-Null
} catch {
    throw "O app não respondeu em $AppUrl. Suba a pilha antes: docker compose up -d"
}

Write-Host 'Abrindo o túnel (leva alguns segundos)...'
$shown = $false
# O cloudflared escreve o log no stderr; 2>&1 junta tudo e vira texto aqui.
$ErrorActionPreference = 'Continue'
& cloudflared tunnel --no-autoupdate --url $AppUrl 2>&1 | ForEach-Object {
    $line = "$_"
    if (-not $shown -and $line -match '(https://[a-z0-9-]+\.trycloudflare\.com)') {
        $shown = $true
        $url = $Matches[1]
        Write-Host ''
        Write-Host '  Sala pelo túnel (abra no celular, qualquer rede):' -ForegroundColor Green
        Write-Host "  $url/sala" -ForegroundColor Green
        Write-Host ''
        Write-Host '  O endereço muda a cada execução. Ctrl+C fecha o túnel.'
        Write-Host ''
    } elseif ($line -match ' ERR ') {
        Write-Host $line -ForegroundColor Yellow
    }
}
