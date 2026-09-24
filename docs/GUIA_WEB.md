# Rodar e publicar o Gerador de Relatórios SC na web

Esta é a versão piloto `0.1.0`. Ela reconhece dois contratos de planilha: séries anuais por macrorregião e um indicador por 17 Regionais de Saúde. A identificação é feita por regras de formato; o Jev ainda não participa. A planilha é enviada ao servidor na inspeção e novamente na geração, mas não é salva permanentemente. Não há banco de dados nem histórico de usuários.

## Rodar localmente

Pré-requisitos: Python 3.14, Node.js 22 e npm.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm run build --prefix frontend
```

Defina uma senha com pelo menos 12 caracteres e um segredo aleatório com pelo menos 32 caracteres. Gere o segredo localmente com `python3.14 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Para iniciar o servidor em desenvolvimento:

```bash
APP_ENV=local APP_ACCESS_PASSWORD='sua-senha-forte' APP_SESSION_SECRET='seu-segredo-aleatorio' .venv/bin/uvicorn webapp.api:app --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000`. Com `APP_ENV=local`, o cookie funciona em HTTP local. Em produção, não use essa variável: o cookie exige HTTPS. Não publique a senha ou o segredo no Git; configure-os como variáveis de ambiente do serviço.

## Publicação

O `Dockerfile` compila a interface React/Vite e roda a API Python no mesmo serviço. Ele copia o motor e os recursos geográficos, sem copiar as planilhas reais em `data/`, os PDFs em `output/` nem os arquivos históricos em `archive/`. Um serviço que aceite contêiner Docker e HTTPS pode usar esse arquivo. Configure `APP_ACCESS_PASSWORD` e `APP_SESSION_SECRET` no painel do provedor, e uma porta `PORT` se a plataforma exigir. A verificação de saúde está em `/api/health`.

Escolha o plano de hospedagem após medir tempo e memória com os dois relatórios reais. O upload máximo nesta versão é 10 MB; arquivos `.xlsx` muito expandidos são rejeitados. Cada geração é processada em série para evitar colisões no Matplotlib. O servidor precisa de disco temporário gravável para cada requisição, mas não de volume persistente.

Uma medição local com os arquivos recebidos e um PDF por vez levou aproximadamente 4,5 s para o mapa regional e 3,8 s para um relatório anual de uma tabela; o processo Python atingiu cerca de 185 MB de memória residente. Esses valores são do computador de desenvolvimento e não garantem o desempenho da hospedagem. Antes de liberar a URL, configure no provedor um limite de tempo compatível com gerações maiores e verifique memória e download no serviço publicado.

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
