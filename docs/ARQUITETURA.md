# Arquitetura — Lex Praxis

## Visão geral

Lex Praxis é um monólito Flask organizado em camadas claras, com separação
entre captura de dados, classificação, persistência e apresentação. A escolha
de SQLite por padrão visa simplicidade de deploy, mas toda a camada de dados
é SQLAlchemy 2 e pode apontar para Postgres sem mudança de código.

## Camadas

```
┌──────────────────────────────────────────────────────────────┐
│  web/  — Flask Blueprints (HTML + Auth)                     │
│  api/  — REST versionada em /api/v1                         │
├──────────────────────────────────────────────────────────────┤
│  core/  — Models, extensions, utils                         │
│  intel/ — Classificador (regras + LLM)                      │
│  harvest/ — Adaptadores de tribunais + scheduler            │
│  alerts/ — SMTP, ICS                                        │
└──────────────────────────────────────────────────────────────┘
```

## Fluxo de captura (harvest)

```
APScheduler (a cada N min)
   │
   ▼
HarvestManager.get(tribunal).fetch(cnj)
   │
   ▼
Lista de AndamentoCapturado (data, texto, fonte, url)
   │
   ▼
para cada novo (dedup por hash):
   ├─► Classificador (regras ou LLM) → Classificacao
   ├─► Tabela de prazos (refinamento) → Classificacao
   └─► Persistência
        ├─ Andamento (com classificação e resumo)
        └─ Prazo (se prazo_dias > 0)
   │
   ▼
db.session.commit()
```

## Fluxo de classificação

A função `app.intel.classifier.classify(texto, llm_provider, llm_key, ...)`:

1. Se `LLM_PROVIDER` for `openai` ou `anthropic` **e** houver `LLM_API_KEY`,
   chama a API com prompt estruturado que exige JSON.
2. Se a chamada falhar (rede, autenticação, JSON inválido), cai automaticamente
   para `classify_by_rules`.
3. As regras (em `classifier.py:RULES` e `rules_extra.py:TABELA_PRAZOS`) são
   regex com prioridade e fallback.

A tabela de prazos é curada manualmente para os atos mais comuns do CPC/2015
(contrarrazões, réplica, apelação, embargos, agravo, recurso especial etc.).
Casos fora do catálogo ficam com `prazo_dias=null` e podem ser ajustados
manualmente na UI.

## Fluxo de alertas

1. APScheduler dispara `send_daily_digest()` diariamente às
   `DAILY_DIGEST_HOUR:DAILY_DIGEST_MINUTE`.
2. Para cada usuário com `active=true` e `receive_digest=true`:
   - Busca prazos abertos com `data_limite <= hoje+15d` e `>= hoje-30d`.
   - Renderiza HTML.
   - Envia via SMTP configurado.
3. Se SMTP não estiver configurado, apenas loga.

## Multi-tenancy (futuro)

Hoje o sistema é single-tenant. Para virar multi:
- Adicionar `tenant_id` em todas as tabelas.
- Carregar `tenant_id` do `current_user` em cada query.
- Usar `SQLAlchemy event listeners` para injeção automática.

## Escalabilidade

| Cenário | Recomendação |
|---------|--------------|
| 1 escritório, < 5k processos | SQLite, 1 processo Flask |
| 5–20 escritórios, < 50k processos | PostgreSQL, 2–4 workers gunicorn |
| 50+ escritórios | Separar harvest (worker dedicado) do web; fila (Celery/RQ) |

## Segurança

- Senhas: `werkzeug.security` (PBKDF2-SHA256).
- CSRF: Flask-WTF instalado (templates podem ser protegidos com `{{ form.csrf_token }}`).
- Cookies: Secure, HttpOnly, SameSite.
- Banco: nunca expor SQLAlchemy em erros 500.
- Adapter de scraping: `User-Agent` identificável e respeitoso; em produção,
  adicionar `time.sleep(0.5)` entre requests.

## Roadmap técnico

- [ ] Migração para Alembic (hoje usa `db.create_all()`)
- [ ] WebSocket para notificações em tempo real (Flask-SocketIO)
- [ ] Fila RQ/Celery para harvest distribuído
- [ ] API GraphQL opcional
- [ ] Auditoria com hash chain (tamper-evident)
