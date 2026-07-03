#!/usr/bin/env bash
# Lex-Praxis — script de início (Linux/macOS)
# Uso: bash start.sh
set -e

cd "$(dirname "$0")"

echo "==================================================="
echo "  Lex-Praxis — Gestão processual com IA"
echo "==================================================="
echo

# 1. Verificar Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: python3 não encontrado. Instale Python 3.10+ em https://python.org"
  exit 1
fi

PY=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "→ Python ${PY} detectado"

# 2. Criar/ativar venv
if [ ! -d ".venv" ]; then
  echo "→ Criando ambiente virtual (.venv)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. Instalar dependências
echo "→ Instalando dependências..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 4. Configurar .env
if [ ! -f ".env" ]; then
  echo "→ Criando .env a partir do exemplo..."
  cp .env.example .env
fi

# 5. Popular banco (idempotente — só popula se vazio)
echo "→ Verificando banco de dados..."
python3 -m app.seed

# 6. Subir servidor
PORT="${PORT:-5000}"
echo
echo "==================================================="
echo "  Servidor iniciando em http://localhost:${PORT}"
echo "  Login: admin@lexpraxis.local"
echo "  Senha: 1234"
echo "  (Aperte Ctrl+C para parar)"
echo "==================================================="
echo

# Tenta abrir o navegador (não bloqueia se falhar)
URL="http://localhost:${PORT}/login"
( sleep 1.5 && (xdg-open "$URL" 2>/dev/null || open "$URL" 2>/dev/null || true) ) &

python3 -m app.main
