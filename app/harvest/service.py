"""Servico de captura de andamentos - orquestra PJe Comunica + Motor de Prazos.

Fluxo:
  - harvest_processo(proc): busca publicacoes DJE de um processo por CNJ
  - harvest_all_active(): itera todos os processos ativos
"""
from __future__ import annotations
import logging
from datetime import datetime, date
from typing import Tuple

from flask import current_app

from app.core.extensions import db
from app.core.models import Processo, Andamento, Prazo
from app.core.utils import hash_text
from app.core.prazos import get_motor
from app.intel.classifier import classify
from app.intel.rules_extra import inferir_prazo, dias_uteis
from .manager import get_manager

log = logging.getLogger(__name__)


def harvest_processo(proc: Processo, days_back: int = None, so_hoje: bool = False) -> Tuple[int, int]:
    """Busca publicacoes DJe de um processo e gera Andamentos/Prazos.

    so_hoje: se True, consulta apenas a data de hoje.
    days_back: se fornecido, usa essa janela (so_hoje tem prioridade).
    """
    manager = get_manager()
    cfg = current_app.config
    provider = cfg.get("LLM_PROVIDER", "local")
    llm_key = cfg.get("LLM_API_KEY", "")
    llm_model = cfg.get("LLM_MODEL", "gpt-4o-mini")
    llm_timeout = cfg.get("LLM_TIMEOUT_SECONDS", 20)
    motor = get_motor()

    # Janela: so_hoje -> 1 dia so com so_hoje=True; days_back -> custom; senao 30
    if so_hoje:
        fetch_days_back = 1
        fetch_so_hoje = True
    elif days_back is not None:
        fetch_days_back = days_back
        fetch_so_hoje = False
    else:
        fetch_days_back = 30
        fetch_so_hoje = False

    # manager.fetch e a engine de tribunal local - mantemos para compat.
    capturados = manager.fetch(proc.tribunal, proc.numero_cnj)
    if not capturados:
        proc.ultima_verificacao = datetime.utcnow()
        db.session.commit()
        return 0, 0

    hashes_existentes = {a.hash_conteudo for a in proc.andamentos if a.hash_conteudo}
    novos_a = novos_p = 0

    for cap in capturados:
        h = hash_text(cap.texto + cap.data.isoformat())
        if h in hashes_existentes:
            continue

        classificacao = classify(
            cap.texto,
            llm_provider=provider, llm_key=llm_key,
            llm_model=llm_model, timeout=llm_timeout,
        )
        refino = inferir_prazo(cap.texto)
        if refino and not classificacao.prazo_dias:
            classificacao.prazo_dias = refino["prazo_dias"]
            classificacao.prazo_marco = refino["prazo_marco"]
        if refino and not classificacao.tarefa_sugerida:
            classificacao.tarefa_sugerida = refino["tarefa_sugerida"]

        andam = Andamento(
            processo_id=proc.id, data=cap.data,
            texto=cap.texto, texto_limpo=(cap.texto or "")[:1000],
            tipo_ato=classificacao.tipo_ato, prazo_dias=classificacao.prazo_dias,
            prazo_marco=classificacao.prazo_marco,
            tarefa_sugerida=classificacao.tarefa_sugerida,
            resumo_cliente=classificacao.resumo_cliente,
            fonte=cap.fonte, hash_conteudo=h,
            classificacao_origem=classificacao.origem,
        )
        db.session.add(andam)
        db.session.flush()
        novos_a += 1

        if classificacao.prazo_dias and classificacao.prazo_dias > 0:
            if not Prazo.query.filter_by(processo_id=proc.id, andamento_id=andam.id).first():
                pz = motor.calcular(classificacao.tipo_ato, cap.data, cap.texto)
                data_limite = pz.data_limite or dias_uteis(cap.data.date(), classificacao.prazo_dias)
                db.session.add(Prazo(
                    processo_id=proc.id, andamento_id=andam.id,
                    descricao=classificacao.tarefa_sugerida or pz.tarefa_sugerida or f"Prazo: {classificacao.tipo_ato}",
                    data_inicio=cap.data.date(), data_limite=data_limite,
                    tipo=classificacao.tipo_ato, responsavel_id=proc.responsavel_id,
                    status="aberto", prioridade=pz.prioridade or "normal",
                ))
                novos_p += 1

    proc.ultima_verificacao = datetime.utcnow()
    db.session.commit()
    return novos_a, novos_p


def harvest_all_active(days_back: int = None, so_hoje: bool = False) -> dict:
    """Itera todos os processos ativos e executa harvest por CNJ via DJEN.

    so_hoje: se True, cada processo consulta apenas a data de hoje.
    days_back: se fornecido, usa essa janela (so_hoje tem prioridade).
    """
    from app.harvest.oab_capture import MonitorOAB
    processos = Processo.query.filter_by(ativo=True).all()
    total_a = total_p = total_pub = 0
    erros = []
    monitor = MonitorOAB()
    for p in processos:
        try:
            r = monitor.atualizar_andamentos(p, so_hoje=so_hoje, days_back=days_back)
            if r.get("status") == "ok":
                total_pub += r.get("publicacoes_encontradas", 0)
                total_a += r.get("andamentos_novos", 0)
                total_p += r.get("prazos_novos", 0)
        except Exception as e:
            log.exception("Falha ao processar %s", p.numero_cnj)
            erros.append({"processo": p.numero_cnj, "erro": str(e)})
    return {
        "total_processos": len(processos),
        "processos": len(processos),
        "total_publicacoes": total_pub,
        "publicacoes_encontradas": total_pub,
        "total_andamentos": total_a,
        "andamentos_novos": total_a,
        "total_prazos": total_p,
        "prazos_novos": total_p,
        "erros": erros,
    }
