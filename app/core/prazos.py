"""Motor de prazos - converte publicacoes DJE em prazos processuais.

Recebe um evento de publicacao (tipo_ato, data_publicacao, texto) e retorna
um Prazo com data_inicio/data_limite calculada por dias uteis.

Regras base (configuraveis via PRAZOS_REGRAS_JSON no .env):
  - sentenca                 -> 15 dias uteis
  - acordao                  -> 15 dias uteis
  - decisao_interlocutoria   -> 10 dias uteis
  - despacho                 -> 5  dias uteis
  - recurso_apelacao         -> 15 dias uteis
  - recurso_agravo           -> 15 dias uteis
  - embargos_declaracao      -> 5  dias uteis
  - embargos_execucao        -> 15 dias uteis
  - contrarrazoes            -> 15 dias uteis
  - contestacao (citacao)    -> 15 dias uteis
  - audiencia                -> sem prazo (data marcada)
  - intimacao                -> 5  dias uteis
  - penhora / alvara         -> sem prazo automatico
  - demais (outros)          -> 10 dias uteis (conservador)
"""
from __future__ import annotations
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)


REGRAS_DEFAULT = {
    "sentenca": {"dias": 15, "marco": "publicacao", "tarefa": "Recurso de apelacao"},
    "acordao": {"dias": 15, "marco": "publicacao", "tarefa": "Recurso / embargos"},
    "decisao_interlocutoria": {"dias": 10, "marco": "publicacao", "tarefa": "Recurso de agravo"},
    "despacho": {"dias": 5, "marco": "publicacao", "tarefa": "Manifestacao sobre despacho"},
    "recurso_apelacao": {"dias": 15, "marco": "publicacao", "tarefa": "Contrarrazoes a apelacao"},
    "recurso_agravo": {"dias": 15, "marco": "publicacao", "tarefa": "Contrarrazoes a agravo"},
    "embargos_declaracao": {"dias": 5, "marco": "publicacao", "tarefa": "Contrarrazoes a embargos"},
    "embargos_execucao": {"dias": 15, "marco": "publicacao", "tarefa": "Manifestacao sobre embargos"},
    "contrarrazoes": {"dias": 15, "marco": "publicacao", "tarefa": "Manifestacao complementar"},
    "contestacao": {"dias": 15, "marco": "citacao", "tarefa": "Contestacao"},
    "citacao": {"dias": 15, "marco": "citacao", "tarefa": "Contestacao"},
    "audiencia": {"dias": 0, "marco": "audiencia", "tarefa": "Comparecer a audiencia"},
    "intimacao": {"dias": 5, "marco": "intimacao", "tarefa": "Cumprir intimacao"},
    "mandado_seguranca": {"dias": 10, "marco": "publicacao", "tarefa": "Manifestacao sobre MS"},
    "tutela_urgencia": {"dias": 5, "marco": "publicacao", "tarefa": "Manifestacao sobre tutela"},
    "penhora": {"dias": 0, "marco": "publicacao", "tarefa": "Manifestacao sobre penhora"},
    "alvara": {"dias": 0, "marco": "publicacao", "tarefa": "Manifestacao sobre alvara"},
    "outros": {"dias": 10, "marco": "publicacao", "tarefa": "Verificar publicacao"},
}


@dataclass
class PrazoCalculado:
    tipo: str
    data_inicio: date
    data_limite: Optional[date]
    marco: str
    tarefa_sugerida: str
    prioridade: str  # alta, normal, baixa
    gera_prazo: bool  # False para audiencia/penhora (data marcada)


def _carregar_regras() -> dict:
    """Permite customizar via env PRAZOS_REGRAS_JSON."""
    raw = os.environ.get("PRAZOS_REGRAS_JSON", "").strip()
    if not raw:
        return REGRAS_DEFAULT
    try:
        cfg = json.loads(raw)
        merged = dict(REGRAS_DEFAULT)
        merged.update(cfg)
        return merged
    except (ValueError, TypeError) as e:
        log.warning("PRAZOS_REGRAS_JSON invalido, usando default: %s", e)
        return REGRAS_DEFAULT


def _dias_uteis(inicio: date, dias: int) -> date:
    """Calcula data limite somando N dias uteis (exclui sabado/domingo).

    Sem suporte a feriados nacionais/estaduais por enquanto (pode evoluir
    via TabelaFeriado se necessario).
    """
    if dias <= 0:
        return inicio
    cur = inicio
    adicionados = 0
    while adicionados < dias:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # 0=seg, 4=sex, 5=sab, 6=dom
            adicionados += 1
    return cur


_DIAS_TEXTO = {
    5: r"cinco|5",
    10: r"dez|10",
    15: r"quinze|15",
    20: r"vinte|20",
    30: r"trinta|30",
}


def _extrair_prazo_do_texto(texto: str) -> Optional[int]:
    """Detecta prazo explícito no texto da publicacao: 'prazo de 15 dias'."""
    if not texto:
        return None
    t = texto.lower()
    m = re.search(r"prazo\s+(?:de\s+)?(\d{1,3})\s*dias?\s*(uteis)?", t)
    if m:
        try:
            n = int(m.group(1))
            return n
        except (ValueError, TypeError):
            return None
    for n, padroes in _DIAS_TEXTO.items():
        m = re.search(rf"prazo\s+(?:de\s+)?({padroes})\s*dias?\s*(uteis)?", t)
        if m:
            return n
    return None


def _normalizar_tipo(tipo_ato: str, texto: str = "") -> str:
    """Mapeia o tipo_ato classificado pela engine DJE para uma chave do motor."""
    if not tipo_ato:
        return "outros"
    t = (tipo_ato or "").lower()
    if "contest" in t:
        return "contestacao"
    if t in REGRAS_DEFAULT:
        return t
    return "outros"


class MotorPrazos:
    """Calcula prazos a partir de publicacoes DJE."""

    def __init__(self):
        self.regras = _carregar_regras()

    def calcular(self, tipo_ato: str, data_publicacao,
                 texto: str = "", permitir_override_texto: bool = True) -> PrazoCalculado:
        """Retorna PrazoCalculado. Se gerar_prazo=False, data_limite pode ser None.

        - tipo_ato: chave do classificador (sentenca, acordao, despacho, etc)
        - data_publicacao: date ou datetime da publicacao
        - texto: texto da publicacao (usado para extrair prazo explicito)
        - permitir_override_texto: se True e o texto disser "prazo de X dias",
          sobrescreve o default.
        """
        if isinstance(data_publicacao, datetime):
            data_publicacao = data_publicacao.date()
        elif not isinstance(data_publicacao, date):
            data_publicacao = date.today()

        chave = _normalizar_tipo(tipo_ato, texto)
        regra = self.regras.get(chave, self.regras["outros"])

        # Override pelo texto (prazo explicito na publicacao)
        if permitir_override_texto and texto:
            prazo_texto = _extrair_prazo_do_texto(texto)
            if prazo_texto and prazo_texto > 0:
                dias = prazo_texto
            else:
                dias = regra["dias"]
        else:
            dias = regra["dias"]

        marco = regra["marco"]
        tarefa = regra["tarefa"]

        # Data inicio depende do marco
        if marco == "citacao" and data_publicacao > date.today():
            # citacao futura improvavel; usa a publicacao
            data_inicio = data_publicacao
        else:
            data_inicio = data_publicacao

        gera_prazo = dias > 0 and chave not in ("audiencia", "penhora", "alvara")
        if gera_prazo:
            data_limite = _dias_uteis(data_inicio, dias)
        else:
            data_limite = None

        if dias == 0:
            prioridade = "normal"
        elif dias <= 5:
            prioridade = "alta"
        elif dias <= 10:
            prioridade = "normal"
        else:
            prioridade = "normal"

        return PrazoCalculado(
            tipo=chave,
            data_inicio=data_inicio,
            data_limite=data_limite,
            marco=marco,
            tarefa_sugerida=tarefa,
            prioridade=prioridade,
            gera_prazo=gera_prazo,
        )


def get_motor() -> MotorPrazos:
    """Singleton lazy do motor."""
    global _motor
    try:
        return _motor
    except NameError:
        _motor = MotorPrazos()
        return _motor
