# Validacao da primeira versao

## Revisao de confiabilidade - 16/09/2026

Foram corrigidos os nove problemas descritos em `README_REVISAO_PLANEJAMENTO.md` e os estados de operacao simultanea cobertos pelo plano:

- remapeamento preserva os limites entre tabelas da mesma aba;
- coluna de ano nao pode ser usada como identificacao;
- valores que parecem anos dentro dos dados nao criam cabecalhos falsos;
- anos fora de ordem, duplicados e tabelas repetidas sao rejeitados;
- a metodologia usa anos, unidade e indicador efetivos;
- CSV preserva campos entre aspas com quebras de linha;
- tabelas invalidas nao aparecem como prontas para mapa;
- cancelamento da exportacao e encaminhado ate a copia atomica;
- destino vazio ou pasta produz mensagem acionavel;
- nova importacao, navegacao e fechamento durante workers sao bloqueados ou adiados com limpeza segura.

## Caso executado

O caso de referencia `data/exemplos/BANCO DE DADOS CV - AMANDA E EMILENE.xlsx` foi importado sem alterar seus bytes. A deteccao encontrou 21 abas e 22 tabelas, incluindo os dois blocos da aba `POLIOMIELITE`. O fluxo completo foi executado com paineis, linhas e mapa, e o PDF de aceite foi revisado por renderizacao de paginas representativas.

Os valores vazios continuam como ausentes, zeros continuam como zero, valores acima de 100% continuam visiveis e as colunas de media e total nao entram automaticamente nas series anuais.

## Comandos de verificacao

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q gerador_sc
.venv/bin/pyside6-deploy --dry-run -c pysidedeploy.spec --name "Gerador de Relatorios SC"
```

Resultado no ambiente Linux: **21 testes passando**, dependencias sem problemas, compilacao concluida e dry-run de empacotamento concluido com os recursos de `geodados` incluidos.

Na planilha de referencia, a importacao continuou produzindo 21 abas, 22 tabelas validas, 17 tabelas aptas para mapa e 160 formulas. Os valores permaneceram equivalentes a `archive/relatorios_vacinacao/graficos/dados_graficos.json`, e o hash do arquivo de origem continuou `f579543f0136427c82ba0605875c70d04fb3a30d94c69f7c01591f38dfe855dc`.

Foram revisados visualmente paginas representativas de paineis, metodologia e mapa. A pre-visualizacao completa tem 23 paginas e a de mapa tem 2 paginas, ambas com texto extraivel em todas as paginas.

## Gates pendentes antes da producao

- A planilha real da colega esta em `data/exemplos/taxa estado SC.xlsx`. Ela revelou um segundo contrato, vertical e sem serie anual, que ainda nao e aceito pelo importador da aplicacao. O programa nao deve ser considerado abrangente antes de esse formato ser planejado, implementado e validado.
- Este ambiente Linux nao produziu nem abriu um instalador Windows ou macOS. Os scripts de build estao preparados, mas a validacao de instalacao, desinstalacao, assinatura e notarizacao precisa ocorrer nos sistemas correspondentes.
- Ainda falta um teste acompanhado com uma futura usuaria sem terminal ou Python instalados.
