# Lex Praxis

**Sistema próprio de acompanhamento processual, gestão de prazos e classificação
inteligente de andamentos — pensado para escritórios de advocacia que querem
substituir (ou complementar) CPJ/SAJ/Escritawer/Projudi, com controle total
dos dados e custo mínimo.**

> “Em vez de um ChatGPT jurídico, um CPJ/SAJ com esteroides de IA.”

---

## ✨ O que o sistema faz

| Módulo | Função |
|--------|--------|
| **Cadastro** | Clientes, processos (CNJ detectado automaticamente), andamentos, prazos, usuários com permissão |
| **Monitoramento** | Robô periódico busca andamentos em portais de tribunais (TJSP, TJs, TRFs, STJ, STF) |
| **Classificação** | Cada andamento é classificado em *tipo de ato*, *prazo*, *tarefa sugerida* e *resumo para o cliente* — por regras (offline) ou LLM (OpenAI/Anthropic) |
| **Prazos** | Cálculo em dias úteis, prioridade automática, conclusão/cancelamento, vencidos destacados |
| **Agenda** | Calendário mensal visual + exportação `.ics` (Google Calendar, Apple, Outlook) |
| **Alertas** | Digest diário por e-mail (SMTP) e feed iCalendar |
| **Relatórios** | Painel com KPIs: prazos abertos, vencidos, próximos, andamentos do mês, etc. |
| **Multi-usuário** | Login, papéis (admin/advogado/assistente), digest por usuário |
| **Auditoria** | Log de ações, IP, timestamp |

---

## 🏗️ Arquitetura

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Frontend   │    │  Flask (API+UI)  │    │  Banco       │
│  Bootstrap  │◀──▶│  /api/v1 + /     │◀──▶│  SQLite/PG   │
│  Vanilla JS │    │  Blueprints      │    └──────────────┘
└─────────────┘    └────────┬─────────┘
                            │
        ┌───────────────────┼─────────────────────┐
        ▼                   ▼                     ▼
   ┌─────────┐         ┌──────────┐         ┌──────────┐
   │Harvest  │         │ Classifier│         │ Alerts   │
   │Adapters │         │  Regras+  │         │ SMTP/ICS │
   │ TJ/TRF  │         │  LLM      │         └──────────┘
   └─────────┘         └──────────┘
```

### Stack

- **Backend**: Python 3.10+ · Flask 3 · SQLAlchemy 2 · APScheduler
- **Frontend**: Bootstrap 5 (CDN) · JavaScript vanilla · sem build
- **Banco**: SQLite (default) ou PostgreSQL (mude `DATABASE_URL`)
- **IA**: motor de regras (sempre ativo) + adaptadores OpenAI/Anthropic (opcional)
- **Scraping**: `requests` + `BeautifulSoup` por tribunal, com fallback offline

---

## 🚀 Quickstart

```bash
# 1) Instalar dependências
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) Configurar
cp .env.example .env
# (edite SECRET_KEY, SMTP, LLM_API_KEY etc. — tudo é opcional)

# 3) Inicializar banco + popular com dados de demonstração
python -m app.seed

# 4) Rodar
python -m app.main
# ou:
FLASK_APP=app.main flask run --port 5000
```

Abra http://localhost:5000 e entre com:

| E-mail | Senha | Papel |
|--------|-------|-------|
| `admin@lexpraxis.local` | `1234` | admin |
| `advogado@lexpraxis.local` | `demo123` | advogado (criado pelo seed) |

> **Troque essas senhas em produção!**

---

## ⚙️ Configuração (.env)

| Variável | Padrão | O que faz |
|----------|--------|-----------|
| `SECRET_KEY` | `dev-secret-change-me` | Chave de sessão. **Troque em produção.** |
| `DATABASE_URL` | `sqlite:///lex_praxis.db` | URI SQLAlchemy. `postgresql://user:pw@host/db` para Postgres. |
| `HARVEST_INTERVAL_MINUTES` | `120` | A cada quantos minutos o robô busca andamentos |
| `HARVEST_RUN_ON_START` | `false` | Se `true`, roda o harvest assim que o servidor sobe |
| `LLM_PROVIDER` | `local` | `openai` ou `anthropic` habilita o classificador LLM |
| `LLM_API_KEY` | — | Chave da API |
| `LLM_MODEL` | `gpt-4o-mini` | Modelo (OpenAI ou Anthropic) |
| `SMTP_HOST` etc. | — | Para envio de e-mails; sem SMTP, apenas loga os envios |
| `DAILY_DIGEST_HOUR` / `_MINUTE` | `7` / `0` | Horário do e-mail diário de prazos |
| `ENABLE_TJSP`, `ENABLE_TRF1`… | `true` | Liga/desliga adaptadores por tribunal |

---

## 🧠 Classificador de andamentos

Todo andamento capturado passa por um classificador em duas camadas:

1. **Regras (offline, sem custo)**: ~20 padrões de expressões regulares que cobrem
   intimações, despachos, sentenças, acórdãos, audiências, embargos etc. Tabela
   de referência em `app/intel/classifier.py` (RULES) e `app/intel/rules_extra.py`
   (TABELA_PRAZOS).

2. **LLM (opcional)**: se `LLM_PROVIDER` for `openai` ou `anthropic` e houver
   `LLM_API_KEY`, o classificador usa o LLM com prompt estruturado que **retorna
   JSON**. Cai automaticamente para regras se a chamada falhar.

Saída sempre inclui:
- `tipo_ato` (slug canônico: `intimacao_contrarrazoes`, `sentenca`, …)
- `prazo_dias` (inteiro ou `null`)
- `prazo_marco` (`publicacao` | `intimacao` | `citacao` | `juntada`)
- `tarefa_sugerida` (“Elaborar e protocolar contrarrazões”)
- `resumo_cliente` (explicação em 1 linha)
- `confianca` e `origem` (`regras` | `llm`)

Endpoint de teste: `POST /api/v1/classificar {"texto": "..."}`

---

## 🔌 Adaptadores de tribunais

Cada tribunal implementa a interface `CourtAdapter` em
`app/harvest/base.py`:

```python
class CourtAdapter(abc.ABC):
    tribunal: str
    def fetch(self, numero_cnj: str) -> list[AndamentoCapturado]: ...
```

Já incluídos:

| Tribunal | Status |
|----------|--------|
| **TJSP** | Estrutura completa (e-SAJ + PJe) com parsing de HTML — implementar `_fetch_*` para o seu uso real |
| TJMS, TJRS, TRF1..5, STJ, STF | Stubs com fallback para o `OfflineAdapter` |
| **OfflineAdapter** | Gera andamentos determinísticos para teste/demo |

Quando o scraping real falha, o sistema usa o OfflineAdapter
automaticamente — **o scheduler nunca derruba por causa de um portal fora do ar**.

### Adicionando um novo tribunal

1. Crie `app/harvest/courts/tjse.py`:

```python
from ..base import CourtAdapter, AndamentoCapturado
from ..offline import OfflineAdapter

class TJSEAdapter(CourtAdapter):
    tribunal = "TJSE"
    def __init__(self, **kw):
        super().__init__(**kw)
        self.session = ...
        self._fallback = OfflineAdapter(seed=hash("TJSE") & 0xFFFF, **kw)
    def fetch(self, cnj):
        try:
            # sua lógica aqui
            ...
        except Exception:
            return self._fallback.fetch(cnj)
```

2. Registre em `app/harvest/manager.py` (`_REGISTRY`) e em `app/config.py`
   (`COURT_FLAGS`).

---

## 📡 API REST (resumo)

Todos os endpoints exigem login (cookie de sessão), exceto `/login` e `/api/v1/health`.

| Método | Endpoint | Função |
|--------|----------|--------|
| GET | `/api/v1/health` | Healthcheck |
| GET | `/api/v1/dashboard` | KPIs + últimos andamentos + próximos prazos |
| GET / POST | `/api/v1/clientes` | Listar / criar clientes |
| GET / POST | `/api/v1/processos` | Listar / criar processos |
| GET | `/api/v1/processos/<id>` | Detalhe com andamentos e prazos |
| POST | `/api/v1/processos/<id>/harvest` | Forçar captura agora |
| POST | `/api/v1/harvest/all` | Capturar todos os processos ativos |
| GET / POST | `/api/v1/andamentos` | Listar / registrar andamento manual |
| GET | `/api/v1/prazos` | Listar prazos (filtros: status, horizon) |
| POST | `/api/v1/prazos/<id>/concluir` | Marcar como concluído |
| POST | `/api/v1/prazos/<id>/cancelar` | Cancelar |
| POST | `/api/v1/classificar` | Classificar texto avulso |
| GET | `/api/v1/ics` | Feed iCalendar de prazos |
| GET | `/cal.ics` | Mesma coisa, autenticado pela web |

---

## ⏰ Scheduler

Configurado em `app/harvest/scheduler.py`:

- A cada `HARVEST_INTERVAL_MINUTES`: `harvest_all_active()`
- Diariamente às `DAILY_DIGEST_HOUR:DAILY_DIGEST_MINUTE`: `send_daily_digest()`

Para desligar em dev: `LEX_SCHEDULER=0 python -m app.main`.

Para deploy com workers separados (recomendado em produção), use:

```bash
# Web
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app

# Worker de harvest (1 processo, agendador exclusivo)
LEX_SCHEDULER=1 gunicorn -w 1 --preload -b 0.0.0.0:5001 wsgi:app
```

---

## 💰 Custos reais (estimativa escritório pequeno)

| Item | Custo/mês |
|------|-----------|
| VPS Linux 2 vCPU 2 GB (Hetzner/DigitalOcean) | US$ 5–10 |
| Domínio + SSL (Let’s Encrypt) | ~US$ 1 |
| LLM (OpenAI `gpt-4o-mini` ou Anthropic `haiku`) — opcional, ~R$ 0,01/andamento | R$ 5–30 |
| SMTP (Gmail/Workplace) | US$ 0–6 |
| **Total** | **< US$ 20/mês** |

Sem o LLM externo, o classificador por regras já cobre 80–90% dos casos comuns.
Você pode migrar para LLM quando o volume justificar.

---

## 🗺️ Roadmap

- [ ] Webhooks para Diários Oficiais (DOU, DJE)
- [ ] Integração WhatsApp / Telegram
- [ ] Captura de publicações por OAB
- [ ] Multi-tenancy (vários escritórios num mesmo banco)
- [ ] App mobile (PWA já é viável)
- [ ] Classificação de peças (petições iniciais, recursos)
- [ ] OCR de PDFs anexados a andamentos
- [ ] Exportação para PJe / PROJUDI (protocolo integrado)

---

## 🧪 Testes rápidos

```bash
# Criar venv e instalar
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Rodar seed
python -m app.seed

# Bateria de fumaça
PYTHONPATH=. DATABASE_URL=sqlite:////tmp/lp.db python -c "
from app import create_app
app = create_app()
c = app.test_client()
c.post('/login', data={'email':'admin@lexpraxis.local','password':'1234'})
print(c.get('/api/v1/dashboard').get_json()['kpi'])
"
```

---

## 📜 Licença

MIT — use, modifique, distribua, comercialize. Mantenha os créditos.

---

## 🤝 Créditos

Conceito e código: você + Lex Praxis.
Stack: Flask, SQLAlchemy, APScheduler, BeautifulSoup, Bootstrap, OpenAI/Anthropic (opcional).
