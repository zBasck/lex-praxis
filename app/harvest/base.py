"""Interface base para adaptadores de tribunais."""
from __future__ import annotations
import abc
from typing import List
from datetime import datetime


class AndamentoCapturado:
    """Andamento bruto retornado por um adaptador."""
    __slots__ = ("data", "texto", "fonte", "url", "metadados")

    def __init__(self, data: datetime, texto: str, fonte: str, url: str = "", metadados: dict | None = None):
        self.data = data
        self.texto = texto
        self.fonte = fonte
        self.url = url
        self.metadados = metadados or {}


class CourtAdapter(abc.ABC):
    """Contrato para qualquer adaptador de tribunal."""

    #: sigla do tribunal
    tribunal: str = ""

    def __init__(self, timeout: int = 30, user_agent: str | None = None):
        self.timeout = timeout
        self.user_agent = user_agent or (
            "Mozilla/5.0 (compatible; LexPraxis/0.1; +https://lexpraxis.local/bot)"
        )

    @abc.abstractmethod
    def fetch(self, numero_cnj: str) -> List[AndamentoCapturado]:
        """Busca andamentos do processo no portal do tribunal."""
        raise NotImplementedError

    @property
    def is_available(self) -> bool:
        return True
