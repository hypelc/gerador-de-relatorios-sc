$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Instalando dependencias fixadas..."
python -m pip install -r requirements.txt
Write-Host "Construindo o pacote Windows com pyside6-deploy..."
pyside6-deploy -f -c "$ProjectRoot/pysidedeploy.spec" --name "Gerador de Relatorios SC"
Write-Host "Pacote gerado em dist. A instalacao .exe ainda precisa ser criada e testada em Windows."
