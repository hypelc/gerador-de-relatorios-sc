# Builds de plataforma

O projeto usa `pyside6-deploy` como primeira opcao. O arquivo `pysidedeploy.spec` inclui o pacote Python e os recursos de `geodados`.

## Windows

Em Windows 10 ou 11 de 64 bits, com Python na versao suportada:

```powershell
.\packaging\build_windows.ps1
```

O resultado e um pacote em `dist`. Um instalador `.exe` (por exemplo, via Inno Setup) deve ser produzido somente depois de abrir o aplicativo em Windows e testar importacao, pre-visualizacao, exportacao e desinstalacao.

## macOS

No macOS, confirme antes se o computador usa Apple Silicon ou Intel e execute:

```bash
./packaging/build_macos.sh
```

O resultado e um `.app` em `dist`. A imagem `.dmg`, assinatura e notarizacao ficam para a etapa de distribuicao e precisam ser verificadas no mesmo macOS e arquitetura do pacote.

Este ambiente Linux nao valida nenhum instalador Windows ou macOS. O mesmo codigo nao deve ser tratado como um instalador multiplataforma sem esses testes.
