# Rodar e publicar o Gerador de Relatórios SC na web

Esta é a versão piloto `0.1.0`. Ela reconhece dois contratos de planilha: séries anuais por macrorregião e um indicador por 17 Regionais de Saúde. A identificação é feita por regras de formato; o Jev ainda não participa. A planilha é enviada ao servidor na inspeção e novamente na geração, mas não é salva permanentemente. Não há banco de dados nem histórico de usuários.

A interface Next.js fica na Vercel e a API FastAPI no Render. O navegador usa somente a URL da Vercel; o Next.js encaminha `/api/*` ao Render. Isso mantém o cookie de sessão, o envio das planilhas e o download dos PDFs na mesma origem para a usuária.

## Rodar localmente

Pré-requisitos: Python 3.14, Node.js 22 e npm.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm ci --prefix frontend
```

Defina uma senha com pelo menos 12 caracteres e um segredo aleatório com pelo menos 32 caracteres. Gere o segredo localmente com `python3.14 -c 'import secrets; print(secrets.token_urlsafe(48))'`. No primeiro terminal, inicie a API:

```bash
APP_ENV=local APP_ACCESS_PASSWORD='sua-senha-forte' APP_SESSION_SECRET='seu-segredo-aleatorio' .venv/bin/uvicorn webapp.api:app --host 127.0.0.1 --port 8000
```

No segundo terminal, na raiz do projeto, inicie a interface:

```bash
API_BACKEND_URL=http://127.0.0.1:8000 npm run dev --prefix frontend
```

Abra `http://127.0.0.1:3000`. Com `APP_ENV=local`, o cookie funciona em HTTP local. Em produção, não use essa variável: o cookie exige HTTPS. Não publique a senha ou o segredo no Git; configure-os no Render. Para conferir uma compilação de produção local, rode `API_BACKEND_URL=http://127.0.0.1:8000 npm run build --prefix frontend`.

## Publicação

O `Dockerfile` roda apenas a API Python no Render. Ele copia o motor e os recursos geográficos, sem copiar a interface, as planilhas reais em `data/`, os PDFs em `output/` nem os arquivos históricos em `archive/`. A verificação de saúde está em `/api/health`.

O `render.yaml` descreve o serviço Docker gratuito no Render, ligado à branch `main`, com deploy em cada commit enviado ao GitHub. A senha é solicitada durante a criação do serviço; o segredo de sessão é gerado pelo provedor. Nenhuma credencial fica no repositório. O arquivo apenas descreve a publicação; criar o serviço e validar sua URL são etapas separadas.

### 1. Enviar os commits ao GitHub

O repositório local já tem o remoto `origin` em `https://github.com/hypelc/gerador-de-relatorios-sc.git`, com a branch `main` publicada. O proprietário preferiu fazer os próximos envios por conta própria. Depois de conferir o commit local e os arquivos que serão enviados, use:

```bash
git status --short
git ls-files | rg '^(data/|output/|archive/)|(^|/)\.env$'
git remote -v
git push -u origin main
```

O segundo comando não deve mostrar nenhum arquivo de pesquisa, relatório ou segredo. Se mostrar algo, corrija antes do push. Em 24/09/2026, o repositório remoto estava **público**; confira se essa é a visibilidade desejada antes de compartilhar o link. O acesso ao site continua protegido pela senha da API.

### 2. Conectar o Render

No Render, conecte o repositório à conta GitHub e crie o serviço a partir do `render.yaml` (Blueprint). Ele usa a branch `main`, o `Dockerfile` da raiz e o plano gratuito. Defina `APP_ACCESS_PASSWORD` com uma senha forte para a equipe; o Render gera `APP_SESSION_SECRET`. Não defina `APP_ENV=local`. Aguarde o primeiro deploy, confira `/api/health` e anote a URL `https://...onrender.com`.

### 3. Conectar a Vercel

Importe o mesmo repositório na Vercel, selecione **Root Directory = `frontend`** e **Framework = Next.js**. Configure `API_BACKEND_URL` com a URL HTTPS do Render, sem `/api` no final, nos ambientes de produção e prévia. A compilação falha com uma mensagem clara se essa variável faltar. O arquivo `frontend/next.config.mjs` encaminha `/api/*` ao Render; o navegador não chama o domínio do Render diretamente. Conectado ao GitHub, um push para `main` gera novo deploy de produção na Vercel. O Render também redeploya automaticamente após push para `main`.

Os dois serviços publicam de forma independente. Ao mudar o contrato da API no futuro, mantenha compatibilidade com a interface anterior durante a troca das versões. Não é preciso GitHub Actions nem Supabase para esta primeira publicação.

Escolha o plano de hospedagem após medir tempo e memória com os dois relatórios reais. O upload máximo nesta versão é 10 MB; arquivos `.xlsx` muito expandidos são rejeitados. Cada geração é processada em série para evitar colisões no Matplotlib. O servidor precisa de disco temporário gravável para cada requisição, mas não de volume persistente.

Uma medição local com os arquivos recebidos e um PDF por vez levou aproximadamente 4,5 s para o mapa regional e 3,8 s para um relatório anual de uma tabela; o processo Python atingiu cerca de 185 MB de memória residente. Esses valores são do computador de desenvolvimento e não garantem o desempenho da hospedagem. Antes de liberar a URL, configure no provedor um limite de tempo compatível com gerações maiores e verifique memória e download no serviço publicado.

No plano gratuito, o Render desliga o serviço após 15 minutos sem acesso e pode levar cerca de um minuto para acordar. Requisições encaminhadas pela Vercel a um serviço externo têm limite de 120 segundos; se uma geração maior exceder isso, será preciso reduzir o lote ou escolher processamento assíncrono/mais recursos. A interface pode abrir rapidamente enquanto a API ainda acorda, mas login e geração esperarão pelo Render. Referências: [Render gratuito](https://render.com/docs/free) e [limite de proxy da Vercel](https://vercel.com/docs/errors/router_external_target_error).

Antes de compartilhar a URL, faça login em uma janela comum do navegador, importe os dois exemplos, gere os dois PDFs e o PNG regional, confira as figuras e confirme que o download funciona. Teste também senha incorreta, arquivo incompatível e tela estreita. Essa validação de uma URL publicada ainda não foi feita neste ambiente local.

## Como o fluxo funciona

1. A interface envia o arquivo a `/api/inspect`.
2. O servidor lê o formato, valida a estrutura e devolve as tabelas ou Regionais reconhecidas; apaga o temporário.
3. A usuária confere os dados e escolhe um modelo visual compatível.
4. A interface reenvia o mesmo arquivo e as escolhas a `/api/generate`. O servidor valida tudo de novo, gera PDF ou PNG e apaga os temporários.
5. O navegador mantém o PDF da prévia para download. A interface não guarda relatórios de sessões anteriores.

Os números vêm da planilha. Células vazias de séries anuais continuam ausentes e zeros continuam zero. O mapa das 17 Regionais exige correspondência completa dos nomes com a composição geográfica utilizada. Quando o arquivo não atende a um contrato, o site mostra o problema em vez de escolher um relatório arbitrário.

## Próximas versões

- `0.1.x`: correções do piloto, mantendo os dados e os contratos existentes.
- `0.2.0`: novo contrato de planilha acompanhado de exemplo real e teste; Jev poderá ser avaliado para decidir entre modelos conhecidos, com confirmação humana.
- Posterior: contas, histórico e banco apenas se a equipe precisar identificar quem gerou e consultar relatórios antigos.
