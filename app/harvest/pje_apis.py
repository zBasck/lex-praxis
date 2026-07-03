"""Integracao com APIs publicas do PJe/TJRJ para enriquecer cadastros.

Modulos:
- TJRJ OrgaosService (publico, JSON): lista comarcas e orgaos julgadores
- DJEN Comunica (publico, JSON): ja usado em dje_comunica.py

MNI (Modelo Nacional de Interoperabilidade) e SOAP/XML, exige
certificado digital A1/A3 ou credencial PJe. Nao integrado aqui -
para usar, instale zeep e implemente o client por tribunal.
"""
import logging
from typing import Optional, Dict, List
import requests

log = logging.getLogger(__name__)

TJRJ_ORGAOS_URL = "https://www3.tjrj.jus.br/orgaoservicepub/api/ServicoPub/Orgao"
TJRJ_COMARCAS_URL = "https://www3.tjrj.jus.br/orgaoservicepub/api/ServicoPub/Comarca"
DEFAULT_TIMEOUT = 8


def _get(url: str, params: Optional[dict] = None, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict]:
    try:
        r = requests.get(url, params=params or {}, timeout=timeout,
                         headers={"Accept": "application/json"})
        if r.ok:
            return r.json()
    except Exception as e:
        log.debug("TJRJ API %s falhou: %s", url, e)
    return None


def listar_orgaos_tjrj(pagina: int = 1, tamanho: int = 50,
                       comarca_codigo: Optional[int] = None) -> List[dict]:
    """Lista orgaos julgadores do TJRJ (ate 2023 resultados)."""
    params = {"page": pagina, "size": tamanho}
    if comarca_codigo is not None:
        params["comarca"] = comarca_codigo
    data = _get(TJRJ_ORGAOS_URL, params)
    if not data:
        return []
    return data.get("data") or []


def listar_comarcas_tjrj(pagina: int = 1, tamanho: int = 50) -> List[dict]:
    """Lista comarcas do TJRJ."""
    data = _get(TJRJ_COMARCAS_URL, {"page": pagina, "size": tamanho})
    if not data:
        return []
    return data.get("data") or []


# Cache local de orgaos TJRJ (carregado lazily, 1h TTL)
_ORGAOS_CACHE: List[dict] = []
_CACHE_TTL_S = 3600
_CACHE_LOADED_AT: float = 0

def _orgaos_todos() -> List[dict]:
    """Retorna a lista completa de orgaos TJRJ. Como a API so retorna
    10 por pagina (bug do servidor) e nao aceita page diferente,
    esta funcao retorna uma lista limitada. Para o uso real, prefira
    a busca on-demand por comarca."""
    global _ORGAOS_CACHE, _CACHE_LOADED_AT
    import time
    if _ORGAOS_CACHE and (time.time() - _CACHE_LOADED_AT) < _CACHE_TTL_S:
        return _ORGAOS_CACHE
    # Carrega paginas (max 10, ate 100 orgaos, suficiente para matches mais provaveis)
    out: List[dict] = []
    for pagina in range(1, 11):
        d = _get(TJRJ_ORGAOS_URL, {"page": pagina, "size": 10})
        if not d or not d.get("data"):
            break
        out.extend(d["data"])
    _ORGAOS_CACHE = out
    _CACHE_LOADED_AT = time.time()
    return out

def buscar_orgao_por_nome(nome: str, limite: int = 5) -> List[dict]:
    """Busca orgaos por trecho do nome (case-insensitive).
    A API do TJRJ ignora o parametro page e devolve sempre as primeiras
    10 entradas. Esta funcao faz o melhor que pode: busca nas primeiras
    paginas. Para uso avancado, o cliente deve usar o modulo de comarca
    (buscar_orgao_por_comarca)."""
    if not nome or len(nome) < 3:
        return []
    nome_lower = nome.lower()
    encontrados: List[dict] = []
    for o in _orgaos_todos():
        if o.get("ativo") != "S":
            continue
        if nome_lower in (o.get("nome") or "").lower():
            encontrados.append(o)
            if len(encontrados) >= limite:
                return encontrados
    return encontrados

def buscar_orgao_por_comarca(cod_comarca: int, limite: int = 50) -> List[dict]:
    """Lista orgaos de uma comarca especifica do TJRJ."""
    if not cod_comarca:
        return []
    d = _get(TJRJ_ORGAOS_URL, {"comarca": cod_comarca, "size": 50})
    if not d:
        return []
    return d.get("data") or []


def enriquecer_orgao_de_nome(nome_parcial: str) -> Optional[dict]:
    """Tenta encontrar o orgao TJRJ a partir de um nome parcial (vara)."""
    matches = buscar_orgao_por_nome(nome_parcial, limite=1)
    return matches[0] if matches else None
