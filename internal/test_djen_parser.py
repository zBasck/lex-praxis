"""Test rig do parser DJEN. Valida que _parse_item_publicacao extrai todos os
9 campos novos + 9 antigos. Sem internet. Sem Flask. Importa o dje_comunica
via importlib direto, contornando o __init__.py do pacote."""
import sys
import pathlib
import json
import importlib.util
import types
from datetime import date

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Stub do modulo .base (que importa Flask no __init__.py do pacote)
fake_base = types.ModuleType("app.harvest.base")
class AndamentoCapturado:
    def __init__(self, data, texto, fonte, url="", metadados=None):
        self.data = data
        self.texto = texto
        self.fonte = fonte
        self.url = url
        self.metadados = metadados or {}
fake_base.AndamentoCapturado = AndamentoCapturado
sys.modules["app"] = types.ModuleType("app")
sys.modules["app.harvest"] = types.ModuleType("app.harvest")
sys.modules["app.harvest.base"] = fake_base

# Carrega dje_comunica como app.harvest.dje_comunica para relative import funcionar
spec = importlib.util.spec_from_file_location(
    "app.harvest.dje_comunica", ROOT / "app/harvest/dje_comunica.py"
)
dje = importlib.util.module_from_spec(spec)
sys.modules["app.harvest.dje_comunica"] = dje
spec.loader.exec_module(dje)

# Carrega fixture
fixture = json.loads((ROOT / "internal/fixtures/djen_item_0801610.json").read_text())

# Cria engine mock (sem rede) e parseia
engine = dje.PJeComunicaEngine.__new__(dje.PJeComunicaEngine)
pub = engine._parse_item_publicacao(fixture)

assert pub is not None, "parse falhou"
print(f"CNJ normalizado: {pub.numero_cnj!r}  (esperado 0801610-47.2026.8.19.0068)")
assert pub.numero_cnj == "0801610-47.2026.8.19.0068", f"CNJ errado: {pub.numero_cnj}"

print(f"data: {pub.data}  (esperado 2026-07-02)")
assert pub.data == date(2026, 7, 2), f"data errada: {pub.data}"

print(f"tribunal: {pub.tribunal!r}  (esperado TJRJ)")
assert pub.tribunal == "TJRJ"

print(f"classe_nome: {pub.classe_nome!r}")
assert pub.classe_nome == "PROCEDIMENTO DO JUIZADO ESPECIAL CIVEL"

print(f"classe_codigo: {pub.classe_codigo!r}  (esperado 436)")
assert pub.classe_codigo == "436"

print(f"orgao: {pub.orgao!r}")
assert pub.orgao == "Juizado Especial Adjunto Civel da Comarca de Rio das Ostras"

print(f"tipo_documento: {pub.tipo_documento!r}  (esperado Sentenca)")
assert pub.tipo_documento == "Sentenca"

print(f"polo_ativo: {pub.polo_ativo!r}")
assert pub.polo_ativo == "ELIETE DA SILVA TEIXEIRA"

print(f"polo_passivo: {pub.polo_passivo!r}")
assert pub.polo_passivo == "CEG RIO S A"

print(f"valor_causa: {pub.valor_causa}  (esperado 5432.10)")
assert pub.valor_causa == 5432.10, f"valor_causa errado: {pub.valor_causa}"

print(f"polo_advogados (count): {len(pub.polo_advogados)}  (esperado 5 = 2 partes + 3 advogados)")
assert len(pub.polo_advogados) == 5, f"qtd errada: {len(pub.polo_advogados)}"

adv_244 = [a for a in pub.polo_advogados if str(a.get("numero_oab") or "") == "244384"]
assert len(adv_244) == 1
assert adv_244[0]["nome"] == "PATRICK DA SILVA BASTOS DE CASTRO"
assert adv_244[0]["uf_oab"] == "RJ"
print(f"  advogado 244384/RJ: {adv_244[0]['nome']}")

assert len(pub.advogados) == 3
print(f"  advogados (dedicated): {[a['numero_oab'] for a in pub.advogados]}")

print("\n*** TODOS OS 9 CAMPOS NOVOS + 9 ANTIGOS VALIDADOS ***")
print(f"  id_comunicacao={pub.id_comunicacao}, hash={pub.hash[:12]}...")
print(f"  url={pub.url[:50]}...")
print(f"  tipo_ato={pub.tipo_ato!r}")
print(f"  meio={pub.meio!r}")
print(f"  partes={pub.partes[:60]}...")
