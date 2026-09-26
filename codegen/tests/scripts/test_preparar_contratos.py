import json
import subprocess
import sys
from pathlib import Path
from shutil import copyfile, copytree


def test_preparacao_acompanha_schemas_e_runtime_resolve_novas_referencias(tmp_path: Path) -> None:
    componente = Path(__file__).resolve().parents[2]
    origem = tmp_path / "contracts" / "domain"
    artefato = tmp_path / "codegen"
    scripts = artefato / "scripts"
    scripts.mkdir(parents=True)
    copyfile(componente / "scripts" / "preparar_contratos.py", scripts / "preparar_contratos.py")
    copytree(componente.parent / "contracts" / "domain", origem)
    copytree(componente / "app", artefato / "app")
    novo = origem / "extensao-teste.schema.json"
    novo.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "https://synapse.local/contracts/domain/extensao-teste.schema.json",
                "type": "string",
                "const": "extensao_valida",
            }
        ),
        encoding="utf-8",
    )
    raiz = origem / "representacao-regra.schema.json"
    esquema = json.loads(raiz.read_text(encoding="utf-8"))
    esquema["properties"]["extensao"] = {"$ref": novo.name}
    esquema["required"].append("extensao")
    raiz.write_text(json.dumps(esquema), encoding="utf-8")

    subprocess.run([sys.executable, str(scripts / "preparar_contratos.py")], check=True)

    destino = artefato / "contracts" / "domain"
    assert {p.name: p.read_bytes() for p in destino.glob("*.schema.json")} == {
        p.name: p.read_bytes() for p in origem.glob("*.schema.json")
    }
    programa = """
import sys
sys.path.insert(0, sys.argv[1])
from app.representacao_regra import RepresentacaoRegra
from pydantic import ValidationError
regra = {"nucleo": {}, "especificacoes": [], "extensao": "extensao_valida"}
assert RepresentacaoRegra.model_validate(regra).para_contrato() == regra
regra["extensao"] = "extensao_invalida"
try:
    RepresentacaoRegra.model_validate(regra)
except ValidationError:
    pass
else:
    raise AssertionError("Runtime ignorou a nova referência")
"""
    subprocess.run([sys.executable, "-I", "-c", programa, str(artefato)], cwd=artefato, check=True)

    renomeado = novo.with_name("extensao-renomeada.schema.json")
    novo.rename(renomeado)
    esquema["properties"]["extensao"] = {"$ref": renomeado.name}
    raiz.write_text(json.dumps(esquema), encoding="utf-8")
    conteudo = json.loads(renomeado.read_text(encoding="utf-8"))
    conteudo["$id"] = f"https://synapse.local/contracts/domain/{renomeado.name}"
    renomeado.write_text(json.dumps(conteudo), encoding="utf-8")

    subprocess.run([sys.executable, str(scripts / "preparar_contratos.py")], check=True)

    assert {p.name: p.read_bytes() for p in destino.glob("*.schema.json")} == {
        p.name: p.read_bytes() for p in origem.glob("*.schema.json")
    }
    subprocess.run([sys.executable, "-I", "-c", programa, str(artefato)], cwd=artefato, check=True)


def test_preparacao_incorpora_eventos_e_referencias_fora_do_monorepo(tmp_path: Path) -> None:
    componente = Path(__file__).resolve().parents[2]
    origem = tmp_path / "contracts"
    artefato = tmp_path / "codegen"
    scripts = artefato / "scripts"
    scripts.mkdir(parents=True)
    copyfile(componente / "scripts" / "preparar_contratos.py", scripts / "preparar_contratos.py")
    copytree(componente.parent / "contracts", origem)
    copytree(componente / "app", artefato / "app")
    subprocess.run([sys.executable, str(scripts / "preparar_contratos.py")], check=True)
    destino = artefato / "contracts"
    assert {p.relative_to(destino): p.read_bytes() for p in destino.rglob("*.schema.json")} == {
        p.relative_to(origem): p.read_bytes() for p in origem.rglob("*.schema.json")
    }
    programa = """
import sys
sys.path.insert(0, sys.argv[1])
from app.contratos.mensagens import NoConcluido
from app.contratos.validacao import validar, ContratoError
import simplejson
from pathlib import Path
payload = simplejson.loads(
    (Path(sys.argv[1]) / 'contracts/examples/events/no-concluido.json').read_bytes(),
    use_decimal=True,
)
validar("no-concluido", payload)
NoConcluido.model_validate_json(simplejson.dumps(payload))
payload["concluido_em"] = "2025-11-28T14:32:10"
try:
    validar("no-concluido", payload)
except ContratoError:
    pass
else:
    raise AssertionError("Runtime ignorou o formato do schema incorporado")
"""
    copytree(origem / "examples", destino / "examples")
    origem.rename(tmp_path / "fonte-indisponivel")
    subprocess.run([sys.executable, "-I", "-c", programa, str(artefato)], cwd=artefato, check=True)
