# Gerador de Relatórios SC — plano da primeira versão web

**Planejamento iniciado em 23/09/2026; implementação local iniciada em 24/09/2026.** O objetivo é mostrar um MVP à tia e às colegas e evoluí-lo durante a semana. A arquitetura foi ajustada por escolha do proprietário: interface Next.js na Vercel e API FastAPI no Render. O repositório já existe no GitHub; a publicação da URL ainda depende de enviar este commit e conectar os dois serviços. O `README.md` continua descrevendo a aplicação desktop existente; o site não promete interpretar qualquer planilha.

## Resultado a entregar

Um site em português, com acesso restrito para a tia e as colegas, no qual a pessoa:

1. entra com uma senha compartilhada;
2. envia uma planilha `.xlsx` ou `.csv`;
3. vê quais dados e qual formato foram reconhecidos e confirma o modelo sugerido;
4. informa título, autores, fonte e, quando existir nos dados, o período;
5. vê a prévia e baixa o PDF. Para a figura das Regionais, também pode baixar PNG.

O arquivo original permanece intacto. O site informa o motivo de rejeição de um arquivo incompatível, incluindo aba/linha/coluna quando disponíveis. Os relatórios registram origem, data, autores, indicador, unidade e método **somente com informações conhecidas ou confirmadas**; não inventam ano nem denominador de uma taxa.

## Dois formatos de entrada, dois caminhos de geração

| Formato dos dados | Exemplo real | O que gerar primeiro |
| --- | --- | --- |
| Séries anuais horizontais por 8 macrorregiões | `data/exemplos/BANCO DE DADOS CV - AMANDA E EMILENE.xlsx` | Evolução em painéis ou linhas; mapa de macrorregiões quando a tabela atender ao contrato geográfico. |
| Uma taxa por 17 Regionais de Saúde, em colunas verticais | `data/exemplos/taxa estado SC.xlsx` | Figura de distribuição no mapa de SC, com escala, legenda e tabela de valores; PDF e PNG. |

**Formato da planilha** é diferente de **modelo visual**. Primeiro identificamos e validamos as colunas e regiões; depois oferecemos apenas os gráficos compatíveis. Os dois formatos agora passam pelo motor em `gerador_sc/`: as séries anuais pelo módulo existente e as 17 Regionais por `gerador_sc/regional.py`. O script em `scripts/figuras/` usa esse mesmo módulo para reproduzir a figura original.

Para arquivos parecidos, mas não idênticos, o site mostra o que encontrou e permite confirmar opções já suportadas. Arquivos fora desses contratos recebem um diagnóstico; não são transformados por suposição.

## Arquitetura enxuta

- **Dois serviços no mesmo repositório:** interface Next.js publicada na Vercel, com raiz em `frontend/`, e API FastAPI publicada no Render por Docker. O Next.js encaminha `/api/*` ao Render; para o navegador, login, upload e download continuam na mesma origem. A URL do Render é configurada em `API_BACKEND_URL` no projeto Vercel.
- **Motor Python reaproveitado:** importação, validação, gráficos, mapas e PDF continuam no Python. A interface Qt fica fora da execução web. Dependências web e desktop devem ficar separadas.
- **Sem banco de dados e sem contas individuais:** senha compartilhada guardada em variável de ambiente do Render. Sessão em cookie seguro encaminhada pela Vercel, sem mostrar a senha no código do navegador. Não haverá histórico nem registro confiável de quem gerou cada relatório; o campo "autores" é informado pela pessoa.
- **Sem guardar planilhas ou relatórios:** `inspecionar` recebe o arquivo, devolve o diagnóstico e descarta a cópia temporária. O navegador mantém o arquivo selecionado e o envia novamente em `gerar`, junto com as escolhas. O servidor valida tudo de novo, gera o PDF/PNG, devolve o arquivo e limpa os temporários. Prévia e download usam o mesmo resultado já gerado no navegador.
- **Proteção operacional mínima:** limite de tamanho e tipo de arquivo, limite de requisições, processamento serial dos gráficos, isolamento e limpeza de diretórios temporários, mensagens de erro sem expor dados da planilha ou segredos. O servidor não executa macros nem fórmulas do Excel. O tempo máximo de requisição deverá ser configurado na hospedagem antes de publicar.

O site precisa de hospedagem para executar Python, mesmo sem banco. O upload sai do computador da usuária e é processado nesse servidor; isso precisa ficar claro na tela de importação. Não cabe prometer execução totalmente local ou gratuita.

## Onde o Jev entraria

Jev é um classificador de decisões estruturadas: pode escolher uma opção entre `serie_anual_macro`, `taxa_regional` e `desconhecido`. Ele **não** substitui leitura de Excel, validação dos números, correspondência geográfica nem renderização do relatório. Escolher uma opção válida também não garante que a opção esteja correta. Referência: [documentação oficial da TypeSafe](https://docs.typesafe.ai/introduction).

Como ainda não há chave de API e precisamos primeiro provar os dois formatos conhecidos, Jev fica **fora do caminho obrigatório da primeira versão**. A detecção inicial usa regras verificáveis: presença de anos, disposição das colunas, rótulos e quantidade/códigos de regiões, sempre com confirmação da pessoa. O código deve deixar um ponto de integração para testar Jev depois, somente se novos formatos criarem ambiguidade real. Nesse teste, enviar apenas metadados estruturais mínimos e revisar privacidade antes de usar dados de pesquisa; baixa confiança, erro de API ou resposta `desconhecido` levam à escolha manual. A chave fica exclusivamente no servidor.

## Sequência de execução para a entrega

1. **Fechar o motor para os dois exemplos reais:** converter o gerador das 17 Regionais em importador/validador/renderizador reutilizável; preservar as regras dos relatórios anuais já verificados.
2. **Expor duas operações web:** inspeção e geração. Todas as escolhas recebidas do navegador são validadas no servidor; diagnóstico legível volta para a interface.
3. **Montar a interface curta:** login, upload, confirmação dos dados, escolhas compatíveis, prévia e download. Campos avançados ficam recolhidos. Estados de carregamento/erro precisam estar claros.
4. **Testar ponta a ponta:** os dois arquivos reais, PDF/PNG abrindo, prévia igual ao download, valores e regiões corretos, arquivo inválido, acesso sem senha e limpeza de temporários. Revisar visualmente os PDFs; não basta contar testes automatizados.
5. **Publicar e testar a URL final:** o proprietário envia o commit ao repositório GitHub existente; Render e Vercel conectam-se à branch `main` para deploy automático. Configurar senha no Render e `API_BACKEND_URL` na Vercel, fazer upload e download pela URL final em uma sessão comum, conferir uso em tela estreita e registrar a versão entregue.

## Critério de aceite e corte de escopo

Entrega utilizável significa que uma colega entra pela URL, consegue importar **cada um dos dois formatos suportados**, confere o reconhecimento, gera e baixa um relatório fiel aos dados, sem Python instalado. O site deve explicar as limitações e oferecer fonte/metodologia no PDF. Se o teste do formato das 17 Regionais ou do acesso restrito falhar, não anunciar a entrega como completa.

Ficam para depois: Jev ativo, planilhas arbitrárias, contas individuais, histórico de alterações, banco de dados, editor livre de gráficos, uso simultâneo em grande escala e atualização dos instaladores desktop. Histórico com autor real exigirá autenticação individual e armazenamento persistente; só então vale escolher um banco.

## Versionamento e evolução

- **Versionamento:** o repositório Git local está conectado a `https://github.com/hypelc/gerador-de-relatorios-sc.git`. Excluir de commits planilhas reais, relatórios, senhas, arquivos temporários e ambientes virtuais; usar exemplos anonimizados quando possível. O proprietário optou por enviar os próximos commits ao GitHub por conta própria.
- **`v0.1.0` — piloto web:** fluxo completo com os dois formatos definidos acima, acesso restrito, prévia e download implementados localmente. Falta validar a URL publicada. A versão aparece no site e na metodologia do PDF.
- **`v0.1.x` — correções do piloto:** ajustar erros observados sem mudar o significado dos dados nem quebrar planilhas já aceitas. Cada correção tem um caso reproduzível e verificação do PDF.
- **`v0.2.0` — ampliação por demanda real:** novo formato de planilha ou novo modelo visual somente depois de receber um exemplo e definir seu contrato. Testar Jev com exemplos conhecidos e desconhecidos antes de ativá-lo para usuárias.
- **Versão posterior, se necessária:** contas individuais, histórico e banco quando as colegas realmente precisarem consultar relatórios de outras pessoas ou saber quem os gerou.

Após o piloto, registrar para cada pedido novo: planilha de exemplo ou estrutura anonimizada, indicador, unidade, geografia, período, figura esperada e uso acadêmico pretendido. Isso evita que a palavra "planilha" esconda contratos diferentes. A próxima versão deve responder a pedidos repetidos, não a casos hipotéticos.

Antes de escolher a hospedagem, medir tempo e memória de geração dos dois PDFs com os arquivos reais; depois escolher um serviço Python que suporte o maior relatório com margem. Registrar o procedimento de publicação e retorno à versão anterior. A URL publicada só é considerada validada após upload e download feitos nela, fora do ambiente de desenvolvimento.
