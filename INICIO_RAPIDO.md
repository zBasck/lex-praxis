# ⚡ Início Rápido — Lex-Praxis

## 1. Extraia o ZIP
```bash
unzip lex-praxis.zip
cd lex-praxis
```

## 2. Rode o script de início (recomendado)
O script faz tudo: cria venv, instala deps, popula banco e sobe o servidor.

**Linux/macOS:**
```bash
bash start.sh
```

**Windows:**
```cmd
start.bat
```

O navegador abre sozinho em `http://localhost:5000/login`.

**Credenciais:**
- Email: `admin@lexpraxis.local`
- Senha: `1234`

---

## Se preferir fazer manualmente

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed          # popula banco de demo
python -m app.main          # inicia servidor
```

Acesse `http://localhost:5000` (ou `/login`).

---

## ⚠️ Troubleshooting

### "Nada funcionou" / Servidor não responde

**Causa 1 — esqueceu de ativar o venv:**
```bash
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate.bat  # Windows
```

**Causa 2 — fechou o terminal achando que travou:**
O comando `python -m app.main` é bloqueante (fica rodando no terminal). É o comportamento normal do Flask. Para parar, use `Ctrl+C`.

Para rodar em background e liberar o terminal:
```bash
# Linux/macOS
nohup python -m app.main > lex-praxis.log 2>&1 &
tail -f lex-praxis.log  # ver logs

# Windows (PowerShell)
Start-Process python -ArgumentList "-m","app.main" -NoNewWindow
```

**Causa 3 — porta 5000 ocupada (macOS Monterey+):**
O AirPlay Receiver usa a porta 5000. Desative em:
`Ajustes do Sistema → Geral → AirDrop e Handoff → Receptor AirPlay (desativar)`
ou rode em outra porta: `PORT=5001 python -m app.main`

**Causa 4 — erro de permissão no venv (Linux):**
```bash
sudo apt install python3-venv   # Debian/Ubuntu
```

### "ModuleNotFoundError: No module named 'flask'"
Você não ativou o venv antes de rodar o `pip install`. Ative:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### "/dashboard dá 404"
Use `/` (a home) ou `/login` para começar. `/dashboard` também funciona nesta versão.

### "Quero resetar o banco"
```bash
rm instance/lex_praxis.db
python -m app.seed
```

### "Não quero dados de demonstração"
Não rode `python -m app.seed`. O sistema funciona vazio; você cadastra processos manualmente.

### "Como ativo o LLM externo?"
Edite `.env` e descomente:
```ini
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```
Depois reinicie o servidor. Sem isso, o classificador de andamentos usa regras locais (cobre 80-90% dos casos comuns).

### "Como ativo o e-mail para alertas digest?"
Edite `.env` e preencha os campos `SMTP_*`. Reinicie o servidor. Se não preencher, o digest fica desativado.

### "DJe não trouxe nada"
- O PJe Comunica (comunica.pje.jus.br) é a fonte principal. Funciona para processos que tramitam em tribunais com PJe (STF, STJ, TRFs, TRTs, e vários TJs).
- Alguns TJs usam DJe próprio (TJSP, TJRJ etc.). Para esses, ative o scraping direto via `.env` e personalize a engine.
- A coleta roda a cada 2h; para forçar: `curl -X POST http://localhost:5000/api/v1/dje/coletar`.

---

## Estrutura do projeto

```
lex-praxis/
├── app/
│   ├── main.py             ← entry point
│   ├── web/                ← páginas HTML
│   ├── api/                ← API REST
│   ├── core/               ← modelos, extensões
│   ├── harvest/            ← scraping dos tribunais + DJe
│   ├── intel/              ← classificador de andamentos (regras + LLM)
│   ├── alerts/             ← digest por e-mail + ICS
│   └── seed.py             ← dados de demonstração
├── instance/               ← banco SQLite
├── docs/                   ← documentação técnica
├── start.sh / start.bat    ← scripts de início
├── requirements.txt
├── .env.example
└── README.md
```

---

## Onde buscar ajuda

- **Documentação completa:** `docs/USO.md` e `docs/ARQUITETURA.md`
- **README:** visão geral, custos, próximos passos
- **Logs:** `lex-praxis.log` (se você rodou com `nohup`)
- **API:** `http://localhost:5000/api/v1/health` deve retornar `{"ok": true}`
