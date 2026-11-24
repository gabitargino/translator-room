# SPDX-FileCopyrightText: 2026 Allan Gabriel, Gabriele Targino
# SPDX-License-Identifier: AGPL-3.0-or-later
<#
.SYNOPSIS
    translator-room (Etapa 4): prepara o notebook para os celulares da Wi-Fi.

.DESCRIPTION
    1. Descobre o IP do notebook na rede local (ou usa -Ip).
    2. Atualiza o .env: ROOM_LAN_IP, ROOM_PUBLIC_BASE_URL, ALLOWED_ORIGINS e
       inclui docker-compose.https.yml em COMPOSE_FILE.
    3. Com -Firewall (PowerShell como administrador): libera as portas HTTPS e
       do certificado no Firewall do Windows, só para a sub-rede local.
    4. Mostra os endereços para abrir no celular.

    Depois de rodar: docker compose up -d   (recria o proxy e o app com o novo IP)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\rede-local.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\rede-local.ps1 -Firewall
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\rede-local.ps1 -Ip 192.168.43.20
#>
[CmdletBinding()]
param(
    [string]$Ip,
    [int]$HttpsPort = 9443,
    [int]$CertPort = 9080,
    [switch]$Firewall,
    [string]$EnvFile
)

$ErrorActionPreference = 'Stop'
# No PowerShell 5.1, $PSScriptRoot ainda está vazio nos valores padrão do param().
if (-not $EnvFile) { $EnvFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env' }

function Find-LanIp {
    # Interface com gateway padrão, ignorando VPNs e adaptadores virtuais
    # (Tailscale, WSL/Hyper-V "vEthernet", Docker, VirtualBox).
    $skip = 'Tailscale|vEthernet|Docker|VirtualBox|VMware|Loopback|WSL|ZeroTier'
    $configs = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' -and $_.InterfaceAlias -notmatch $skip }
    # Prefere a Wi-Fi: é a rede em que os celulares estão.
    $wifi = $configs | Where-Object { $_.InterfaceAlias -match 'Wi-?Fi|WLAN|Wireless' } | Select-Object -First 1
    $chosen = if ($wifi) { $wifi } else { $configs | Select-Object -First 1 }
    if (-not $chosen) { return $null }
    return [pscustomobject]@{
        Ip        = ($chosen.IPv4Address | Select-Object -First 1).IPAddress
        Interface = $chosen.InterfaceAlias
        Category  = (Get-NetConnectionProfile -InterfaceAlias $chosen.InterfaceAlias -ErrorAction SilentlyContinue).NetworkCategory
    }
}

function Set-EnvValue([string[]]$lines, [string]$key, [string]$value) {
    $pattern = "^\s*#?\s*$([regex]::Escape($key))="
    $active = "^\s*$([regex]::Escape($key))="
    $idx = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match $active) { $idx = $i } }
    if ($idx -lt 0) {
        for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match $pattern) { $idx = $i } }
    }
    if ($idx -ge 0) { $lines[$idx] = "$key=$value"; return , $lines }
    return , ($lines + "$key=$value")
}

function Get-EnvValue([string[]]$lines, [string]$key) {
    $line = $lines | Where-Object { $_ -match "^\s*$([regex]::Escape($key))=" } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim() }
    return ''
}

# 1. IP -------------------------------------------------------------------
$category = $null
if (-not $Ip) {
    $found = Find-LanIp
    if (-not $found) { throw 'Nenhuma rede com gateway encontrada. Conecte-se à Wi-Fi ou passe -Ip.' }
    $Ip = $found.Ip
    $category = $found.Category
    Write-Host "Rede: $($found.Interface)  IP: $Ip  Perfil: $category"
} else {
    Write-Host "IP informado: $Ip"
}

# 2. .env -----------------------------------------------------------------
if (-not (Test-Path $EnvFile)) { throw "Arquivo $EnvFile não existe. Copie .env.example para .env primeiro." }
$utf8 = New-Object System.Text.UTF8Encoding($false)
$lines = [System.IO.File]::ReadAllLines($EnvFile, $utf8)

$httpsBase = "https://${Ip}:$HttpsPort"
$lines = Set-EnvValue $lines 'ROOM_LAN_IP' $Ip
$lines = Set-EnvValue $lines 'ROOM_HTTPS_PORT' "$HttpsPort"
$lines = Set-EnvValue $lines 'ROOM_CERT_PORT' "$CertPort"
$lines = Set-EnvValue $lines 'ROOM_PUBLIC_BASE_URL' $httpsBase

# Origens: mantém as que não são HTTPS da porta do proxy (ex.: localhost:9000)
# e troca as HTTPS antigas (IP de outra rede) pelas atuais.
$origins = (Get-EnvValue $lines 'ALLOWED_ORIGINS') -split ',' |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and $_ -notmatch "^https://.*:$HttpsPort$" }
$origins = @($origins) + @($httpsBase, "https://localhost:$HttpsPort")
$lines = Set-EnvValue $lines 'ALLOWED_ORIGINS' (($origins | Select-Object -Unique) -join ',')

$compose = Get-EnvValue $lines 'COMPOSE_FILE'
if (-not $compose) { $compose = 'docker-compose.yml' }
if ($compose -notmatch 'docker-compose\.https\.yml') {
    $sep = if ((Get-EnvValue $lines 'COMPOSE_PATH_SEPARATOR')) { Get-EnvValue $lines 'COMPOSE_PATH_SEPARATOR' } else { ';' }
    $lines = Set-EnvValue $lines 'COMPOSE_PATH_SEPARATOR' $sep
    $lines = Set-EnvValue $lines 'COMPOSE_FILE' "$compose${sep}docker-compose.https.yml"
}
[System.IO.File]::WriteAllLines($EnvFile, $lines, $utf8)
Write-Host ".env atualizado ($EnvFile)"

# 3. Firewall --------------------------------------------------------------
$ruleName = 'translator-room HTTPS (Etapa 4)'
if ($Firewall) {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { throw 'Para -Firewall, abra o PowerShell como administrador.' }
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    # Perfis Privado e Público: redes de celular/universidade costumam ser
    # "Públicas" no Windows. LocalSubnet limita a quem está na mesma rede.
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $HttpsPort, $CertPort -RemoteAddress LocalSubnet -Profile Private, Public | Out-Null
    Write-Host "Firewall: portas $HttpsPort e $CertPort liberadas para a sub-rede local."
} elseif (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    Write-Host "Firewall: regra '$ruleName' não existe. Se o celular não alcançar o notebook, rode de novo com -Firewall (como administrador)."
}

# 4. Endereços ---------------------------------------------------------------
Write-Host ''
Write-Host 'Agora: docker compose up -d'
Write-Host ''
Write-Host "No celular (mesma Wi-Fi):"
Write-Host "  1. Certificado (uma vez):  http://${Ip}:$CertPort"
Write-Host "  2. Sala:                   $httpsBase/sala"
Write-Host "No notebook:                 https://localhost:$HttpsPort/sala"
