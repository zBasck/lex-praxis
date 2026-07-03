# Lex-Praxis — script de inicio (PowerShell)
# Uso: .\start.ps1
$ErrorActionPreference = "Stop"
chcp 65001 > $null
Set-Location $PSScriptRoot

Write-Host "==================================================="
Write-Host "  Lex-Praxis - Gestao processual com IA"
Write-Host "==================================================="

# 1. Verificar Python
$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) {
    Write-Host "ERRO: Python nao encontrado. Instale Python 3.10+ em https://python.org" -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}
$pyVer = & python --version 2>&1
Write-Host ">> $pyVer detectado"

# 2. Criar/ativar venv
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host ">> Criando ambiente virtual .venv..."
    & python -m venv .venv
}
& .venv\Scripts\Activate.ps1

# 3. Instalar deps
Write-Host ">> Instalando dependencias (pode demorar 2-5 min na primeira vez)..."
& python -m pip install --quiet --upgrade pip
& python -m pip install --quiet -r requirements.txt

# 4. .env
if (-not (Test-Path ".env")) {
    Write-Host ">> Criando .env a partir de .env.example..."
    Copy-Item .env.example .env -Force
}

# 5. Seed
Write-Host ">> Verificando banco de dados..."
& python -m app.seed

# 6. Subir
$env:PORT = "5000"
Write-Host ""
Write-Host "==================================================="
Write-Host "  Servidor em http://localhost:5000"
Write-Host "  Login: admin@lexpraxis.local"
Write-Host "  Senha: 1234"
Write-Host "  (Ctrl+C para parar)"
Write-Host "==================================================="

# Abrir navegador depois de 2s
Start-Job -ScriptBlock { Start-Sleep -Seconds 2; Start-Process "http://localhost:5000/login" } | Out-Null

& python -m app.main
Read-Host "Pressione Enter para sair"
