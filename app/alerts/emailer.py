"""Envio de e-mails (alertas + digest diário)."""
from __future__ import annotations
import smtplib
import logging
import ssl
from datetime import date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

from flask import current_app

from app.core.models import User, Prazo, Processo
from app.core.extensions import db

log = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("SMTP_HOST") and cfg.get("SMTP_USER") and cfg.get("SMTP_PASSWORD"))


def _send(msg: MIMEMultipart):
    cfg = current_app.config
    if not _smtp_configured():
        log.info("SMTP não configurado — simulando envio para %s", msg["To"])
        return False
    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"]) as server:
        if cfg.get("SMTP_USE_TLS"):
            server.starttls(context=context)
        server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        server.send_message(msg)
    return True


def render_digest(user: User, prazos: List[Prazo]) -> str:
    if not prazos:
        return f"<p>Olá, {user.name}. Não há prazos relevantes para hoje.</p>"

    rows = []
    for p in prazos:
        proc = p.processo
        dias = p.dias_restantes
        if dias < 0:
            status = f"<span style='color:#c00'>VENCIDO há {-dias}d</span>"
        elif dias == 0:
            status = "<span style='color:#c00'>VENCE HOJE</span>"
        elif dias <= 3:
            status = f"<span style='color:#e67e22'>Em {dias}d</span>"
        else:
            status = f"Em {dias}d"
        rows.append(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee">{proc.numero_cnj}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{p.descricao}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{p.data_limite.strftime('%d/%m/%Y')}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{status}</td>
        </tr>""")
    return f"""
    <h2>Bom dia, {user.name}</h2>
    <p>Você tem <strong>{len(prazos)}</strong> prazo(s) relevante(s) nos próximos dias:</p>
    <table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:14px">
      <thead>
        <tr style="background:#f5f5f5">
          <th style="padding:8px;text-align:left">Processo</th>
          <th style="padding:8px;text-align:left">Descrição</th>
          <th style="padding:8px;text-align:left">Data limite</th>
          <th style="padding:8px;text-align:left">Status</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p style="color:#888;font-size:12px;margin-top:24px">
      Enviado por Lex Praxis · {date.today().strftime('%d/%m/%Y')}
    </p>
    """


def send_daily_digest() -> int:
    """Envia digest diário para todos os usuários ativos que optaram por receber."""
    today = date.today()
    horizon = today + timedelta(days=15)

    users = User.query.filter_by(active=True, receive_digest=True).all()
    enviados = 0
    for user in users:
        prazos = (Prazo.query
                  .filter(Prazo.status == "aberto")
                  .filter(Prazo.data_limite <= horizon)
                  .filter(Prazo.data_limite >= today - timedelta(days=30))
                  .filter((Prazo.responsavel_id == user.id) | (Prazo.responsavel_id.is_(None)))
                  .order_by(Prazo.data_limite)
                  .all())
        if not prazos:
            continue
        body = render_digest(user, prazos)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Lex Praxis] {len(prazos)} prazo(s) — {today.strftime('%d/%m')}"
        msg["From"] = current_app.config["SMTP_FROM"]
        msg["To"] = user.email
        msg.attach(MIMEText(body, "html"))
        if _send(msg):
            enviados += 1
    return enviados


def send_prazo_alert(user: User, prazo: Prazo) -> bool:
    proc = prazo.processo
    body = f"""
    <h3>Prazo crítico</h3>
    <p><strong>Processo:</strong> {proc.numero_cnj}</p>
    <p><strong>Descrição:</strong> {prazo.descricao}</p>
    <p><strong>Data limite:</strong> {prazo.data_limite.strftime('%d/%m/%Y')}</p>
    <p><strong>Restam:</strong> {prazo.dias_restantes} dia(s)</p>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[PRAZO] {proc.numero_cnj} — {prazo.descricao}"
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = user.email
    msg.attach(MIMEText(body, "html"))
    return _send(msg)


def export_prazos_ics(user: User) -> str:
    """Gera feed iCalendar com os prazos do usuário."""
    from icalendar import Calendar, Event
    from datetime import datetime

    cal = Calendar()
    cal.add("prodid", "-//Lex Praxis//Prazos//PT-BR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    prazos = (Prazo.query
              .filter(Prazo.status == "aberto")
              .filter((Prazo.responsavel_id == user.id) | (Prazo.responsavel_id.is_(None)))
              .all())
    for p in prazos:
        ev = Event()
        ev.add("summary", f"{p.descricao} ({p.processo.numero_cnj})")
        ev.add("dtstart", p.data_limite)
        ev.add("dtend", p.data_limite)
        ev.add("description", f"Processo: {p.processo.numero_cnj}\nDescrição: {p.descricao}")
        ev.add("priority", 1 if p.prioridade in {"alta", "critica"} else 5)
        cal.add_component(ev)
    return cal.to_ical().decode("utf-8")
