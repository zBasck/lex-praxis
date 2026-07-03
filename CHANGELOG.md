# Changelog Lex-Praxis

## v2.0.0 (2026-07-03) - Release com IA local + Multi-usuario

### NOVOS RECURSOS
- **Busca nacional de OAB**: o monitor agora busca publicacoes da OAB em **todos os tribunais PJe do Brasil** (sem filtro de `siglaTribunal` por default).
- **Motor de IA local** (`app/intel/llm_local.py`): suporte a Ollama, LM Studio, llama.cpp, qualquer endpoint OpenAI-compat. Funcoes: resumir publicacao, classificar ato, sugerir tarefa. **100% gratuito, offline**.
- **Pagina de IA** (`/ia`): testa conexao, lista modelos disponiveis, e tem area de teste com 3 ferramentas.
- **Configuracoes do usuario** (`/configuracoes`): preferencias pessoais (tema, OAB padrao, intervalo, digest), IA local (provider, endpoint, modelo, API key), notificacoes (email, WhatsApp).
- **Painel admin** (`/admin`): visivel so para `role=admin`.
  - `/admin/usuarios`: criar, editar, desativar, resetar senha.
  - `/admin/configs`: configuracoes globais do sistema (chave/valor).
  - `/admin/logs`: logs de auditoria (acao, categoria, usuario, IP).
- **Multi-usuario**: cada usuario ve apenas seus proprios processos (admin ve todos com escopo=todos). Processo agora tem `origem` (manual/oab_monitor), `oab_origem`, `partes_json`, `link_djen`, `orgao`.
- **CRUD completo**:
  - `PATCH/DELETE /api/v1/oab/<id>` — editar/excluir OAB cadastrada.
  - `PATCH/DELETE /api/v1/processos/<id>` — editar/excluir processo.
  - `POST /api/v1/processos/<id>/vincular-oab` — vincular OAB a processo.
  - `POST /api/v1/processos/<id>/andamento` — adicionar andamento manual.
  - `POST /api/v1/processos/<id>/historico` — buscar historico completo (ate 2 anos).
  - `POST /api/v1/dje/consultar-cnj/<cnj>` — endpoint dedicado para auto-preenchimento de formulario (extrai classe, assunto, vara, partes do DJEN).
- **Tabela `ProcessoOAB`**: rastreabilidade — cada processo sabe quais OABs o capturaram.
- **Tabela `CapturaOABPublicacao`**: cada publicacao sabe qual captura OAB a trouxe.
- **Tabela `UserConfig`**: preferencias por usuario.
- **Tabela `SystemConfig`**: configuracoes globais (admin-only).
- **Tabela `ActionLog`**: auditoria de todas as acoes sensiveis.

### MELHORIAS
- **Deduplicacao em 3 niveis**: `hash_conteudo` (SHA-256 do texto+data), `id_comunicacao` (ID do DJEN), e `numero_cnj+data`. Processo cadastrado manualmente nao duplica quando OAB traz publicacao dele.
- **Prazos vinculados ao processo** com vinculo clicavel (id_processo na URL).
- **Deteccao de duplicidade** ao cadastrar processo: se CNJ ja existe, vincula OAB e retorna o existente (status 200, nao 409).
- **Auto-preenchimento** de formulario a partir do DJEN: extrai classe, assunto, vara, partes e link.
- **OAB origem** visivel na lista de processos (badge "via OAB" + numero da OAB).
- **Status do DJe** mostra "(busca nacional)" quando ativo.
- **Bloco de credenciais PJe** no `monitor_dje` para modo autenticado.
- **Cache de imports** e tratamento de erros do DJEN mais robusto.
- **Versionamento**: 2.0.0 - DJe + OAB + IA + Multi-usuario.

### BUGS CORRIGIDOS
- `capturar_todas_oabs` nao passava `oab_id` para o `CapturaOAB` (NOT NULL constraint).
- `dje/coletar` sem CNJ dava 400 (agora faz fallback para monitor de todas as OABs).
- `oabs.html` chamava `/api/v1/oabs` (plural) e `/api/v1/oabs/status` que nao existiam (adicionados aliases).
- `dje_comunica.py` usava `dataInicio`/`dataFim` (nomes errados do DJEN, agora usa `dataDisponibilizacaoInicio`/`dataDisponibilizacaoFim`).
- `start.bat` quebrava no Windows CMD com `else` em linha separada (reescrito sem `else`).

### ARQUIVOS MODIFICADOS
- `app/harvest/dje_comunica.py` - busca nacional
- `app/harvest/oab_capture.py` - rastreabilidade OAB + Processo
- `app/core/models.py` - 4 novas tabelas + 7 novas colunas
- `app/api/__init__.py` - 20+ novos endpoints
- `app/web/__init__.py` - 6 novas rotas
- `app/seed.py` - cria UserConfig + SystemConfig defaults
- `app/intel/llm_local.py` (NOVO)
- `app/web/templates/base.html` - menu admin + versao 2.0.0
- `app/web/templates/monitor_dje.html` - botoes editar/deletar OAB
- `app/web/templates/processos.html` - edicao, OAB origem, historico
- `app/web/templates/processo_detalhe.html` - vincular OAB + historico + editar
- `app/web/templates/configuracoes.html` (NOVO)
- `app/web/templates/ia.html` (NOVO)
- `app/web/templates/admin/*.html` (NOVO - 4 templates)
- `app/static/js/app.js` (NOVO) - LexPravis global
- `app/static/css/app.css` (NOVO)
- `.env.example` - secao IA local
- `start.bat` / `start.sh` - copia `.env.example` se nao existir

## v1.0.0 (2026-07-02)
- Versao inicial: DJe + Monitor de OAB (sem DataJud, sem DJR).
