"""Subpacote core."""
from .extensions import db, login_manager
from .models import User, Cliente, Processo, Andamento, Prazo, AuditLog

__all__ = ["db", "login_manager", "User", "Cliente", "Processo", "Andamento", "Prazo", "AuditLog"]
