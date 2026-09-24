# Rodar e publicar o Gerador de Relatórios SC na web

Esta é a versão piloto `0.1.0`. Ela reconhece séries anuais por macrorregião, tabelas regionais de período único e o contrato específico de 17 Regionais de Saúde de SC. Os cinco exemplos fictícios em `tests/fixtures/` cobrem anos em ordem normal, descendente ou misturada, séries transpostas, banco consolidado em linhas e múltiplos blocos na mesma aba. A identificação é feita por regras de formato; o Jev ainda não participa. A planilha é enviada ao servidor na inspeção e novamente na geração, mas não é salva permanentemente. Não há login, banco de dados nem histórico de relatórios. Qualquer pessoa com a URL pode usar o gerador.

A interface Next.js fica na Vercel e a API FastAPI no Render. O navegador usa somente a URL da Vercel; o Next.js encaminha `/api/*` ao Render. Assim, o envio das planilhas e o download dos PDFs usam a mesma origem para a usuária.

## Rodar localmente

Pré-requisitos: Python 3.14, Node.js 22 e npm.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm ci --prefix frontend
```

No primeiro terminal, inicie a API:

```bash
.venv/bin/uvicorn webapp.api:app --host 127.0.0.1 --port 8000
```

No segundo terminal, na raiz do projeto, inicie a interface:

```bash
API_BACKEND_URL=http://127.0.0.1:8000 npm run dev --prefix frontend
```

Abra `http://127.0.0.1:3000`. Para conferir uma compilação de produção local, rode `API_BACKEND_URL=http://127.0.0.1:8000 npm run build --prefix frontend`.

## Publicação

O `Dockerfile` roda apenas a API Python no Render. Ele copia o motor e os recursos geográficos, sem copiar a interface, as planilhas reais em `data/`, os PDFs em `output/` nem os arquivos históricos em `archive/`. A verificação de saúde está em `/api/health`.

O `render.yaml` descreve o serviço Docker gratuito no Render, ligado à branch `main`, com deploy em cada commit enviado ao GitHub. Não é preciso configurar senha ou segredo de sessão. O arquivo apenas descreve a publicação; criar o serviço e validar sua URL são etapas separadas.

### 1. Enviar os commits ao GitHub

O repositório local já tem o remoto `origin` em `https://github.com/hypelc/gerador-de-relatorios-sc.git`, com a branch `main` publicada. O proprietário preferiu fazer os próximos envios por conta própria. Depois de conferir o commit local e os arquivos que serão enviados, use:

```bash
git status --short
git ls-files | rg '^(data/|output/|archive/)|(^|/)\.env$'
git remote -v
git push -u origin main
```

O segundo comando não deve mostrar nenhum arquivo de pesquisa, relatório ou segredo. Se mostrar algo, corrija antes do push. Em 24/09/2026, o repositório remoto estava **público**; confira se essa é a visibilidade desejada antes de compartilhar o link. Nesta versão o site também não exige login.

### 2. Conectar o Render

No Render, conecte o repositório à conta GitHub e crie o serviço a partir do `render.yaml` (Blueprint). Ele usa a branch `main`, o `Dockerfile` da raiz e o plano gratuito. Se criar o serviço manualmente, escolha **Docker**, deixe **Root Directory** vazio e use o `Dockerfile` da raiz; os comandos de instalação e início já estão nele. Não configure `APP_ACCESS_PASSWORD`, `APP_SESSION_SECRET` nem `APP_ENV`. Aguarde o primeiro deploy, confira `/api/health` e anote a URL `https://...onrender.com`.

### 3. Conectar a Vercel

Importe o mesmo repositório na Vercel, selecione **Root Directory = `frontend`** e **Framework = Next.js**. Configure `API_BACKEND_URL` com a URL HTTPS do Render, sem `/api` no final, nos ambientes de produção e prévia. A compilação falha com uma mensagem clara se essa variável faltar. O arquivo `frontend/next.config.mjs` encaminha `/api/*` ao Render; o navegador não chama o domínio do Render diretamente. Conectado ao GitHub, um push para `main` gera novo deploy de produção na Vercel. O Render também redeploya automaticamente após push para `main`.

Os dois serviços publicam de forma independente. Ao mudar o contrato da API no futuro, mantenha compatibilidade com a interface anterior durante a troca das versões. Não é preciso GitHub Actions nem Supabase para esta primeira publicação.

Escolha o plano de hospedagem após medir tempo e memória com os dois relatórios reais. O upload máximo nesta versão é 10 MB; arquivos `.xlsx` muito expandidos são rejeitados. Cada geração é processada em série para evitar colisões no Matplotlib. O servidor precisa de disco temporário gravável para cada requisição, mas não de volume persistente.

Uma medição local com os arquivos recebidos e um PDF por vez levou aproximadamente 4,5 s para o mapa regional e 3,8 s para um relatório anual de uma tabela; o processo Python atingiu cerca de 185 MB de memória residente. Esses valores são do computador de desenvolvimento e não garantem o desempenho da hospedagem. Antes de liberar a URL, configure no provedor um limite de tempo compatível com gerações maiores e verifique memória e download no serviço publicado.

No plano gratuito, o Render desliga o serviço após 15 minutos sem acesso e pode levar cerca de um minuto para acordar. Requisições encaminhadas pela Vercel a um serviço externo têm limite de 120 segundos; se uma geração maior exceder isso, será preciso reduzir o lote ou escolher processamento assíncrono/mais recursos. A interface pode abrir rapidamente enquanto a API ainda acorda, mas inspeção e geração esperarão pelo Render. Referências: [Render gratuito](https://render.com/docs/free) e [limite de proxy da Vercel](https://vercel.com/docs/errors/router_external_target_error).

Antes de compartilhar a URL, abra o site em uma janela comum do navegador, importe os dois exemplos, gere os dois PDFs e o PNG regional, confira as figuras e confirme que o download funciona. Teste também arquivo incompatível e tela estreita. Essa validação de uma URL publicada ainda não foi feita neste ambiente local.

## Como o fluxo funciona

1. A interface envia o arquivo a `/api/inspect`.
2. O servidor lê o formato, valida a estrutura e devolve as tabelas ou Regionais reconhecidas; apaga o temporário.
3. A usuária confere os dados e escolhe um modelo visual compatível. Séries anuais oferecem painéis, linhas e barras; mapa somente com os oito códigos reais de SC. Pizza só é oferecida para contagens regionais aditivas, de um ano, sem lacunas; taxas e coberturas não são partes de um total. Tabelas regionais de período único geram barras com o valor estadual como referência, quando houver.
4. A interface reenvia o mesmo arquivo e as escolhas a `/api/generate`. O servidor valida tudo de novo, gera PDF ou PNG e apaga os temporários.
5. O navegador mantém o PDF da prévia para download. A interface não guarda relatórios de sessões anteriores.

Os números vêm da planilha. Anos fora de ordem são apresentados cronologicamente mantendo a correspondência original entre ano e valor. Colunas `MÉDIA` e `TOTAL` não entram na série anual. Células vazias continuam ausentes, zeros continuam zero e valores acima de 100% são preservados. Se o indicador não estiver identificado, o sistema usa `Valor informado na planilha`, sem supor que seja cobertura vacinal. As regiões fictícias dos exemplos não são desenhadas no mapa de SC. O mapa das 17 Regionais exige correspondência completa dos nomes com a composição geográfica utilizada. Quando o arquivo não atende a um contrato, o site mostra o problema em vez de escolher um relatório arbitrário.

## Próximas versões

- `0.1.x`: correções do piloto, mantendo os dados e os contratos existentes.
- `0.2.0`: novo contrato de planilha acompanhado de exemplo real e teste; Jev poderá ser avaliado para decidir entre modelos conhecidos, com confirmação humana.
- Posterior: login individual e um banco para salvar cada relatório com data, autor autenticado e informações da geração. Definir quem pode consultar e apagar esses registros antes de armazená-los.
