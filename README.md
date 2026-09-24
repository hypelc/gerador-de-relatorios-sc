# Gerador de Relatórios SC — especificação da aplicação desktop

> Status: primeira versão local implementada e validada no Linux. Os instaladores de Windows e macOS ainda precisam ser produzidos e testados nos respectivos sistemas.

> **Versão web piloto:** o site agora está em desenvolvimento no mesmo projeto. O fluxo, os limites e a execução da versão web estão em [`docs/PLANO_SITE_MVP.md`](docs/PLANO_SITE_MVP.md) e [`docs/GUIA_WEB.md`](docs/GUIA_WEB.md). O restante deste README preserva a especificação da aplicação desktop.

## Como navegar no projeto

- `gerador_sc/`: aplicação desktop atual. Este é o código principal.
- `webapp/`: API Python da versão web piloto, que reutiliza o motor.
- `frontend/`: interface React/Vite da versão web piloto.
- `tests/`: testes do motor e da interface.
- `data/exemplos/`: planilhas reais usadas para entender e validar formatos.
- `geodados/`: recursos geográficos usados pelos mapas.
- `scripts/figuras/`: atalhos de reprodução de figuras específicas; o mapa regional usa o motor compartilhado.
- `scripts/legado/`: primeiros scripts experimentais, preservados como referência.
- `output/`: PDFs e imagens finais recentes, prontos para abrir ou enviar.
- `archive/`: relatórios antigos preservados, sem participação na execução atual.
- `docs/`: validações, revisão técnica e prompt usado na implementação.
- `packaging/`: preparação dos pacotes de Windows e macOS.

Uma explicação mais detalhada está em [`docs/ESTRUTURA_DO_PROJETO.md`](docs/ESTRUTURA_DO_PROJETO.md).

## Problem Statement

Pesquisadoras, professoras e alunas que trabalham com dados agregados de vacinação em Santa Catarina recebem planilhas com anos, indicadores e macrorregiões de saúde. Hoje, transformar essas planilhas em gráficos e mapas exige executar scripts Python e conhecer detalhes técnicos do formato dos arquivos.

O programa precisa permitir que uma pessoa sem conhecimento de programação importe uma planilha compatível, confira como os dados foram interpretados, escolha um modelo de relatório, visualize o resultado e salve um PDF. O relatório deve explicar sua origem e seu método de geração de forma suficiente para uso acadêmico.

O programa também precisa impedir resultados enganosos. Dados ausentes não podem virar zero, abas incompatíveis não podem ser ignoradas silenciosamente e o aplicativo não deve inferir significados que a planilha não fornece.

## Solution

Construir uma aplicação desktop local, provisoriamente chamada **Gerador de Relatórios SC**, com interface em português e funcionamento sem servidor. A aplicação será desenvolvida em Python com PySide6, reutilizando e reorganizando o motor já validado de gráficos e mapas.

O fluxo principal será:

1. Selecionar ou arrastar uma planilha `.xlsx` ou `.csv`.
2. Inspecionar o arquivo e mostrar as abas, tabelas, anos, séries e problemas reconhecidos.
3. Permitir que a pessoa confirme a interpretação ou faça ajustes limitados de mapeamento.
4. Selecionar dados, período e um modelo pronto de visualização.
5. Informar título, autores e fonte.
6. Gerar uma prévia do relatório.
7. Salvar um único PDF no local escolhido.

O processamento e os arquivos permanecerão no computador da pessoa. A primeira versão terá instaladores separados para Windows e macOS, produzidos a partir da mesma base de código.

## Objetivos do produto

- Reduzir o trabalho manual para gerar relatórios visuais a partir de planilhas semelhantes às já avaliadas.
- Oferecer modelos prontos que produzam resultados claros sem exigir conhecimento de design ou programação.
- Explicar problemas da planilha em linguagem simples e indicar como corrigi-los.
- Preservar os dados originais e a distinção entre zero, valor ausente e valor inválido.
- Registrar no PDF o título, autores, data de geração, origem dos dados, período, unidade e método utilizado.
- Manter o motor de análise separado da interface para permitir uma futura versão web sem reescrever as regras principais.

## Público inicial

- Professoras e pesquisadoras que trabalham com cobertura vacinal e indicadores agregados.
- Colegas de trabalho e alunas que precisam gerar ou consultar os relatórios.
- Pessoas que usam Windows ou macOS e não devem precisar instalar Python ou bibliotecas manualmente.

## Escopo dos dados

### Formatos aceitos

- `.xlsx`, com uma ou várias abas.
- `.csv`, representando uma tabela por arquivo.

### Estrutura esperada

A primeira versão atenderá tabelas horizontais semelhantes ao modelo já validado:

- Uma coluna identifica a macrorregião, região, indicador ou série.
- Uma linha de cabeçalho contém anos consecutivos ou ordenados.
- As células de dados contêm números ou estão vazias.
- Colunas de média e total podem existir, mas não entram automaticamente na série temporal.
- Uma planilha pode conter mais de uma tabela reconhecível.
- Abas auxiliares podem existir e devem ser marcadas como não reconhecidas, sem impedir o uso das tabelas válidas.

O importador deve procurar sequências de pelo menos três anos válidos e propor a coluna de identificação mais próxima. A pessoa poderá ajustar a aba, linha de cabeçalho, coluna de identificação, unidade e tipo de indicador quando a detecção automática não for suficiente.

O aplicativo não promete interpretar qualquer planilha. Quando o contrato não for atendido, deve explicar qual requisito faltou e manter o arquivo original intacto.

### Geografia inicial

- Santa Catarina.
- Oito macrorregiões de saúde identificadas pelos códigos usados na base do Ministério da Saúde.
- Os mapas somente ficam disponíveis quando todas as regiões necessárias ao modelo estão presentes e sem códigos duplicados.
- Os valores do mapa representam a macrorregião. O aplicativo não deve apresentar esses valores como dados municipais.

## Modelos de relatório

### Evolução por macrorregião

- Modelo padrão.
- Um pequeno gráfico de linhas para cada macrorregião.
- Mesma escala entre os painéis de uma figura.
- Ano no eixo horizontal e unidade explícita no eixo vertical.
- Valor do último ano rotulado quando estiver disponível.
- Lacunas permanecem como interrupções na linha.

### Comparação em linhas

- Todas as regiões ou séries selecionadas aparecem no mesmo gráfico.
- Cores e marcadores consistentes.
- Legenda legível e colocada fora da área dos dados quando necessário.
- Adequado para comparação geral; a interface deve descrevê-lo dessa forma.

### Mapa de Santa Catarina

- Mapa coroplético por macrorregião de saúde.
- Um ano selecionado ou uma sequência de mapas anuais.
- Faixas de cobertura visíveis na legenda.
- Valores ausentes recebem padrão visual próprio e nunca a cor de zero.
- Disponível somente para dados que satisfaçam o contrato geográfico.

### Personalização disponível na primeira versão

- Seleção de tabelas, indicadores, anos e modelo.
- Título do relatório.
- Um ou mais autores em texto livre.
- Fonte dos dados em texto livre.
- Unidade e nome do indicador, com valores sugeridos pelo importador.
- Uma pequena seleção de paletas prontas e acessíveis.

Não haverá editor livre de layout. As opções avançadas ficarão recolhidas para preservar o fluxo simples.

## Conteúdo do PDF

Cada PDF exportado deve conter:

- Título informado pela pessoa.
- Autores informados pela pessoa.
- Data e hora de geração.
- Nome do arquivo de origem.
- Fonte dos dados, quando informada.
- Indicador, unidade, território e período.
- Gráficos ou mapas selecionados.
- Nota sobre valores ausentes e qualquer exclusão confirmada pela pessoa.
- Seção breve de metodologia informando o nome e a versão do aplicativo, os campos utilizados, o tratamento de células vazias e, em mapas, as fontes geográficas.

Uma formulação base da metodologia é:

> Relatório elaborado pelo Gerador de Relatórios SC a partir das colunas de identificação, anos e valores confirmadas durante a importação. Os valores foram mantidos conforme o arquivo fornecido; células vazias não foram convertidas em zero. Os gráficos foram produzidos em Python com Matplotlib. Para mapas de Santa Catarina, foram utilizados limites municipais do IBGE e a composição das macrorregiões publicada pelo Ministério da Saúde.

O texto deve ser adaptado automaticamente ao conteúdo real. Não deve mencionar mapas quando nenhum mapa foi gerado.

## User Stories

1. Como pesquisadora, quero selecionar uma planilha no computador, para gerar um relatório sem executar comandos.
2. Como usuária, quero arrastar um arquivo para a janela, para iniciar a importação rapidamente.
3. Como usuária, quero saber se o arquivo é `.xlsx` ou `.csv` compatível antes da análise, para entender rejeições imediatas.
4. Como pesquisadora, quero visualizar as abas e tabelas encontradas, para confirmar o que será usado.
5. Como pesquisadora, quero ver os anos, séries, regiões e unidades reconhecidos, para validar a interpretação do programa.
6. Como usuária, quero que abas auxiliares sejam sinalizadas, para não confundi-las com dados descartados silenciosamente.
7. Como usuária, quero receber uma mensagem que indique a aba, linha, coluna e natureza de um problema quando possível, para conseguir corrigi-lo.
8. Como pesquisadora, quero ajustar a linha de cabeçalho e a coluna de identificação, para lidar com pequenas diferenças entre planilhas semelhantes.
9. Como pesquisadora, quero selecionar apenas as tabelas válidas, para continuar quando uma parte do arquivo não for necessária.
10. Como pesquisadora, quero ver claramente as tabelas excluídas, para saber exatamente o que não aparecerá no relatório.
11. Como pesquisadora, quero escolher anos e indicadores, para gerar somente o recorte relevante.
12. Como pesquisadora, quero escolher o modelo de evolução por painéis, para acompanhar cada macrorregião ao longo do tempo.
13. Como pesquisadora, quero escolher o modelo de linhas juntas, para comparar as regiões no mesmo gráfico.
14. Como pesquisadora, quero gerar um mapa de SC, para visualizar a distribuição espacial por macrorregião.
15. Como usuária, quero que a opção de mapa seja desabilitada com uma explicação quando faltarem códigos geográficos, para não produzir um mapa incorreto.
16. Como pesquisadora, quero visualizar uma prévia antes de salvar, para conferir títulos, dados e legibilidade.
17. Como usuária, quero voltar às etapas anteriores sem perder as escolhas válidas, para corrigir a configuração.
18. Como usuária, quero ver o progresso durante a geração, para saber que o aplicativo continua funcionando.
19. Como usuária, quero cancelar uma geração longa antes da exportação, para recuperar o controle da aplicação.
20. Como pesquisadora, quero preencher o título e os autores, para identificar o trabalho no PDF.
21. Como pesquisadora, quero informar a fonte dos dados, para manter a rastreabilidade acadêmica.
22. Como pesquisadora, quero escolher entre poucas paletas legíveis, para personalizar o relatório sem prejudicar a interpretação.
23. Como pesquisadora, quero que anos e unidades apareçam nos gráficos, para que o PDF seja compreensível fora do programa.
24. Como pesquisadora, quero que valores vazios permaneçam como lacunas, para não criar resultados inexistentes.
25. Como pesquisadora, quero que coberturas acima de 100% sejam preservadas, para não alterar a base fornecida.
26. Como pesquisadora, quero que o relatório informe exclusões e dados ausentes, para explicar suas limitações.
27. Como pesquisadora, quero uma descrição de como o relatório foi produzido, para citar o programa e o processo na pesquisa.
28. Como usuária, quero escolher onde salvar o PDF, para organizá-lo junto ao trabalho correspondente.
29. Como usuária, quero ser avisada antes de substituir um arquivo existente, para não perder um relatório anterior.
30. Como usuária, quero abrir a pasta ou o PDF depois da exportação, para acessar o resultado imediatamente.
31. Como usuária, quero que a planilha permaneça inalterada, para preservar a fonte original.
32. Como usuária, quero que arquivos temporários sejam removidos depois da operação, para não acumular dados desnecessários.
33. Como usuária de Windows, quero instalar e abrir o aplicativo pelo menu do sistema, para usá-lo como um programa comum.
34. Como usuária de macOS, quero instalar e abrir o aplicativo pela pasta Aplicativos, para usá-lo como um programa comum.
35. Como usuária, quero que o programa funcione sem internet para gerar relatórios, para não depender de um serviço externo.
36. Como desenvolvedor, quero que a lógica de importação e geração não dependa da interface, para reutilizá-la em uma futura aplicação web.
37. Como desenvolvedor, quero obter erros estruturados do motor, para traduzi-los em mensagens claras na interface.
38. Como desenvolvedor, quero validar a aplicação com outra planilha real antes da versão estável, para verificar variações que o primeiro arquivo não revelou.
39. Como desenvolvedor, quero gerar pacotes separados para Windows e macOS a partir do mesmo código, para manter uma única aplicação.
40. Como desenvolvedor, quero identificar a versão do programa nos relatórios e na tela Sobre, para dar suporte a resultados antigos.

## Experiência da interface

A interface usará Qt Widgets por meio do PySide6 e será organizada como um assistente em etapas, usando uma janela única:

1. **Importar:** área de arrastar e soltar, botão para procurar arquivo e breve explicação dos formatos aceitos.
2. **Conferir dados:** resumo das tabelas reconhecidas, alertas, seleção de tabelas e acesso ao mapeamento limitado.
3. **Montar relatório:** cartões dos modelos com miniaturas, campos de título, autores e fonte, seletores de período e opções avançadas recolhidas.
4. **Prévia:** páginas ou imagens do resultado, resumo das escolhas e botão para voltar.
5. **Exportar:** escolha do destino, progresso e confirmação com ações para abrir o PDF ou a pasta.

Diretrizes visuais:

- Aparência limpa, clara e profissional, sem excesso de painéis ou termos técnicos.
- Hierarquia baseada em tipografia, espaço e poucos tons de azul, verde e neutros.
- Estados de foco, contraste e tamanhos adequados para uso com teclado e telas de diferentes escalas.
- Botão principal único por etapa.
- Mensagens de erro próximas ao campo ou item afetado.
- Termos de análise explicados em frases curtas quando aparecem pela primeira vez.
- A janela deve continuar responsiva durante leitura, prévia e exportação.

## Implementation Decisions

- Usar Python como linguagem única do motor e da aplicação desktop.
- Usar PySide6 com Qt Widgets para a interface multiplataforma.
- Manter o motor independente de PySide6. Ele receberá arquivos e configurações por interfaces Python e devolverá modelos de dados, diagnósticos e artefatos.
- Dividir o motor em importação, normalização, validação, catálogo de modelos, renderização e exportação.
- Representar cada tabela reconhecida com identificador estável, origem, cabeçalho, coluna de rótulo, anos, séries, unidade, tipo de indicador e diagnósticos.
- Representar diagnósticos com severidade, código, mensagem para a pessoa, localização e ação sugerida.
- Aceitar `.xlsx` e `.csv` por importadores separados, convergindo para o mesmo modelo normalizado.
- Ler Excel com atenção a fórmulas: informar quando o arquivo contém fórmulas sem valores calculados disponíveis. O aplicativo não atuará como mecanismo de recálculo do Excel.
- Tratar `None` e célula vazia como dado ausente. Zero numérico permanece zero.
- Rejeitar valores não numéricos dentro da região de dados confirmada, em vez de convertê-los silenciosamente.
- Detectar tabelas válidas sem exigir que toda aba seja válida.
- Exigir confirmação explícita para excluir uma tabela problemática da geração.
- Reutilizar as regras visuais validadas dos geradores atuais, extraindo-as para renderizadores configuráveis.
- Preservar a malha e as fontes geográficas já validadas, distribuindo esses recursos com o aplicativo.
- Fazer toda geração pesada fora da thread principal da interface e comunicar progresso, sucesso, cancelamento e falha.
- Gerar prévias em diretório temporário exclusivo por sessão.
- Exportar primeiro para arquivo temporário e mover o PDF concluído para o destino, evitando PDFs parciais.
- Usar diretórios padrão do sistema operacional para preferências e cache. Não copiar permanentemente a planilha importada.
- Salvar apenas preferências não sensíveis, como pasta de exportação recente e paleta escolhida.
- Centralizar nome, versão e identificação do aplicativo para uso na interface, metodologia e pacotes.
- Empacotar separadamente para Windows e macOS. O mesmo instalador não será compartilhado entre os sistemas.
- Usar `pyside6-deploy` como primeira opção para produzir os pacotes da aplicação. Se incompatibilidades comprovadas com Matplotlib, Shapely ou PyProj impedirem a entrega, usar PyInstaller e documentar a razão.
- Criar um instalador Windows a partir do pacote construído no Windows e uma imagem de instalação macOS a partir do pacote construído no macOS.
- Manter scripts de build reproduzíveis e versões de dependências fixadas para cada lançamento.
- Não afirmar compatibilidade de um pacote que não tenha sido aberto e testado no sistema correspondente.
- Preparar a arquitetura para verificação futura de atualizações, mantendo a versão acessível e separando essa função do motor. O atualizador não será implementado na primeira versão.
- Manter o projeto apto a ganhar uma interface web futura por meio do mesmo motor, sem incluir servidor nesta entrega.

## Contrato principal do motor

O limite principal entre interface e motor será um serviço de aplicação que execute o fluxo completo:

1. Inspeciona o arquivo e devolve tabelas candidatas e diagnósticos.
2. Aceita as confirmações e ajustes de mapeamento.
3. Valida uma solicitação de relatório.
4. Gera a prévia.
5. Exporta o PDF final.

A interface não deve ler células, calcular escalas ou desenhar gráficos diretamente. Ela apenas apresenta o estado e envia escolhas ao motor.

## Testing Decisions

- O principal ponto de teste será o fluxo do motor da importação ao PDF. Esse teste usa um arquivo real controlado, uma configuração de relatório e verifica diagnósticos, dados normalizados, páginas esperadas e valores representativos no resultado.
- Testes devem observar comportamento externo. Não devem afirmar quais funções internas foram chamadas nem duplicar cálculos do código.
- O arquivo atual será uma referência de regressão: deve continuar produzindo 22 tabelas reconhecidas a partir de 21 abas, preservar lacunas e permitir os modelos já validados.
- A planilha da colega será adicionada como segundo caso de aceitação quando recebida. A importação não será considerada estável antes desse teste.
- Criar casos pequenos para CSV, múltiplas tabelas, aba auxiliar, anos como números, valor zero, célula vazia, valor inválido, região duplicada, região ausente e fórmula sem valor calculado.
- Validar que a planilha de entrada permanece byte a byte inalterada após importação e exportação.
- Validar que uma falha não deixa PDF parcial no destino.
- Renderizar páginas representativas do PDF para inspeção visual automatizada básica e revisão humana, verificando conteúdo vazio, texto cortado, legendas ilegíveis e mapas incompletos.
- Testar na interface somente os fluxos essenciais: selecionar arquivo, avançar com dados válidos, exibir diagnósticos, voltar sem perder escolhas, gerar prévia e exportar.
- Fazer teste manual de instalação, abertura, importação, prévia, exportação e desinstalação em Windows.
- Fazer teste manual de instalação, abertura, importação, prévia, exportação e remoção em macOS.
- Testar caminhos com espaços, caracteres acentuados, arquivos somente leitura e pastas sem permissão de escrita.
- O critério principal de aceite é um fluxo completo executado por uma pessoa sem terminal nem Python instalado.

## Plano de implementação

### Etapa 1 — Base reproduzível

- Organizar o projeto como pacote Python instalável.
- Fixar versão suportada do Python e dependências.
- Separar código, recursos geográficos, testes e artefatos gerados.
- Preservar os scripts atuais como referência até que o novo motor reproduza seus resultados.

### Etapa 2 — Motor de importação e validação

- Criar modelos normalizados e diagnósticos estruturados.
- Implementar importadores `.xlsx` e `.csv`.
- Detectar múltiplas tabelas e ignorar apenas regiões vazias fora das tabelas.
- Implementar ajustes limitados de mapeamento.
- Cobrir o contrato de entrada com testes.

### Etapa 3 — Motor de relatórios

- Migrar gráficos de painéis, linhas conjuntas e mapas para renderizadores reutilizáveis.
- Acrescentar metadados, metodologia e PDF consolidado.
- Implementar paletas prontas e prévia.
- Comparar os resultados com os relatórios já validados.

### Etapa 4 — Interface desktop

- Criar o assistente em cinco etapas.
- Implementar arrastar e soltar, seleção de arquivo e telas de conferência.
- Conectar os modelos prontos, metadados, prévia e exportação.
- Executar tarefas pesadas em worker e manter a janela responsiva.
- Adicionar tela Sobre com versão e fontes do projeto.

### Etapa 5 — Robustez e experiência

- Traduzir exceções em mensagens acionáveis.
- Implementar confirmação de exclusões e substituição de arquivos.
- Tratar cancelamento, diretórios temporários e limpeza.
- Revisar acessibilidade, escala de tela, textos e estados vazios.

### Etapa 6 — Distribuição

- Produzir e testar o pacote Windows em ambiente Windows.
- Gerar o instalador Windows e validar instalação e desinstalação.
- Produzir e testar o pacote macOS em ambiente macOS.
- Gerar a imagem de instalação macOS e avaliar assinatura e notarização antes de distribuição externa.
- Reunir as duas versões em uma pasta de distribuição, com nomes e versões inequívocos.

### Etapa 7 — Validação com uso real

- Executar o fluxo com a planilha atual.
- Executar o fluxo com a planilha da colega quando ela for recebida.
- Fazer um teste acompanhado com pelo menos uma futura usuária.
- Corrigir problemas observados antes de marcar a versão como estável.

## Critérios de conclusão da primeira versão

- Abre por ícone em Windows e macOS sem exigir instalação manual de Python.
- Importa `.xlsx` e `.csv` compatíveis.
- Mostra dados reconhecidos e problemas antes da geração.
- Permite selecionar dados, modelo e metadados.
- Produz prévia legível e PDF consolidado.
- Preserva valores, lacunas e arquivo de origem.
- Produz gráficos de painéis, linhas juntas e mapas quando aplicáveis.
- Inclui metodologia e identificação do relatório.
- Não congela durante tarefas demoradas.
- Não substitui arquivos sem confirmação.
- Passa pelos testes do motor e pelos testes manuais nos dois sistemas.
- Foi validado com a planilha atual e com o segundo exemplo real.

## Out of Scope

- Contas de usuário, autenticação e permissões.
- Banco de dados remoto, Supabase ou outro backend.
- Histórico compartilhado de relatórios.
- Colaboração entre professoras e alunas dentro do programa.
- Processamento em servidor.
- Sincronização entre computadores.
- Aplicação web.
- Atualização automática na primeira versão.
- Suporte inicial a Linux como pacote distribuído.
- Outros estados, municípios ou divisões territoriais.
- Dados individuais de pacientes ou pessoas.
- Editor livre de gráficos e páginas.
- Inferências causais, recomendações clínicas ou explicações automáticas sobre mudanças nos indicadores.
- Correção de valores da planilha dentro do aplicativo.
- Leitura de `.xls`, Google Sheets ou formatos fora de `.xlsx` e `.csv`.

## Further Notes

- O nome **Gerador de Relatórios SC** é provisório e deve ficar centralizado para ser trocado sem alterar regras ou relatórios manualmente.
- A aplicação será local e funcionará sem internet. Uma futura verificação de atualização poderá usar internet sem enviar planilhas.
- O código atual provou a geração dos gráficos e mapas, mas contém regras acopladas à planilha inicial. A implementação deve extrair conhecimento útil e evitar apenas colocar uma janela sobre os scripts existentes.
- A nova planilha solicitada à colega é parte do aceite do importador. Ela deve ser analisada antes de ampliar o contrato de entrada.
- O alvo inicial presumido é Windows 10/11 de 64 bits. Antes do empacotamento final, confirmar as versões reais usadas pelas futuras usuárias.
- Antes do pacote macOS, confirmar a versão do sistema e se o computador usa Apple Silicon ou processador Intel. Produzir o pacote para a arquitetura confirmada; oferecer uma segunda arquitetura ou pacote universal somente depois de validar todas as dependências nesse formato.
- Pacotes internos de teste podem ser distribuídos sem assinatura, aceitando os avisos do sistema. Uma distribuição simples para pessoas não técnicas exige avaliar certificado de assinatura no Windows e conta Apple Developer para assinatura e notarização no macOS.
- A pasta de entrega deve conter subpastas `Windows` e `macOS`, cada uma com o instalador, versão, instrução curta e arquivo de integridade correspondente.
- Este diretório ainda não é um repositório Git e não possui issue tracker configurado. A especificação não foi publicada como issue nem recebeu o rótulo `ready-for-agent`.
