"""Classificador de andamentos processuais.

Combina:
  1) motor de regras (rápido, offline, sempre funciona);
  2) LLM opcional (se configurado) para entender casos ambíguos.
"""
from __future__ import annotations
import re
import json
import logging
from dataclasses import dataclass, asdict
from typing import Optional

import requests

log = logging.getLogger(__name__)


@dataclass
class Classificacao:
    tipo_ato: str
    prazo_dias: Optional[int] = None
    prazo_marco: str = "publicacao"  # publicacao, intimacao, juntada, citacao
    tarefa_sugerida: str = ""
    resumo_cliente: str = ""
    confianca: float = 0.0
    origem: str = "regras"  # regras | llm

    def to_dict(self):
        return asdict(self)


# ============== REGRAS ==============

# (regex, tipo_ato, prazo_dias, prazo_marco, tarefa_sugerida)
RULES = [
    (r"\bintim(em|a-se|ação|ar)\b.{0,80}contrarrazões", "intimacao_contrarrazoes", 15, "publicacao",
     "Elaborar e protocolar contrarrazões"),
    (r"\bintim(em|a-se|ação|ar)\b.{0,80}manifesta(ç|c)ão", "intimacao_manifestacao", 15, "publicacao",
     "Manifestar-se nos autos"),
    (r"\bintim(em|a-se|ação|ar)\b.{0,80}replica", "intimacao_replica", 15, "publicacao",
     "Apresentar réplica"),
    (r"\bintim(em|a-se|ação|ar)\b.{0,80}alegações finais", "intimacao_alegacoes", 15, "publicacao",
     "Apresentar alegações finais"),
    (r"\bintim(em|a-se|ação|ar)\b.{0,80}recurso", "intimacao_recurso", 15, "publicacao",
     "Interpor recurso"),
    (r"\bintim(em|a-se|ação|ar)\b.{0,80}cumprimento", "intimacao_cumprimento", 15, "publicacao",
     "Cumprimento de decisão/sentença"),
    (r"\bcit(ação|ar|em)\b", "citacao", 15, "citacao", "Verificar tempestividade da citação"),
    (r"\baudiência\b.{0,40}(designad|marcad|realiz)", "audiencia", None, "intimacao",
     "Comparecer à audiência"),
    (r"\bsentença\b", "sentenca", None, "publicacao", "Analisar sentença e interpor recurso se cabível"),
    (r"\bdespacho\b", "despacho", None, "publicacao", ""),
    (r"\bdecis(ão|ão interlocutória)\b", "decisao_interlocutoria", None, "publicacao",
     "Analisar decisão interlocutória"),
    (r"\b(embargo[s]? de declaraç(ão|ões))\b", "acordao_embargos", 5, "publicacao",
     "Interpor embargos de declaração"),
    (r"\bacórd(ão|am)\b", "acordao", 15, "publicacao", "Analisar acórdão e interpor recurso se cabível"),
    (r"\bjulgad(o|amento)\b", "julgamento", None, "publicacao", "Verificar resultado do julgamento"),
    (r"\bpublicad(o|a)\b.{0,30}intimação", "publicacao_intimacao", 0, "publicacao", ""),
    (r"\bcertidão\b", "certidao", None, "publicacao", ""),
    (r"\bconclus(ão|os)\b.{0,30}(sentença|decisão|despacho)", "conclusao", None, "juntada", ""),
    (r"\bjuntada\b", "juntada", None, "juntada", ""),
    (r"\bexpedid(o|a)\b.{0,30}alvará", "expedicao_alvara", None, "publicacao", "Levantar alvará"),
    (r"\bpenhor(a|ado)\b", "penhora", None, "publicacao", "Verificar penhora"),
    (r"\bleil(ão|ões)\b", "leilao", None, "publicacao", "Acompanhar leilão"),
]

DEADLINE_HINTS = [
    (r"\b(\d{1,2})\s*\(?dias\)?\b", None),
    (r"\bprazo\s*de\s*(\d{1,3})\b", None),
]


def classify_by_rules(texto: str) -> Classificacao:
    if not texto:
        return Classificacao(tipo_ato="outros", origem="regras")

    t = texto.lower()

    for pat, tipo, prazo, marco, tarefa in RULES:
        if re.search(pat, t, re.IGNORECASE):
            # Tenta refinar prazo a partir do texto (ex: "prazo de 10 dias")
            if prazo is None:
                for dpat, _ in DEADLINE_HINTS:
                    m = re.search(dpat, t)
                    if m:
                        try:
                            prazo = int(m.group(1))
                            break
                        except Exception:
                            pass
            return Classificacao(
                tipo_ato=tipo,
                prazo_dias=prazo,
                prazo_marco=marco,
                tarefa_sugerida=tarefa,
                resumo_cliente=_resumo(tipo, texto),
                confianca=0.75,
                origem="regras",
            )

    return Classificacao(
        tipo_ato="outros",
        prazo_dias=_extract_days(t),
        prazo_marco="publicacao",
        tarefa_sugerida="Revisar andamento",
        resumo_cliente="Movimentação processual sem classificação específica.",
        confianca=0.4,
        origem="regras",
    )


def _extract_days(texto: str) -> Optional[int]:
    m = re.search(r"prazo\s*de\s*(\d{1,3})\s*dias", texto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,2})\s*dias\b", texto, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 60:
            return n
    return None


def _resumo(tipo: str, texto: str) -> str:
    base = {
        "intimacao_contrarrazoes": "Você foi intimado a apresentar contrarrazões.",
        "intimacao_manifestacao": "Você foi intimado a se manifestar nos autos.",
        "intimacao_replica": "Você foi intimado a apresentar réplica.",
        "intimacao_alegacoes": "Você foi intimado a apresentar alegações finais.",
        "intimacao_recurso": "Você foi intimado a interpor recurso.",
        "intimacao_cumprimento": "Você foi intimado a cumprir decisão/sentença.",
        "citacao": "Houve citação nos autos.",
        "audiencia": "Audiência designada/marcada/realizada.",
        "sentenca": "Sentença proferida. Avaliar recurso cabível.",
        "despacho": "Despacho judicial — sem prazo recursal em regra.",
        "decisao_interlocutoria": "Decisão interlocutória. Avaliar agravo, se cabível.",
        "acordao_embargos": "Embargos de declaração — prazo curto de 5 dias.",
        "acordao": "Acórdão publicado. Avaliar recurso cabível.",
        "julgamento": "Julgamento realizado.",
        "publicacao_intimacao": "Publicação de intimação.",
        "certidao": "Certidão juntada aos autos.",
        "conclusao": "Autos conclusos ao juiz.",
        "juntada": "Documento/protocolo juntado.",
        "expedicao_alvara": "Alvará expedido.",
        "penhora": "Penhora registrada.",
        "leilao": "Leilão marcado/realizado.",
        "outros": "Movimentação processual.",
    }
    return base.get(tipo, "Movimentação processual registrada.")


# ============== LLM (opcional) ==============

PROMPT_SISTEMA = """Você é um classificador jurídico brasileiro. Recebe o texto de um andamento processual e devolve EXCLUSIVAMENTE um JSON válido com os campos:
- tipo_ato: uma das opções [sentenca, decisao_interlocutoria, despacho, acordao, acordao_embargos, intimacao_recurso, intimacao_contrarrazoes, intimacao_manifestacao, intimacao_replica, intimacao_alegacoes, intimacao_cumprimento, audiencia, citacao, publicacao_intimacao, certidao, conclusao, juntada, expedicao_alvara, penhora, leilao, julgamento, outros]
- prazo_dias: inteiro ou null (número de dias úteis ou corridos, conforme texto)
- prazo_marco: uma das opções [publicacao, intimacao, citacao, juntada]
- tarefa_sugerida: ação objetiva que o advogado deve tomar (string curta)
- resumo_cliente: explicação clara em 1 linha para o cliente final
Responda apenas o JSON, sem markdown, sem comentários."""


def classify_by_llm(texto: str, provider: str, api_key: str, model: str, timeout: int = 20) -> Optional[Classificacao]:
    if not api_key:
        return None
    try:
        if provider == "openai":
            return _openai(texto, api_key, model, timeout)
        if provider == "anthropic":
            return _anthropic(texto, api_key, model, timeout)
    except Exception as e:
        log.warning("LLM classifier falhou: %s", e)
    return None


def _openai(texto, api_key, model, timeout):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": texto[:4000]},
            ],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    return Classificacao(
        tipo_ato=data.get("tipo_ato", "outros"),
        prazo_dias=data.get("prazo_dias"),
        prazo_marco=data.get("prazo_marco", "publicacao"),
        tarefa_sugerida=data.get("tarefa_sugerida", ""),
        resumo_cliente=data.get("resumo_cliente", ""),
        confianca=0.95,
        origem="llm",
    )


def _anthropic(texto, api_key, model, timeout):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model or "claude-3-5-haiku-20241022",
            "max_tokens": 600,
            "system": PROMPT_SISTEMA,
            "messages": [{"role": "user", "content": texto[:4000]}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    blocks = r.json().get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    # Extrai JSON mesmo se vier com blocos de código
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(m.group(0) if m else text)
    return Classificacao(
        tipo_ato=data.get("tipo_ato", "outros"),
        prazo_dias=data.get("prazo_dias"),
        prazo_marco=data.get("prazo_marco", "publicacao"),
        tarefa_sugerida=data.get("tarefa_sugerida", ""),
        resumo_cliente=data.get("resumo_cliente", ""),
        confianca=0.95,
        origem="llm",
    )


# ============== FACHADA ==============

def classify(texto: str, llm_provider: str = "local", llm_key: str = "",
             llm_model: str = "llama3.1:8b", timeout: int = 20) -> Classificacao:
    """Classifica usando LLM quando disponível; cai para regras se falhar.

    Providers suportados:
      - openai / anthropic (requer llm_key)
      - local (Ollama/LM Studio/llama.cpp) - via app.intel.llm_local
    """
    # 1) OpenAI / Anthropic (pago)
    if llm_provider in {"openai", "anthropic"} and llm_key:
        out = classify_by_llm(texto, llm_provider, llm_key, llm_model, timeout)
        if out:
            return out
    # 2) Local (Ollama, LM Studio, llama.cpp) - GRATUITO
    if llm_provider in {"local", "ollama", "openai_compat", "lmstudio"}:
        try:
            from app.intel.llm_local import classificar_ato
            res = classificar_ato(texto)
            if res and isinstance(res, str):
                import json as _json
                try:
                    parsed = _json.loads(res)
                    if isinstance(parsed, dict):
                        return Classificacao(
                            tipo_ato=parsed.get("tipo_ato", "outros"),
                            prazo_dias=parsed.get("prazo_dias"),
                            prazo_marco=parsed.get("prazo_marco", "publicacao"),
                            tarefa_sugerida=parsed.get("tarefa_sugerida", ""),
                            resumo_cliente=parsed.get("resumo_cliente", ""),
                            confianca=0.8,
                            origem="llm_local",
                        )
                except (_json.JSONDecodeError, ValueError):
                    # LLM devolveu texto livre - tenta extrair tipo_ato
                    return Classificacao(
                        tipo_ato=res.strip()[:50] or "outros",
                        tarefa_sugerida="Verificar publicacao",
                        confianca=0.5,
                        origem="llm_local",
                    )
        except Exception as e:
            log.debug("LLM local indisponivel, usando regras: %s", e)
    # 3) Regras (fallback)
    return classify_by_rules(texto)
