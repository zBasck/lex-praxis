"""
Engine DJe via DJEN/PJe Comunica (comunicaapi.pje.jus.br).

O DJEN (Diario de Justica Eletronico Nacional) e o agregador oficial de
comunicacoes processuais do CNJ, cobrindo todos os tribunais PJe.

DOCUMENTACAO OFICIAL (DJEN v1.0.4, ultima atualizacao 04-03-2026):
- Endpoints sem cadeado nao exigem autenticacao
- Endpoints autenticados e de login sao exclusivos dos Tribunais
- Uso abusivo esta sujeito a bloqueios. Observar x-ratelimit-* headers

ESTRATEGIAS DE BUSCA (em ordem de prioridade):

1) CONSULTA DIRETA via GET /api/v1/comunicacao (PUBLICO, sem autenticacao):
   GET https://comunicaapi.pje.jus.br/api/v1/comunicacao
       ?numeroOab=<num>&ufOab=<UF>
       &dataDisponibilizacaoInicio=<YYYY-MM-DD>
       &dataDisponibilizacaoFim=<YYYY-MM-DD>
       &siglaTribunal=<TJRJ> (opcional)
   Retorna JSON: {"status":"ok","message":"...","count":N,"items":[...]}
   Cada item contem: numero_processo, data_disponibilizacao, texto,
                      destinatarioadvogados[].advogado.numero_oab/uf_oab,
                      siglaTribunal, link, hash, etc.
   ESTRATEGIA PRIMARIA - funciona sem credenciais e com filtro direto por OAB.

2) CONSULTA POR CNJ via GET /api/v1/comunicacao?numeroProcesso=<CNJ>:
   Mesmo endpoint, filtro por CNJ. Retorna publicacoes daquele processo.
   Usado para atualizar processos cadastrados manualmente.

3) CADERNOS via GET /api/v1/caderno/<TRIB>/<DATA>/<D|J>:
   Retorna {"url": "https://...arquivo.zip"} - download caderno completo
   do dia. Usado como FALLBACK quando a consulta direta falha.
   Cobre todos os ~52 tribunais PJe (STF, STJ, TRFs, TRTs, principais TJs).

4) CONSULTA AUTENTICADA via POST /api/v1/comunicacao (requer login PJe):
   Body: {numeroOab, ufOab, dataDisponibilizacaoInicio, dataDisponibilizacaoFim, siglaTribunal}
   Autenticacao: Basic Auth com usuario+senha PJe
   Ativar no .env: DJE_COMUNICA_AUTH_ENABLED=true
                   DJE_COMUNICA_USER=<seu login PJe>
                   DJE_COMUNICA_PASSWORD=<sua senha PJe>

Para ativar basta: DJE_COMUNICA_ENABLED=true
"""
from __future__ import annotations
import io
import json
import logging
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import requests

from .base import AndamentoCapturado

log = logging.getLogger(__name__)


URL_BASE_WEB = "https://comunica.pje.jus.br"
URL_BASE_API = "https://comunicaapi.pje.jus.br"

# Tribunais cobertos pelo DJEN/PJe Comunica (subset dos ~92 do CNJ).
# Lista alinhada com o swagger oficial do comunicaapi.
TRIBUNAIS_PJE = [
    # Superiores
    "STF", "STJ", "TST", "TSE",
    # Federais
    "TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6",
    # Trabalhistas
    "TRT1", "TRT2", "TRT3", "TRT4", "TRT5", "TRT6", "TRT7", "TRT8",
    "TRT9", "TRT10", "TRT11", "TRT12", "TRT13", "TRT14", "TRT15", "TRT16",
    "TRT17", "TRT18", "TRT19", "TRT20", "TRT21", "TRT22", "TRT23", "TRT24",
    # Estaduais com PJe
    "TJAC", "TJAL", "TJAP", "TJAM", "TJBA", "TJCE", "TJDFT", "TJES",
    "TJGO", "TJMA", "TJMT", "TJMS", "TJMG", "TJPA", "TJPB", "TJPR",
    "TJPE", "TJPI", "TJRJ", "TJRN", "TJRS", "TJRO", "TJRR", "TJSC",
    "TJSP", "TJSE", "TJTO",
]

# Cadernos disponiveis: D = Diario Eletronico, E = Edital
CADERNOS = ["D", "E"]


class DJeUnavailableError(RuntimeError):
    """DJe foi chamado sem DJE_COMUNICA_ENABLED=true."""


class DJeAuthRequiredError(RuntimeError):
    """Endpoint requer autenticacao PJe."""


@dataclass
class PublicacaoDJE:
    """Publicacao estruturada retornada pelo DJEN/PJe Comunica."""
    numero_cnj: str
    data: date
    tipo_ato: str
    texto: str
    partes: str
    tribunal: str
    url: str
    advogados: List[dict] = field(default_factory=list)
    id_comunicacao: Optional[int] = None
    hash: Optional[str] = None
    meio: Optional[str] = None
    classe: Optional[str] = None

    def to_andamento(self) -> AndamentoCapturado:
        hora = datetime.min.time()
        return AndamentoCapturado(
            data=datetime.combine(self.data, hora),
            texto=self.texto,
            fonte=f"{self.tribunal} - DJEN",
            url=self.url,
            metadados={
                "numero_cnj": self.numero_cnj,
                "tipo_ato": self.tipo_ato,
                "partes": self.partes,
                "tribunal": self.tribunal,
                "id_comunicacao": self.id_comunicacao,
                "advogados": self.advogados,
            },
        )


_CNJ_REGEX = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")


def _normalize_cnj(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    if len(digits) != 20:
        return s or ""
    return f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:20]}"


def _extract_cnj(texto: str) -> str:
    m = _CNJ_REGEX.search(texto or "")
    return _normalize_cnj(m.group(0)) if m else ""


def _parse_data_iso(s: str) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Tira timezone no final
    s_clean = re.sub(r"[-+]\d{2}:?\d{2}$", "", s)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(s_clean[:19] if "T" in s_clean else s_clean, fmt[:19] if "T" in s_clean else fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _oab_match(adv: dict, oab_num: str, oab_uf: str) -> bool:
    """Verifica se o advogado do item casa com a OAB procurada."""
    if not isinstance(adv, dict):
        return False
    a = adv.get("advogado") or {}
    num_db = re.sub(r"\D", "", str(a.get("numero_oab") or ""))
    uf_db = (a.get("uf_oab") or "").upper().strip()
    if oab_uf and uf_db != oab_uf.upper():
        return False
    if oab_num and num_db != oab_num:
        return False
    return True


class PJeComunicaEngine:
    """Coleta publicacoes do DJE via DJEN/PJe Comunica (CNJ)."""

    def __init__(self, enabled=None, timeout: int = 30, user_agent: str = ""):
        env = (os.environ.get("DJE_COMUNICA_ENABLED", "") or "").lower()
        if enabled is None:
            enabled = env in ("1", "true", "yes", "on")
        self.enabled = bool(enabled)
        self.timeout = timeout
        self.user_agent = user_agent or (
            "Mozilla/5.0 (compatible; LexPraxis/1.0; +https://lexpraxis.local/bot)"
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        })
        # Modo autenticado (opcional)
        auth_env = (os.environ.get("DJE_COMUNICA_AUTH_ENABLED", "") or "").lower()
        self.auth_enabled = auth_env in ("1", "true", "yes", "on")
        self.auth_user = os.environ.get("DJE_COMUNICA_USER", "") or ""
        self.auth_password = os.environ.get("DJE_COMUNICA_PASSWORD", "") or ""
        if self.auth_enabled and (self.auth_user and self.auth_password):
            self.session.auth = (self.auth_user, self.auth_password)
        # Stats para UI
        self._last_scan_stats = {
            "modo": "desabilitado",
            "request_count": 0,
            "items_recebidos": 0,
            "items_apos_filtro": 0,
        }

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        s = {
            "enabled": self.enabled,
            "url_base": URL_BASE_WEB,
            "url_api": URL_BASE_API,
            "modo": "real" if self.enabled else "desabilitado",
            "auth_enabled": self.auth_enabled and bool(self.auth_user),
            "auth_user": self.auth_user if self.auth_enabled else "",
            "tribunais_cobertos": len(TRIBUNAIS_PJE),
        }
        if hasattr(self, "_last_scan_stats"):
            s["last_scan"] = self._last_scan_stats
        return s

    def _require_enabled(self):
        if not self.enabled:
            raise DJeUnavailableError(
                "DJe Comunica desabilitado. Para ativar a coleta real, "
                "defina no .env: DJE_COMUNICA_ENABLED=true. "
                "O sistema NAO gera publicacoes sinteticas."
            )

    def _get(self, path: str, params: Optional[dict] = None) -> Tuple[Optional[dict], Optional[str]]:
        """GET com tratamento de erro. Retorna (json, erro)."""
        url = f"{URL_BASE_API}{path}"
        self._last_scan_stats["request_count"] += 1
        try:
            r = self.session.get(url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as e:
            return None, f"conexao: {e}"
        if r.status_code == 401 or r.status_code == 403:
            return None, f"autenticacao requerida (HTTP {r.status_code})"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {(r.text or '')[:200]}"
        try:
            data = r.json()
        except ValueError as e:
            return None, f"resposta nao-JSON: {e}"
        # Detecta HTTP 200 com payload de erro (DJEN as vezes faz isso)
        if isinstance(data, dict) and data.get("status") == "error":
            return None, f"API: {data.get('message', 'erro sem mensagem')}"
        return data, None

    def _post(self, path: str, body: dict) -> Tuple[Optional[dict], Optional[str]]:
        """POST com tratamento de erro."""
        url = f"{URL_BASE_API}{path}"
        self._last_scan_stats["request_count"] += 1
        try:
            r = self.session.post(url, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            return None, f"conexao: {e}"
        if r.status_code == 401 or r.status_code == 403:
            return None, f"autenticacao invalida (HTTP {r.status_code})"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {(r.text or '')[:200]}"
        try:
            return r.json(), None
        except ValueError as e:
            return None, f"resposta nao-JSON: {e}"

    # ===================================================================
    # CONSULTA DIRETA (PRIMARIA) - GET /api/v1/comunicacao
    # Documentado como PUBLICO no swagger do DJEN.
    # ===================================================================
    def _consulta_publica(self, params: dict) -> Tuple[List[PublicacaoDJE], Optional[str]]:
        """Consulta direta via GET /api/v1/comunicacao (PUBLICO)."""
        data, err = self._get("/api/v1/comunicacao", params=params)
        if err:
            return [], err
        if not isinstance(data, dict):
            return [], f"resposta inesperada: {type(data).__name__}"
        # DJEN retorna HTTP 200 + {"message":"Server Error"} quando ha
        # bug no servidor (ex: OAB pura com 4 params juntos). Detecta:
        if data.get("status") == "error" or ("message" in data and "items" not in data and "count" not in data):
            return [], f"API retornou erro: {data.get('message', 'sem mensagem')}"
        items = data.get("items") or data.get("data") or []
        if not isinstance(items, list):
            return [], "campo 'items' nao e uma lista"
        self._last_scan_stats["items_recebidos"] += len(items)
        pubs: List[PublicacaoDJE] = []
        for item in items:
            pub = self._parse_item_publicacao(item)
            if pub is not None:
                pubs.append(pub)
        return pubs, None

    # ===================================================================
    # fetch_por_oab - estrategia primaria
    # ===================================================================
    def fetch_por_oab(self, numero_oab: str, uf: str,
                      days_back: int = 7,
                      tribunais: Optional[List[str]] = None
                      ) -> List[PublicacaoDJE]:
        """Busca publicacoes por OAB.

        Estrategia 1 (primaria): GET /api/v1/comunicacao?numeroOab&ufOab
                                  (PUBLICO, sem autenticacao, filtro direto).
        Estrategia 2 (fallback):  cadernos diarios + filtro local OAB.
        Estrategia 3 (autenticada): POST com credenciais PJe.
        """
        self._require_enabled()
        numero_oab = re.sub(r"\D", "", str(numero_oab or ""))
        uf = (uf or "").upper().strip()
        if not numero_oab:
            raise ValueError("Numero de OAB vazio")
        if not uf or len(uf) != 2:
            raise ValueError(f"UF invalida: {uf!r} (esperado 2 letras)")

        modo = "autenticado" if (self.auth_enabled and self.auth_user) else "publico"
        self._last_scan_stats["modo"] = modo
        self._last_scan_stats["request_count"] = 0
        self._last_scan_stats["items_recebidos"] = 0
        self._last_scan_stats["items_apos_filtro"] = 0

        # Estrategia 1: consulta direta (publica)
        pubs, err = self._consulta_publica_oab(numero_oab, uf, days_back, tribunais)
        estrategia = "consulta_direta"
        if err:
            log.warning("DJe consulta direta OAB falhou (%s), tentando cadernos...", err)
            # Estrategia 2: cadernos + filtro local
            pubs, err2 = self._fetch_por_oab_cadernos(numero_oab, uf, days_back, tribunais)
            estrategia = "cadernos"
            if err2:
                log.error("DJe cadernos OAB tambem falhou: %s", err2)
                # Estrategia 3: autenticada (se disponivel)
                if self.auth_enabled and self.auth_user:
                    pubs, err3 = self._fetch_por_oab_auth(numero_oab, uf, days_back, tribunais)
                    estrategia = "autenticado"
                    if err3:
                        raise RuntimeError(
                            f"DJe indisponivel: consulta_direta={err}; "
                            f"cadernos={err2}; autenticado={err3}"
                        )

        # Dedup
        seen = set()
        deduped: List[PublicacaoDJE] = []
        for p in pubs:
            key = (p.numero_cnj, p.data.isoformat(), p.id_comunicacao, p.hash)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(p)
        self._last_scan_stats["items_apos_filtro"] = len(deduped)
        self._last_scan_stats["estrategia"] = estrategia
        self._last_scan_stats["oab"] = f"{numero_oab}/{uf}"
        self._last_scan_stats["days_back"] = days_back
        log.info(
            "DJe OAB %s/%s: estrategia=%s, %d publicacoes (de %d items)",
            numero_oab, uf, estrategia, len(deduped), self._last_scan_stats["items_recebidos"],
        )
        return deduped

    def _consulta_publica_oab(self, oab: str, uf: str, days_back: int,
                               tribunais: Optional[List[str]] = None,
                               escopo: str = "nacional") -> Tuple[List[PublicacaoDJE], Optional[str]]:
        """GET /api/v1/comunicacao com filtro por OAB+UF. PUBLICO.

        Por padrao, faz busca NACIONAL (sem siglaTribunal) - o que permite
        encontrar publicacoes da OAB em qualquer tribunal PJe do Brasil.
        Se o usuario passar tribunais=[...] E escopo='restrito', filtra.
        """
        data_fim = date.today()
        data_inicio = data_fim - timedelta(days=days_back)
        params = {
            "numeroOab": oab,
            "ufOab": uf,
            "dataDisponibilizacaoInicio": data_inicio.isoformat(),
            "dataDisponibilizacaoFim": data_fim.isoformat(),
        }
        # Apenas filtra por tribunal quando o usuario restringiu explicitamente.
        if escopo == "restrito" and tribunais and len(tribunais) == 1:
            params["siglaTribunal"] = tribunais[0]
        pubs, err = self._consulta_publica(params)
        if err:
            return [], err
        # A API ja filtra por OAB; confere se todos os itens retornados
        # realmente casam (defesa em profundidade)
        out: List[PublicacaoDJE] = []
        for p in pubs:
            advs = p.advogados
            if not any(
                re.sub(r"\D", "", str(a.get("numero_oab") or "")) == oab
                and (a.get("uf_oab") or "").upper() == uf
                for a in advs
            ):
                continue
            out.append(p)
        return out, None

    def _fetch_por_oab_auth(self, oab: str, uf: str, days_back: int,
                            tribunais: Optional[List[str]]) -> Tuple[List[PublicacaoDJE], Optional[str]]:
        """POST /api/v1/comunicacao autenticado."""
        data_fim = date.today()
        data_inicio = data_fim - timedelta(days=days_back)
        body = {
            "numeroOab": oab,
            "ufOab": uf,
            "dataDisponibilizacaoInicio": data_inicio.isoformat(),
            "dataDisponibilizacaoFim": data_fim.isoformat(),
        }
        if tribunais and len(tribunais) == 1:
            body["siglaTribunal"] = tribunais[0]
        data, err = self._post("/api/v1/comunicacao", body)
        if err:
            return [], err
        if not isinstance(data, dict):
            return [], "resposta nao e dict"
        items = data.get("items") or []
        pubs: List[PublicacaoDJE] = []
        for item in items:
            pub = self._parse_item_publicacao(item)
            if pub is not None:
                pubs.append(pub)
        return pubs, None

    # ===================================================================
    # fetch_por_cnj - consulta por CNJ
    # ===================================================================
    def fetch_por_cnj(self, numero_cnj: str, days_back: int = 30,
                      tribunais: Optional[List[str]] = None
                      ) -> List[AndamentoCapturado]:
        """Busca publicacoes de um CNJ especifico.

        Estrategia 1: GET /api/v1/comunicacao?numeroProcesso=<CNJ> (PUBLICO)
        Estrategia 2: cadernos + filtro local
        """
        self._require_enabled()
        cnj = _normalize_cnj(numero_cnj)
        if not _CNJ_REGEX.search(cnj):
            raise ValueError(f"CNJ invalido: {numero_cnj} (esperado 20 digitos)")

        self._last_scan_stats["modo"] = "publico" if not (self.auth_enabled and self.auth_user) else "autenticado"
        self._last_scan_stats["request_count"] = 0
        self._last_scan_stats["items_recebidos"] = 0
        self._last_scan_stats["items_apos_filtro"] = 0

        # Estrategia 1: consulta direta
        pubs, err = self._consulta_publica_cnj(cnj, days_back, tribunais)
        estrategia = "consulta_direta"
        if err:
            log.warning("DJe consulta direta CNJ falhou (%s), tentando cadernos...", err)
            pubs, err2 = self._fetch_por_cnj_cadernos(cnj, days_back, tribunais)
            estrategia = "cadernos"
            if err2 and self.auth_enabled and self.auth_user:
                body = {
                    "numeroProcesso": cnj,
                    "dataDisponibilizacaoInicio": (date.today() - timedelta(days=days_back)).isoformat(),
                    "dataDisponibilizacaoFim": date.today().isoformat(),
                }
                if tribunais and len(tribunais) == 1:
                    body["siglaTribunal"] = tribunais[0]
                data, err3 = self._post("/api/v1/comunicacao", body)
                if not err3 and isinstance(data, dict):
                    items = data.get("items") or []
                    pubs = []
                    for item in items:
                        pub = self._parse_item_publicacao(item)
                        if pub is not None:
                            pubs.append(pub)
                    estrategia = "autenticado"

        # Dedup
        seen = set()
        deduped: List[PublicacaoDJE] = []
        for p in pubs:
            key = (p.numero_cnj, p.data.isoformat(), p.id_comunicacao, p.hash)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(p)
        self._last_scan_stats["items_apos_filtro"] = len(deduped)
        self._last_scan_stats["estrategia"] = estrategia
        self._last_scan_stats["cnj"] = cnj
        log.info(
            "DJe CNJ %s: estrategia=%s, %d publicacoes",
            cnj, estrategia, len(deduped),
        )
        return [p.to_andamento() for p in deduped]

    def _consulta_publica_cnj(self, cnj: str, days_back: int,
                               tribunais: Optional[List[str]]) -> Tuple[List[PublicacaoDJE], Optional[str]]:
        """GET /api/v1/comunicacao com filtro por CNJ."""
        data_fim = date.today()
        data_inicio = data_fim - timedelta(days=days_back)
        # O CNJ puro (20 digitos) sem mascara e o que costuma funcionar
        cnj_digits = re.sub(r"\D", "", cnj)
        params = {
            "numeroProcesso": cnj_digits,
            "dataDisponibilizacaoInicio": data_inicio.isoformat(),
            "dataDisponibilizacaoFim": data_fim.isoformat(),
        }
        if tribunais and len(tribunais) == 1:
            params["siglaTribunal"] = tribunais[0]
        pubs, err = self._consulta_publica(params)
        if err:
            return [], err
        # Filtra localmente (a API pode trazer mais de um match)
        out: List[PublicacaoDJE] = []
        for p in pubs:
            if p.numero_cnj == cnj:
                out.append(p)
        return out, None

    # ===================================================================
    # Estrategia de cadernos (fallback)
    # ===================================================================
    def _fetch_por_oab_cadernos(self, oab: str, uf: str, days_back: int,
                                 tribunais: Optional[List[str]]) -> Tuple[List[PublicacaoDJE], Optional[str]]:
        """Varre cadernos e filtra localmente por OAB+UF."""
        lista = tribunais or TRIBUNAIS_PJE
        tasks = []
        for trib in lista:
            for d in range(days_back):
                dia = date.today() - timedelta(days=d)
                for caderno in CADERNOS:
                    tasks.append((trib, dia, caderno))

        cadernos_varridos = 0
        pubs: List[PublicacaoDJE] = []
        with ThreadPoolExecutor(max_workers=12) as ex:
            futs = {
                ex.submit(
                    self._fetch_caderno_dia,
                    trib, dia, caderno,
                    filtro_oab=oab, filtro_uf=uf,
                ): (trib, dia, caderno)
                for trib, dia, caderno in tasks
            }
            for fut in as_completed(futs):
                try:
                    res = fut.result()
                except Exception as e:  # noqa: BLE001
                    log.debug("caderno %s falhou: %s", futs[fut], e)
                    continue
                cadernos_varridos += 1
                pubs.extend(res)

        self._last_scan_stats["cadernos_varridos"] = cadernos_varridos
        self._last_scan_stats["items_recebidos"] += len(pubs)
        return pubs, None

    def _fetch_por_cnj_cadernos(self, cnj: str, days_back: int,
                                 tribunais: Optional[List[str]]) -> Tuple[List[PublicacaoDJE], Optional[str]]:
        """Varre cadernos e filtra localmente por CNJ."""
        lista = tribunais or TRIBUNAIS_PJE
        tasks = []
        for trib in lista:
            for d in range(days_back):
                dia = date.today() - timedelta(days=d)
                for caderno in CADERNOS:
                    tasks.append((trib, dia, caderno))

        cadernos_varridos = 0
        pubs: List[PublicacaoDJE] = []
        with ThreadPoolExecutor(max_workers=12) as ex:
            futs = {
                ex.submit(
                    self._fetch_caderno_dia,
                    trib, dia, caderno,
                    filtro_cnj=cnj,
                ): (trib, dia, caderno)
                for trib, dia, caderno in tasks
            }
            for fut in as_completed(futs):
                try:
                    res = fut.result()
                except Exception as e:  # noqa: BLE001
                    log.debug("caderno %s falhou: %s", futs[fut], e)
                    continue
                cadernos_varridos += 1
                pubs.extend(res)

        self._last_scan_stats["cadernos_varridos"] = cadernos_varridos
        self._last_scan_stats["items_recebidos"] += len(pubs)
        return pubs, None

    def _fetch_caderno_dia(self, tribunal: str, dia: date, caderno: str = "D",
                            filtro_oab: str = "", filtro_uf: str = "",
                            filtro_cnj: str = "") -> List[PublicacaoDJE]:
        """Baixa o caderno do dia para um tribunal e filtra publicacoes."""
        path = f"/api/v1/caderno/{tribunal}/{dia.isoformat()}/{caderno}"
        data, err = self._get(path)
        if err:
            return []
        if not isinstance(data, dict):
            return []
        zip_url = data.get("url")
        if not zip_url:
            return []
        try:
            r2 = self.session.get(zip_url, timeout=self.timeout * 3)
            r2.raise_for_status()
        except requests.RequestException as e:
            log.debug("download %s falhou: %s", zip_url, e)
            return []
        try:
            zf = zipfile.ZipFile(io.BytesIO(r2.content))
        except zipfile.BadZipFile as e:
            log.debug("zip invalido %s: %s", zip_url, e)
            return []
        out: List[PublicacaoDJE] = []
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            try:
                content = zf.read(name).decode("utf-8", errors="ignore")
                item = json.loads(content)
                if not isinstance(item, dict):
                    continue
                pub = self._parse_item_publicacao(item)
                if pub is None:
                    continue
                # Filtro local
                if filtro_oab and not any(
                    re.sub(r"\D", "", str(a.get("numero_oab") or "")) == filtro_oab
                    and (a.get("uf_oab") or "").upper() == filtro_uf
                    for a in pub.advogados
                ):
                    continue
                if filtro_cnj and pub.numero_cnj != filtro_cnj:
                    continue
                out.append(pub)
            except Exception as e:  # noqa: BLE001
                log.debug("parse %s falhou: %s", name, e)
                continue
        return out

    # ===================================================================
    # Parsing comum
    # ===================================================================
    def _parse_item_publicacao(self, item) -> Optional[PublicacaoDJE]:
        if not isinstance(item, dict):
            return None
        cnj = (item.get("numero_processo")
               or item.get("numeroProcesso")
               or item.get("numeroprocessocommascara")
               or "")
        cnj_norm = _normalize_cnj(cnj) or _extract_cnj(
            item.get("texto") or item.get("numeroprocessocommascara") or ""
        )
        if not cnj_norm:
            return None
        data_str = (item.get("data_disponibilizacao")
                    or item.get("datadisponibilizacao")
                    or item.get("dataDisponibilizacao")
                    or item.get("data_publicacao")
                    or "")
        data_pub = _parse_data_iso(data_str) or date.today()
        dests = item.get("destinatarios") or []
        partes_parts = []
        for d in dests:
            if isinstance(d, dict):
                polo = d.get("polo", "?")
                nome = d.get("nome", "")
                if nome:
                    partes_parts.append(f"{polo}: {nome}")
        partes = "; ".join(partes_parts)
        advs_raw = item.get("destinatarioadvogados") or []
        lista_advs = []
        for a in advs_raw:
            if isinstance(a, dict):
                ad = a.get("advogado") or {}
                if isinstance(ad, dict):
                    lista_advs.append({
                        "nome": ad.get("nome"),
                        "numero_oab": ad.get("numero_oab"),
                        "uf_oab": ad.get("uf_oab"),
                    })
        return PublicacaoDJE(
            numero_cnj=cnj_norm,
            data=data_pub,
            tipo_ato=(item.get("tipoComunicacao")
                      or item.get("tipo_comunicacao")
                      or item.get("tipoDocumento")
                      or "outros"),
            texto=(item.get("texto") or "")[:4000],
            partes=partes,
            tribunal=(item.get("siglaTribunal")
                      or item.get("sigla_tribunal")
                      or "DJEN"),
            url=(item.get("link") or item.get("url") or ""),
            advogados=lista_advs,
            id_comunicacao=(item.get("numeroComunicacao")
                            or item.get("numero_comunicacao")
                            or item.get("id")),
            hash=item.get("hash"),
            meio=(item.get("meio") or item.get("meiocompleto")),
            classe=(item.get("nomeClasse")
                    or item.get("codigoClasse")
                    or item.get("classe")),
        )
