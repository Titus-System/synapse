# T-220 — checkpoint da validação

- Branch confirmada: feature/t-220-motor-reextracao; base HEAD 27b64f7.
- Etapas 1 e 2 presentes; alterações pré-existentes preservadas, incluindo os
  arquivos de distribuição t220-etapa2.zip e t220-etapa2/ na raiz.
- git diff --check passou; 59 testes focados passaram (focados-inicial.txt).
- Integração usa Decimal, rejeita chaves duplicadas, mantém parâmetros completos,
  aplica operações pela Etapa 1 e retorna diagnósticos locais sem serializá-los.
- Instruções e dados separados; nenhum bind de ferramenta ou execução dinâmica.
- Ambiente investigado: virtualenv existente incompleto, sem SDK Google. Poetry
  install --no-root --no-interaction concluiu usando poetry.lock após autorização.
  Manifestos não alterados. Log em ambiente-install.txt.
- Ruff identificou SIM105 no tratamento de exceção; mypy dos dois módulos passou.
- Lacunas: teste de schema não inspeciona kwargs, falta precisão monetária
  fracionária; casos bloqueado/truncado usam JSON já inválido e não isolam o motivo.
- Pendência contratual de DiagnosticoOperacao mantida; não impede aplicação em memória.
- Asserções fortalecidas: schema/mime efetivamente enviados, mensagem enviada igual
  ao prompt auditado, diagnósticos exatos; bloqueio/truncamento usam JSON válido.
- Quatro casos adicionados: precisão monetária/metadados/imutabilidade, texto vazio,
  cancelamento e falha permanente sanitizada para parâmetros incompatíveis.
- RED por mutações restauradas byte a byte: 19 falhas por remoção da orquestração;
  1 falha pela omissão da correção no prompt. Cobrem todos os 20 casos unitários da
  Etapa 2. Evidências red-etapa2-orquestracao.txt e red-etapa2-prompt.txt.
- Corrigidos SIM105, formatação/imports, nome canônico orcamento no prompt e
  documentação da interface assíncrona e limites de persistência/observabilidade.
- Regressão focada final: 126 passed in 2.64s (focados-final.txt).
- Gate completo: Ruff passou; 161 arquivos conformes; mypy passou em 79 módulos.
- Pytest integral: 832 passed, 65 skipped, 22 erros de setup por permissão em tmp_path.
  Repetidos somente esses 22 com autorização fora do sandbox: 22 passed em 15,57 s.
  Consolidado: 854 aprovados, 65 skips condicionais, nenhuma falha remanescente.
- Credencial Google ausente pela configuração efetiva: teste real não executado.
- Base develop remota conhecida: 27b64f7; develop local está atrasada em 9260389.
- Relatório final escrito em t220-final-relatorio.md; limites de persistência,
  provedor real, retry sanitizado e observabilidade documentados.
- Diff/status finais gerados: 11 arquivos no diff, incluindo 9 não rastreados;
  git apply --check --reverse e git diff --check passaram. Índice vazio,
  manifestos inalterados, relatórios ignorados pelo Git.
- Trabalho encerrado. Próximo passo externo: revisão humana do diff e CI do PR;
  nenhum comando de staging, commit, push, merge ou rebase foi executado.
