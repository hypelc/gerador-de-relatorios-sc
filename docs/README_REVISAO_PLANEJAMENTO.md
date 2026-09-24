# Revisão do planejamento — Gerador de Relatórios SC

**Data da revisão:** 16/09/2026

**Status:** problemas conferidos no código atual; pronto para o chat de execução

**Escopo:** diagnóstico e instruções de correção; nenhum código de aplicação foi alterado nesta revalidação

Este documento deve ser lido junto com o [`README.md`](../README.md). O `README.md` continua sendo a especificação do produto; este arquivo define as correções de confiabilidade da versão já implementada. Onde houver diferença, use o contrato do produto do `README.md` e os casos reproduzidos aqui para orientar a correção. O chat de execução deve implementar e testar estas correções, sem redesenhar o produto.

## Resumo executivo

O sistema funciona para o arquivo de referência já validado, mas ainda não deve ser considerado estável para planilhas variadas. Os **nove problemas numerados abaixo foram confirmados** nesta revalidação por reprodução temporária ou por caminho direto no código. Há também duas falhas observáveis no controle de operações simultâneas; a consequência específica de apagar uma prévia durante a cópia ainda requer um teste controlado.

O maior risco é produzir um relatório aparentemente válido com dados interpretados incorretamente. Por isso, a próxima etapa deve começar pelos limites do motor de importação e validação, antes de ampliar a interface ou o empacotamento.

Nenhum bug foi corrigido durante esta revisão. Os nove testes existentes continuam passando; isso confirma que faltam testes para os cenários descritos abaixo, não que o comportamento esteja correto.

## Sistema revisado

Componentes principais:

- `gerador_sc/importers.py`: leitura de XLSX/CSV, detecção de tabelas e remapeamento.
- `gerador_sc/models.py`: tabelas reconhecidas, séries e diagnósticos.
- `gerador_sc/engine.py`: validação, prévia, exportação e limpeza.
- `gerador_sc/rendering.py`: gráficos, mapas, PDF e metodologia.
- `gerador_sc/ui.py`: assistente Qt em cinco etapas.
- `geodados/`: limites e recursos geográficos das oito macrorregiões.
- `tests/`: testes existentes do motor e da interface.
- `packaging/`: preparação de build para Windows e macOS.

Não há repositório Git, `CONTEXT.md` ou ADRs neste diretório.

## Evidência e limite das verificações

O chat de revisão anterior executou os comandos abaixo no ambiente virtual do projeto:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q gerador_sc scripts
.venv/bin/pyside6-deploy --dry-run -c pysidedeploy.spec --name "Gerador de Relatorios SC"
```

Resultados registrados pelo chat de revisão:

- 9 testes existentes passaram; nesta revalidação, `.venv/bin/python -m pytest -q` também terminou com **9 testes passando**.
- A compilação passou.
- Não foram encontradas dependências quebradas.
- O `pyside6-deploy --dry-run` passou; houve apenas avisos sobre chaves opcionais ausentes.
- O Python global não possui `pytest`; a execução correta depende de `.venv`.

Nesta revalidação, os cenários dos itens 1 a 7 foram executados em arquivos temporários `.xlsx` e `.csv`; o item 9 foi reproduzido na interface Qt em modo sem tela. O item 8 foi confirmado pela chamada da interface e pela assinatura do serviço: o evento de cancelamento não atravessa esse limite. Para o item de concorrência, foram reproduzidos o falso estado de uma segunda importação e a remoção da prévia no fechamento com worker marcado como ativo. Esses ensaios não alteraram a planilha de referência nem o código do programa.

### Arquivo de referência

`data/exemplos/BANCO DE DADOS CV - AMANDA E EMILENE.xlsx`:

- 21 abas.
- 22 tabelas reconhecidas e válidas.
- 160 fórmulas detectadas.
- 17 tabelas aptas para mapas.
- Prévia completa com 23 páginas.
- Prévia de mapa com 2 páginas.
- Valores ausentes continuam como `None`/“Sem dado”.
- O arquivo de origem permanece inalterado nos testes realizados.

Essa aprovação vale para o arquivo conhecido. Ainda não existe o segundo arquivo real prometido para o aceite do importador.

## Correções confirmadas para a execução

### 1. Alta — remapeamento mistura tabelas da mesma aba

Ao remapear uma tabela, `remap_table()` chama `_parse_table()` sem preservar o limite da próxima tabela. A primeira tabela de uma aba com dois blocos passa a incluir as séries do bloco seguinte.

Reprodução mínima:

```text
Antes:  Primeira = A, B; Segunda = C
Depois: Primeira remapeada = A, B, Segunda, C
```

Local principal: `gerador_sc/importers.py`, em `remap_table()` e no parâmetro `next_header_index` de `_parse_table()`. Na revalidação, a primeira tabela passou de `['A', 'B']` para `['A', 'B', 'Segunda', 'C']` depois do remapeamento.

Impacto: o relatório pode duplicar ou misturar indicadores sem acusar erro.

**Correção esperada:** manter os limites dos blocos detectados ao remapear; se a nova linha de cabeçalho atravessar outro bloco, rejeitar ou exigir uma redefinição explícita, nunca absorver a tabela seguinte. Testar remapeamento do primeiro e do segundo bloco, com identidades e séries preservadas.

### 2. Alta — remapeamento aceita coluna de ano como identificação

O usuário pode selecionar uma coluna que também pertence às colunas de anos. O resultado é marcado como válido, embora os nomes das séries sejam valores numéricos da planilha.

Reprodução mínima:

```text
Entrada:  Regiao | 2020 | 2021 | 2022
          A      | 1    | 2    | 3
          B      | 4    | 5    | 6

Mapeando a coluna 2020 como identificação:
Resultado válido com séries chamadas 1 e 4.
```

Local principal: `gerador_sc/importers.py`, validações de `selected_label` em `remap_table()`. Na revalidação, a tabela continuou `valid=True`, com séries `['1', '4']` e nenhum diagnóstico.

Impacto: interpretação errada com aparência de resultado correto.

**Correção esperada:** impedir que a coluna de identificação coincida com qualquer coluna usada como ano, tanto na detecção quanto no remapeamento. Devolver um diagnóstico claro; não aceitar a tabela como válida.

### 3. Alta — linha de dados que parece conter anos vira novo cabeçalho

O detector considera qualquer linha com pelo menos três números entre 1900 e 2100 como cabeçalho. Isso pode invalidar uma tabela legítima cujos valores também estejam nessa faixa.

Reprodução mínima:

```text
Regiao | 2019 | 2020 | 2021
A      | 2020 | 2021 | 2022
```

O sistema encontrou duas tabelas inválidas e nenhuma tabela válida. Isso foi reproduzido: as duas linhas viraram cabeçalhos candidatos, ambos com `TABLE_WITHOUT_SERIES`.

Local principal: `gerador_sc/importers.py`, `_candidate_header_rows()`.

Impacto: entrada compatível é rejeitada ou dividida incorretamente.

**Correção esperada:** distinguir cabeçalhos de linhas de valores usando contexto da tabela, além da contagem de números que parecem anos. Evitar criar um novo cabeçalho dentro de um bloco de dados em andamento. Manter a capacidade de reconhecer dois blocos reais na mesma aba.

### 4. Alta — validação aceita anos fora de ordem e tabelas duplicadas

`validate_report()` não rejeita `years=(2021, 2020)`, `years=(2020, 2020)` nem a seleção repetida do mesmo `table_id`. Na revalidação, os três casos retornaram **zero diagnósticos**. A interface normalmente monta anos ordenados e IDs únicos, mas o serviço público também precisa proteger esse contrato.

Local principal: `gerador_sc/engine.py`, `validate_report()`.

Impacto: eixo temporal pode ficar invertido e a mesma tabela pode aparecer mais de uma vez.

**Correção esperada:** validar que anos são inteiros únicos em ordem crescente e que `table_ids` não contém duplicatas, antes da renderização. Não corrigir silenciosamente a ordem enviada; informar o problema a quem chama o motor.

### 5. Média — metodologia do PDF ignora escolhas do relatório

A página de metodologia usa `table.years` e `table.unit`, em vez dos anos e da unidade efetivos da configuração. Também não registra o nome de indicador personalizado. Um PDF gerado na revalidação com apenas 2021 e unidade personalizada exibiu essas escolhas no gráfico, mas registrou `anos 2020 - 2022, Cobertura vacinal (%)` na metodologia.

Reprodução mínima:

```text
Período escolhido: 2021
Unidade escolhida: unidade escolhida
Metodologia exibida: anos 2020 - 2022 e unidade original
```

Local principal: `gerador_sc/rendering.py`, `_methodology_page()`.

Impacto: o PDF pode documentar um período e uma unidade diferentes dos efetivamente apresentados.

**Correção esperada:** fazer a metodologia informar exatamente os anos selecionados, inclusive quando não forem consecutivos, além da unidade e do indicador efetivamente usados no gráfico. Preservar a identificação da aba e das colunas de origem separadamente.

### 6. Média — CSV com campo multilinha é corrompido

O leitor usa `raw.splitlines()` antes do `csv.reader`. Um campo CSV entre aspas que contém quebra de linha é alterado silenciosamente; na revalidação, `"Regiao\nNorte"` virou `RegiaoNorte`.

Local principal: `gerador_sc/importers.py`, leitura do CSV em `_parse_source()`.

Impacto: nomes e rótulos podem ser modificados sem diagnóstico.

**Correção esperada:** entregar o fluxo de texto completo ao `csv.reader` sem remover quebras de linha internas aos campos; preservar aspas, separadores e conteúdo. Testar CSV com campo multilinha, delimitadores suportados e decimal com vírgula.

### 7. Média — tabela inválida aparece como apta para mapa

`RecognizedTable.map_ready` verifica os oito códigos, mas não exige que a tabela seja válida. A interface usa apenas `map_ready` para habilitar o rádio de mapa e também pode exibir `Requer ajuste | mapa` na conferência.

Reprodução mínima:

```text
Tabela com oito códigos e um valor "nao": valid=False, map_ready=True
```

Na revalidação, `valid=False` e `map_ready=True` ocorreram simultaneamente. O motor bloqueia a geração depois por `INVALID_TABLE_SELECTED`, portanto **não foi observado PDF de mapa com a tabela inválida**; o problema confirmado é a indicação contraditória na interface e no modelo.

Locais principais: `gerador_sc/models.py`, `RecognizedTable.map_ready`, e `gerador_sc/ui.py`, `_refresh_build_page()`.

Impacto: estado contraditório e mensagem confusa para a usuária.

**Correção esperada:** a indicação de mapa pronto deve exigir tabela válida e contrato geográfico satisfeito. Manter a razão da indisponibilidade visível na interface.

### 8. Média — cancelamento da exportação não é encaminhado ao motor

O worker recebe um evento de cancelamento, mas a lambda de exportação não o envia ao serviço; `ReportService.export()` também não recebe esse parâmetro. Logo, clicar em “Cancelar exportação” apenas marca o evento, sem interromper a cópia. Esta conclusão foi confirmada no código; não depende do tempo de execução do PDF.

Locais principais: `gerador_sc/ui.py`, `_export_pdf()`, e `gerador_sc/engine.py`, `ReportService.export()`.

Impacto: o botão “Cancelar exportação” não cumpre o que promete.

**Correção esperada:** definir e implementar cancelamento cooperativo de ponta a ponta antes da publicação do arquivo final, com limpeza do temporário. Depois que o arquivo final tiver sido substituído, informar sucesso em vez de afirmar que o cancelamento desfez a exportação. Testar com cópia controlada para tornar o momento do cancelamento determinístico.

### 9. Média — destino vazio causa exceção não tratada

Se a usuária apagar o destino na etapa de exportação, `Path("").with_suffix(".pdf")` gera:

```text
ValueError: PosixPath('.') has an empty name
```

Local principal: `gerador_sc/ui.py`, `_export_pdf()`. A exceção ocorre na thread da interface, antes de iniciar o worker.

Impacto: erro técnico em vez de mensagem acionável.

**Correção esperada:** validar texto vazio, apenas espaços, caminho que aponta para diretório e nome de arquivo inválido antes de chamar `with_suffix()` ou iniciar o worker. Exibir mensagem compreensível e manter a tela utilizável.

## Operações simultâneas: falhas observadas e risco pendente

A interface permite navegação enquanto um worker está ativo. `_run_worker()` simplesmente retorna quando já existe uma operação em andamento, sem informar isso claramente. Na revalidação, pedir uma segunda importação durante um worker alterou o texto para `Lendo segundo.csv...`, mas não chamou `service.inspect()` para esse arquivo. O fechamento da janela com worker marcado como ativo acionou cancelamento e apagou a prévia imediatamente.

O código também permite `_clear_artifact()` durante uma exportação, antes de o worker terminar de ler a prévia. **A falha de cópia resultante é um risco fundamentado, mas não foi reproduzida com uma cópia real nesta revalidação.** O chat de execução deve criar um teste controlado para esse intercalamento e corrigir o ciclo de vida do artefato conforme o resultado.

Os cenários mínimos de teste com worker controlado são:

1. iniciar uma prévia e voltar para outra etapa antes da conclusão;
2. iniciar uma exportação e voltar ou fechar a janela;
3. iniciar uma importação e selecionar outro arquivo antes da primeira terminar.

**Política esperada:** durante uma operação, impedir ou enfileirar navegação e novas ações de forma explícita; um resultado antigo não pode substituir o estado de um arquivo novo. O artefato só deve ser removido quando nenhum worker o utiliza. Ao fechar, cancelar e aguardar ou finalizar com segurança, sem publicar um PDF parcial e sem deixar temporários abandonados.

## Ordem de execução recomendada

1. Criar testes de regressão no limite `ReportService.inspect/remap/validate/preview/export`, antes das correções, reproduzindo os nove casos. Testes de interface devem cobrir apenas os estados que o motor não pode observar.
2. Preservar limites entre múltiplas tabelas durante qualquer remapeamento.
3. Validar relações entre coluna de identificação e colunas de anos.
4. Tornar a detecção de cabeçalhos mais conservadora e adicionar casos de valores que parecem anos.
5. Corrigir leitura CSV conforme o comportamento esperado para campos entre aspas e quebras de linha.
6. Fortalecer `validate_report()` contra anos duplicados/fora de ordem e IDs repetidos.
7. Fazer a metodologia refletir exatamente o período, unidade e indicador configurados.
8. Alinhar o estado visual do mapa com a validade real da tabela.
9. Definir uma política única para cancelamento, navegação e fechamento durante workers; corrigir destino vazio e estados de operação concorrente.
10. Repetir testes existentes e novos, conferir a planilha de referência, revisar visualmente PDFs representativos e só depois avaliar os builds de plataforma.

## Critérios para considerar o motor pronto para nova validação

- A planilha de referência continua produzindo 22 tabelas e os mesmos valores representativos.
- Uma aba com duas tabelas continua separada após inspeção e remapeamento de qualquer bloco.
- Coluna de ano usada como identificação produz diagnóstico de erro.
- Valores numéricos entre 1900 e 2100 em linhas de dados não criam cabeçalhos falsos.
- CSV com separadores aceitos, decimais locais, aspas e campos multilinha tem comportamento definido e testado.
- Anos fora de ordem, anos duplicados e tabelas repetidas são rejeitados pelo motor.
- A metodologia informa o período e a unidade efetivamente usados.
- Tabela inválida nunca aparece como pronta para mapa.
- Cancelamento de prévia e exportação tem efeito observável; não deixa PDF parcial nem diretório temporário abandonado.
- Destino vazio ou inválido produz mensagem compreensível.
- Navegação, nova importação e fechamento durante workers não perdem solicitações silenciosamente nem apagam artefatos ainda em uso.
- O arquivo de entrada permanece inalterado.

## Gates ainda pendentes

- Receber e testar a segunda planilha real.
- Executar instalação, abertura, importação, prévia, exportação e remoção em Windows.
- Executar os mesmos testes em macOS, na arquitetura real da futura usuária.
- Fazer teste acompanhado por uma pessoa sem terminal e sem Python instalado.
- Decidir, após o uso real, se o produto continuará estritamente local ou precisará de recursos conectados.

## Instrução para o chat de execução

Leia o `README.md` e este arquivo integralmente. Corrija os nove problemas confirmados e trate as falhas de operação simultânea com testes controlados. Trabalhe primeiro no motor de importação e validação; preserve as 22 tabelas e os valores do arquivo de referência. Acrescente testes que falhem com o comportamento atual e passem após a correção, execute a suíte completa e confira PDFs representativos. Ajuste a interface somente onde os problemas afetam a pessoa usuária. Não redesenhe o produto nem implemente serviços conectados, novas regiões ou personalizações fora do escopo. Informe separadamente o que foi corrigido, o que foi testado neste ambiente e os gates que continuam pendentes: segunda planilha real e instalação nos sistemas Windows/macOS. Não declare o importador estável para planilhas variadas antes do segundo caso real.
