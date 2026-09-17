package synapse.api.job;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import java.math.BigDecimal;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.dao.EmptyResultDataAccessException;

@Service
class BuscarJobService {
    private final JdbcTemplate jdbc;
    private final JsonMapper json = new JsonMapper();
    BuscarJobService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }
    
    JobDetalhadoDto buscar(UUID jobId) {
        try {
            return this.jdbc.queryForObject("""
                    SELECT
                        j.id,
                        j.status,
                        s.tipo AS origem,
                        j.competencias,
                        j.orcamento,
                        j.criado_em,
                        j.iniciado_em,
                        j.finalizado_em,
                        j.submissao_id,

                        r.id AS regra_id,
                        r.versao AS regra_versao,
                        r.origem AS regra_origem,
                        r.nucleo AS regra_nucleo,
                        r.especificacoes AS regra_especificacoes,
                        r.criada_em AS regra_criada_em,

                        sim.id AS simulacao_id,
                        sim.criado_em AS simulacao_criada_em,
                        sim.flag_baixa_rastreabilidade,

                        rs.status AS simulacao_status,
                        rs.veredito AS simulacao_veredito,
                        rs.totais AS simulacao_totais,
                        rs.assercoes AS simulacao_assercoes,
                        rs.decomposicao AS simulacao_decomposicao

                    FROM jobs j
                    JOIN submissoes s ON s.id = j.submissao_id
                    JOIN regras r ON r.job_id = j.id
                    LEFT JOIN simulacoes sim ON sim.job_id = j.id
                    LEFT JOIN resultados_simulacao rs ON rs.id = sim.resultado_id
                    WHERE j.id = ?
                    """,
                    (rs, rowNum) -> {
                        UUID id = rs.getObject("id", UUID.class);
                        String status = rs.getString("status");
                        String origem = rs.getString("origem");
                        List<String> competencias = List.of((String[]) rs.getArray("competencias").getArray());
                        BigDecimal orcamento = rs.getBigDecimal("orcamento");
                        Instant criadoEm = rs.getTimestamp("criado_em").toInstant();
                        Instant iniciadoEm = rs.getTimestamp("iniciado_em") != null
                                ? rs.getTimestamp("iniciado_em").toInstant()
                                : null;
                        Instant finalizadoEm = rs.getTimestamp("finalizado_em") != null
                                ? rs.getTimestamp("finalizado_em").toInstant()
                                : null;
                        UUID submissaoId = rs.getObject("submissao_id", UUID.class);
                        UUID regraId = rs.getObject("regra_id", UUID.class);
                        int regraVersao = rs.getInt("regra_versao");
                        String regraOrigem = rs.getString("regra_origem");
                        Instant regraCriadaEm = rs.getTimestamp("regra_criada_em").toInstant();

                        NucleoRegraDto regraNucleo = this.json.readValue(
                            rs.getString("regra_nucleo"),
                            NucleoRegraDto.class);

                        List<EspecificacaoRegraDto> regraEspecificacoes = this.json.readValue(
                            rs.getString("regra_especificacoes"),
                            new TypeReference<List<EspecificacaoRegraDto>>() {
                        });

                        RepresentacaoRegraDto representacaoRegra = new RepresentacaoRegraDto(
                            regraNucleo,
                            regraEspecificacoes);

                        RegraCriadaDto regra = new RegraCriadaDto(
                                regraId,
                                regraVersao,
                                regraOrigem,
                                representacaoRegra,
                                regraCriadaEm);

                        UUID simulacaoId = rs.getObject("simulacao_id", UUID.class);

                        SimulacaoDto simulacao = null;

                        if (simulacaoId != null) {
                            Instant simulacaoCriadaEm = rs.getTimestamp("simulacao_criada_em").toInstant();
                            boolean flagBaixaRastreabilidade = rs.getBoolean("flag_baixa_rastreabilidade");

                            String simulacaoStatus = rs.getString("simulacao_status");
                            String simulacaoVeredito = rs.getString("simulacao_veredito");

                            ResultadoSimulacaoDto resultado = null;

                            if (simulacaoStatus != null) {
                                TotaisSimulacaoDto totais = this.json.readValue(
                                        rs.getString("simulacao_totais"),
                                        TotaisSimulacaoDto.class);

                                List<ResultadoAssercaoDto> assercoes = this.json.readValue(
                                        rs.getString("simulacao_assercoes"),
                                        new TypeReference<List<ResultadoAssercaoDto>>() {
                                        });

                                DecomposicaoResultadoDto decomposicao = this.json.readValue(
                                        rs.getString("simulacao_decomposicao"),
                                        DecomposicaoResultadoDto.class);

                                resultado = new ResultadoSimulacaoDto(
                                        totais,
                                        assercoes,
                                        decomposicao);
                            }

                            simulacao = new SimulacaoDto(
                                    simulacaoId,
                                    simulacaoCriadaEm,
                                    simulacaoStatus,
                                    simulacaoVeredito,
                                    flagBaixaRastreabilidade,
                                    resultado);
                        }

                        return new JobDetalhadoDto(id, status, origem, competencias, orcamento, criadoEm, iniciadoEm, finalizadoEm, submissaoId, regra, simulacao);
                    },
                    jobId);
        }
        catch (EmptyResultDataAccessException ex) {
            throw new JobNaoEncontradoException(jobId);
        }
    }

}
