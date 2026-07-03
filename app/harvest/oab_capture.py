"""Monitor de OAB no DJe (PJe Comunica).

Fluxo:
  1) Busca publicacoes no DJe Comunica pela OAB+UF (fetch_por_oab)
  2) Para cada publicacao encontrada:
     - extrai numero CNJ
     - se o processo NAO existe no banco: cria automaticamente
     - se o processo existe: vincula a publicacao e gera Andamento
     - se for ato relevante, gera Prazo via MotorPrazos
     - atualiza a linha do tempo desde o inicio do processo

Ativacao:
  DJE_COMUNICA_ENABLED=true no .env
  DJE_OAB_USUARIO=<numero> e DJE_OAB_UF=<UF> no .env (ou via UI /monitor-dje)
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Optional

from flask import current_app

from app.core.extensions import db
from app.core.models import (
    User, Cliente, Processo, Andamento, Prazo, Publicacao,
    OABMonitorada, CapturaOAB, ProcessoOAB, CapturaOABPublicacao,
)
from app.core.utils import normalize_cnj, hash_text
from app.core.prazos import get_motor
from app.intel.classifier import classify
from app.intel.rules_extra import inferir_prazo, dias_uteis
from app.harvest.dje_comunica import PJeComunicaEngine, DJeUnavailableError, PublicacaoDJE

log = logging.getLogger(__name__)


class MonitorOAB:
    """Executa capturas de publicacoes do DJe para uma OAB+UF."""

    def __init__(self, engine: Optional[PJeComunicaEngine] = None):
        self.engine = engine or PJeComunicaEngine()
        self.motor = get_motor()

    def status(self) -> dict:
        return self.engine.status()

    def capturar_para_oab_oab(self, oab, days_back: int = 7,
                              user: Optional[User] = None) -> dict:
        """Wrapper para captura a partir de um registro OABMonitorada."""
        return self.capturar_para_oab(
            oab.numero, oab.uf, days_back=days_back, user=user,
            oab_id=oab.id, oab=oab,
        )

    def capturar_para_oab(self, numero_oab: str, uf: str,
                          days_back: int = 7,
                          user: Optional[User] = None,
                          oab_id: Optional[int] = None,
                          oab: Optional[OABMonitorada] = None) -> dict:
        """Busca publicacoes da OAB, cadastra processos novos e gera andamentos.

        Retorna dict com estatisticas da captura.
        """
        numero_oab = (numero_oab or "").strip()
        uf = (uf or "").upper().strip()
        if not numero_oab or not uf:
            raise ValueError("OAB e UF sao obrigatorios")

        captura = CapturaOAB(
            oab_id=oab_id, status="rodando", executada_em=datetime.utcnow(),
        ) if oab_id else CapturaOAB(
            status="rodando", executada_em=datetime.utcnow(),
        )
        db.session.add(captura)
        db.session.flush()

        try:
            pubs = self.engine.fetch_por_oab(numero_oab, uf, days_back=days_back)
        except DJeUnavailableError as e:
            captura.status = "indisponivel"
            captura.mensagem = str(e)
            captura.finalizado_em = datetime.utcnow()
            db.session.commit()
            return {
                "status": "indisponivel",
                "mensagem": str(e),
                "captura_id": captura.id,
            }
        except Exception as e:
            captura.status = "erro"
            captura.mensagem = f"{type(e).__name__}: {e}"
            captura.finalizado_em = datetime.utcnow()
            db.session.commit()
            return {
                "status": "erro",
                "mensagem": str(e),
                "captura_id": captura.id,
            }

        if not pubs:
            captura.status = "ok"
            captura.mensagem = f"Nenhuma publicacao encontrada nos ultimos {days_back} dias."
            captura.finalizado_em = datetime.utcnow()
            captura.publicacoes_encontradas = 0
            captura.processos_novos = 0
            captura.andamentos_novos = 0
            captura.prazos_novos = 0
            db.session.commit()
            return {
                "status": "ok",
                "publicacoes_encontradas": 0,
                "processos_novos": 0,
                "andamentos_novos": 0,
                "prazos_novos": 0,
                "captura_id": captura.id,
            }

        proc_novos = and_novos = praz_novos = 0
        erros = []
        for pub in pubs:
            try:
                pnovos, anovos, prnovos = self._processar_publicacao(
                    pub, user, oab_id=oab_id, captura=captura, oab=oab
                )
                proc_novos += pnovos
                and_novos += anovos
                praz_novos += prnovos
            except Exception as e:
                log.exception("Erro processando publicacao %s: %s", pub.numero_cnj, e)
                erros.append({"cnj": pub.numero_cnj, "erro": str(e)})

        captura.status = "ok"
        captura.publicacoes_encontradas = len(pubs)
        captura.processos_novos = proc_novos
        captura.andamentos_novos = and_novos
        captura.prazos_novos = praz_novos
        captura.finalizado_em = datetime.utcnow()
        if erros:
            captura.mensagem = f"{len(erros)} publicacao(oes) com erro."
        db.session.commit()

        return {
            "status": "ok",
            "captura_id": captura.id,
            "publicacoes_encontradas": len(pubs),
            "processos_novos": proc_novos,
            "andamentos_novos": and_novos,
            "prazos_novos": praz_novos,
            "erros": erros,
        }

    def capturar_todas_oabs(self, days_back: int = 7) -> dict:
        """Roda captura para todas as OABs monitoradas ativas."""
        oabs = OABMonitorada.query.filter_by(ativo=True).all()
        if not oabs:
            return {"status": "ok", "oabs": 0, "resultados": []}
        resultados = []
        for oab in oabs:
            try:
                r = self.capturar_para_oab(
                    oab.numero, oab.uf, days_back=days_back,
                    oab_id=oab.id, oab=oab,
                )
            except Exception as e:
                r = {"status": "erro", "oab": f"{oab.numero}/{oab.uf}", "mensagem": str(e)}
            resultados.append({"oab": f"{oab.numero}/{oab.uf}", **r})
        return {"status": "ok", "oabs": len(oabs), "resultados": resultados}

    def atualizar_andamentos(self, processo: Processo) -> dict:
        """Busca publicacoes DJE de um processo especifico (atualizacao por CNJ)
        e gera andamentos novos (deduplicados por hash)."""
        if not self.engine.enabled:
            return {
                "status": "indisponivel",
                "mensagem": "DJE_COMUNICA_ENABLED=false. Ative no .env.",
            }
        try:
            andamentos_cap = self.engine.fetch_por_cnj(processo.numero_cnj)
        except (DJeUnavailableError, RuntimeError) as e:
            return {"status": "erro", "mensagem": str(e)}

        hashes_existentes = {a.hash_conteudo for a in processo.andamentos if a.hash_conteudo}
        novos_and = 0
        novos_praz = 0
        for cap in andamentos_cap:
            h = hash_text(cap.texto + cap.data.isoformat())
            if h in hashes_existentes:
                continue
            andam = self._criar_andamento(processo, cap)
            if andam:
                novos_and += 1
                if self._criar_prazo_de_andamento(processo, andam):
                    novos_praz += 1

        processo.ultima_verificacao = datetime.utcnow()
        db.session.commit()
        return {
            "status": "ok",
            "processo": processo.numero_cnj,
            "andamentos_novos": novos_and,
            "prazos_novos": novos_praz,
        }

    # ---- Internos ----

    def _processar_publicacao(self, pub: PublicacaoDJE, user: Optional[User],
                               oab_id: Optional[int] = None,
                               captura=None,
                               oab: Optional[OABMonitorada] = None):
        """Persiste Publicacao, cria processo se necessario, gera Andamento + Prazo."""
        cnj = normalize_cnj(pub.numero_cnj)
        # Publicacao - dedup por hash
        diario_id = f"OAB-{pub.tribunal}-{pub.data.isoformat()}-{hash(pub.texto) & 0xFFFF:04x}"
        h_pub = hash_text(pub.texto + pub.data.isoformat())
        if Publicacao.query.filter_by(hash_conteudo=h_pub).first():
            return 0, 0, 0

        # Processo: cria se nao existir
        proc = Processo.query.filter_by(numero_cnj=cnj).first()
        proc_criado = False
        if not proc:
            import json as _json
            proc = Processo(
                numero_cnj=cnj,
                tribunal=pub.tribunal or "DJe",
                classe=None,
                assunto=None,
                vara=None,
                instancia="1" if pub.tribunal and pub.tribunal.startswith(("TJ", "TRF", "TRT")) else "1",
                fase="conhecimento",
                observacoes=f"Detectado via monitor de OAB - partes: {pub.partes or 'nao informadas'}",
                ativo=True,
                responsavel_id=user.id if user else None,
                origem="oab_monitor" if oab_id else "manual",
                oab_origem=oab.numero if oab else None,
                uf_oab_origem=oab.uf if oab else None,
                partes_json=_json.dumps(pub.partes) if pub.partes else None,
                link_djen=pub.url,
            )
            db.session.add(proc)
            db.session.flush()
            proc_criado = True
        # Se o processo ja existia (cadastrado manualmente) e a OAB capturou: vincula
        if not proc_criado and oab_id:
            if not ProcessoOAB.query.filter_by(processo_id=proc.id, oab_id=oab_id).first():
                db.session.add(ProcessoOAB(processo_id=proc.id, oab_id=oab_id))
            if not proc.origem or proc.origem == "manual":
                proc.origem = "oab_monitor"
            if not proc.oab_origem and oab:
                proc.oab_origem = oab.numero
                proc.uf_oab_origem = oab.uf

        # Cria Publicacao
        pub_row = Publicacao(
            tribunal=pub.tribunal, data=pub.data,
            caderno="DJe Comunica", secao="Monitor OAB",
            texto=pub.texto, texto_limpo=pub.texto,
            numero_cnj=cnj, processo_id=proc.id,
            diario_edicao=diario_id,
            capturado_em=datetime.utcnow(),
            hash_conteudo=h_pub,
            vinculado_em=datetime.utcnow(),
        )
        db.session.add(pub_row)
        db.session.flush()

        # Vincula publicacao a captura OAB (rastreabilidade)
        if oab_id and captura and getattr(captura, "id", None):
            try:
                rel = CapturaOABPublicacao(
                    captura_id=captura.id,
                    publicacao_id=pub_row.id,
                    oab_id=oab_id,
                )
                db.session.add(rel)
            except Exception:
                db.session.rollback()  # unique constraint - ja vinculada

        # Cria Andamento
        andam = self._criar_andamento(proc, pub.to_andamento(), tipo_ato_override=pub.tipo_ato)
        proc_novos = 1 if proc_criado else 0
        and_novos = 1 if andam else 0
        praz_novos = 0
        if andam:
            if self._criar_prazo_de_andamento(proc, andam):
                praz_novos = 1
        return proc_novos, and_novos, praz_novos

    def _criar_andamento(self, proc: Processo, cap,
                         tipo_ato_override: str = None) -> Optional[Andamento]:
        h = hash_text(cap.texto + cap.data.isoformat())
        if Andamento.query.filter_by(hash_conteudo=h).first():
            return None
        cls = classify(cap.texto)
        refino = inferir_prazo(cap.texto)
        if refino and not cls.prazo_dias:
            cls.prazo_dias = refino["prazo_dias"]
            cls.prazo_marco = refino["prazo_marco"]
        if refino and not cls.tarefa_sugerida:
            cls.tarefa_sugerida = refino["tarefa_sugerida"]
        tipo_ato = tipo_ato_override or cls.tipo_ato
        andam = Andamento(
            processo_id=proc.id, data=cap.data,
            texto=f"[DJe] {cap.texto}", texto_limpo=cap.texto[:1000],
            tipo_ato=tipo_ato, prazo_dias=cls.prazo_dias,
            prazo_marco=cls.prazo_marco, tarefa_sugerida=cls.tarefa_sugerida,
            resumo_cliente=cls.resumo_cliente, fonte=cap.fonte,
            hash_conteudo=h, classificacao_origem=cls.origem,
        )
        db.session.add(andam)
        db.session.flush()
        return andam

    def _criar_prazo_de_andamento(self, proc: Processo, andam: Andamento) -> bool:
        if not andam.prazo_dias or andam.prazo_dias <= 0:
            return False
        if Prazo.query.filter_by(processo_id=proc.id, andamento_id=andam.id).first():
            return False
        pz_calc = self.motor.calcular(andam.tipo_ato, andam.data, andam.texto)
        data_limite = pz_calc.data_limite or dias_uteis(andam.data.date(), andam.prazo_dias)
        db.session.add(Prazo(
            processo_id=proc.id, andamento_id=andam.id,
            descricao=pz_calc.tarefa_sugerida or andam.tarefa_sugerida or f"Prazo: {andam.tipo_ato}",
            data_inicio=andam.data.date(), data_limite=data_limite,
            tipo=andam.tipo_ato, responsavel_id=proc.responsavel_id,
            status="aberto", prioridade=pz_calc.prioridade or "normal",
        ))
        return True


def get_monitor() -> MonitorOAB:
    return MonitorOAB()
