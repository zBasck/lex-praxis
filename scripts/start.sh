#!/usr/bin/env bash
# Lex Praxis — script de inicialização
set -e

if [ ! -d ".venv" ]; then
  echo "→ Criando venv..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "→ Instalando/atualizando dependências..."
pip install -q -U pip
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "→ Criando .env a partir do exemplo..."
  cp .env.example .env
fi

if [ ! -f "instance/lex_praxis.db" ] && [ ! -f "/tmp/lp-data/lex_praxis.db" ]; then
  echo "→ Inicializando banco e dados de demonstração..."
  python -m app.seed
fi

echo "→ Iniciando Lex Praxis em http://localhost:5000"
exec python -m app.main
