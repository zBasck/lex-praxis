# Guia de uso — Lex Praxis

## 1. Primeiro acesso

1. Acesse `http://localhost:5000`
2. Login: `admin@lexpraxis.local` / `1234`
3. Em **Configurações**, edite o `.env` e reinicie para alterar SMTP, LLM, intervalo de harvest etc.

## 2. Cadastrando um cliente

**Clientes → Novo cliente**

Preencha nome e documento. Tipo (`PF`/`PJ`) detecta automaticamente o tamanho. Os
clientes ficam vinculados aos processos; toda a movimentação processual e prazos
são organizados por cliente.

## 3. Cadastrando um processo

**Processos → Novo processo**

- **Número CNJ**: 20 dígitos. Cole o número completo e o sistema normaliza
  automaticamente.
- **Tribunal**: detectado pelo dígito do CNJ (segmento 13-14). Se não detectar,
  escolha manualmente.
- O sistema começa a buscar andamentos a cada `HARVEST_INTERVAL_MINUTES`.

Para forçar uma busca imediata, abra o processo e clique em **Atualizar**.

## 4. Acompanhando andamentos

**Processo → aba Andamentos**

Cada andamento é classificado automaticamente em:
- `tipo_ato` (intimação, sentença, despacho, acórdão, etc.)
- `prazo_dias` (se houver)
- `tarefa_sugerida` (o que o advogado deve fazer)
- `resumo_cliente` (explicação em linguagem simples)

## 5. Prazos

**Prazos** (menu superior)

- Filtros por status (aberto/concluído/cancelado) e horizonte (7/15/30 dias)
- Vencidos aparecem em vermelho
- Críticos (≤ 3 dias) em amarelo
- Concluir / cancelar com um clique
- **Exportar .ics** para assinar a agenda no Google Calendar / Outlook / Apple

**Agenda** (menu superior)

Visão mensal com todos os prazos abertos. Clique no dia para abrir o processo
relacionado. Setas para navegar meses.

## 6. Alertas por e-mail

Configure o SMTP no `.env`:

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seuemail@gmail.com
SMTP_PASSWORD=sua-senha-de-app
SMTP_FROM="Lex Praxis <seuemail@gmail.com>"
SMTP_USE_TLS=true
```

O digest diário é enviado às `DAILY_DIGEST_HOUR:DAILY_DIGEST_MINUTE` (default 07:00)
para todos os usuários com `receive_digest=true`. Para desligar por usuário,
edite o banco ou implemente uma tela de preferências (próximo release).

## 7. Classificação com IA externa

```ini
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

Ou com Claude:

```ini
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-3-5-haiku-20241022
```

Teste via API:

```bash
curl -X POST http://localhost:5000/api/v1/classificar \
     -H "Content-Type: application/json" \
     -d '{"texto":"Intimem-se as partes para apresentar contrarrazões no prazo de 15 dias."}'
```

## 8. Configurações avançadas

### Banco PostgreSQL

```ini
DATABASE_URL=postgresql+psycopg2://user:pass@localhost/lex_praxis
pip install psycopg2-binary
```

### Adicionar novo tribunal

Veja `README.md` → seção “Adicionando um novo tribunal”.

### Deploy em produção

```bash
# Servidor web
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app

# Worker de harvest (1 processo, agendador exclusivo)
LEX_SCHEDULER=1 gunicorn -w 1 --preload -b 0.0.0.0:5001 wsgi:app
```

Aponte um nginx na frente com SSL (Let’s Encrypt).

## 9. Comandos úteis

```bash
# Rodar seed novamente (apaga e recria)
python -m app.seed --force

# Acessar via shell
python -c "
from app import create_app
from app.core.models import *
app = create_app()
with app.app_context():
    print('Processos:', Processo.query.count())
    print('Prazos abertos:', Prazo.query.filter_by(status='aberto').count())
"

# Backup do SQLite
cp instance/lex_praxis.db backup-$(date +%F).db
```

## 10. Dúvidas comuns

**O robô está coletando andamentos reais?**
Por padrão, o `TJSPAdapter` tem a estrutura de scraping mas cai para o
`OfflineAdapter` se o portal mudar de layout. Para o sistema ser 100%
operacional, finalize os seletores dos tribunais que você atua. O
`OfflineAdapter` existe justamente para você não perder prazos enquanto ajusta.

**Posso usar sem LLM?**
Sim. O classificador por regras cobre os andamentos mais comuns (intimações,
despachos, sentenças, acórdãos, audiências, embargos, penhoras, etc.) e cria
prazos automaticamente. A LLM é incremental.

**Quantos andamentos o sistema aguenta?**
SQLite: até ~100k andamentos. Para mais, use PostgreSQL. Não há limite de
processos ou clientes além do FS.

**Como limpo tudo?**
```bash
rm instance/lex_praxis.db
python -m app.seed
```

**Como importo processos de outro sistema?**
A API `POST /api/v1/processos` aceita JSON. Use um script Python que lê o CSV
do CPJ, por exemplo, e faz um POST para cada processo.
