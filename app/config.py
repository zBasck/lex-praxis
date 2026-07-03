"""Configurações centralizadas.

Sistema operando EXCLUSIVAMENTE com DJE/DJR (PJe Comunica) + OAB.
DataJud/MNI foi REMOVIDO COMPLETAMENTE desta versao.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _default_db_uri() -> str:
    """Tenta criar o banco no instance/; se o FS for read-only, usa /tmp."""
    candidates = [
        BASE_DIR / "instance" / "lex_praxis.db",
        Path("/tmp/lp-data/lex_praxis.db"),
    ]
    for c in candidates:
        try:
            c.parent.mkdir(parents=True, exist_ok=True)
            c.touch()
            c.unlink()
            return "sqlite:///" + str(c.resolve())
        except (OSError, PermissionError):
            continue
    return "sqlite:////tmp/lp-data/lex_praxis.db"


def _build_court_flags() -> dict:
    """Gera flags ENABLE_XX para todos os 85 tribunais do catalogo."""
    from app.harvest.tribunais import TRIBUNAIS
    flags = {}
    for t in TRIBUNAIS:
        env = f"ENABLE_{t.sigla}"
        flags[t.sigla] = _bool(os.getenv(env), True)
    flags["DEMO"] = True
    return flags


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or _default_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Scheduler / harvest
    HARVEST_INTERVAL_MINUTES = int(os.getenv("HARVEST_INTERVAL_MINUTES", "120"))
    HARVEST_RUN_ON_START = _bool(os.getenv("HARVEST_RUN_ON_START"), False)

    # Monitor de OAB no DJE/DJR
    OAB_MONITOR_INTERVAL_MINUTES = int(os.getenv("OAB_MONITOR_INTERVAL_MINUTES", "60"))
    OAB_MONITOR_ENABLED = _bool(os.getenv("OAB_MONITOR_ENABLED"), True)
    DJE_HARVEST_ENABLED = _bool(os.getenv("DJE_HARVEST_ENABLED"), True)
    DJE_HARVEST_DAYS_BACK = int(os.getenv("DJE_HARVEST_DAYS_BACK", "7"))
    DJE_COMUNICA_ENABLED = _bool(os.getenv("DJE_COMUNICA_ENABLED"), False)
    PJE_COMUNICA_URL = os.getenv("PJE_COMUNICA_URL", "https://comunica.pje.jus.br")

    # LLM (classificador opcional)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

    # SMTP (digest diario)
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "Lex Praxis <no-reply@lexpraxis.local>")
    SMTP_USE_TLS = _bool(os.getenv("SMTP_USE_TLS"), True)

    DAILY_DIGEST_HOUR = int(os.getenv("DAILY_DIGEST_HOUR", "7"))
    DAILY_DIGEST_MINUTE = int(os.getenv("DAILY_DIGEST_MINUTE", "0"))

    COURT_FLAGS = _build_court_flags()

    # Admin
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@lexpraxis.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Administrador")
