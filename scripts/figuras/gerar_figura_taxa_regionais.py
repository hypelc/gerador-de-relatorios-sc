"""Atalho para reproduzir a figura original usando o motor atual."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gerador_sc.regional import RegionalConfig, render_regional_report


def main() -> None:
    pdf = (
        ROOT
        / "output"
        / "pdf"
        / "distribuicao_taxa_profissionais_regionais_saude_sc.pdf"
    )
    png = (
        ROOT
        / "output"
        / "figuras"
        / "distribuicao_taxa_profissionais_regionais_saude_sc.png"
    )
    render_regional_report(
        ROOT / "data" / "exemplos" / "taxa estado SC.xlsx",
        pdf,
        png,
        RegionalConfig(
            "Distribuição da taxa de profissionais segundo Regionais de Saúde",
            processing_context="local",
        ),
    )
    print(pdf)
    print(png)


if __name__ == "__main__":
    main()
