"""Subpacote alerts."""
from .emailer import send_daily_digest, send_prazo_alert, export_prazos_ics

__all__ = ["send_daily_digest", "send_prazo_alert", "export_prazos_ics"]
