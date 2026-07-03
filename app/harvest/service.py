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


def harvest_processo(proc: Processo) -> Tuple[int, int]:
    """Busca publicacoes DJe de um processo e gera Andamentos/Prazos."""
    manager = get_manager()
    cfg = current_app.config
    provider = cfg.get("LLM_PROVIDER", "local")
    llm_key = cfg.get("LLM_API_KEY", "")
    llm_model = cfg.get("LLM_MODEL", "gpt-4o-mini")
    llm_timeout = cfg.get("LLM_TIMEOUT_SECONDS", 20)
    motor = get_motor()

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


def harvest_all_active() -> dict:
    """Itera todos os processos ativos e executa harvest por CNJ."""
    processos = Processo.query.filter_by(ativo=True).all()
    total_a = total_p = 0
    erros = []
    for p in processos:
        try:
            a, q = harvest_processo(p)
            total_a += a
            total_p += q
        except Exception as e:
            log.exception("Falha ao processar %s", p.numero_cnj)
            erros.append({"processo": p.numero_cnj, "erro": str(e)})
    return {
        "processos": len(processos),
        "andamentos_novos": total_a,
        "prazos_novos": total_p,
        "erros": erros,
    }
