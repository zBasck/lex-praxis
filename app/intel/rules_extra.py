"""Regras extras para detecção de prazos em peças específicas.

Tabelas de referência: CPC/2015 + legislação esparsa. Apenas heurísticas
úteis — a IA pode refinar em casos ambíguos.
"""
from typing import Optional, List
import re


# (palavras-chave, dias, marco, tarefa)
TABELA_PRAZOS = [
    (["contrarrazões", "contrarrazoes", "contrarrazão"], 15, "publicacao", "Apresentar contrarrazões"),
    (["replica", "réplica"], 15, "publicacao", "Apresentar réplica"),
    (["alegações finais", "alegacoes finais"], 15, "publicacao", "Alegações finais"),
    (["recurso de apelação", "recurso de apelacao", "apelação"], 15, "publicacao", "Interpor apelação"),
    (["contrarrazões de apelação", "contrarrazoes de apelacao"], 15, "publicacao", "Contrarrazões de apelação"),
    (["agravo de instrumento", "agravo"], 15, "publicacao", "Interpor agravo de instrumento"),
    (["agravo interno", "agravo regimental"], 15, "publicacao", "Interpor agravo interno"),
    (["embargos de declaração", "embargos de declaracao"], 5, "publicacao", "Opor embargos de declaração"),
    (["embargos à execução", "embargos a execucao"], 15, "publicacao", "Opor embargos à execução"),
    (["embargos de terceiro"], 15, "publicacao", "Opor embargos de terceiro"),
    (["cumprimento de sentença", "cumprimento de sentenca"], 15, "publicacao", "Cumprimento de sentença"),
    (["impugnação ao cumprimento", "impugnacao ao cumprimento"], 15, "publicacao", "Impugnação ao cumprimento"),
    (["manifestação", "manifestacao"], 15, "publicacao", "Manifestação"),
    (["recurso extraordinário", "recurso extraordinario"], 15, "publicacao", "Interpor recurso extraordinário"),
    (["recurso especial"], 15, "publicacao", "Interpor recurso especial"),
    (["razões", "razoes"], 15, "publicacao", "Apresentar razões"),
    (["esclarecimentos"], 5, "publicacao", "Pedir esclarecimentos"),
    (["sindicância", "sindicancia"], 10, "publicacao", "Manifestação em sindicância"),
    (["tributário", "tributario", "fiscal"], 30, "publicacao", "Manifestação fiscal"),
]


def inferir_prazo(texto: str) -> Optional[dict]:
    """Tenta identificar prazo conhecido a partir do texto."""
    if not texto:
        return None
    t = texto.lower()
    for keywords, dias, marco, tarefa in TABELA_PRAZOS:
        for kw in keywords:
            if kw in t:
                return {
                    "prazo_dias": dias,
                    "prazo_marco": marco,
                    "tarefa_sugerida": tarefa,
                    "match": kw,
                }
    return None


def dias_uteis(data_inicio, dias: int) -> "date":
    """Calcula data final considerando apenas dias úteis (aproximação: pula sáb/dom)."""
    from datetime import timedelta, date as _date
    if not isinstance(data_inicio, _date):
        from dateutil import parser
        data_inicio = parser.parse(str(data_inicio)).date()
    d = data_inicio
    adicionados = 0
    while adicionados < dias:
        d = d + timedelta(days=1)
        if d.weekday() < 5:  # 0-4 = seg-sex
            adicionados += 1
    return d
