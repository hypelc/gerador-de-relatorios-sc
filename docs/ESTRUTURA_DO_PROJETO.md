# Estrutura do projeto

Esta pasta contém a aplicação desktop, o piloto web e o histórico que levou até eles. A organização abaixo evita confundir código atual, exemplos, relatórios finais e experimentos antigos.

## O que é o programa atual

O motor fica em `gerador_sc/`. A interface desktop chama `ReportService`, definido em `gerador_sc/engine.py`. O site usa esse serviço para séries anuais e `gerador_sc/regional.py` para as 17 Regionais. A API fica em `webapp/` e a interface web em `frontend/`; nenhuma das interfaces interpreta células nem desenha relatórios por conta própria.

```text
gerador_sc/
├── importers.py   leitura e interpretação de XLSX/CSV
├── models.py      estruturas dos dados e diagnósticos
├── engine.py      fluxo principal usado pela interface e pelos testes
├── rendering.py   gráficos, mapas, metodologia e PDF
├── geography.py   acesso aos recursos geográficos
├── regional.py    leitura, validação e mapa das 17 Regionais
└── ui.py          janela desktop em PySide6
```

## Pastas principais

```text
Data Analyse/
├── README.md                 especificação e entrada principal do projeto
├── gerador_sc/               aplicação atual
├── webapp/                   API do piloto web
├── frontend/                 interface React/Vite do piloto web
├── tests/                    testes automatizados
├── data/exemplos/            planilhas reais de validação
├── geodados/                 malhas e relações territoriais
├── scripts/
│   ├── figuras/              atalhos de reprodução de figuras específicas
│   └── legado/               protótipos anteriores à aplicação
├── output/
│   ├── figuras/              imagens finais recentes
│   └── pdf/                  PDFs finais recentes
├── archive/                  resultados antigos preservados
├── docs/                     revisão, validação e materiais de execução
└── packaging/                comandos de empacotamento por sistema
```

## As duas planilhas reais

`data/exemplos/BANCO DE DADOS CV - AMANDA E EMILENE.xlsx` contém tabelas anuais horizontais. Ela é o caso que a aplicação atual reconhece e usa nos testes: anos nas colunas e séries nas linhas.

`data/exemplos/taxa estado SC.xlsx` contém uma tabela vertical simples: uma Regional de Saúde e uma taxa por linha, sem ano e sem unidade. A figura correspondente é produzida por `gerador_sc/regional.py`, usado pelo site e pelo atalho `scripts/figuras/gerar_figura_taxa_regionais.py`. Esse formato ainda não aparece na interface desktop.

Essa diferença é o motivo para não chamar o importador de “genérico”. O programa deve reconhecer contratos explícitos e mostrar qual deles encontrou. Ele não deve tentar adivinhar qualquer planilha.

## O que pode ser apagado e o que deve ser preservado

- `.venv/`, `__pycache__/`, `.pytest_cache/`, `tmp/`, `build/` e `dist/` são regeneráveis.
- `output/` contém entregas recentes. Só apague depois de confirmar que foram enviadas ou copiadas.
- `archive/` contém o histórico visual do primeiro trabalho. Não é necessário para executar a aplicação.
- `data/exemplos/` e `geodados/` são dados de validação e recursos do projeto; devem ser preservados.
- `gerador_sc/`, `tests/`, `pyproject.toml`, `pysidedeploy.spec` e `packaging/` formam a aplicação e sua preparação de distribuição.

## Regra para novas planilhas

Uma planilha nova entra primeiro em `data/exemplos/`. Antes de alterar o programa, registre:

1. o que cada linha e coluna representa;
2. quais campos são obrigatórios;
3. se existe período, unidade, fonte e território;
4. qual visualização faz sentido;
5. quais informações o programa não pode inferir.

Se ela corresponde a um contrato existente, vira mais um teste. Se exige outra interpretação, recebe um novo importador ou modelo dentro do mesmo motor, com confirmação visível para a pessoa usuária.
