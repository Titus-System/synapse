"""Correção do código gerado cuja execução falhou: o limite e o que volta ao modelo.

O código vem do modelo e falha no sandbox por exceção, por cobertura incompleta, por um
resultado fora do schema ou por uma asserção violada. Nesses casos a falha que o worker gravou
volta ao modelo com o código que a produziu, e o código corrigido é executado de novo. Uma
versão da regra tem no máximo `LIMITE_DE_CODIGOS_POR_VERSAO` códigos: o primeiro e as
correções. A `api` aplica o mesmo limite ao decidir se a falha encerra o job, pela posição do
código entre os da versão, então os dois serviços chegam à mesma decisão em qualquer ordem de
consumo do resultado.

`erro_infra` fica de fora: a falha é do ambiente, e outro código não a resolve.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

LIMITE_DE_CODIGOS_POR_VERSAO: Final = 3

#: O `encaminhamento` da decisão que leva de volta à geração, gravado na trilha (US04).
ENCAMINHAMENTO_CORRECAO: Final = "correcao_codigo"

STATUS_CORRIGIVEIS: Final = frozenset({"erro_codigo", "assercao_violada"})

#: As causas de `erro_codigo` em `resultado-diagnostico.schema.json`, mais `assercao_violada`.
#: Fechado porque é rótulo de métrica; o que não está aqui conta como `desconhecida`.
CAUSAS_DE_CORRECAO: Final = (
    "excecao",
    "timeout",
    "memoria",
    "saida_truncada",
    "sem_envelope",
    "envelope_invalido",
    "envelope_de_outra_execucao",
    "codigo_de_saida_divergente",
    "resultado_fora_do_schema",
    "baseline_divergente",
    "resultado_incoerente",
    "cobertura_incompleta",
    "fora_do_escopo",
    "assercao_violada",
    "desconhecida",
)


@dataclass(frozen=True, slots=True, repr=False)
class FalhaDaExecucao:
    """O desfecho que o worker gravou para a execução que falhou.

    `diagnostico` e `assercoes_violadas` vêm do código gerado e da execução dele: são dados não
    confiáveis, que vão ao prompt da correção e nunca a log, evento ou métrica.
    """

    status: str
    diagnostico: Mapping[str, object] | None = None
    assercoes_violadas: list[Mapping[str, object]] = field(default_factory=list)

    def causa(self) -> str:
        """A causa da falha, do conjunto fechado `CAUSAS_DE_CORRECAO`."""
        if self.status == "assercao_violada":
            return "assercao_violada"
        causa = self.diagnostico.get("causa") if self.diagnostico is not None else None
        return causa if isinstance(causa, str) and causa in CAUSAS_DE_CORRECAO else "desconhecida"

    def para_prompt(self) -> dict[str, object]:
        """O que o modelo precisa para corrigir o código, sem campo vazio."""
        falha: dict[str, object] = {"status": self.status, "causa": self.causa()}
        if self.diagnostico is not None:
            for chave in (
                "falha",
                "problemas",
                "elementos_ausentes",
                "elementos_fora_da_regra",
                "linhas_fora_do_escopo",
            ):
                if self.diagnostico.get(chave):
                    falha[chave] = self.diagnostico[chave]
        if self.assercoes_violadas:
            falha["assercoes_violadas"] = [
                {"nome": assercao.get("nome"), "detalhe": assercao.get("detalhe")}
                for assercao in self.assercoes_violadas
            ]
        return falha


def corrige(status: str | None, posicao_do_codigo: int) -> bool:
    """Diz se a execução com este desfecho volta ao modelo para correção."""
    return status in STATUS_CORRIGIVEIS and posicao_do_codigo < LIMITE_DE_CODIGOS_POR_VERSAO
