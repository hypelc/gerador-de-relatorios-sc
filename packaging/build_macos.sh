#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

python3 -m pip install -r requirements.txt
pyside6-deploy -f -c "$project_root/pysidedeploy.spec" --name "Gerador de Relatorios SC"
echo "Pacote gerado em dist. O .dmg, assinatura e notarizacao ainda precisam ser criados e testados em macOS."
