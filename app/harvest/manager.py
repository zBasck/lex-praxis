"""Gerenciador de adapters DJe/PJe Comunica.

Camada principal: DJe (PJe Comunica). O registry de tribunais serve
apenas para o harvest por CNJ (publicacoes conhecidas). Para descoberta
de processos novos a partir da OAB, use MonitorOAB + PJeComunicaEngine.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

from flask import current_app

from .base import CourtAdapter, AndamentoCapturado
from .dje_comunica import PJeComunicaEngine, DJeUnavailableError

log = logging.getLogger(__name__)


class HarvestManager:
    """Resolve o engine DJe e oferece fetch por CNJ."""

    def __init__(self, enabled_flags: Optional[Dict[str, bool]] = None, **kwargs):
        self._flags = enabled_flags or {}
        self._engine = PJeComunicaEngine()
        self._kwargs = kwargs

    def get(self, tribunal: str) -> CourtAdapter:
        # O harvest por CNJ usa o PJe Comunica, independente do tribunal.
        # Este metodo existe para compatibilidade com a API antiga.
        return _PJeComunicaAdapter(self._engine, **self._kwargs)

    def fetch(self, tribunal: str, numero_cnj: str) -> List[AndamentoCapturado]:
        try:
            return self._engine.fetch_por_cnj(numero_cnj)
        except DJeUnavailableError:
            return []
        except Exception as e:
            log.exception("Erro ao buscar %s no %s: %s", numero_cnj, tribunal, e)
            return []

    def tribunais_disponiveis(self) -> List[str]:
        from .tribunais import TRIBUNAIS
        return [t.sigla for t in TRIBUNAIS]


class _PJeComunicaAdapter(CourtAdapter):
    tribunal = "PJe-Comunica"

    def __init__(self, engine: PJeComunicaEngine, **kwargs):
        super().__init__(**kwargs)
        self.engine = engine

    def fetch(self, numero_cnj: str) -> List[AndamentoCapturado]:
        try:
            return self.engine.fetch_por_cnj(numero_cnj)
        except DJeUnavailableError:
            return []


_manager: Optional[HarvestManager] = None


def get_manager() -> HarvestManager:
    global _manager
    if _manager is None:
        try:
            cfg = current_app.config
            flags = cfg.get("COURT_FLAGS", {})
        except RuntimeError:
            flags = {}
        _manager = HarvestManager(enabled_flags=flags)
    return _manager
