# Verificação de E1 — tentativa em 06/10/2026

Consulta ao código atual: `codegen/app/extracao/motor.py`, `codegen/app/graph/prompts/extraction.py` e `codegen/docs/extracao.md`. A documentação de extração atribui a conferência determinística dos números à T-210. A validação de schema e a preservação de um trecho literal não comprovam que a LLM extraiu corretamente os valores.

O motor recupera descrição ausente a partir de um trecho literal encontrado no texto. Isso não converte números por extenso; o prompt pede percentual em fração e códigos como strings. Não inferir que toda resposta em algarismos funciona ou que toda resposta por extenso falha. É necessária a execução da extração real e revisão da representação produzida para cada transcrição.

Foi preparado um teste auxiliar isolado em `../work/verificar-e1.py` (relativo à raiz do repositório), com as 44 respostas reais de ASR, modelo LLM controlado, preservação literal e rejeição de recuperação por trecho ausente. Esse teste não envia dados a uma LLM e não implementa nem valida conversão numérica. Ele também não substitui o teste de extração com o modelo do codegen.

**Execução bloqueada antes dos casos:** Windows Application Control impediu carregar a biblioteca nativa `_uuid_utils`, dependência importada por langchain-core. Não houve contorno da política nem execução bem-sucedida de E1. As dependências auxiliares foram instaladas somente em `work/e1-deps`, sem alterar manifestos ou código da aplicação. Python usado: runtime integrado do Codex, versão 3.12; dependências diretas obtidas nas versões do requirements: simplejson 3.20.2, jsonschema 4.25.1 e langchain-core 1.6.3. Dependências transitivas desta tentativa isolada não equivalem ao ambiente lockado completo.

Comando tentado: Python integrado executando `../work/verificar-e1.py`. Resultado: ImportError por política de Controle de Aplicativo. A pessoa responsável pelo ambiente pode executar a avaliação em um ambiente autorizado com as dependências do projeto, mantendo essa política.

Nenhuma alegação de E1 aprovado ou compatibilidade numérica validada deve ser feita a partir desta tentativa.
