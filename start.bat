@echo off
REM Lex-Praxis — script de inicio (Windows)
REM Uso: start.bat
chcp 65001 >nul
cd /d "%~dp0"

echo ===================================================
echo   Lex-Praxis - Gestao processual com IA
echo ===================================================
echo.

REM 1. Verificar Python
where python >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python nao encontrado. Instale Python 3.10+ em https://python.org
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo ^>^> Python %%v detectado

REM 2. Criar/ativar venv
if not exist ".venv\Scripts\activate.bat" (
  echo ^>^> Criando ambiente virtual...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

REM 3. Instalar deps
echo ^>^> Instalando dependencias...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

REM 4. .env
if not exist ".env" (
  echo ^>^> Criando .env a partir de .env.example...
  copy /Y .env.example .env >nul
  echo ^>^> Configure DATAJUD_CERT_MODE (a1 ou a3) e demais vars se precisar.
)

REM 5. Seed
echo ^>^> Verificando banco de dados...
python -m app.seed

REM 6. Subir
set PORT=5000
echo.
echo ===================================================
echo   Servidor em http://localhost:%PORT%
echo   Login: admin@lexpraxis.local
echo   Senha: 1234
echo   (Ctrl+C para parar)
echo ===================================================
echo.

REM Abrir navegador
start "" timeout /t 2 /nobreak >nul 2>&1
start "" http://localhost:%PORT%/login

python -m app.main
pause
