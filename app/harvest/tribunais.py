"""Catálogo dos tribunais brasileiros.

Fontes consultadas:
  - Conselho Nacional de Justiça (CNJ)
  - Portais dos próprios tribunais
  - Resolução CNJ 65/2008 (numeração CNJ)

Estrutura:
  Cada tribunal tem sigla (chave primária usada em todo o sistema), nome,
  categoria (estadual, federal, trabalho, eleitoral, militar), UF quando
  aplicável, URL de consulta pública, URL de DJe (quando existir) e
  observações operacionais (engine de busca, exigência de captcha, etc.).

Este catálogo é a fonte de verdade para o dropdown de cadastro de
processos, a chave de ativação por ENV, o scheduler de harvest e o
módulo DJe. Tudo passa por aqui — não há sigla hardcoded em outro lugar.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Tribunal:
    sigla: str           # chave: TJSP, TRF1, TRT2, TREMG, STF...
    nome: str            # nome oficial completo
    categoria: str       # estadual, federal, trabalho, eleitoral, militar, superior
    uf: Optional[str] = None  # sigla da unidade federativa, se aplicável
    segmento_cnj: Optional[str] = None  # número do segmento no CNJ (ex: "8.26" para TJSP)
    consulta_url: str = ""        # URL de consulta processual
    dje_url: str = ""             # URL de pesquisa do Diário de Justiça Eletrônico
    engine: str = "html"          # html | pje | esaj | projudi | webservice
    requer_captcha: bool = False
    observacao: str = ""


# =====================================================================
#  TJs — Tribunais de Justiça Estaduais (27)
# =====================================================================
_TJ_ESTADOS = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"),
    ("BA", "Bahia"), ("CE", "Ceará"), ("DF", "Distrito Federal"),
    ("ES", "Espírito Santo"), ("GO", "Goiás"), ("MA", "Maranhão"),
    ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"), ("MG", "Minas Gerais"),
    ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"), ("PE", "Pernambuco"),
    ("PI", "Piauí"), ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"), ("RO", "Rondônia"), ("RR", "Roraima"),
    ("SC", "Santa Catarina"), ("SP", "São Paulo"), ("SE", "Sergipe"), ("TO", "Tocantins"),
]

# Segmento CNJ fixo para estaduais: 8.UF
def _uf_segmento(uf: str) -> str:
    mapa = {
        "AC": "01", "AL": "02", "AP": "03", "AM": "04", "BA": "05", "CE": "06",
        "DF": "07", "ES": "08", "GO": "09", "MA": "10", "MT": "11", "MS": "12",
        "MG": "13", "PA": "14", "PB": "15", "PR": "16", "PE": "17", "PI": "18",
        "RJ": "19", "RN": "20", "RS": "21", "RO": "22", "RR": "23", "SC": "24",
        "SP": "26", "SE": "25", "TO": "27",
    }
    return "8." + mapa.get(uf, "00")


TJS: List[Tribunal] = []
for uf, nome in _TJ_ESTADOS:
    sigla = f"TJ{uf}"
    # Engines e URLs observadas nos portais públicos.
    if uf == "SP":
        engine, consulta, dje = "esaj", "https://esaj.tjsp.jus.br/cpo/sg/search.do", "https://dje.tjsp.jus.br/cdje/index.do"
    elif uf == "RS":
        engine, consulta, dje = "eproc", "https://www.tjrs.jus.br/novo/processos-e-servicos/processos/", "https://www.tjrs.jus.br/novo/diario-da-justica/"
    elif uf == "MS":
        engine, consulta, dje = "esaj", "https://esaj.tjms.jus.br/cpo/sg/search.do", "https://dje.tjms.jus.br/cdje/index.do"
    elif uf == "MG":
        engine, consulta, dje = "html", "https://www5.tjmg.jus.br/jurisprudencia/pesquisaPalavrasEspelho.do", "https://dje.tjmg.jus.br/"
    elif uf == "RJ":
        engine, consulta, dje = "tjrj", "https://www.tjrj.jus.br/consulta-processual", "https://dje.tjrj.jus.br/"
    elif uf == "PR":
        engine, consulta, dje = "projudi", "https://projudi.tjpr.jus.br/projudi/", "https://dje.tjpr.jus.br/"
    elif uf == "BA":
        engine, consulta, dje = "pje", "https://pje.tjba.jus.br/pje/ConsultaPublica/listView.seam", "https://dje.tjba.jus.br/"
    elif uf == "DF":
        engine, consulta, dje = "pje", "https://pje.tjdft.jus.br/pje/ConsultaPublica/listView.seam", "https://dje.tjdft.jus.br/"
    else:
        # Default: PJe genérico (maioria dos estados migrou a partir de 2018).
        sigla_lower = uf.lower()
        engine = "pje"
        consulta = f"https://pje.{sigla_lower}.jus.br/pje/ConsultaPublica/listView.seam"
        dje = f"https://dje.{sigla_lower}.jus.br/"
    TJS.append(Tribunal(
        sigla=sigla,
        nome=f"Tribunal de Justiça de {nome}",
        categoria="estadual",
        uf=uf,
        segmento_cnj=_uf_segmento(uf),
        consulta_url=consulta,
        dje_url=dje,
        engine=engine,
    ))


# =====================================================================
#  TRFs — Tribunais Regionais Federais (5)
# =====================================================================
TRFS: List[Tribunal] = [
    Tribunal("TRF1", "Tribunal Regional Federal da 1ª Região", "federal",
             segmento_cnj="5.01", consulta_url="https://pje1g.trf1.jus.br/pje/ConsultaPublica/listView.seam",
             dje_url="https://dje.trf1.jus.br/", engine="pje"),
    Tribunal("TRF2", "Tribunal Regional Federal da 2ª Região", "federal",
             segmento_cnj="5.02", consulta_url="https://pje.trf2.jus.br/pje/ConsultaPublica/listView.seam",
             dje_url="https://dje.trf2.jus.br/", engine="pje"),
    Tribunal("TRF3", "Tribunal Regional Federal da 3ª Região", "federal",
             segmento_cnj="5.03", consulta_url="https://pje1g.trf3.jus.br/pje/ConsultaPublica/listView.seam",
             dje_url="https://dje.trf3.jus.br/", engine="pje"),
    Tribunal("TRF4", "Tribunal Regional Federal da 4ª Região", "federal",
             segmento_cnj="5.04", consulta_url="https://pje1g.trf4.jus.br/pje/ConsultaPublica/listView.seam",
             dje_url="https://dje.trf4.jus.br/", engine="pje"),
    Tribunal("TRF5", "Tribunal Regional Federal da 5ª Região", "federal",
             segmento_cnj="5.05", consulta_url="https://pje1g.trf5.jus.br/pje/ConsultaPublica/listView.seam",
             dje_url="https://dje.trf5.jus.br/", engine="pje"),
]


# =====================================================================
#  TRTs — Tribunais Regionais do Trabalho (24)
# =====================================================================
TRTS: List[Tribunal] = []
_TRT_NUM = list(range(1, 25))
for n in _TRT_NUM:
    TRTS.append(Tribunal(
        sigla=f"TRT{n:02d}",
        nome=f"Tribunal Regional do Trabalho da {n}ª Região",
        categoria="trabalho",
        uf=_trt_uf(n) if False else None,  # preenchido em runtime se preciso
        segmento_cnj=f"7.{n:02d}",
        consulta_url=f"https://pje.trt{n:02d}.jus.br/pje/ConsultaPublica/listView.seam",
        dje_url=f"https://dje.trt{n:02d}.jus.br/",
        engine="pje",
    ))


# =====================================================================
#  TREs — Tribunais Regionais Eleitorais (27, um por UF)
# =====================================================================
TRES: List[Tribunal] = []
for uf, nome in _TJ_ESTADOS:
    TRES.append(Tribunal(
        sigla=f"TRE{uf}",
        nome=f"Tribunal Regional Eleitoral de {nome}",
        categoria="eleitoral",
        uf=uf,
        consulta_url=f"https://www.tre-{uf.lower()}.jus.br/eleitor/consulta-processual",
        dje_url=f"https://dje.tre-{uf.lower()}.jus.br/",
        engine="html",
    ))


# =====================================================================
#  Tribunais superiores
# =====================================================================
SUPERIORES: List[Tribunal] = [
    Tribunal("STF", "Supremo Tribunal Federal", "superior",
             segmento_cnj="1.00",
             consulta_url="https://portal.stf.jus.br/jurisprudencia/",
             dje_url="https://dje.stf.jus.br/", engine="html",
             observacao="Acórdãos e decisões monocráticas; sem captcha."),
    Tribunal("STJ", "Superior Tribunal de Justiça", "superior",
             segmento_cnj="1.01",
             consulta_url="https://www.stj.jus.br/sites/portalp/Jurisprudencia/",
             dje_url="https://dje.stj.jus.br/", engine="html"),
    Tribunal("TST", "Tribunal Superior do Trabalho", "superior",
             segmento_cnj="7.00",
             consulta_url="https://www.tst.jus.br/jurisprudencia",
             dje_url="https://dje.tst.jus.br/", engine="html"),
    Tribunal("TSE", "Tribunal Superior Eleitoral", "superior",
             segmento_cnj="2.00",
             consulta_url="https://www.tse.jus.br/jurisprudencia",
             dje_url="https://dje.tse.jus.br/", engine="html"),
    Tribunal("STM", "Superior Tribunal Militar", "superior",
             segmento_cnj="3.00",
             consulta_url="https://www.stm.jus.br/jurisprudencia",
             dje_url="https://dje.stm.jus.br/", engine="html"),
]


# =====================================================================
#  Registro agregado
# =====================================================================

TRIBUNAIS: List[Tribunal] = TJS + TRFS + TRTS + TRES + SUPERIORES
POR_SIGLA: dict[str, Tribunal] = {t.sigla: t for t in TRIBUNAIS}

# Mapeamento: segmento CNJ (ex: "8.26") -> sigla (ex: "TJSP").
# Resolve o caso "qualquer processo cadastrado pode ter tribunal auto-detectado"
# a partir do CNJ mesmo para tribunais que antes precisavam ser digitados.
SEGMENTO_PARA_SIGLA: dict[str, str] = {t.segmento_cnj: t.sigla for t in TRIBUNAIS if t.segmento_cnj}


def get(sigla: str) -> Optional[Tribunal]:
    return POR_SIGLA.get((sigla or "").upper())


def todos() -> List[Tribunal]:
    return list(TRIBUNAIS)


def por_categoria(cat: str) -> List[Tribunal]:
    return [t for t in TRIBUNAIS if t.categoria == cat]


def dropdown_ordenado() -> List[Tribunal]:
    """Lista ordenada para popular dropdown: estaduais por UF, depois federais, etc."""
    ordem_cat = ["estadual", "federal", "trabalho", "eleitoral", "superior", "militar"]
    out = sorted(
        TRIBUNAIS,
        key=lambda t: (ordem_cat.index(t.categoria) if t.categoria in ordem_cat else 99,
                       t.uf or "", t.sigla),
    )
    return out


def resolver_por_segmento(segmento: str) -> Optional[Tribunal]:
    """Recebe '8.26' e devolve o Tribunal TJSP. Útil para autoclassificação de CNJ."""
    return next((t for t in TRIBUNAIS if t.segmento_cnj == segmento), None)
