from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml


DIRETORIO_CONTRATOS = Path(__file__).resolve().parent


def validar_com_alteracao(
    exemplo: str, alterar: Callable[[Any], None]
) -> subprocess.CompletedProcess[str]:
    """Roda o validador sobre uma cópia de contracts/ em que o exemplo foi alterado."""
    with tempfile.TemporaryDirectory() as diretorio_temporario:
        diretorio_copia = Path(diretorio_temporario) / "contracts"
        shutil.copytree(DIRETORIO_CONTRATOS, diretorio_copia)
        caminho_exemplo = diretorio_copia / "examples" / exemplo

        with caminho_exemplo.open(encoding="utf-8") as arquivo:
            conteudo = json.load(arquivo)
        alterar(conteudo)
        with caminho_exemplo.open("w", encoding="utf-8") as arquivo:
            json.dump(conteudo, arquivo, ensure_ascii=False)

        return subprocess.run(
            [sys.executable, str(diretorio_copia / "validar-exemplos.py")],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )


def validar_openapi_com_alteracao(
    alterar: Callable[[Any], None]
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as diretorio_temporario:
        diretorio_copia = Path(diretorio_temporario) / "contracts"
        shutil.copytree(DIRETORIO_CONTRATOS, diretorio_copia)
        caminho_openapi = diretorio_copia / "http" / "openapi.yaml"
        with caminho_openapi.open(encoding="utf-8") as arquivo:
            documento = yaml.safe_load(arquivo)
        alterar(documento)
        with caminho_openapi.open("w", encoding="utf-8") as arquivo:
            yaml.safe_dump(documento, arquivo, allow_unicode=True, sort_keys=False)
        return subprocess.run(
            [sys.executable, str(diretorio_copia / "validar-exemplos.py")],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )


class TestarOpenApi(unittest.TestCase):
    def test_valida_limites_e_obrigatoriedade_do_nome(self) -> None:
        for requisicao, valido in (
            ({}, False),
            ({"nome": None}, False),
            ({"nome": 123}, False),
            ({"nome": ""}, False),
            ({"nome": " \t\n "}, False),
            ({"nome": "a" * 101}, False),
            ({"nome": "😀" * 101}, False),
            ({"nome": "a"}, True),
            ({"nome": "a" * 100}, True),
            ({"nome": "😀" * 100}, True),
            ({"nome": "  Comissão  de novembro  ", "campo_futuro": True}, True),
        ):
            with self.subTest(requisicao=requisicao):
                def alterar(documento: Any) -> None:
                    conteudo = documento["paths"]["/jobs/{id}/nome"]["put"]["requestBody"]
                    conteudo["content"]["application/json"]["examples"] = {
                        "caso": {"value": requisicao}
                    }

                resultado = validar_openapi_com_alteracao(alterar)
                if valido:
                    self.assertEqual(resultado.returncode, 0, resultado.stderr)
                else:
                    self.assertNotEqual(resultado.returncode, 0)
                    self.assertIn("exemplo caso", resultado.stderr)

    def test_resposta_usa_schema_referenciado_sem_copia(self) -> None:
        def alterar(documento: Any) -> None:
            documento["components"]["schemas"]["JobDetalhado"]["required"].append(
                "campo_futuro_obrigatorio"
            )

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("exemplo jobRenomeado", resultado.stderr)
        self.assertIn("'campo_futuro_obrigatorio' is a required property", resultado.stderr)

    def test_rejeita_resposta_invalida_pelo_schema_de_dominio(self) -> None:
        def alterar(documento: Any) -> None:
            resposta = documento["paths"]["/jobs/{id}/nome"]["put"]["responses"]["200"]
            resposta["content"]["application/json"]["examples"]["jobRenomeado"]["value"][
                "orcamento"
            ] = "invalido"

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("exemplo jobRenomeado, campo $.orcamento", resultado.stderr)

    def test_lista_usa_job_resumo_referenciado(self) -> None:
        def alterar(documento: Any) -> None:
            pagina = documento["paths"]["/jobs"]["get"]["responses"]["200"]
            itens = pagina["content"]["application/json"]["examples"]["nomesResolvidos"][
                "value"
            ]["itens"]
            itens[1]["nome"] = 123

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.itens[1].nome", resultado.stderr)

    def test_respostas_preservam_compatibilidade_com_nome_nulo_e_ausente(self) -> None:
        def alterar(documento: Any) -> None:
            documento["components"]["schemas"]["JobResumo"]["examples"][0]["nome"] = None
            resposta = documento["paths"]["/jobs/{id}"]["get"]["responses"]["200"]
            exemplos = resposta["content"]["application/json"]["examples"]
            exemplos["descricaoEmExtracao"]["value"]["nome"] = None
            del exemplos["simulacaoInviavel"]["value"]["nome"]

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_estrutura_openapi_invalida(self) -> None:
        def alterar(documento: Any) -> None:
            del documento["paths"]["/jobs/{id}/nome"]["put"]["responses"]["200"]["description"]

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("http/openapi.yaml", resultado.stderr)

    def test_rejeita_referencias_quebradas(self) -> None:
        for referencia in (
            "#/components/schemas/Inexistente",
            "../domain/inexistente.schema.json",
        ):
            with self.subTest(referencia=referencia):
                def alterar(documento: Any) -> None:
                    conteudo = documento["paths"]["/jobs/{id}/nome"]["put"]["requestBody"]
                    conteudo["content"]["application/json"]["schema"] = {"$ref": referencia}

                resultado = validar_openapi_com_alteracao(alterar)

                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn("http/openapi.yaml", resultado.stderr)

    def test_valida_exemplo_reutilizado_por_referencia(self) -> None:
        def alterar(documento: Any) -> None:
            documento["components"]["examples"] = {"NomeInvalido": {"value": {"nome": 123}}}
            conteudo = documento["paths"]["/jobs/{id}/nome"]["put"]["requestBody"]
            conteudo["content"]["application/json"]["examples"] = {
                "referenciado": {"$ref": "#/components/examples/NomeInvalido"}
            }

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("exemplo referenciado, campo $.nome", resultado.stderr)

    def test_rejeita_evento_invalido_dentro_do_exemplo_sse(self) -> None:
        def alterar(documento: Any) -> None:
            resposta = documento["paths"]["/jobs/{id}/events"]["get"]["responses"]["200"]
            exemplo = resposta["content"]["text/event-stream"]["examples"]["streamDeUmJob"]
            exemplo["value"] = exemplo["value"].replace(
                '"status":"gerando_regra"', '"status":"invalido"'
            )

        resultado = validar_openapi_com_alteracao(alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("exemplo streamDeUmJob", resultado.stderr)


class TestarValidador(unittest.TestCase):
    def test_rejeita_exemplo_com_campo_invalido(self) -> None:
        def alterar(exemplo: Any) -> None:
            exemplo["tokens_in"] = "invalido"

        resultado = validar_com_alteracao("domain/consumo-tokens.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/consumo-tokens.json", resultado.stderr)
        self.assertIn("campo $.tokens_in", resultado.stderr)


class TestarDiagnostico(unittest.TestCase):
    def test_rejeita_diagnostico_sem_causa(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["causa"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-timeout.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/resultado-diagnostico-timeout.json", resultado.stderr)
        self.assertIn("'causa' is a required property", resultado.stderr)

    def test_rejeita_falha_sem_traceback(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["falha"]["traceback"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-excecao.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.falha", resultado.stderr)
        self.assertIn("'traceback' is a required property", resultado.stderr)

    def test_rejeita_excecao_sem_falha(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["falha"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-excecao.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'falha' is a required property", resultado.stderr)

    def test_rejeita_falha_em_causa_sem_excecao_capturada(self) -> None:
        def alterar(diagnostico: Any) -> None:
            diagnostico["falha"] = {"tipo": "TimeoutError", "mensagem": "", "traceback": ""}

        resultado = validar_com_alteracao("domain/resultado-diagnostico-timeout.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/resultado-diagnostico-timeout.json: campo $:", resultado.stderr)

    def test_rejeita_resultado_fora_do_schema_sem_problemas(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["problemas"]

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-fora-do-schema.json", alterar
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'problemas' is a required property", resultado.stderr)

    def test_rejeita_valor_na_palavra_chave(self) -> None:
        def alterar(diagnostico: Any) -> None:
            diagnostico["problemas"][0]["palavra_chave"] = "type: 'abc'"

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-fora-do-schema.json", alterar
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.problemas[0].palavra_chave", resultado.stderr)

    def test_rejeita_cobertura_incompleta_sem_os_elementos(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["elementos_ausentes"]

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-cobertura-incompleta.json", alterar
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/resultado-diagnostico-cobertura-incompleta.json", resultado.stderr)

    def test_aceita_cobertura_incompleta_so_com_elemento_fora_da_regra(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["elementos_ausentes"]
            diagnostico["elementos_fora_da_regra"] = ["elem.9"]

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-cobertura-incompleta.json", alterar
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_elementos_em_causa_que_nao_e_cobertura(self) -> None:
        def alterar(diagnostico: Any) -> None:
            diagnostico["elementos_ausentes"] = ["elem.1"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-timeout.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/resultado-diagnostico-timeout.json: campo $:", resultado.stderr)

    def test_rejeita_elemento_ausente_fora_do_espaco_de_identificacao(self) -> None:
        def alterar(diagnostico: Any) -> None:
            diagnostico["elementos_ausentes"] = ["percentual"]

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-cobertura-incompleta.json", alterar
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.elementos_ausentes[0]", resultado.stderr)


class TestarExecutarCodigo(unittest.TestCase):
    def test_aceita_comando_sem_elementos_exigidos(self) -> None:
        # O campo é aditivo: um comando publicado antes dele continua válido.
        def alterar(comando: Any) -> None:
            del comando["elementos_exigidos"]

        resultado = validar_com_alteracao("events/executar-codigo-cobertura.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_elementos_exigidos_vazia(self) -> None:
        def alterar(comando: Any) -> None:
            comando["elementos_exigidos"] = []

        resultado = validar_com_alteracao("events/executar-codigo-cobertura.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn(
            "events/executar-codigo-cobertura.json: campo $.elementos_exigidos", resultado.stderr
        )

    def test_rejeita_elemento_exigido_repetido(self) -> None:
        def alterar(comando: Any) -> None:
            comando["elementos_exigidos"] = ["elem.1", "elem.1"]

        resultado = validar_com_alteracao("events/executar-codigo-cobertura.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.elementos_exigidos", resultado.stderr)

    def test_rejeita_elemento_exigido_fora_do_espaco_de_identificacao(self) -> None:
        def alterar(comando: Any) -> None:
            comando["elementos_exigidos"] = ["percentual"]

        resultado = validar_com_alteracao("events/executar-codigo-cobertura.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.elementos_exigidos[0]", resultado.stderr)


class TestarJobEncerrado(unittest.TestCase):
    def test_rejeita_estado_que_nao_e_terminal(self) -> None:
        # Processamento, inviabilidade e espera pelo usuário são pausas retomáveis.
        nao_terminais = (
            "gerando_regra",
            "simulando",
            "simulacao_inviavel",
            "aguardando_decisao_usuario",
        )
        for status in nao_terminais:
            with self.subTest(status=status):

                def alterar(evento: Any, status: str = status) -> None:
                    evento["status"] = status

                resultado = validar_com_alteracao("events/job-encerrado.json", alterar)

                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn("events/job-encerrado.json: campo $.status", resultado.stderr)

    def test_rejeita_encerramento_sem_identificador_estavel(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["evento_id"]

        resultado = validar_com_alteracao("events/job-encerrado.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'evento_id' is a required property", resultado.stderr)

    def test_rejeita_encerramento_sem_o_instante_da_transicao(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["encerrado_em"]

        resultado = validar_com_alteracao("events/job-encerrado-erro.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'encerrado_em' is a required property", resultado.stderr)


class TestarConflitos(unittest.TestCase):
    def test_rejeita_lista_de_conflitos_vazia(self) -> None:
        # A falta de conflito é a ausência do campo, não uma lista vazia.
        def alterar(evento: Any) -> None:
            evento["conflitos"] = []

        resultado = validar_com_alteracao("events/etapa-alterada-conflitos.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("events/etapa-alterada-conflitos.json: campo $.conflitos", resultado.stderr)

    def test_rejeita_conflito_sem_motivo(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["conflitos"][0]["motivo"]

        resultado = validar_com_alteracao("events/etapa-alterada-conflitos.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'motivo' is a required property", resultado.stderr)

    def test_rejeita_elemento_fora_do_espaco_de_identificacao(self) -> None:
        def alterar(evento: Any) -> None:
            evento["conflitos"][1]["elementos"] = ["loja"]

        resultado = validar_com_alteracao("events/etapa-alterada-conflitos.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.conflitos[1].elementos[0]", resultado.stderr)

    def test_aceita_etapa_sem_regra_e_sem_conflitos(self) -> None:
        # regra_id e conflitos são aditivos: um evento anterior a eles continua válido.
        def alterar(evento: Any) -> None:
            evento["status"] = "iniciada"
            del evento["regra_id"]
            del evento["conflitos"]

        resultado = validar_com_alteracao("events/etapa-alterada-conflitos.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_aceita_falha_da_reextracao_sem_regra(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["regra_id"]

        resultado = validar_com_alteracao("events/etapa-alterada-falha-reextracao.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_pausa_para_correcao_sem_a_versao_analisada(self) -> None:
        # Sem regra_id, a API não sabe sobre qual versão abrir a rodada.
        def alterar(evento: Any) -> None:
            del evento["regra_id"]

        resultado = validar_com_alteracao("events/etapa-alterada-conflitos.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'regra_id' is a required property", resultado.stderr)

    def test_rejeita_pausa_para_correcao_sem_conflitos(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["conflitos"]

        resultado = validar_com_alteracao("events/etapa-alterada-conflitos.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'conflitos' is a required property", resultado.stderr)


class TestarConflitosDaRodada(unittest.TestCase):
    def test_rejeita_lista_vazia(self) -> None:
        # Uma rodada só existe porque houve conflito.
        def alterar(conflitos: Any) -> None:
            conflitos.clear()

        resultado = validar_com_alteracao("domain/conflitos-rodada.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/conflitos-rodada.json: campo $:", resultado.stderr)

    def test_rejeita_conflito_sem_elementos(self) -> None:
        def alterar(conflitos: Any) -> None:
            del conflitos[0]["elementos"]

        resultado = validar_com_alteracao("domain/conflitos-rodada.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'elementos' is a required property", resultado.stderr)

    def test_rejeita_conflito_com_elementos_vazio(self) -> None:
        def alterar(conflitos: Any) -> None:
            conflitos[0]["elementos"] = []

        resultado = validar_com_alteracao("domain/conflitos-rodada.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $[0].elementos", resultado.stderr)

    def test_rejeita_conflito_com_motivo_vazio(self) -> None:
        def alterar(conflitos: Any) -> None:
            conflitos[1]["motivo"] = ""

        resultado = validar_com_alteracao("domain/conflitos-rodada.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $[1].motivo", resultado.stderr)


class TestarRegraSubmetida(unittest.TestCase):
    def test_rejeita_origem_texto_sem_submissao(self) -> None:
        # O texto da descrição só é alcançável pela submissão (claim-check).
        def alterar(evento: Any) -> None:
            del evento["submissao_id"]

        resultado = validar_com_alteracao("events/regra-submetida-texto.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("events/regra-submetida-texto.json", resultado.stderr)
        self.assertIn("'submissao_id' is a required property", resultado.stderr)

    def test_aceita_origem_texto_republicada_com_a_versao_extraida(self) -> None:
        def alterar(evento: Any) -> None:
            evento["regra_id"] = "9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f"

        resultado = validar_com_alteracao("events/regra-submetida-texto.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)


class TestarParametrosConfirmados(unittest.TestCase):
    def test_aceita_evento_sem_competencias_e_sem_orcamento(self) -> None:
        # Os campos são aditivos: uma mensagem publicada antes deles continua válida.
        def alterar(evento: Any) -> None:
            del evento["competencias"]
            del evento["orcamento"]

        resultado = validar_com_alteracao("events/parametros-confirmados.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_competencias_vazia(self) -> None:
        def alterar(evento: Any) -> None:
            evento["competencias"] = []

        resultado = validar_com_alteracao("events/parametros-confirmados.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("events/parametros-confirmados.json: campo $.competencias", resultado.stderr)

    def test_rejeita_competencia_fora_de_aaaa_mm(self) -> None:
        def alterar(evento: Any) -> None:
            evento["competencias"] = ["2025-13"]

        resultado = validar_com_alteracao("events/parametros-confirmados.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.competencias[0]", resultado.stderr)

    def test_rejeita_orcamento_negativo(self) -> None:
        def alterar(evento: Any) -> None:
            evento["orcamento"] = -0.01

        resultado = validar_com_alteracao("events/parametros-confirmados.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("events/parametros-confirmados.json: campo $.orcamento", resultado.stderr)


class TestarCorrecao(unittest.TestCase):
    def test_rejeita_correcao_submetida_sem_submissao(self) -> None:
        # O texto da correção só é alcançável pela submissão (claim-check).
        def alterar(evento: Any) -> None:
            del evento["submissao_id"]

        resultado = validar_com_alteracao("events/correcao-submetida.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'submissao_id' is a required property", resultado.stderr)

    def test_aceita_correcao_submetida_sem_competencias(self) -> None:
        # Campo aditivo: uma correção publicada antes dele continua válida.
        def alterar(evento: Any) -> None:
            del evento["competencias"]

        resultado = validar_com_alteracao("events/correcao-submetida.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_correcao_submetida_com_competencias_vazia(self) -> None:
        def alterar(evento: Any) -> None:
            evento["competencias"] = []

        resultado = validar_com_alteracao("events/correcao-submetida.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("events/correcao-submetida.json: campo $.competencias", resultado.stderr)

    def test_rejeita_correcao_proposta_sem_representacao(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["representacao"]

        resultado = validar_com_alteracao("events/correcao-proposta.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'representacao' is a required property", resultado.stderr)

    def test_rejeita_correcao_proposta_fora_do_formato_da_regra(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["representacao"]["especificacoes"]

        resultado = validar_com_alteracao("events/correcao-proposta.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.representacao", resultado.stderr)


class TestarRegraExtraida(unittest.TestCase):
    def test_rejeita_extracao_sem_submissao(self) -> None:
        # É pela submissão que a API confere que a extração pertence ao job.
        def alterar(evento: Any) -> None:
            del evento["submissao_id"]

        resultado = validar_com_alteracao("events/regra-extraida.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'submissao_id' is a required property", resultado.stderr)

    def test_rejeita_extracao_sem_referencia(self) -> None:
        def alterar(evento: Any) -> None:
            evento.pop("extracao_id", None)

        resultado = validar_com_alteracao("events/regra-extraida.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'extracao_id' is a required property", resultado.stderr)

    def test_rejeita_conteudo_mesmo_com_referencia(self) -> None:
        def alterar(evento: Any) -> None:
            evento["extracao_id"] = "2d963df3-e310-5d11-bf21-36918cae4ce4"
            evento["representacao"] = {"nucleo": {}, "especificacoes": []}

        resultado = validar_com_alteracao("events/regra-extraida.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("False schema", resultado.stderr)

    def test_rejeita_referencia_invalida(self) -> None:
        def alterar(evento: Any) -> None:
            evento["extracao_id"] = "invalido"

        resultado = validar_com_alteracao("events/regra-extraida.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.extracao_id", resultado.stderr)


class TestarDecomposicao(unittest.TestCase):
    def test_aceita_decomposicao_sem_as_quebras_absolutas(self) -> None:
        # As quebras absolutas são aditivas: um resultado anterior a elas continua válido.
        def alterar(decomposicao: Any) -> None:
            for quebra in ("matricula", "loja_absoluto", "competencia_absoluto"):
                del decomposicao[quebra]

        resultado = validar_com_alteracao("domain/resultado-decomposicao.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_rejeita_valor_absoluto_que_nao_e_numero(self) -> None:
        def alterar(decomposicao: Any) -> None:
            decomposicao["matricula"]["MATRIC-422"] = "141300"

        resultado = validar_com_alteracao("domain/resultado-decomposicao.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.matricula.MATRIC-422", resultado.stderr)

    def test_rejeita_competencia_absoluta_fora_de_aaaa_mm(self) -> None:
        def alterar(decomposicao: Any) -> None:
            decomposicao["competencia_absoluto"]["2025-13"] = 0

        resultado = validar_com_alteracao("domain/resultado-decomposicao.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.competencia_absoluto", resultado.stderr)


class TestarResultadoLinhas(unittest.TestCase):
    def test_rejeita_competencia_fora_de_aaaa_mm(self) -> None:
        for competencia in ("2025-13", "2025-00", "2025-8", "2025-08-01"):
            with self.subTest(competencia=competencia):

                def alterar(linhas: Any, competencia: str = competencia) -> None:
                    linhas[competencia] = linhas.pop("2025-08")

                resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn("domain/resultado-linhas.json: campo $:", resultado.stderr)

    def test_rejeita_linha_sem_campo_obrigatorio(self) -> None:
        for campo in (
            "cod_loja", "cod_marca", "cod_cargo", "comissao_baseline",
            "comissao_simulada", "diferenca", "contribuicoes",
        ):
            with self.subTest(campo=campo):

                def alterar(linhas: Any, campo: str = campo) -> None:
                    del linhas["2025-08"]["MATRIC-1"][campo]

                resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn(f"'{campo}' is a required property", resultado.stderr)

    def test_rejeita_contribuicao_fora_do_espaco_de_identificacao(self) -> None:
        def alterar(linhas: Any) -> None:
            linhas["2025-11"]["MATRIC-1"]["contribuicoes"] = {"bonus": 500}

        resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.2025-11.MATRIC-1.contribuicoes", resultado.stderr)

    def test_rejeita_contribuicao_com_delta_zero(self) -> None:
        def alterar(linhas: Any) -> None:
            linhas["2025-08"]["MATRIC-1"]["contribuicoes"] = {"elem.1": 0}

        resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.2025-08.MATRIC-1.contribuicoes.elem.1", resultado.stderr)

    def test_rejeita_matricula_vazia(self) -> None:
        def alterar(linhas: Any) -> None:
            linhas["2025-08"][""] = linhas["2025-08"].pop("MATRIC-1")

        resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.2025-08", resultado.stderr)

    def test_rejeita_codigo_numerico(self) -> None:
        for campo in ("cod_loja", "cod_marca", "cod_cargo"):
            with self.subTest(campo=campo):

                def alterar(linhas: Any, campo: str = campo) -> None:
                    linhas["2025-08"]["MATRIC-1"][campo] = 75

                resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn(f"campo $.2025-08.MATRIC-1.{campo}", resultado.stderr)

    def test_aceita_reducao_de_comissao(self) -> None:
        def alterar(linhas: Any) -> None:
            linha = linhas["2025-11"]["MATRIC-1"]
            linha["comissao_simulada"] = 119.63
            linha["diferenca"] = -500
            linha["contribuicoes"] = {"elem.1": -500}

        resultado = validar_com_alteracao("domain/resultado-linhas.json", alterar)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)


if __name__ == "__main__":
    unittest.main()
