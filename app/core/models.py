"""Modelos do banco de dados."""
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from .extensions import db


# ============== USUÁRIOS ==============

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default="advogado")  # admin, advogado, assistente
    oab = db.Column(db.String(30))
    phone = db.Column(db.String(30))
    active = db.Column(db.Boolean, default=True)
    receive_digest = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    prazos_responsavel = db.relationship("Prazo", backref="responsavel", foreign_keys="Prazo.responsavel_id")

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def __repr__(self):
        return f"<User {self.email}>"


# ============== CLIENTES ==============

class Cliente(db.Model):
    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False, index=True)
    documento = db.Column(db.String(30), index=True)  # CPF ou CNPJ
    tipo = db.Column(db.String(10), default="PF")  # PF ou PJ
    email = db.Column(db.String(180))
    phone = db.Column(db.String(30))
    endereco = db.Column(db.Text)
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    processos = db.relationship("Processo", backref="cliente", lazy="dynamic")

    @property
    def processos_count(self):
        return self.processos.filter_by(ativo=True).count()


# ============== PROCESSOS ==============

class Processo(db.Model):
    __tablename__ = "processos"

    id = db.Column(db.Integer, primary_key=True)
    numero_cnj = db.Column(db.String(30), unique=True, nullable=False, index=True)
    tribunal = db.Column(db.String(20), nullable=False, index=True)  # TJSP, TRF1, STF...
    vara = db.Column(db.String(200))
    classe = db.Column(db.String(200))
    assunto = db.Column(db.String(300))
    valor_causa = db.Column(db.Numeric(14, 2))
    instancia = db.Column(db.String(20))  # 1ª, 2ª, superior
    fase = db.Column(db.String(80))  # conhecimento, recursal, execução
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    responsavel_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    polo = db.Column(db.String(20))  # ativo, passivo, terceiro
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    ultima_verificacao = db.Column(db.DateTime)
    origem = db.Column(db.String(30), default="manual")
    oab_origem = db.Column(db.String(20))
    uf_oab_origem = db.Column(db.String(2))
    partes_json = db.Column(db.Text)
    link_djen = db.Column(db.String(500))
    orgao = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    andamentos = db.relationship("Andamento", backref="processo", lazy="dynamic",
                                 order_by="desc(Andamento.data)")
    prazos = db.relationship("Prazo", backref="processo", lazy="dynamic",
                             order_by="Prazo.data_limite")
    responsavel = db.relationship("User", foreign_keys=[responsavel_id])

    @property
    def proximo_prazo(self):
        return (self.prazos.filter_by(status="aberto")
                .filter(Prazo.data_limite >= date.today())
                .order_by(Prazo.data_limite).first())

    @property
    def prazos_vencidos(self):
        return self.prazos.filter_by(status="aberto").filter(Prazo.data_limite < date.today()).count()

    def __repr__(self):
        return f"<Processo {self.numero_cnj}>"


# ============== ANDAMENTOS ==============

class Andamento(db.Model):
    __tablename__ = "andamentos"

    id = db.Column(db.Integer, primary_key=True)
    processo_id = db.Column(db.Integer, db.ForeignKey("processos.id"), nullable=False, index=True)
    data = db.Column(db.DateTime, nullable=False, index=True)
    texto = db.Column(db.Text, nullable=False)
    texto_limpo = db.Column(db.Text)  # normalizado
    tipo_ato = db.Column(db.String(80), index=True)  # decisão, despacho, sentença, intimação...
    prazo_dias = db.Column(db.Integer)  # detectado por IA ou regras
    prazo_marco = db.Column(db.String(60))  # publicação, intimação, juntada
    tarefa_sugerida = db.Column(db.String(300))
    resumo_cliente = db.Column(db.Text)  # explicação em linguagem simples
    fonte = db.Column(db.String(80))  # "TJSP - e-SAJ", "STJ", "manual"...
    capturado_em = db.Column(db.DateTime, default=datetime.utcnow)
    hash_conteudo = db.Column(db.String(64), index=True)  # deduplicação
    classificacao_origem = db.Column(db.String(20), default="regras")  # regras | llm | manual

    prazos = db.relationship("Prazo", backref="andamento_origem")


# ============== PRAZOS ==============

class Prazo(db.Model):
    __tablename__ = "prazos"

    id = db.Column(db.Integer, primary_key=True)
    processo_id = db.Column(db.Integer, db.ForeignKey("processos.id"), nullable=False, index=True)
    andamento_id = db.Column(db.Integer, db.ForeignKey("andamentos.id"))
    descricao = db.Column(db.String(400), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_limite = db.Column(db.Date, nullable=False, index=True)
    tipo = db.Column(db.String(80))  # recursal, manifestação, audiência, cumprimento
    responsavel_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(20), default="aberto")  # aberto, concluido, vencido, cancelado
    prioridade = db.Column(db.String(20), default="normal")  # baixa, normal, alta, critica
    observacoes = db.Column(db.Text)
    concluido_em = db.Column(db.DateTime)
    concluido_por_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def dias_restantes(self):
        return (self.data_limite - date.today()).days

    @property
    def vencido(self):
        return self.status == "aberto" and self.data_limite < date.today()


# ============== PUBLICAÇÕES DJe ==============

class Publicacao(db.Model):
    """Publicação coletada do Diário de Justiça Eletrônico de um tribunal.

    Diferente do Andamento (que é movimento do processo na visão do advogado),
    Publicacao é o texto bruto que saiu no diário oficial. A vinculação
    Publicacao <-> Processo é feita por número CNJ no harvest; a mesma
    Publicacao pode dar origem a um Andamento + Prazo.
    """
    __tablename__ = "publicacoes"

    id = db.Column(db.Integer, primary_key=True)
    tribunal = db.Column(db.String(20), nullable=False, index=True)
    data = db.Column(db.Date, nullable=False, index=True)
    caderno = db.Column(db.String(60))
    secao = db.Column(db.String(80))
    texto = db.Column(db.Text, nullable=False)
    texto_limpo = db.Column(db.Text)
    numero_cnj = db.Column(db.String(30), index=True)
    processo_id = db.Column(db.Integer, db.ForeignKey("processos.id"), index=True)
    diario_edicao = db.Column(db.String(60))
    url_original = db.Column(db.String(500))
    capturado_em = db.Column(db.DateTime, default=datetime.utcnow)
    hash_conteudo = db.Column(db.String(64), index=True)
    vinculado_em = db.Column(db.DateTime)

    processo = db.relationship("Processo", backref="publicacoes", foreign_keys=[processo_id])


# ============== AUDIT LOG ==============

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    acao = db.Column(db.String(80), nullable=False)
    entidade = db.Column(db.String(40))
    entidade_id = db.Column(db.Integer)
    detalhes = db.Column(db.Text)
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



# ============== OABs MONITORADAS ==============

class OABMonitorada(db.Model):
    """OAB cadastrada para monitoramento automatico via DataJud / portais."""
    __tablename__ = "oabs_monitoradas"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), nullable=False, index=True)
    uf = db.Column(db.String(2), nullable=False, index=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    apelido = db.Column(db.String(120))
    ativo = db.Column(db.Boolean, default=True)
    ultima_busca_em = db.Column(db.DateTime)
    proxima_busca_em = db.Column(db.DateTime)
    intervalo_minutos = db.Column(db.Integer, default=240)
    total_processos_encontrados = db.Column(db.Integer, default=0)
    total_processos_criados = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    capturas = db.relationship("CapturaOAB", backref="oab", lazy="dynamic",
                               order_by="desc(CapturaOAB.executada_em)")
    responsavel = db.relationship("User", foreign_keys=[responsavel_id])

    @property
    def oab_formatada(self):
        return f"{self.numero}/{self.uf}"

    def __repr__(self):
        return f"<OAB {self.oab_formatada}>"


class CapturaOAB(db.Model):
    """Registro de uma execucao de busca por OAB."""
    __tablename__ = "capturas_oab"

    id = db.Column(db.Integer, primary_key=True)
    oab_id = db.Column(db.Integer, db.ForeignKey("oabs_monitoradas.id"), nullable=False, index=True)
    executada_em = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    finalizada_em = db.Column(db.DateTime)
    duracao_ms = db.Column(db.Integer)
    fonte = db.Column(db.String(40))
    status = db.Column(db.String(20))
    processos_encontrados = db.Column(db.Integer, default=0)
    processos_novos = db.Column(db.Integer, default=0)
    processos_atualizados = db.Column(db.Integer, default=0)
    andamentos_criados = db.Column(db.Integer, default=0)
    prazos_gerados = db.Column(db.Integer, default=0)
    alertas_gerados = db.Column(db.Integer, default=0)
    mensagem = db.Column(db.Text)
    erro = db.Column(db.Text)


# ============== PARTES E VINCULACAO ==============

class ParteProcesso(db.Model):
    """Parte envolvida em um processo (autor, reu, advogado)."""
    __tablename__ = "partes_processo"

    id = db.Column(db.Integer, primary_key=True)
    processo_id = db.Column(db.Integer, db.ForeignKey("processos.id"), nullable=False, index=True)
    nome = db.Column(db.String(200), nullable=False, index=True)
    documento = db.Column(db.String(30), index=True)
    tipo_pessoa = db.Column(db.String(10))
    polo = db.Column(db.String(20))
    tipo_parte = db.Column(db.String(40))
    oab = db.Column(db.String(20), index=True)
    uf_oab = db.Column(db.String(2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    processo = db.relationship("Processo", backref="partes", foreign_keys=[processo_id])


# ============== DOCUMENTOS DE CLIENTES ==============

class DocumentoCliente(db.Model):
    """Documentos vinculados a um cliente (CPF, CNPJ, OAB, nome)."""
    __tablename__ = "documentos_cliente"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False)
    valor = db.Column(db.String(60), nullable=False, index=True)
    valor_normalizado = db.Column(db.String(60), index=True)
    principal = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cliente = db.relationship("Cliente", backref="documentos", foreign_keys=[cliente_id])


# ============== ALERTAS DE CLIENTE ==============

class AlertaCliente(db.Model):
    """Alerta gerado quando cruzamento OAB <-> cliente detecta envolvimento."""
    __tablename__ = "alertas_cliente"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    processo_id = db.Column(db.Integer, db.ForeignKey("processos.id"), nullable=False, index=True)
    oab_id = db.Column(db.Integer, db.ForeignKey("oabs_monitoradas.id"))
    captura_id = db.Column(db.Integer, db.ForeignKey("capturas_oab.id"))
    tipo = db.Column(db.String(40))
    severidade = db.Column(db.String(20), default="info")
    titulo = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    match_tipo = db.Column(db.String(30))
    match_valor = db.Column(db.String(200))
    lido = db.Column(db.Boolean, default=False)
    lido_em = db.Column(db.DateTime)
    lido_por_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    cliente = db.relationship("Cliente", backref="alertas", foreign_keys=[cliente_id])
    processo = db.relationship("Processo", backref="alertas", foreign_keys=[processo_id])
    oab = db.relationship("OABMonitorada", foreign_keys=[oab_id])
    captura = db.relationship("CapturaOAB", backref="alertas", foreign_keys=[captura_id])




# ============== CONFIGURACOES POR USUARIO ==============

class UserConfig(db.Model):
    __tablename__ = "user_configs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    theme = db.Column(db.String(20), default="light")
    language = db.Column(db.String(10), default="pt-BR")
    default_oab = db.Column(db.String(20))
    default_uf = db.Column(db.String(2))
    days_back_padrao = db.Column(db.Integer, default=7)
    intervalo_monitor_min = db.Column(db.Integer, default=60)
    receber_digest = db.Column(db.Boolean, default=True)
    digest_hora = db.Column(db.Integer, default=7)
    llm_provider = db.Column(db.String(30), default="local")
    llm_model = db.Column(db.String(80), default="")
    llm_endpoint = db.Column(db.String(200), default="http://localhost:11434")
    llm_enabled = db.Column(db.Boolean, default=False)
    llm_api_key = db.Column(db.String(200))
    notif_email = db.Column(db.Boolean, default=True)
    notif_whatsapp = db.Column(db.Boolean, default=False)
    whatsapp_number = db.Column(db.String(30))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("config", uselist=False), foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id,
            "theme": self.theme, "language": self.language,
            "default_oab": self.default_oab, "default_uf": self.default_uf,
            "days_back_padrao": self.days_back_padrao,
            "intervalo_monitor_min": self.intervalo_monitor_min,
            "receber_digest": self.receber_digest, "digest_hora": self.digest_hora,
            "llm_provider": self.llm_provider, "llm_model": self.llm_model,
            "llm_endpoint": self.llm_endpoint, "llm_enabled": self.llm_enabled,
            "llm_api_key": "***" if self.llm_api_key else "",
            "notif_email": self.notif_email, "notif_whatsapp": self.notif_whatsapp,
            "whatsapp_number": self.whatsapp_number,
        }


# ============== CONFIGURACOES GLOBAIS DO SISTEMA ==============

class SystemConfig(db.Model):
    __tablename__ = "system_configs"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(300))
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "key": self.key, "value": self.value,
            "description": self.description,
            "updated_by_id": self.updated_by_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============== VINCULO OAB <-> PROCESSO ==============

class ProcessoOAB(db.Model):
    __tablename__ = "processo_oab"
    id = db.Column(db.Integer, primary_key=True)
    processo_id = db.Column(db.Integer, db.ForeignKey("processos.id"), nullable=False, index=True)
    oab_id = db.Column(db.Integer, db.ForeignKey("oabs_monitoradas.id"), nullable=False, index=True)
    primeira_captura_em = db.Column(db.DateTime, default=datetime.utcnow)
    ultima_captura_em = db.Column(db.DateTime, default=datetime.utcnow)
    capturas_total = db.Column(db.Integer, default=1)

    processo = db.relationship("Processo", backref=db.backref("oabs_origem_list", lazy="selectin"), foreign_keys=[processo_id])
    oab = db.relationship("OABMonitorada", foreign_keys=[oab_id])

    __table_args__ = (db.UniqueConstraint("processo_id", "oab_id", name="uq_proc_oab"),)


class CapturaOABPublicacao(db.Model):
    __tablename__ = "capturas_oab_publicacoes"
    id = db.Column(db.Integer, primary_key=True)
    captura_id = db.Column(db.Integer, db.ForeignKey("capturas_oab.id"), nullable=False, index=True)
    publicacao_id = db.Column(db.Integer, db.ForeignKey("publicacoes.id"), nullable=False, index=True)
    oab_id = db.Column(db.Integer, db.ForeignKey("oabs_monitoradas.id"), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint("captura_id", "publicacao_id", name="uq_capt_pub"),)


# ============== LOG DE ACOES ==============

class ActionLog(db.Model):
    __tablename__ = "action_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    acao = db.Column(db.String(120), nullable=False, index=True)
    categoria = db.Column(db.String(60), index=True)
    alvo_tipo = db.Column(db.String(60))
    alvo_id = db.Column(db.Integer)
    detalhes = db.Column(db.Text)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id,
            "acao": self.acao, "categoria": self.categoria,
            "alvo_tipo": self.alvo_tipo, "alvo_id": self.alvo_id,
            "detalhes": self.detalhes, "ip": self.ip,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }



# ============== to_dict() para os modelos novos ==============

def _add_to_dict_methods():
    def oab(self):
        return {
            "id": self.id, "numero": self.numero, "uf": self.uf,
            "oab_formatada": self.oab_formatada, "apelido": self.apelido,
            "ativo": self.ativo,
            "ultima_busca_em": self.ultima_busca_em.isoformat() if self.ultima_busca_em else None,
            "proxima_busca_em": self.proxima_busca_em.isoformat() if self.proxima_busca_em else None,
            "intervalo_minutos": self.intervalo_minutos,
            "total_processos_encontrados": self.total_processos_encontrados,
            "total_processos_criados": self.total_processos_criados,
            "responsavel_id": self.responsavel_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    OABMonitorada.to_dict = oab

    def captura(self):
        return {
            "id": self.id, "oab_id": self.oab_id,
            "executada_em": self.executada_em.isoformat() if self.executada_em else None,
            "finalizada_em": self.finalizada_em.isoformat() if self.finalizada_em else None,
            "duracao_ms": self.duracao_ms,
            "fonte": self.fonte, "status": self.status,
            "processos_encontrados": self.processos_encontrados,
            "processos_novos": self.processos_novos,
            "processos_atualizados": self.processos_atualizados,
            "andamentos_criados": self.andamentos_criados,
            "prazos_gerados": self.prazos_gerados,
            "alertas_gerados": self.alertas_gerados,
            "mensagem": self.mensagem,
            "erro": self.erro,
        }
    CapturaOAB.to_dict = captura

    def parte(self):
        return {
            "id": self.id, "processo_id": self.processo_id,
            "nome": self.nome, "documento": self.documento,
            "tipo_pessoa": self.tipo_pessoa, "polo": self.polo,
            "tipo_parte": self.tipo_parte, "oab": self.oab, "uf_oab": self.uf_oab,
        }
    ParteProcesso.to_dict = parte

    def doc(self):
        return {
            "id": self.id, "cliente_id": self.cliente_id, "tipo": self.tipo,
            "valor": self.valor, "valor_normalizado": self.valor_normalizado,
            "principal": self.principal,
        }
    DocumentoCliente.to_dict = doc

    def alerta(self):
        return {
            "id": self.id, "cliente_id": self.cliente_id,
            "cliente_nome": self.cliente.nome if self.cliente else None,
            "processo_id": self.processo_id,
            "processo_cnj": self.processo.numero_cnj if self.processo else None,
            "oab_id": self.oab_id,
            "oab_formatada": self.oab.oab_formatada if self.oab else None,
            "tipo": self.tipo, "severidade": self.severidade,
            "titulo": self.titulo, "descricao": self.descricao,
            "match_tipo": self.match_tipo, "match_valor": self.match_valor,
            "lido": self.lido,
            "lido_em": self.lido_em.isoformat() if self.lido_em else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    AlertaCliente.to_dict = alerta

_add_to_dict_methods()
