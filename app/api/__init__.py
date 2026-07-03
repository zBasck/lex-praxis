"""API REST - DJE/DJR + OAB + monitor.

Sistema opera exclusivamente com DJe (PJe Comunica) + Monitor de OAB.
DataJud/MNI foi removido. Sem fallback sintetico.
"""
import os
import re
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta

from app.core.extensions import db
from app.core.models import (
    User, Cliente, Processo, Andamento, Prazo, Publicacao, AuditLog,
    OABMonitorada, CapturaOAB, ParteProcesso, DocumentoCliente, AlertaCliente,
    UserConfig, SystemConfig, ProcessoOAB, CapturaOABPublicacao, ActionLog,
)
from app.core.utils import normalize_cnj, detect_tribunal_from_cnj
from app.core.prazos import get_motor
from app.harvest.service import harvest_processo, harvest_all_active
from app.harvest.dje import HarvestDJe
from app.harvest.dje_comunica import PJeComunicaEngine, DJeUnavailableError
from app.harvest.oab_capture import MonitorOAB
from app.harvest.tribunais import dropdown_ordenado, POR_SIGLA
from app.alerts.emailer import send_daily_digest, export_prazos_ics
from app.intel.classifier import classify

bp = Blueprint("api", __name__)


def _err(msg, code=400):
    return jsonify({"error": msg}), code


@bp.errorhandler(404)
def _not_found(e):
    return _err("recurso nao encontrado", 404)


@bp.errorhandler(500)
def _server_error(e):
    current_app.logger.exception("erro api")
    return _err("erro interno", 500)


# ------------------ Healthcheck ------------------

@bp.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "datajud_removido": True,
        "fonte": "DJe (PJe Comunica) + Monitor de OAB",
        "time": datetime.utcnow().isoformat() + "Z",
        "tribunais_suportados": len(POR_SIGLA),
    })


# ------------------ Tribunais ------------------

@bp.get("/tribunais")
@login_required
def list_tribunais():
    items = [{
        "sigla": t.sigla, "nome": t.nome, "categoria": t.categoria,
        "uf": t.uf, "segmento_cnj": t.segmento_cnj, "engine": t.engine,
        "tem_dje": bool(t.dje_url), "dje_url": t.dje_url,
        "consulta_url": t.consulta_url,
    } for t in dropdown_ordenado()]
    return jsonify({"items": items, "total": len(items)})


# ------------------ DJe (PJe Comunica) ------------------

@bp.get("/dje/status")
@login_required
def dje_status():
    engine = PJeComunicaEngine()
    s = engine.status()
    tribunais_pje = [t.sigla for t in dropdown_ordenado()
                     if t.engine in ("pje", "esaj")]
    return jsonify({
        "fonte": "DJe (PJe Comunica)",
        "datajud_removido": True,
        "modo": s["modo"],
        "enabled": s["enabled"],
        "pje_comunica_url": s["url_base"],
        "tribunais_cobertos_pje_comunica": len(tribunais_pje),
        "tribunais_total": len(list(dropdown_ordenado())),
        "configuracao": {
            "DJE_COMUNICA_ENABLED": s["enabled"],
            "OAB_MONITOR_ENABLED": current_app.config.get("OAB_MONITOR_ENABLED", True),
            "OAB_MONITOR_INTERVAL_MINUTES": current_app.config.get("OAB_MONITOR_INTERVAL_MINUTES", 60),
        },
    })


# ============== IA LOCAL (LLM) ==============

@bp.get("/ia/status")
@login_required
def ia_status():
    from app.intel.llm_local import status as llm_status, cfg_from_user_config
    cfg_model = UserConfig.query.filter_by(user_id=current_user.id).first()
    cfg = cfg_from_user_config(cfg_model)
    return jsonify(llm_status(cfg))


@bp.post("/ia/resumir")
@login_required
def ia_resumir():
    from app.intel.llm_local import resumir_publicacao, cfg_from_user_config
    data = request.get_json() or {}
    texto = data.get("texto", "")
    if not texto:
        return _err("texto obrigatorio")
    cfg = data.get("config")
    if not cfg:
        cfg_model = UserConfig.query.filter_by(user_id=current_user.id).first()
        cfg = cfg_from_user_config(cfg_model)
    resumo = resumir_publicacao(texto, cfg)
    if not resumo:
        return jsonify({"disponivel": False, "resumo": None,
                        "mensagem": "LLM local indisponivel ou desabilitado"}), 503
    return jsonify({"disponivel": True, "resumo": resumo})


@bp.post("/ia/classificar")
@login_required
def ia_classificar():
    from app.intel.llm_local import classificar_ato, cfg_from_user_config
    data = request.get_json() or {}
    texto = data.get("texto", "")
    if not texto:
        return _err("texto obrigatorio")
    cfg = data.get("config")
    if not cfg:
        cfg_model = UserConfig.query.filter_by(user_id=current_user.id).first()
        cfg = cfg_from_user_config(cfg_model)
    categoria = classificar_ato(texto, cfg)
    if not categoria:
        return jsonify({"disponivel": False, "categoria": None,
                        "mensagem": "LLM local indisponivel"}), 503
    return jsonify({"disponivel": True, "categoria": categoria})


@bp.post("/ia/sugerir-tarefa")
@login_required
def ia_sugerir_tarefa():
    from app.intel.llm_local import sugerir_tarefa, cfg_from_user_config
    data = request.get_json() or {}
    texto = data.get("texto", "")
    if not texto:
        return _err("texto obrigatorio")
    cfg = data.get("config")
    if not cfg:
        cfg_model = UserConfig.query.filter_by(user_id=current_user.id).first()
        cfg = cfg_from_user_config(cfg_model)
    tarefa = sugerir_tarefa(texto, cfg)
    if not tarefa:
        return jsonify({"disponivel": False, "tarefa": None,
                        "mensagem": "LLM local indisponivel"}), 503
    return jsonify({"disponivel": True, "tarefa": tarefa})


@bp.post("/dje/consultar-cnj/<path:cnj>")
@login_required
def consultar_cnj_para_form(cnj):
    """Consulta DJe e retorna metadados para auto-preenchimento de formulario."""
    cnj = re.sub(r"\D", "", str(cnj or ""))
    if len(cnj) != 20:
        return _err("CNJ invalido")
    engine = PJeComunicaEngine()
    if not engine.enabled:
        return jsonify({"status": "desabilitado", "encontrado": False,
                        "mensagem": "DJe desabilitado"}), 503
    try:
        pubs = engine.fetch_por_cnj(cnj, days_back=90)
    except Exception as e:
        return jsonify({"status": "erro", "encontrado": False, "erro": str(e)}), 502
    if not pubs:
        return jsonify({"status": "ok", "encontrado": False,
                        "mensagem": "Sem publicacoes no DJe nos ultimos 90 dias."})
    # Extrai metadados da publicacao mais recente
    p = pubs[0]
    texto = p.texto or ""
    tribunal = (p.metadados or {}).get("tribunal") or ""
    # Extrai classe/assunto do texto (heuristica)
    classe = ""
    m = re.search(r"Classe\s*:\s*([A-Z\s]+?)(?:\(|/|Processo|$)", texto, re.IGNORECASE)
    if m:
        classe = m.group(1).strip()[:200]
    assunto = ""
    m = re.search(r"Assunto\s*:\s*([^\n\r]+)", texto, re.IGNORECASE)
    if m:
        assunto = m.group(1).strip()[:300]
    # Vara/orgao
    vara = ""
    m = re.search(r"(\d+\s*Vara\s+(?:Civel|Criminal|Trabalhista|Federal|de Familia|...)", texto, re.IGNORECASE)
    if m:
        vara = m.group(1).strip()[:200]
    if not vara:
        # Tenta "Juizado" ou "Vara Unica"
        m = re.search(r"((?:Juizado|Vara)\s+[^,\n]+?)\s+(?:da|de|do)\s+", texto, re.IGNORECASE)
        if m:
            vara = m.group(1).strip()[:200]
    return jsonify({
        "status": "ok",
        "encontrado": True,
        "tribunal": tribunal,
        "classe": classe,
        "assunto": assunto,
        "vara": vara,
        "partes": (p.metadados or {}).get("partes", ""),
        "texto_resumo": (texto[:400] + "...") if len(texto) > 400 else texto,
        "url": p.url,
        "data": p.data.isoformat() if p.data else None,
        "total_publicacoes": len(pubs),
        "mensagem": f"Encontrado: {len(pubs)} publicacao(oes) no DJe. Campos preenchidos.",
    })


@bp.post("/dje/coletar")
@login_required
def trigger_dje():
    """Coleta publicacoes de um CNJ especifico, OU (se sem CNJ) dispara
    o monitor de todas as OABs ativas (cadernos dos ultimos N dias)."""
    data = request.get_json(silent=True) or {}
    cnj = (data.get("cnj") or request.args.get("cnj") or "").strip()
    days_back = int(data.get("days_back") or request.args.get("days_back") or 3)

    # Sem CNJ: dispara o monitor de todas as OABs ativas
    if not cnj:
        from app.harvest.oab_capture import MonitorOAB
        monitor = MonitorOAB()
        st = monitor.engine.status()
        if not st.get("enabled"):
            return jsonify({
                "status": "desabilitado",
                "erro": "DJe desabilitado. Ative DJE_COMUNICA_ENABLED=true no .env",
                "oabs": [],
            }), 503
        res = monitor.capturar_todas_oabs(days_back=days_back)
        return jsonify(res)

    # Com CNJ: busca andamentos por CNJ
    engine = PJeComunicaEngine()
    try:
        pubs = engine.fetch_por_cnj(cnj)
    except DJeUnavailableError as e:
        return jsonify({"status": "desabilitado", "erro": str(e), "publicacoes": []}), 503
    except (RuntimeError, ValueError) as e:
        return jsonify({"status": "erro", "erro": str(e), "publicacoes": []}), 502
    return jsonify({
        "status": "ok",
        "cnj": cnj,
        "publicacoes": [{
            "data": p.data.isoformat() if hasattr(p.data, "isoformat") else str(p.data),
            "tribunal": p.metadados.get("tribunal", "DJe"),
            "numero_cnj": p.metadados.get("numero_cnj", cnj),
            "texto": (p.texto or "")[:500] + ("..." if len(p.texto or "") > 500 else ""),
            "url": p.url,
        } for p in pubs],
        "total": len(pubs),
    })


# ------------------ Monitor de OAB ------------------

@bp.get("/oab")
@login_required
def list_oabs():
    oabs = OABMonitorada.query.order_by(OABMonitorada.uf, OABMonitorada.numero).all()
    return jsonify({"items": [o.to_dict() for o in oabs], "total": len(oabs)})


# Aliases (singular <-> plural) + endpoint de status para tolerar templates antigos
@bp.get("/oabs")
@login_required
def list_oabs_plural():
    return list_oabs()


@bp.get("/oab/status")
@login_required
def oab_status():
    """Status geral do monitor de OAB + DJe (compat com templates antigos)."""
    engine = PJeComunicaEngine()
    s = engine.status()
    oabs_ativas = OABMonitorada.query.filter_by(ativo=True).count()
    total_capturas = CapturaOAB.query.count()
    ultima = CapturaOAB.query.order_by(CapturaOAB.executada_em.desc()).first()
    return jsonify({
        "fonte": "DJe (PJe Comunica)",
        "datajud_removido": True,
        "modo_dje": s["modo"],
        "dje_enabled": s["enabled"],
        "dje_url": s["url_base"],
        "oabs_ativas": oabs_ativas,
        "total_capturas": total_capturas,
        "ultima_captura": ultima.executada_em.isoformat() if ultima else None,
        "configuracao": {
            "DJE_COMUNICA_ENABLED": s["enabled"],
            "OAB_MONITOR_ENABLED": current_app.config.get("OAB_MONITOR_ENABLED", True),
            "OAB_MONITOR_INTERVAL_MINUTES": current_app.config.get("OAB_MONITOR_INTERVAL_MINUTES", 60),
        },
    })


@bp.get("/oabs/status")
@login_required
def oab_status_plural():
    return oab_status()


@bp.post("/oab")
@login_required
def create_oab():
    data = request.get_json() or {}
    numero = re.sub(r"\D", "", str(data.get("numero", "")))
    uf = (data.get("uf", "") or "").upper().strip()
    if not numero or len(uf) != 2:
        return _err("numero e uf sao obrigatorios")
    if OABMonitorada.query.filter_by(numero=numero, uf=uf).first():
        return _err(f"OAB {numero}/{uf} ja cadastrada", 409)
    o = OABMonitorada(
        numero=numero, uf=uf,
        apelido=data.get("apelido"),
        responsavel_id=current_user.id,
        ativo=True,
        intervalo_minutos=int(data.get("intervalo_minutos", 60)),
    )
    db.session.add(o)
    db.session.commit()
    return jsonify(o.to_dict()), 201


@bp.patch("/oab/<int:oid>")
@login_required
def update_oab(oid):
    o = OABMonitorada.query.get_or_404(oid)
    data = request.get_json() or {}
    for c in ["numero", "uf", "apelido", "ativo", "intervalo_minutos", "responsavel_id"]:
        if c in data:
            if c == "ativo":
                setattr(o, c, bool(data[c]))
            elif c == "uf":
                setattr(o, c, (data[c] or "").upper().strip())
            else:
                setattr(o, c, data[c])
    db.session.commit()
    return jsonify(o.to_dict())

@bp.delete("/oab/<int:oid>")
@login_required
def delete_oab(oid):
    o = OABMonitorada.query.get_or_404(oid)
    db.session.delete(o)
    db.session.commit()
    return jsonify({"deleted": True, "id": oid})

@bp.post("/oab/<int:oid>/capturar")
@login_required
def capturar_oab(oid):
    """Executa captura DJe para uma OAB cadastrada (cadastra processos novos)."""
    o = OABMonitorada.query.get_or_404(oid)
    days = int(request.args.get("days_back", 7))
    monitor = MonitorOAB()
    res = monitor.capturar_para_oab_oab(o, days_back=days, user=current_user)
    o.ultima_busca_em = datetime.utcnow()
    if res.get("status") == "ok":
        o.total_processos_encontrados = (o.total_processos_encontrados or 0) + res.get("publicacoes_encontradas", 0)
        o.total_processos_criados = (o.total_processos_criados or 0) + res.get("processos_novos", 0)
    db.session.commit()
    code = 200 if res.get("status") in ("ok",) else (503 if res.get("status") == "indisponivel" else 502)
    return jsonify(res), code


@bp.post("/oab/capturar-todas")
@login_required
def capturar_todas_oabs():
    monitor = MonitorOAB()
    res = monitor.capturar_todas_oabs(days_back=int(request.args.get("days_back", 7)))
    return jsonify(res)


@bp.post("/oab/buscar")
@login_required
def buscar_oab_avulsa():
    """Captura avulsa por OAB+UF sem cadastrar (para teste)."""
    data = request.get_json() or {}
    numero = re.sub(r"\D", "", str(data.get("numero", "")))
    uf = (data.get("uf", "") or "").upper().strip()
    days = int(data.get("days_back", 7))
    if not numero or len(uf) != 2:
        return _err("numero e uf sao obrigatorios")
    engine = PJeComunicaEngine()
    try:
        pubs = engine.fetch_por_oab(numero, uf, days_back=days)
    except DJeUnavailableError as e:
        return jsonify({"status": "desabilitado", "erro": str(e)}), 503
    except (RuntimeError, ValueError) as e:
        return jsonify({"status": "erro", "erro": str(e)}), 502
    return jsonify({
        "status": "ok",
        "oab": f"{numero}/{uf}",
        "publicacoes": [{
            "numero_cnj": p.numero_cnj, "data": p.data.isoformat(),
            "tipo_ato": p.tipo_ato, "partes": p.partes,
            "tribunal": p.tribunal, "texto": (p.texto or "")[:500],
        } for p in pubs],
        "total": len(pubs),
    })


# ============== GESTAO DE USUARIOS (ADMIN) ==============

def _admin_required():
    if current_user.role != "admin":
        return _err("Apenas admin", 403)
    return None


@bp.get("/users")
@login_required
def list_users():
    """Lista todos os usuarios (admin). Admin sempre visivel."""
    if current_user.role != "admin":
        return jsonify({"items": [_user_public(current_user)], "total": 1})
    users = User.query.order_by(User.name).all()
    return jsonify({"items": [_user_public(u) for u in users], "total": len(users)})


@bp.post("/users")
@login_required
def create_user():
    """Admin cria novo usuario (colega)."""
    err = _admin_required()
    if err:
        return err
    data = request.get_json() or {}
    if not data.get("email") or not data.get("password") or not data.get("name"):
        return _err("name, email e password sao obrigatorios")
    email = data["email"].strip().lower()
    if User.query.filter_by(email=email).first():
        return _err("Email ja cadastrado", 409)
    u = User(
        name=data["name"],
        email=email,
        role=data.get("role", "advogado"),
        oab=data.get("oab"),
        phone=data.get("phone"),
        active=True,
    )
    u.set_password(data["password"])
    db.session.add(u)
    db.session.commit()
    # Cria config padrao
    cfg = UserConfig(user_id=u.id)
    db.session.add(cfg)
    db.session.commit()
    return jsonify(_user_public(u)), 201


@bp.patch("/users/<int:uid>")
@login_required
def update_user(uid):
    """Admin edita qualquer usuario; usuario edita so seus proprios dados."""
    u = User.query.get_or_404(uid)
    if current_user.role != "admin" and current_user.id != u.id:
        return _err("sem permissao", 403)
    data = request.get_json() or {}
    # Campos que o proprio usuario pode editar
    for c in ["name", "phone", "oab"]:
        if c in data:
            setattr(u, c, data[c])
    if current_user.role == "admin":
        for c in ["email", "role", "active", "password"]:
            if c in data:
                if c == "email":
                    u.email = data[c].strip().lower()
                elif c == "password":
                    u.set_password(data[c])
                else:
                    setattr(u, c, data[c])
    db.session.commit()
    return jsonify(_user_public(u))


@bp.delete("/users/<int:uid>")
@login_required
def delete_user(uid):
    err = _admin_required()
    if err:
        return err
    u = User.query.get_or_404(uid)
    if u.id == current_user.id:
        return _err("Nao pode deletar seu proprio usuario", 400)
    u.active = False
    db.session.commit()
    return jsonify({"deleted": True, "id": uid})


@bp.get("/me")
@login_required
def me():
    cfg = UserConfig.query.filter_by(user_id=current_user.id).first()
    if not cfg:
        cfg = UserConfig(user_id=current_user.id)
        db.session.add(cfg)
        db.session.commit()
    return jsonify({
        "user": _user_public(current_user),
        "config": cfg.to_dict(),
        "is_admin": current_user.role == "admin",
    })


@bp.patch("/me/config")
@login_required
def update_my_config():
    cfg = UserConfig.query.filter_by(user_id=current_user.id).first()
    if not cfg:
        cfg = UserConfig(user_id=current_user.id)
        db.session.add(cfg)
    data = request.get_json() or {}
    for c in ["theme", "language", "default_oab", "default_uf", "days_back_padrao",
              "intervalo_monitor_min", "receber_digest", "digest_hora",
              "llm_provider", "llm_model", "llm_endpoint", "llm_enabled",
              "llm_api_key", "notif_email", "notif_whatsapp", "whatsapp_number"]:
        if c in data:
            setattr(cfg, c, data[c])
    db.session.commit()
    return jsonify(cfg.to_dict())


# ============== SYSTEM CONFIG (ADMIN) ==============

@bp.get("/system/configs")
@login_required
def list_system_configs():
    err = _admin_required()
    if err:
        return err
    cfgs = SystemConfig.query.order_by(SystemConfig.key).all()
    return jsonify({"items": [c.to_dict() for c in cfgs], "total": len(cfgs)})


@bp.put("/system/configs/<string:key>")
@login_required
def set_system_config(key):
    err = _admin_required()
    if err:
        return err
    data = request.get_json() or {}
    cfg = SystemConfig.query.get(key)
    if not cfg:
        cfg = SystemConfig(key=key)
        db.session.add(cfg)
    cfg.value = data.get("value")
    if "description" in data:
        cfg.description = data["description"]
    cfg.updated_by_id = current_user.id
    db.session.commit()
    return jsonify(cfg.to_dict())


@bp.delete("/system/configs/<string:key>")
@login_required
def del_system_config(key):
    err = _admin_required()
    if err:
        return err
    cfg = SystemConfig.query.get(key)
    if cfg:
        db.session.delete(cfg)
        db.session.commit()
    return jsonify({"deleted": True, "key": key})


# ============== LOG DE ACOES ==============

@bp.get("/action-logs")
@login_required
def list_action_logs():
    if current_user.role != "admin":
        q = ActionLog.query.filter_by(user_id=current_user.id)
    else:
        q = ActionLog.query
    if request.args.get("categoria"):
        q = q.filter(ActionLog.categoria == request.args.get("categoria"))
    items = q.order_by(ActionLog.created_at.desc()).limit(200).all()
    return jsonify({"items": [a.to_dict() for a in items], "total": len(items)})


@bp.get("/oab/capturas")
@login_required
def list_capturas():
    oab_id = request.args.get("oab_id", type=int)
    limit = min(int(request.args.get("limit", 50)), 200)
    q = CapturaOAB.query
    if oab_id:
        q = q.filter(CapturaOAB.oab_id == oab_id)
    items = q.order_by(CapturaOAB.executada_em.desc()).limit(limit).all()
    return jsonify({"items": [c.to_dict() for c in items], "total": len(items)})


# ------------------ Alertas ------------------

@bp.get("/alertas")
@login_required
def list_alertas():
    lido = request.args.get("lido")
    sev = request.args.get("severidade")
    q = AlertaCliente.query
    if lido is not None:
        q = q.filter(AlertaCliente.lido == (lido.lower() == "true"))
    if sev:
        q = q.filter(AlertaCliente.severidade == sev)
    items = q.order_by(AlertaCliente.created_at.desc()).limit(200).all()
    return jsonify({"items": [a.to_dict() for a in items], "total": len(items)})


@bp.post("/alertas/<int:aid>/lido")
@login_required
def marcar_alerta_lido(aid):
    a = AlertaCliente.query.get_or_404(aid)
    a.lido = True
    a.lido_em = datetime.utcnow()
    a.lido_por_id = current_user.id
    db.session.commit()
    return jsonify(a.to_dict())


# ------------------ Stats / Dashboard ------------------

@bp.get("/dashboard")
@login_required
def dashboard():
    today = date.today()
    horizon = today + timedelta(days=15)
    total_proc = Processo.query.filter_by(ativo=True).count()
    total_cli = Cliente.query.filter_by(ativo=True).count()
    prazos_abertos = Prazo.query.filter_by(status="aberto").count()
    prazos_vencidos = (Prazo.query.filter_by(status="aberto")
                       .filter(Prazo.data_limite < today).count())
    prazos_proximos = (Prazo.query.filter_by(status="aberto")
                       .filter(Prazo.data_limite.between(today, horizon)).count())
    andamentos_30d = (Andamento.query
                      .filter(Andamento.capturado_em >= datetime.utcnow() - timedelta(days=30))
                      .count())
    publicacoes_30d = (Publicacao.query
                       .filter(Publicacao.capturado_em >= datetime.utcnow() - timedelta(days=30))
                       .count())
    ultimos_andamentos = (Andamento.query
                          .order_by(Andamento.capturado_em.desc())
                          .limit(10).all())
    proximos_prazos = (Prazo.query
                       .filter(Prazo.status == "aberto")
                       .filter(Prazo.data_limite >= today)
                       .order_by(Prazo.data_limite)
                       .limit(10).all())
    ultimas_publicacoes = (Publicacao.query
                           .order_by(Publicacao.capturado_em.desc())
                           .limit(10).all())
    oabs_ativas = OABMonitorada.query.filter_by(ativo=True).count()
    alertas_abertos = AlertaCliente.query.filter_by(lido=False).count()
    por_tribunal = (db.session.query(Processo.tribunal, db.func.count(Processo.id))
                    .filter(Processo.ativo.is_(True))
                    .group_by(Processo.tribunal)
                    .all())
    return jsonify({
        "kpi": {
            "processos_ativos": total_proc,
            "clientes_ativos": total_cli,
            "prazos_abertos": prazos_abertos,
            "prazos_vencidos": prazos_vencidos,
            "prazos_proximos": prazos_proximos,
            "andamentos_30d": andamentos_30d,
            "publicacoes_30d": publicacoes_30d,
            "oabs_ativas": oabs_ativas,
            "alertas_abertos": alertas_abertos,
        },
        "ultimos_andamentos": [_andamento(a) for a in ultimos_andamentos],
        "proximos_prazos": [_prazo(p) for p in proximos_prazos],
        "ultimas_publicacoes": [_publicacao(p) for p in ultimas_publicacoes],
        "processos_por_tribunal": [{"tribunal": t, "count": c} for t, c in por_tribunal],
    })


# ------------------ Clientes ------------------

@bp.get("/clientes")
@login_required
def list_clientes():
    q = (request.args.get("q") or "").strip()
    query = Cliente.query.filter_by(ativo=True)
    if q:
        query = query.filter(Cliente.nome.ilike(f"%{q}%"))
    clientes = query.order_by(Cliente.nome).limit(200).all()
    return jsonify({"items": [_cliente(c) for c in clientes]})


@bp.post("/clientes")
@login_required
def create_cliente():
    data = request.get_json() or {}
    if not data.get("nome"):
        return _err("nome e obrigatorio")
    c = Cliente(
        nome=data["nome"], documento=data.get("documento"),
        tipo=data.get("tipo", "PF"), email=data.get("email"),
        phone=data.get("phone"), endereco=data.get("endereco"),
        observacoes=data.get("observacoes"),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(_cliente(c)), 201


@bp.get("/clientes/<int:cid>")
@login_required
def get_cliente(cid):
    c = Cliente.query.get_or_404(cid)
    processos = c.processos.filter_by(ativo=True).all()
    return jsonify({**_cliente(c), "processos": [_processo(p) for p in processos]})


# ------------------ Processos ------------------

@bp.get("/processos")
@login_required
def list_processos():
    q = (request.args.get("q") or "").strip()
    cliente = request.args.get("cliente_id", type=int)
    tribunal = request.args.get("tribunal")
    escopo = request.args.get("escopo", "todos")  # todos | meus
    query = Processo.query.filter_by(ativo=True)
    # Filtro multi-usuario: nao-admin so ve os proprios (a menos que escopo=todos + admin)
    if current_user.role != "admin" or escopo == "meus":
        query = query.filter(
            db.or_(
                Processo.responsavel_id == current_user.id,
                Processo.responsavel_id.is_(None),
            )
        )
    if q:
        query = query.filter(db.or_(
            Processo.numero_cnj.ilike(f"%{q}%"),
            Processo.assunto.ilike(f"%{q}%"),
            Processo.classe.ilike(f"%{q}%"),
        ))
    if cliente:
        query = query.filter(Processo.cliente_id == cliente)
    if tribunal:
        query = query.filter(Processo.tribunal == tribunal)
    processos = query.order_by(Processo.updated_at.desc()).limit(500).all()
    return jsonify({"items": [_processo(p) for p in processos]})


@bp.post("/processos")
@login_required
def create_processo():
    data = request.get_json() or {}
    numero = data.get("numero_cnj")
    if not numero:
        return _err("numero_cnj e obrigatorio")
    numero = normalize_cnj(numero)
    existente = Processo.query.filter_by(numero_cnj=numero).first()
    if existente:
        # Nao duplica - vincula OAB se informada e retorna
        if data.get("oab_id"):
            if not ProcessoOAB.query.filter_by(processo_id=existente.id, oab_id=data["oab_id"]).first():
                db.session.add(ProcessoOAB(processo_id=existente.id, oab_id=data["oab_id"]))
                db.session.commit()
        return jsonify(_processo(existente)), 200
    tribunal = data.get("tribunal") or detect_tribunal_from_cnj(numero) or "DJe"
    p = Processo(
        numero_cnj=numero, tribunal=tribunal,
        vara=data.get("vara"), classe=data.get("classe"),
        assunto=data.get("assunto"), valor_causa=data.get("valor_causa"),
        instancia=data.get("instancia"), fase=data.get("fase"),
        cliente_id=data.get("cliente_id"),
        responsavel_id=data.get("responsavel_id") or current_user.id,
        polo=data.get("polo"), observacoes=data.get("observacoes"),
        origem=data.get("origem", "manual"),
        oab_origem=data.get("oab_origem"),
        uf_oab_origem=data.get("uf_oab_origem"),
        partes_json=data.get("partes_json"),
        link_djen=data.get("link_djen"),
        orgao=data.get("orgao"),
    )
    db.session.add(p)
    db.session.commit()
    if data.get("oab_id"):
        db.session.add(ProcessoOAB(processo_id=p.id, oab_id=data["oab_id"]))
        db.session.commit()
    return jsonify(_processo(p)), 201


@bp.patch("/processos/<int:pid>")
@login_required
def update_processo(pid):
    p = Processo.query.get_or_404(pid)
    data = request.get_json() or {}
    campos = ["vara", "classe", "assunto", "instancia", "fase", "polo",
              "observacoes", "valor_causa", "cliente_id", "responsavel_id",
              "tribunal", "orgao"]
    for c in campos:
        if c in data:
            setattr(p, c, data[c] if data[c] != "" else None)
    if "partes" in data and isinstance(data["partes"], (list, dict)):
        import json as _json
        p.partes_json = _json.dumps(data["partes"], ensure_ascii=False)
    db.session.commit()
    return jsonify(_processo(p))

@bp.delete("/processos/<int:pid>")
@login_required
def delete_processo(pid):
    p = Processo.query.get_or_404(pid)
    p.ativo = False
    db.session.commit()
    return jsonify({"deleted": True, "id": pid})

@bp.post("/processos/<int:pid>/vincular-oab")
@login_required
def vincular_oab_processo(pid):
    """Vincula manualmente uma OAB a um processo (rastreabilidade)."""
    p = Processo.query.get_or_404(pid)
    data = request.get_json() or {}
    oab_id = data.get("oab_id")
    if not oab_id:
        return _err("oab_id obrigatorio")
    if not OABMonitorada.query.get(oab_id):
        return _err("OAB nao encontrada", 404)
    rel = ProcessoOAB.query.filter_by(processo_id=pid, oab_id=oab_id).first()
    if not rel:
        db.session.add(ProcessoOAB(processo_id=pid, oab_id=oab_id))
        db.session.commit()
    return jsonify({"status": "vinculado", "processo_id": pid, "oab_id": oab_id})

@bp.post("/processos/<int:pid>/historico")
@login_required
def buscar_historico_processo(pid):
    """Busca historico completo do processo (retroativo ate onde o DJEN tiver)."""
    p = Processo.query.get_or_404(pid)
    days = int(request.args.get("days_back", 365))
    if days > 730:
        days = 730
    try:
        monitor = MonitorOAB()
        # Primeiro busca as publicacoes
        pubs = []
        try:
            from app.harvest.dje_comunica import PJeComunicaEngine
            engine = PJeComunicaEngine()
            if engine.enabled:
                pubs = engine.fetch_por_cnj(p.numero_cnj, days_back=days)
        except Exception as e:
            current_app.logger.warning("Falha busca CNJ: %s", e)
        # Persiste as publicacoes
        from app.core.utils import hash_text
        from app.core.models import Publicacao
        hashes_existentes = {a.hash_conteudo for a in p.andamentos if a.hash_conteudo}
        novos = 0
        for cap in pubs:
            h = hash_text(cap.texto + cap.data.isoformat())
            if h in hashes_existentes:
                continue
            # cria Publicacao + Andamento
            pub_row = Publicacao(
                tribunal=p.tribunal or "DJe", data=cap.data,
                caderno="DJe Comunica", secao="Historico",
                texto=cap.texto, texto_limpo=cap.texto,
                numero_cnj=p.numero_cnj, processo_id=p.id,
                diario_edicao=f"HIST-{p.id}-{hash(cap.texto) & 0xFFFF:04x}",
                capturado_em=datetime.utcnow(),
                hash_conteudo=h, vinculado_em=datetime.utcnow(),
            )
            db.session.add(pub_row)
            db.session.flush()
            novos += 1
            monitor._criar_andamento(p, cap)
        p.ultima_verificacao = datetime.utcnow()
        db.session.commit()
        return jsonify({
            "status": "ok",
            "processo": p.numero_cnj,
            "publicacoes_encontradas": len(pubs),
            "novas_inseridas": novos,
        })
    except Exception as e:
        return _err(str(e), 502)


@bp.get("/processos/<int:pid>")
@login_required
def get_processo(pid):
    p = Processo.query.get_or_404(pid)
    andamentos = p.andamentos.limit(200).all()
    prazos = p.prazos.limit(200).all()
    publicacoes = (Publicacao.query
                   .filter(Publicacao.processo_id == p.id)
                   .order_by(Publicacao.data.desc())
                   .limit(100).all())
    return jsonify({
        **_processo(p),
        "andamentos": [_andamento(a) for a in andamentos],
        "prazos": [_prazo(pz) for pz in prazos],
        "publicacoes": [_publicacao(pu) for pu in publicacoes],
    })


@bp.post("/processos/<int:pid>/harvest")
@login_required
def trigger_harvest(pid):
    p = Processo.query.get_or_404(pid)
    try:
        a, q = harvest_processo(p)
        return jsonify({"andamentos_novos": a, "prazos_novos": q})
    except Exception as e:
        return _err(str(e), 502)


@bp.post("/processos/<int:pid>/andamento")
@login_required
def add_andamento_manual(pid):
    """Adiciona andamento manual ao processo."""
    p = Processo.query.get_or_404(pid)
    data = request.get_json() or {}
    texto = data.get("texto", "").strip()
    if not texto:
        return _err("texto obrigatorio")
    from app.core.utils import hash_text
    from app.intel.classifier import classify
    h = hash_text(texto + (data.get("data") or ""))
    if Andamento.query.filter_by(hash_conteudo=h).first():
        return _err("andamento duplicado", 409)
    data_pub = data.get("data")
    if data_pub:
        try:
            data_dt = datetime.fromisoformat(data_pub.replace("Z", "+00:00"))
        except ValueError:
            data_dt = datetime.utcnow()
    else:
        data_dt = datetime.utcnow()
    cls = classify(texto)
    a = Andamento(
        processo_id=p.id, data=data_dt, texto=texto,
        texto_limpo=texto[:1000], tipo_ato=cls.tipo_ato,
        prazo_dias=cls.prazo_dias, prazo_marco=cls.prazo_marco,
        tarefa_sugerida=cls.tarefa_sugerida, resumo_cliente=cls.resumo_cliente,
        fonte="manual", hash_conteudo=h, classificacao_origem=cls.origem,
    )
    db.session.add(a)
    db.session.commit()
    _log("andamento_manual_create", "processo", "Processo", p.id, texto[:200])
    return jsonify({"id": a.id, "processo_id": p.id}), 201


@bp.post("/processos/<int:pid>/atualizar-dje")
@login_required
def atualizar_dje_processo(pid):
    """Busca publicacoes DJe por CNJ e atualiza andamentos."""
    p = Processo.query.get_or_404(pid)
    monitor = MonitorOAB()
    res = monitor.atualizar_andamentos(p)
    code = 200 if res.get("status") == "ok" else (503 if res.get("status") == "indisponivel" else 502)
    return jsonify(res), code


@bp.post("/harvest/all")
@login_required
def trigger_harvest_all():
    res = harvest_all_active()
    return jsonify(res)


# ------------------ Prazos (motor) ------------------

@bp.post("/prazos/calcular")
@login_required
def calcular_prazo():
    """Testa o motor de prazos: recebe tipo_ato, data, texto -> retorna prazo."""
    data = request.get_json() or {}
    tipo = data.get("tipo_ato", "outros")
    data_pub = data.get("data_publicacao")
    if data_pub:
        try:
            data_pub = datetime.fromisoformat(data_pub.replace("Z", "+00:00")).date()
        except ValueError:
            return _err("data_publicacao invalida (use ISO)")
    else:
        data_pub = date.today()
    motor = get_motor()
    pz = motor.calcular(tipo, data_pub, data.get("texto", ""))
    return jsonify({
        "tipo": pz.tipo, "data_inicio": pz.data_inicio.isoformat(),
        "data_limite": pz.data_limite.isoformat() if pz.data_limite else None,
        "marco": pz.marco, "tarefa_sugerida": pz.tarefa_sugerida,
        "prioridade": pz.prioridade, "gera_prazo": pz.gera_prazo,
    })


# ------------------ Prazos CRUD ------------------

@bp.get("/prazos")
@login_required
def list_prazos():
    status = request.args.get("status", "aberto")
    q = Prazo.query
    if status:
        q = q.filter(Prazo.status == status)
    items = q.order_by(Prazo.data_limite).limit(200).all()
    return jsonify({"items": [_prazo(p) for p in items], "total": len(items)})


@bp.post("/prazos/<int:pzid>/concluir")
@login_required
def concluir_prazo(pzid):
    p = Prazo.query.get_or_404(pzid)
    p.status = "concluido"
    p.concluido_em = datetime.utcnow()
    db.session.commit()
    return jsonify(_prazo(p))


# ------------------ Helpers de serializacao ------------------

def _user_public(u):
    return {
        "id": u.id, "name": u.name, "email": u.email, "role": u.role,
        "oab": u.oab, "phone": u.phone, "active": u.active,
        "receive_digest": u.receive_digest,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _log(acao, categoria, alvo_tipo=None, alvo_id=None, detalhes=None):
    """Registra acao do usuario para auditoria."""
    try:
        log = ActionLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            acao=acao, categoria=categoria, alvo_tipo=alvo_tipo,
            alvo_id=alvo_id, detalhes=str(detalhes)[:1000] if detalhes else None,
            ip=request.remote_addr,
            user_agent=(request.headers.get("User-Agent") or "")[:300],
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _cliente(c):
    return {
        "id": c.id, "nome": c.nome, "documento": c.documento, "tipo": c.tipo,
        "email": c.email, "phone": c.phone, "ativo": c.ativo,
        "processos_count": c.processos_count,
    }


def _processo(p):
    oabs = [{"id": po.oab.id, "oab": po.oab.oab_formatada,
             "primeira_captura": po.primeira_captura_em.isoformat() if po.primeira_captura_em else None}
            for po in getattr(p, "oabs_origem_list", [])]
    return {
        "id": p.id, "numero_cnj": p.numero_cnj, "tribunal": p.tribunal,
        "vara": p.vara, "classe": p.classe, "assunto": p.assunto,
        "instancia": p.instancia, "fase": p.fase, "ativo": p.ativo,
        "cliente_id": p.cliente_id, "responsavel_id": p.responsavel_id,
        "origem": getattr(p, "origem", "manual"),
        "oab_origem": getattr(p, "oab_origem", None),
        "uf_oab_origem": getattr(p, "uf_oab_origem", None),
        "partes_json": getattr(p, "partes_json", None),
        "link_djen": getattr(p, "link_djen", None),
        "orgao": getattr(p, "orgao", None),
        "oabs_origem": oabs,
        "ultima_verificacao": p.ultima_verificacao.isoformat() if p.ultima_verificacao else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _andamento(a):
    return {
        "id": a.id, "processo_id": a.processo_id, "data": a.data.isoformat() if a.data else None,
        "texto": (a.texto or "")[:500], "tipo_ato": a.tipo_ato,
        "prazo_dias": a.prazo_dias, "tarefa_sugerida": a.tarefa_sugerida,
        "fonte": a.fonte, "capturado_em": a.capturado_em.isoformat() if a.capturado_em else None,
    }


def _prazo(p):
    return {
        "id": p.id, "processo_id": p.processo_id, "descricao": p.descricao,
        "data_inicio": p.data_inicio.isoformat() if p.data_inicio else None,
        "data_limite": p.data_limite.isoformat() if p.data_limite else None,
        "tipo": p.tipo, "status": p.status, "prioridade": p.prioridade,
        "dias_restantes": p.dias_restantes, "vencido": p.vencido,
    }


def _publicacao(p):
    return {
        "id": p.id, "tribunal": p.tribunal, "data": p.data.isoformat() if p.data else None,
        "caderno": p.caderno, "secao": p.secao,
        "texto": (p.texto or "")[:500], "numero_cnj": p.numero_cnj,
        "processo_id": p.processo_id,
        "capturado_em": p.capturado_em.isoformat() if p.capturado_em else None,
    }
