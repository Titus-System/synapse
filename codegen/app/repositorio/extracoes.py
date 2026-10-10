from dataclasses import dataclass
from uuid import UUID, uuid5

import simplejson
from sqlalchemy import RowMapping, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.extracao.modelos import Rebaixamento, ResultadoExtracao
from app.extracao.parametros import validar_parametros
from app.extracao.validacao import validar_conteudo
from app.repositorio.artefatos import gravar_prompt_e_resposta_na_sessao
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra

_NAMESPACE = UUID("b09cb3bf-59fb-5f4c-8ee8-683455f69e82")
_BUSCAR = text(
    "SELECT e.id, e.job_id, e.submissao_id, e.resposta_id, r.prompt_id,"
    " e.representacao::text AS representacao, e.rebaixamentos::text AS rebaixamentos,"
    " e.parametros::text AS parametros"
    " FROM extracoes_regras e JOIN respostas_modelo r ON r.id = e.resposta_id"
    " WHERE e.job_id = :job_id AND e.submissao_id = :submissao_id"
)
_INSERIR = text(
    "INSERT INTO extracoes_regras"
    " (id, job_id, submissao_id, resposta_id, representacao, rebaixamentos, parametros,"
    " criado_em)"
    " VALUES (:id, :job_id, :submissao_id, :resposta_id,"
    " CAST(:representacao AS jsonb), CAST(:rebaixamentos AS jsonb), CAST(:parametros AS jsonb),"
    " now())"
    " ON CONFLICT DO NOTHING RETURNING id"
)


class PersistenciaExtracaoError(RuntimeError):
    """Falha de infraestrutura sanitizada, sujeita à reentrega do chamador."""

    pass


class _ExtracaoConcorrenteError(Exception):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class ExtracaoPersistida:
    id: UUID
    job_id: UUID
    submissao_id: UUID
    prompt_id: UUID
    resposta_id: UUID
    representacao: RepresentacaoRegra
    rebaixamentos: list[Rebaixamento]
    parametros: dict[str, ValorRegra]


def _ler(linha: RowMapping) -> ExtracaoPersistida:
    representacao = RepresentacaoRegra.model_validate(
        simplejson.loads(linha["representacao"], use_decimal=True)
    )
    rebaixamentos = [Rebaixamento(**item) for item in simplejson.loads(linha["rebaixamentos"])]
    validar_conteudo(representacao, rebaixamentos)
    parametros = validar_parametros(simplejson.loads(linha["parametros"], use_decimal=True))
    return ExtracaoPersistida(
        id=linha["id"],
        job_id=linha["job_id"],
        submissao_id=linha["submissao_id"],
        prompt_id=linha["prompt_id"],
        resposta_id=linha["resposta_id"],
        representacao=representacao,
        rebaixamentos=rebaixamentos,
        parametros=parametros,
    )


async def buscar_extracao(
    sessoes: async_sessionmaker[AsyncSession], *, job_id: UUID, submissao_id: UUID
) -> ExtracaoPersistida | None:
    falhou = False
    linha = None
    try:
        async with sessoes() as sessao:
            consulta = await sessao.execute(
                _BUSCAR, {"job_id": job_id, "submissao_id": submissao_id}
            )
            linha = consulta.mappings().one_or_none()
    except SQLAlchemyError:
        falhou = True
    if falhou:
        raise PersistenciaExtracaoError("Não foi possível consultar a extração")
    return None if linha is None else _ler(linha)


async def gravar_extracao(
    sessoes: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    submissao_id: UUID,
    resultado: ResultadoExtracao,
) -> ExtracaoPersistida:
    existente = await buscar_extracao(sessoes, job_id=job_id, submissao_id=submissao_id)
    if existente is not None:
        return existente
    representacao, rebaixamentos = validar_conteudo(
        resultado.representacao, resultado.rebaixamentos
    )
    parametros = validar_parametros(resultado.parametros)
    extracao_id = uuid5(_NAMESPACE, f"extracao:{job_id}:{submissao_id}")
    chamada = resultado.chamada
    salvo = None
    falhou = False
    try:
        async with sessoes() as sessao, sessao.begin():
            prompt_id, resposta_id = await gravar_prompt_e_resposta_na_sessao(
                sessao,
                job_id=job_id,
                no="extracao_parametros",
                prompt=chamada.prompt,
                modelo=chamada.modelo,
                resposta=chamada.resposta,
                consumo_tokens=chamada.consumo_tokens,
            )
            insercao = await sessao.execute(
                _INSERIR,
                {
                    "id": extracao_id,
                    "job_id": job_id,
                    "submissao_id": submissao_id,
                    "resposta_id": resposta_id,
                    "representacao": simplejson.dumps(
                        representacao, use_decimal=True, allow_nan=False
                    ),
                    "rebaixamentos": simplejson.dumps(rebaixamentos, ensure_ascii=False),
                    "parametros": simplejson.dumps(parametros, use_decimal=True, allow_nan=False),
                },
            )
            if insercao.scalar_one_or_none() is None:
                # Reverte também a chamada perdedora; o evento deve apontar o vencedor.
                raise _ExtracaoConcorrenteError
            salvo = ExtracaoPersistida(
                id=extracao_id,
                job_id=job_id,
                submissao_id=submissao_id,
                prompt_id=prompt_id,
                resposta_id=resposta_id,
                representacao=RepresentacaoRegra.model_validate(representacao),
                rebaixamentos=list(resultado.rebaixamentos),
                parametros=parametros,
            )
    except _ExtracaoConcorrenteError:
        pass
    except SQLAlchemyError:
        falhou = True
    # Nunca encadear a exceção do driver: ela pode conter parâmetros SQL e artefatos.
    if falhou:
        raise PersistenciaExtracaoError("Não foi possível persistir a extração")
    if salvo is not None:
        return salvo
    existente = await buscar_extracao(sessoes, job_id=job_id, submissao_id=submissao_id)
    if existente is None:
        raise PersistenciaExtracaoError("Extração concorrente indisponível")
    return existente
