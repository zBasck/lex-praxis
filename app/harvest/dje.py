"""Coletor de DJe - camada de orquestracao que usa PJeComunicaEngine.

Unica fonte de publicacoes: PJe Comunica (comunica.pje.jus.br).
Para ativar: DJE_COMUNICA_ENABLED=true no .env
Sem isso, qualquer coleta levanta DJeUnavailableError - sem fallback sintetico.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Optional

from flask import current_app

from app.core.extensions import db
from app.core.models import Publicacao, Processo, Andamento, Prazo
from app.core.utils import hash_text
from app.core.prazos import get_motor
from app.intel.classifier import classify
from app.intel.rules_extra import inferir_prazo, dias_uteis
from app.harvest.tribunais import get as get_tribunal
from app.harvest.dje_comunica import PJeComunicaEngine, DJeUnavailableError

log = logging.getLogger(__name__)


class HarvestDJe:
    """Coleta publicacoes do DJe (PJe Comunica) para processos conhecidos.

    Por processo: consulta PJe Comunica por CNJ, persiste Publicacao,
    gera Andamento + Prazo derivado.
    """

    def __init__(self, enabled_flags=None, days_back: int = 7, **_):
        self._days_back = days_back
        self.engine = PJeComunicaEngine()

    def status(self) -> dict:
        return self.engine.status()

    def _enabled(self, sigla: str) -> bool:
        return True  # DJe Comunica cobre todos os tribunais do PJe

    def collect(self, tribunais: Optional[List[str]] = None) -> dict:
        """Coleta publicacoes para todos os processos ativos (ou filtro)."""
        if not self.engine.enabled:
            return {
                "publicacoes_novas": 0, "andamentos_novos": 0, "prazos_novos": 0,
                "tribunais": [], "modo": "desabilitado",
                "aviso": "DJE_COMUNICA_ENABLED=false. Ative no .env para coletar.",
            }

        processos = Processo.query.filter_by(ativo=True).all()
        if not processos:
            return {
                "publicacoes_novas": 0, "andamentos_novos": 0, "prazos_novos": 0,
                "tribunais": [], "modo": "real",
            }

        siglas = tribunais or sorted({p.tribunal for p in processos})
        total_pubs = total_and = total_prazos = 0
        detalhes = []
        for sigla in siglas:
            if not self._enabled(sigla):
                continue
            processos_trib = [p for p in processos if p.tribunal == sigla]
            if not processos_trib:
                continue
            try:
                pubs = self._collect_para_tribunal(sigla, processos_trib)
            except DJeUnavailableError as e:
                log.warning("DJe desabilitado durante collect: %s", e)
                continue
            except Exception as e:
                log.exception("DJe falhou para %s: %s", sigla, e)
                detalhes.append({"tribunal": sigla, "erro": str(e)})
                continue
            if not pubs:
                continue
            salvas, ands, prazos = self._persistir(pubs, processos_trib)
            total_pubs += salvas
            total_and += ands
            total_prazos += prazos
            detalhes.append({"tribunal": sigla, "publicacoes": salvas,
                             "andamentos": ands, "prazos": prazos})

        return {
            "publicacoes_novas": total_pubs,
            "andamentos_novos": total_and,
            "prazos_novos": total_prazos,
            "tribunais": detalhes,
            "modo": "real",
        }

    def _collect_para_tribunal(self, sigla, processos):
        out = []
        for p in processos:
            try:
                ands = self.engine.fetch_por_cnj(p.numero_cnj)
            except (DJeUnavailableError, RuntimeError) as e:
                log.warning("Falha ao buscar %s no DJe: %s", p.numero_cnj, e)
                continue
            for a in ands:
                cnj = a.metadados.get("numero_cnj") or p.numero_cnj
                diario_id = f"COMUNICA-{sigla}-{a.data.strftime('%Y%m%d')}-{hash(a.texto) & 0xFFFF:04x}"
                out.append(Publicacao(
                    tribunal=sigla, data=a.data.date() if hasattr(a.data, "date") else a.data,
                    caderno="Comunica", secao="DJe",
                    texto=a.texto, texto_limpo=a.texto, numero_cnj=cnj,
                    processo_id=p.id, diario_edicao=diario_id,
                    capturado_em=datetime.utcnow(),
                    hash_conteudo=hash_text(a.texto + a.data.isoformat()),
                    vinculado_em=datetime.utcnow(),
                ))
        return out

    def _persistir(self, pubs, processos):
        proc_por_cnj = {p.numero_cnj: p for p in processos}
        salvas = ands = prazos = 0
        motor = get_motor()
        for pub in pubs:
            if Publicacao.query.filter_by(hash_conteudo=pub.hash_conteudo).first():
                continue
            proc = proc_por_cnj.get(pub.numero_cnj)
            if not proc and pub.numero_cnj:
                proc = Processo.query.filter_by(numero_cnj=pub.numero_cnj).first()
            if proc:
                pub.processo_id = proc.id
                pub.vinculado_em = datetime.utcnow()
            db.session.add(pub)
            db.session.flush()
            salvas += 1
            if not proc:
                continue

            cls = classify(pub.texto)
            refino = inferir_prazo(pub.texto)
            if refino and not cls.prazo_dias:
                cls.prazo_dias = refino["prazo_dias"]
                cls.prazo_marco = refino["prazo_marco"]
            if refino and not cls.tarefa_sugerida:
                cls.tarefa_sugerida = refino["tarefa_sugerida"]

            h = hash_text(pub.texto + pub.data.isoformat())
            if Andamento.query.filter_by(hash_conteudo=h).first():
                continue
            andam = Andamento(
                processo_id=proc.id, data=datetime.combine(pub.data, datetime.min.time()),
                texto=f"[DJe/{pub.caderno}] " + pub.texto, texto_limpo=pub.texto,
                tipo_ato=cls.tipo_ato, prazo_dias=cls.prazo_dias,
                prazo_marco=cls.prazo_marco, tarefa_sugerida=cls.tarefa_sugerida,
                resumo_cliente=cls.resumo_cliente, fonte=f"{pub.tribunal} - DJe",
                hash_conteudo=h, classificacao_origem=cls.origem,
            )
            db.session.add(andam)
            db.session.flush()
            ands += 1

            if cls.prazo_dias and cls.prazo_dias > 0:
                if Prazo.query.filter_by(processo_id=proc.id, andamento_id=andam.id).first():
                    continue
                pz_calc = motor.calcular(cls.tipo_ato, pub.data, pub.texto)
                data_limite = pz_calc.data_limite or dias_uteis(pub.data, cls.prazo_dias)
                db.session.add(Prazo(
                    processo_id=proc.id, andamento_id=andam.id,
                    descricao=cls.tarefa_sugerida or pz_calc.tarefa_sugerida or f"Publicacao DJe: {cls.tipo_ato}",
                    data_inicio=pub.data, data_limite=data_limite,
                    tipo=cls.tipo_ato, responsavel_id=proc.responsavel_id,
                    status="aberto",
                    prioridade=pz_calc.prioridade or ("alta" if cls.prazo_dias <= 5 else "normal"),
                ))
                prazos += 1
        db.session.commit()
        return salvas, ands, prazos


def get_harvest_dje() -> HarvestDJe:
    return HarvestDJe()
