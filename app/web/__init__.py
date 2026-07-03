"""Blueprint web - paginas HTML. DJe (PJe Comunica) + Monitor de OAB."""
from pathlib import Path
from flask import Blueprint, render_template, redirect, url_for, request, flash, Response
from flask_login import login_user, logout_user, login_required, current_user
from datetime import date, datetime, timedelta

from app.core.extensions import db
from app.core.models import (
    User, Cliente, Processo, Andamento, Prazo, Publicacao,
    OABMonitorada, CapturaOAB, AlertaCliente,
)
from app.core.utils import normalize_cnj
from app.alerts.emailer import export_prazos_ics
from app.harvest.dje_comunica import PJeComunicaEngine

_TEMPLATE_DIR = str(Path(__file__).resolve().parent / "templates")
bp = Blueprint("web", __name__, template_folder=_TEMPLATE_DIR)


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("web.dashboard"))
    return render_template("login.html")


@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Credenciais invalidas", "danger")
        return redirect(url_for("web.login"))
    login_user(user)
    return redirect(url_for("web.dashboard"))


@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("web.login"))


@bp.get("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


@bp.get("/processos")
@login_required
def processos():
    return render_template("processos.html")


@bp.get("/processos/<int:pid>")
@login_required
def processo_detalhe(pid):
    p = Processo.query.get_or_404(pid)
    return render_template("processo_detalhe.html", processo=p)


@bp.get("/clientes")
@login_required
def clientes():
    return render_template("clientes.html")


@bp.get("/prazos")
@login_required
def prazos():
    return render_template("prazos.html")


@bp.get("/agenda")
@login_required
def agenda():
    return render_template("agenda.html")


@bp.get("/config")
@login_required
def config():
    return render_template("config.html")


@bp.get("/dje")
@login_required
def dje():
    tribunal = request.args.get("tribunal")
    q = Publicacao.query
    if tribunal:
        q = q.filter(Publicacao.tribunal == tribunal)
    pubs = q.order_by(Publicacao.data.desc()).limit(200).all()
    return render_template("dje.html", publicacoes=pubs, filtro_tribunal=tribunal)


@bp.get("/cal.ics")
@login_required
def cal_ics():
    text = export_prazos_ics(current_user)
    return Response(text, mimetype="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=lex-praxis.ics"})


@bp.get("/oabs")
@login_required
def oabs():
    return render_template("oabs.html")


@bp.get("/alertas")
@login_required
def alertas():
    return render_template("alertas.html")


@bp.get("/capturas")
@login_required
def capturas():
    return render_template("capturas.html")


@bp.get("/monitor-dje")
@login_required
def monitor_dje():
    engine = PJeComunicaEngine()
    oabs = OABMonitorada.query.order_by(OABMonitorada.uf, OABMonitorada.numero).all()
    capturas = (CapturaOAB.query
                .order_by(CapturaOAB.executada_em.desc())
                .limit(50).all())
    return render_template("monitor_dje.html",
                           oabs=oabs, capturas=capturas,
                           dje_status=engine.status())


# ============== CONFIGURACOES DO USUARIO ==============

@bp.get("/configuracoes")
@login_required
def configuracoes():
    from app.core.models import UserConfig
    cfg = UserConfig.query.filter_by(user_id=current_user.id).first()
    if not cfg:
        cfg = UserConfig(user_id=current_user.id)
        from app.core.extensions import db
        db.session.add(cfg)
        db.session.commit()
    return render_template("configuracoes.html", cfg=cfg, is_admin=current_user.role == "admin")


# ============== ADMIN ==============

def _is_admin():
    return current_user.is_authenticated and current_user.role == "admin"


@bp.get("/admin")
@login_required
def admin_home():
    if not _is_admin():
        flash("Acesso restrito ao admin", "danger")
        return redirect(url_for("web.dashboard"))
    return render_template("admin/index.html")


@bp.get("/admin/usuarios")
@login_required
def admin_usuarios():
    if not _is_admin():
        flash("Acesso restrito ao admin", "danger")
        return redirect(url_for("web.dashboard"))
    users = User.query.order_by(User.name).all()
    return render_template("admin/usuarios.html", users=users)


@bp.get("/admin/configs")
@login_required
def admin_configs():
    if not _is_admin():
        flash("Acesso restrito ao admin", "danger")
        return redirect(url_for("web.dashboard"))
    from app.core.models import SystemConfig
    cfgs = SystemConfig.query.order_by(SystemConfig.key).all()
    return render_template("admin/configs.html", configs=cfgs)


@bp.get("/admin/logs")
@login_required
def admin_logs():
    if not _is_admin():
        flash("Acesso restrito ao admin", "danger")
        return redirect(url_for("web.dashboard"))
    from app.core.models import ActionLog
    logs = ActionLog.query.order_by(ActionLog.created_at.desc()).limit(300).all()
    return render_template("admin/logs.html", logs=logs)


# ============== IA: pagina de teste ==============

@bp.get("/ia")
@login_required
def ia_pagina():
    return render_template("ia.html")

