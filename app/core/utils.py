"""Utilitários diversos."""
import re
import hashlib
from datetime import datetime, date
from dateutil import parser as dateparser


def normalize_cnj(numero: str) -> str:
    """Normaliza número CNJ para 20 dígitos com pontuação."""
    if not numero:
        return ""
    digits = re.sub(r"\D", "", numero)
    if len(digits) != 20:
        return numero.strip()
    return f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:20]}"


def detect_tribunal_from_cnj(numero: str) -> str:
    """Detecta a sigla do tribunal a partir do CNJ (segmento 13-14-15-16).

    O número CNJ tem o formato NNNNNNN-DD.AAAA.J.TR.OOOO, onde:
      - J = ramo da justiça (1 STF/STJ, 2 eleitoral, 3 militar, 4 superior,
        5 federal, 6 federal antiga, 7 trabalho, 8 estadual, 9 juizado)
      - TR = tribunal dentro do ramo (UF para estaduais, nº para federais/trabalho)
    """
    digits = re.sub(r"\D", "", numero or "")
    if len(digits) < 16:
        return ""
    try:
        justica = int(digits[13])
        tribunal_num = int(digits[14:16])
    except (ValueError, IndexError):
        return ""

    # Lazy import para não criar ciclo
    from app.harvest.tribunais import POR_SIGLA

    if justica == 1:
        # STF = 00, STJ = 01
        if tribunal_num == 0:
            return "STF"
        if tribunal_num == 1:
            return "STJ"
        if tribunal_num == 2:
            return "TST"
    if justica == 2:
        # TSE = 00; regionais TREUF
        if tribunal_num == 0:
            return "TSE"
        uf_code = tribunal_num
        uf = _uf_por_segmento_eleitoral(uf_code)
        return f"TRE{uf}" if uf else ""
    if justica == 3:
        return "STM"
    if justica == 7:
        if tribunal_num == 0:
            return "TST"
        return f"TRT{tribunal_num:02d}"
    if justica in (5, 6):
        # TRF 1..5
        if 1 <= tribunal_num <= 5:
            return f"TRF{tribunal_num}"
    if justica == 8:
        # TJ + UF (código 01..27)
        uf = _uf_por_codigo(tribunal_num)
        return f"TJ{uf}" if uf else ""
    if justica == 9:
        # Juizados especiais federais/estaduais — manter TJ/UF como aproximação
        uf = _uf_por_codigo(tribunal_num)
        return f"TJ{uf}" if uf else ""
    return ""


# Códigos UF para o segmento CNJ (ordem alfabética do código, não alfabética do estado)
_CODIGO_UF_CNJ = {
    1: "AC", 2: "AL", 3: "AP", 4: "AM", 5: "BA", 6: "CE", 7: "DF", 8: "ES",
    9: "GO", 10: "MA", 11: "MT", 12: "MS", 13: "MG", 14: "PA", 15: "PB",
    16: "PR", 17: "PE", 18: "PI", 19: "RJ", 20: "RN", 21: "RS", 22: "RO",
    23: "RR", 24: "SC", 25: "SE", 26: "SP", 27: "TO",
}


def _uf_por_codigo(codigo: int) -> str:
    return _CODIGO_UF_CNJ.get(codigo, "")


def _uf_por_segmento_eleitoral(codigo: int) -> str:
    # TREs seguem o mesmo mapeamento de UF dos TJs
    return _uf_por_codigo(codigo)


def parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return date.today()
    try:
        return dateparser.parse(str(value), dayfirst=True).date()
    except Exception:
        return date.today()


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").strip().lower().encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def extrair_cnj_de_texto(texto: str) -> str:
    """Extrai o primeiro número CNJ de 20 dígitos encontrado no texto."""
    if not texto:
        return ""
    m = re.search(r"\b(\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4})\b", texto)
    if m:
        return normalize_cnj(m.group(1))
    m = re.search(r"\b(\d{20})\b", texto)
    if m:
        return normalize_cnj(m.group(1))
    return ""
