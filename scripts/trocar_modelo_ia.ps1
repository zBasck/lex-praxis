# Lex-Praxis - Trocar modelo de IA no banco de dados
# Uso: .\scripts\trocar_modelo_ia.ps1
#
# Lista os modelos Ollama instalados e atualiza a config do admin
# para usar o modelo escolhido. Resolve o problema de "IA desabilitada"
# quando o banco tem configurado um modelo que nao existe mais.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "ERRO: .venv nao encontrado. Rode .\start.ps1 primeiro." -ForegroundColor Red
    exit 1
}
& .venv\Scripts\Activate.ps1

Write-Host "==================================================="
Write-Host "  Trocar modelo de IA (Ollama)"
Write-Host "==================================================="

# 1. Lista modelos do Ollama
Write-Host ""
Write-Host "Consultando Ollama em http://localhost:11434..." -ForegroundColor Cyan
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    $modelos = $tags.models | ForEach-Object { $_.name }
} catch {
    Write-Host "ERRO: Ollama nao esta rodando em http://localhost:11434" -ForegroundColor Red
    Write-Host "       Inicie o Ollama: ollama serve" -ForegroundColor Yellow
    exit 1
}

if (-not $modelos) {
    Write-Host "ERRO: Nenhum modelo instalado. Baixe um com:" -ForegroundColor Red
    Write-Host "       ollama pull llama3.1:8b" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Modelos disponiveis:" -ForegroundColor Green
for ($i = 0; $i -lt $modelos.count; $i++) {
    Write-Host "  $($i+1). $($modelos[$i])"
}

# 2. Pergunta qual modelo
$escolha = Read-Host ""
Write-Host "Numero do modelo (1-$($modelos.Count)):" -NoNewline
$escolha = Read-Host
$idx = [int]$escolha - 1
if ($idx -lt 0 -or $idx -ge $modelos.count) {
    Write-Host "Opcao invalida." -ForegroundColor Red
    exit 1
}
$modeloEscolhido = $modelos[$idx]
Write-Host "Modelo escolhido: $modeloEscolhido" -ForegroundColor Green

# 3. Atualiza o banco via Python (SQLAlchemy)
$env:LEXP_MODELO = $modeloEscolhido
$pyScript = @'
import os
from app import create_app
from app.core.extensions import db
from app.core.models import User, UserConfig

app = create_app()
with app.app_context():
    admin = User.query.filter_by(email="admin@lexpraxis.local").first()
    if not admin:
        print("ERRO: usuario admin nao encontrado")
        exit(1)
    cfg = UserConfig.query.filter_by(user_id=admin.id).first()
    if not cfg:
        cfg = UserConfig(user_id=admin.id)
        db.session.add(cfg)
    modelo = os.environ.get("LEXP_MODELO", "")
    cfg.llm_enabled = True
    cfg.llm_provider = "ollama"
    cfg.llm_endpoint = "http://localhost:11434"
    cfg.llm_model = modelo
    db.session.commit()
    print(f"OK: user_id={admin.id} llm_enabled=True llm_model={modelo}")
'@
& python -c $pyScript

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Pronto! Reinicie o servidor e va em /ia no navegador." -ForegroundColor Green
    Write-Host "A IA deve mostrar 'Disponivel' agora." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "ERRO ao atualizar banco." -ForegroundColor Red
    exit 1
}
