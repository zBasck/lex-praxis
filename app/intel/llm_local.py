"""Integracao com modelos de IA locais (Ollama, llama.cpp, LM Studio, etc).

Suporta os seguintes providers locais (todos gratuitos):

1) **Ollama** (recomendado) - https://ollama.com
   - Instale: curl -fsSL https://ollama.com/install.sh | sh
   - Baixe um modelo: ollama pull llama3.1:8b
   - Endpoint padrao: http://localhost:11434

2) **LM Studio** - https://lmstudio.ai
   - GUI desktop, servidor OpenAI-compat em http://localhost:1234/v1

3) **llama.cpp server** - linha de comando

4) **Qualquer endpoint OpenAI-compat** (llamafile, vllm, etc)

Modelos leves recomendados (4-8 GB RAM):
- llama3.1:8b (Ollama) - bom equilibrio qualidade/velocidade
- qwen2.5:7b (Ollama) - excelente em portugues
- gemma2:9b (Ollama) - bom para tarefas estruturadas
- mistral:7b (Ollama) - rapido

Modelos ainda mais leves (2-4 GB):
- llama3.2:3b
- phi3:mini
- gemma2:2b

Para os casos de uso do Lex-Praxis (resumir publicacoes, classificar andamentos,
sugerir tarefas), um modelo de 3-8B parametros e suficiente.
"""
from __future__ import annotations
import json
import logging
import os
import re
from typing import Optional

import requests

log = logging.getLogger(__name__)


DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "local")
DEFAULT_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "llama3.1:8b")
DEFAULT_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))


class LocalLLMClient:
    """Cliente unificado para providers locais de LLM."""

    def __init__(self, provider: str = None, endpoint: str = None,
                 model: str = None, api_key: str = None,
                 timeout: int = None, enabled: bool = True):
        self.enabled = bool(enabled) if enabled is not None else True
        self.provider = (provider or DEFAULT_PROVIDER).lower()
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.timeout = timeout or DEFAULT_TIMEOUT

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        try:
            if self.provider == "ollama":
                r = requests.get(f"{self.endpoint}/api/tags", timeout=10)
                return r.status_code == 200
            if self.provider in ("openai", "openai_compat", "lmstudio"):
                r = requests.get(f"{self.endpoint}/v1/models", timeout=10)
                return r.status_code == 200
        except Exception as e:
            log.debug("LLM local indisponivel: %s", e)
        return False

    def list_models(self) -> list:
        try:
            if self.provider == "ollama":
                r = requests.get(f"{self.endpoint}/api/tags", timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    return [m.get("name") for m in data.get("models", []) if m.get("name")]
            if self.provider in ("openai", "openai_compat", "lmstudio"):
                r = requests.get(f"{self.endpoint}/v1/models", timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    return [m.get("id") for m in data.get("data", []) if m.get("id")]
        except Exception as e:
            log.warning("Falha listando modelos: %s", e)
        return []

    def generate(self, prompt: str, system: str = None,
                 temperature: float = 0.1, max_tokens: int = 1024) -> Optional[str]:
        if self.provider == "ollama":
            return self._generate_ollama(prompt, system, temperature, max_tokens)
        if self.provider in ("openai", "openai_compat", "lmstudio"):
            return self._generate_openai_compat(prompt, system, temperature, max_tokens)
        return None

    def _generate_ollama(self, prompt, system, temperature, max_tokens) -> Optional[str]:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            body["system"] = system
        try:
            r = requests.post(f"{self.endpoint}/api/generate",
                              json=body, timeout=self.timeout)
            if r.status_code != 200:
                log.warning("Ollama HTTP %s: %s", r.status_code, r.text[:200])
                return None
            data = r.json()
            return data.get("response", "").strip() or None
        except Exception as e:
            log.warning("Ollama request falhou: %s", e)
            return None

    def _generate_openai_compat(self, prompt, system, temperature, max_tokens) -> Optional[str]:
        url = f"{self.endpoint}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            if r.status_code != 200:
                log.warning("OpenAI-compat HTTP %s: %s", r.status_code, r.text[:200])
                return None
            data = r.json()
            choices = data.get("choices") or []
            if choices:
                return (choices[0].get("message") or {}).get("content", "").strip() or None
        except Exception as e:
            log.warning("OpenAI-compat request falhou: %s", e)
        return None


SYSTEM_PROMPT_PT = """Voce e um assistente juridico brasileiro. Responda de forma clara,
objetiva e em portugues. Use terminologia juridica adequada. Seja conciso."""


PROMPT_RESUMIR = """Resuma a publicacao juridica abaixo em ate 3 frases, indicando:
- Tipo de ato (sentenca, decisao, despacho, etc)
- Conteudo principal (o que foi decidido/determinado)
- Proxima providencia sugerida (se houver)

PUBLICACAO:
{texto}

RESUMO:"""


PROMPT_CLASSIFICAR = """Classifique a publicacao juridica abaixo em UMA das categorias:
- sentenca
- acordao
- decisao_interlocutoria
- despacho
- intimacao
- recurso_apelacao
- recurso_agravo
- embargos_declaracao
- contestacao
- audiencia
- penhora
- alvara
- outros

Responda APENAS com a categoria (uma palavra), sem explicacao.

PUBLICACAO:
{texto}

CATEGORIA:"""


PROMPT_TAREFA = """Voce e advogado brasileiro. Analise a publicacao abaixo e sugira a
proxima tarefa a ser feita pelo advogado (em portugues, ate 200 caracteres).

PUBLICACAO:
{texto}

TAREFA SUGERIDA:"""


def resumir_publicacao(texto: str, cfg: dict = None) -> Optional[str]:
    client = _client_from_cfg(cfg)
    if not client or not client.is_available():
        return None
    prompt = PROMPT_RESUMIR.format(texto=(texto or "")[:3500])
    return client.generate(prompt, system=SYSTEM_PROMPT_PT, temperature=0.2, max_tokens=300)


def classificar_ato(texto: str, cfg: dict = None) -> Optional[str]:
    client = _client_from_cfg(cfg)
    if not client or not client.is_available():
        return None
    prompt = PROMPT_CLASSIFICAR.format(texto=(texto or "")[:3000])
    resp = client.generate(prompt, system=SYSTEM_PROMPT_PT, temperature=0.0, max_tokens=20)
    if resp:
        resp = resp.lower().strip().strip(".")
        resp = re.sub(r"[^a-z_]", "", resp)
        return resp or None
    return None


def sugerir_tarefa(texto: str, cfg: dict = None) -> Optional[str]:
    client = _client_from_cfg(cfg)
    if not client or not client.is_available():
        return None
    prompt = PROMPT_TAREFA.format(texto=(texto or "")[:3500])
    return client.generate(prompt, system=SYSTEM_PROMPT_PT, temperature=0.3, max_tokens=150)


def _client_from_cfg(cfg: dict = None) -> Optional[LocalLLMClient]:
    if not cfg:
        cfg = {}
    enabled = cfg.get("llm_enabled")
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("1", "true", "yes", "on")
    if not enabled:
        return None
    return LocalLLMClient(
        provider=cfg.get("llm_provider", "ollama"),
        endpoint=cfg.get("llm_endpoint") or DEFAULT_ENDPOINT,
        model=cfg.get("llm_model") or DEFAULT_MODEL,
        api_key=cfg.get("llm_api_key"),
        enabled=True,
    )


def status(cfg: dict = None) -> dict:
    """Retorna status do LLM local. Se `cfg` (dict com chaves llm_*)
    for passado, usa ele. Senao, cai para o os.environ (retrocompat)."""
    if not cfg:
        cfg = {
            "llm_enabled": os.environ.get("LLM_ENABLED", "0") in ("1", "true", "yes"),
            "llm_provider": DEFAULT_PROVIDER,
            "llm_endpoint": DEFAULT_ENDPOINT,
            "llm_model": DEFAULT_MODEL,
        }
    # Coerce llm_enabled pra bool (vem do banco como int 0/1 ou bool)
    enabled = cfg.get("llm_enabled")
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("1", "true", "yes", "on")
    elif enabled is None:
        enabled = False
    else:
        enabled = bool(enabled)
    if not enabled:
        return {
            "available": False, "enabled": False, "modelos": [],
            "provider": cfg.get("llm_provider", DEFAULT_PROVIDER),
            "endpoint": cfg.get("llm_endpoint", DEFAULT_ENDPOINT),
            "model": cfg.get("llm_model", DEFAULT_MODEL),
        }
    client = _client_from_cfg(cfg)
    if not client:
        return {"available": False, "enabled": True, "modelos": []}
    available = client.is_available()
    modelos = client.list_models() if available else []
    return {
        "available": available,
        "enabled": True,
        "provider": client.provider,
        "endpoint": client.endpoint,
        "model": client.model,
        "modelos": modelos,
    }


def cfg_from_user_config(user_config) -> dict:
    """Monta o dict cfg a partir de um UserConfig (modelo do banco).
    Aceita o objeto OU None (retorna {})."""
    if not user_config:
        return {}
    return {
        "llm_enabled": bool(getattr(user_config, "llm_enabled", False)),
        "llm_provider": getattr(user_config, "llm_provider", None) or "ollama",
        "llm_endpoint": getattr(user_config, "llm_endpoint", None) or DEFAULT_ENDPOINT,
        "llm_model": getattr(user_config, "llm_model", None) or DEFAULT_MODEL,
        "llm_api_key": getattr(user_config, "llm_api_key", None) or "",
    }
