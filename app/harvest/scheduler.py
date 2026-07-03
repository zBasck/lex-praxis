"""Scheduler APScheduler - gerencia harvests DJe, monitor de OAB e digests.

Jobs:
  - harvest_all: itera processos ativos e busca publicacoes DJe por CNJ
  - oab_monitor_periodic: executa MonitorOAB para todas as OABs ativas
  - daily_digest: digest diario por e-mail
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.harvest.service import harvest_all_active
from app.harvest.dje import HarvestDJe
from app.harvest.oab_capture import MonitorOAB
from app.alerts.emailer import send_daily_digest

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def configure(app):
    """Configura e inicia o scheduler. Idempotente."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    interval = app.config.get("HARVEST_INTERVAL_MINUTES", 120)
    hour = app.config.get("DAILY_DIGEST_HOUR", 7)
    minute = app.config.get("DAILY_DIGEST_MINUTE", 0)
    oab_enabled = app.config.get("OAB_MONITOR_ENABLED", True)
    oab_interval = app.config.get("OAB_MONITOR_INTERVAL_MINUTES", 60)

    # Harvest DJe por CNJ (processos conhecidos)
    scheduler.add_job(
        func=_safe_harvest,
        trigger=IntervalTrigger(minutes=interval),
        id="harvest_all", replace_existing=True,
        max_instances=1, coalesce=True,
    )
    # Monitor de OAB no DJe (descobre processos novos pela OAB)
    if oab_enabled:
        scheduler.add_job(
            func=_safe_oab_monitor,
            trigger=IntervalTrigger(minutes=oab_interval),
            id="oab_monitor_periodic", replace_existing=True,
            max_instances=1, coalesce=True,
        )
    # Digest diario
    scheduler.add_job(
        func=_safe_digest,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_digest", replace_existing=True,
        max_instances=1, coalesce=True,
    )
    if app.config.get("HARVEST_RUN_ON_START"):
        scheduler.add_job(func=_safe_harvest, trigger="date",
                          id="harvest_startup", run_date=datetime.utcnow())
        if oab_enabled:
            scheduler.add_job(func=_safe_oab_monitor, trigger="date",
                              id="oab_startup",
                              run_date=datetime.utcnow() + timedelta(seconds=30))

    scheduler.start()
    _scheduler = scheduler
    log.info("Scheduler iniciado (harvest %s min, OAB %s min, digest %02d:%02d)",
             interval, oab_interval, hour, minute)
    return scheduler


def shutdown():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _safe_harvest():
    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            res = harvest_all_active()
            log.info("Harvest DJe concluido: %s", res)
        except Exception as e:
            log.exception("Erro no harvest: %s", e)


def _safe_oab_monitor():
    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            monitor = MonitorOAB()
            res = monitor.capturar_todas_oabs(days_back=app.config.get("OAB_MONITOR_DAYS_BACK", 7))
            log.info("Monitor OAB concluido: %s", res)
        except Exception as e:
            log.exception("Erro no monitor OAB: %s", e)


def _safe_digest():
    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            n = send_daily_digest()
            log.info("Digest diario: %s destinatarios", n)
        except Exception as e:
            log.exception("Erro no digest: %s", e)
