"""Gera gráficos locais a partir das tabelas anuais do banco de dados."""
import argparse
import html
import json
import math
from pathlib import Path
import re
import textwrap
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter, MaxNLocator
import openpyxl


ROOT = Path(__file__).resolve().parents[2]


def normalizar(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def nome_regiao(texto):
    return re.sub(r"\s+", " ", re.sub(r"\b\d{4}\s*", "", normalizar(texto))).strip().upper()


def extrair(caminho):
    wb = openpyxl.load_workbook(caminho, data_only=True)
    tabelas = []
    for sheet in wb:
        linhas = list(sheet.values)
        cabecalhos = [(i, [(c, int(v)) for c, v in enumerate(r) if isinstance(v, (int, float)) and 1900 <= v <= 2100 and v == int(v)]) for i, r in enumerate(linhas)]
        cabecalhos = [(i, cols) for i, cols in cabecalhos if len(cols) >= 3 and cols[0][0] == 1]
        if not cabecalhos:
            raise ValueError(f"Nenhuma tabela anual encontrada: {sheet.title}")
        for bloco, (i, cols) in enumerate(cabecalhos):
            fim = cabecalhos[bloco + 1][0] if bloco + 1 < len(cabecalhos) else len(linhas)
            anos = [ano for _, ano in cols]
            if anos != sorted(set(anos)):
                raise ValueError(f"Anos duplicados ou fora de ordem: {sheet.title}")
            inicio = cabecalhos[bloco - 1][0] + 1 if bloco else 0
            titulos = [str(r[0]).split(" por Ano")[0] for r in linhas[inicio:i] if r[0] and " por Ano" in str(r[0])]
            titulo = titulos[-1] if titulos else sheet.title.strip()
            series = []
            macro = "MACRO" in normalizar(str(linhas[i][0])).upper()
            for num, r in enumerate(linhas[i + 1:fim], i + 2):
                if not r[0] or (macro and not re.match(r"^\d{4}\b", str(r[0]))):
                    continue
                vals = [r[c] for c, _ in cols]
                if not any(v is not None for v in vals):
                    continue
                if not any(isinstance(v, (int, float)) for v in vals):
                    continue
                if any(v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v)) for v in vals):
                    raise ValueError(f"Valor não numérico em {sheet.title}, linha {num}")
                series.append({"nome": str(r[0]).strip(), "valores": vals, "linha": num})
            if not series:
                raise ValueError(f"Tabela sem séries em {sheet.title}, linha {i + 1}")
            chave = normalizar(sheet.title).upper()
            tipo = "mortalidade" if "MORTALIDADE" in chave else "nascidos" if "NASCIDOS" in chave else "vacina"
            tabelas.append(dict(aba=sheet.title, titulo=titulo, anos=anos, series=series, tipo=tipo, macro=macro, cabecalho=i + 1))
    wb.close()
    return tabelas


def desenhar_series(tabela, estilos, teto, layout):
    """Mantém os dados intactos e escolhe entre comparação conjunta e painéis."""
    paineis = layout == "paineis" and len(tabela["series"]) > 1
    quantidade = len(tabela["series"])
    if paineis:
        colunas = 2 if quantidade <= 8 else 4
        linhas = math.ceil(quantidade / colunas)
        fig, grade = plt.subplots(linhas, colunas, figsize=(14 if colunas == 2 else 18, 3 * linhas + 2), squeeze=False)
        eixos = list(grade.flat)
        fig.subplots_adjust(left=.08, right=.95, top=.84, bottom=.12, hspace=.66, wspace=.22)
    else:
        fig, ax = plt.subplots(figsize=(14, 8))
        fig.subplots_adjust(left=.08, right=.67, top=.79, bottom=.19)
        eixos = [ax]
    limite = teto if tabela["tipo"] == "vacina" else max(v for s in tabela["series"] for v in s["valores"] if v is not None) * 1.15
    unidade = "Cobertura vacinal (%)" if tabela["tipo"] == "vacina" else "Nascidos vivos (número)" if tabela["tipo"] == "nascidos" else "Mortalidade infantil (valor absoluto)"
    for j, serie in enumerate(tabela["series"]):
        ax = eixos[j] if paineis else eixos[0]
        nome = nome_regiao(serie["nome"]) if tabela["macro"] else serie["nome"]
        cor, marcador = estilos[nome] if tabela["macro"] else (plt.get_cmap("tab20")(j % 20), "o")
        ax.plot(tabela["anos"], [float("nan") if v is None else v for v in serie["valores"]], label=textwrap.fill(nome, 30), color=cor, marker=marcador, markersize=5, linewidth=2)
        if paineis:
            ax.set_title(textwrap.fill(nome, 40), loc="left", fontsize=11, weight="bold", pad=12)
            # Só rotula o último ano se existir um valor nesse ano.
            ultimo = serie["valores"][-1]
            if ultimo is not None:
                rotulo = f"{ultimo:.2f}%".replace(".", ",") if tabela["tipo"] == "vacina" else f"{ultimo:,.0f}".replace(",", ".")
                ax.annotate(rotulo, (tabela["anos"][-1], ultimo), xytext=(0, 10), textcoords="offset points", ha="center", fontsize=9, color=cor)
    for ax in eixos[:quantidade if paineis else 1]:
        ax.set_xticks(tabela["anos"])
        ax.tick_params(axis="x", labelsize=9, rotation=45 if paineis and quantidade > 8 else 0)
        ax.set_xlabel("Ano", labelpad=7)
        ax.set_ylim(0, limite)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".")))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5 if paineis else 7, integer=True))
        ax.grid(axis="y", color="#e0e5eb", linewidth=.7)
        ax.set_axisbelow(True)
    if paineis:
        fig.supylabel(unidade, x=.02, fontsize=12)
        for ax in eixos[quantidade:]:
            ax.set_visible(False)
    else:
        eixos[0].set_ylabel(unidade, labelpad=12)
        eixos[0].legend(loc="center left", bbox_to_anchor=(1.02, .5), frameon=False, fontsize=9 if quantidade > 10 else 10, labelspacing=.85)
    return fig, paineis


def gerar(entrada, saida, layout="paineis"):
    tabelas = extrair(entrada)
    saida.mkdir(parents=True, exist_ok=True)
    cores = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#8C6D00", "#56B4E9", "#332288", "#555555", "#AA4499"]
    regioes = list(dict.fromkeys(nome_regiao(s["nome"]) for t in tabelas if t["macro"] for s in t["series"]))
    estilos = {nome: (cores[i % len(cores)], ["o", "s", "^", "D", "v", "P", "X", "h", "*"][i % 9]) for i, nome in enumerate(regioes)}
    max_vacina = max(v for t in tabelas if t["tipo"] == "vacina" for s in t["series"] for v in s["valores"] if v is not None)
    teto = math.ceil(max_vacina / 20) * 20
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    cards = []
    with PdfPages(saida / "todos_os_graficos.pdf") as pdf:
        for indice, tabela in enumerate(tabelas, 1):
            fig, paineis = desenhar_series(tabela, estilos, teto, layout)
            title = tabela["titulo"]
            if tabela["tipo"] == "nascidos":
                title = "Nascidos vivos" if tabela["macro"] else "Nascidos vivos — total estadual"
            elif tabela["tipo"] == "mortalidade":
                title = "Mortalidade infantil" if tabela["macro"] else "Mortalidade infantil — total estadual"
            elif tabela["aba"].strip() == "PNEUMOCÓCICA 1 REF":
                title = "Pneumocócica — 1º reforço (conforme aba)"
            if tabela["aba"].strip() == "TOTAL DE IMUNIZAÇÕES EM SC":
                title = "Cobertura vacinal por vacina"
            fig.text(.08, .96 if paineis else .935, "SANTA CATARINA", fontsize=11, color="#52606d", weight="bold")
            fig.text(.08, .923 if paineis else .87, title, fontsize=19, weight="bold", color="#162b40")
            subtitulo = f'{tabela["anos"][0]}–{tabela["anos"][-1]}  •  ' + ("Por macrorregião de saúde" if tabela["macro"] else "Total estadual")
            if paineis:
                subtitulo += "  •  Mesma escala em todos os painéis"
            fig.text(.08, .89 if paineis else .825, subtitulo, color="#52606d")
            faltantes = sorted({ano for s in tabela["series"] for ano, v in zip(tabela["anos"], s["valores"]) if v is None})
            notas = ["Fonte: " + entrada.name + " | Aba: " + tabela["aba"].strip()]
            if faltantes:
                notas.append("Dados ausentes em parte ou em todas as séries: " + ", ".join(map(str, faltantes)) + ". Lacunas sem interpolação.")
            if tabela["tipo"] == "vacina":
                notas.append("Valores originais; coberturas acima de 100% preservadas. Colunas de média e total excluídas.")
            elif tabela["tipo"] == "mortalidade":
                notas.append("Valores absolutos da planilha; não representam uma taxa por mil nascidos vivos.")
            fig.text(.08, .045, "\n".join(notas), fontsize=8.5, color="#52606d", linespacing=1.6)
            slug = re.sub(r"[^a-z0-9]+", "_", normalizar(title).lower()).strip("_")
            arquivo = f"{indice:02d}_{slug}.png"
            fig.savefig(saida / arquivo, dpi=200, facecolor="white")
            pdf.savefig(fig, facecolor="white")
            plt.close(fig)
            tabela["arquivo"] = arquivo
            cards.append(f'<article><h2>{html.escape(title)}</h2><a href="{arquivo}" download>Baixar PNG</a><img loading="lazy" src="{arquivo}" alt="{html.escape(title)}"></article>')
    pagina = '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Gráficos — Santa Catarina</title><style>body{font:16px system-ui;margin:40px auto;padding:0 20px;max-width:1200px;background:#f3f5f7;color:#162b40}article{background:white;padding:24px;margin:24px 0;border-radius:10px}img{width:100%;height:auto}a{color:#0072b2}h2{font-size:20px}</style><h1>Gráficos — Santa Catarina</h1><p>' + str(len(tabelas)) + ' gráficos. Cada ponto corresponde a um valor anual da planilha.</p><a href="todos_os_graficos.pdf">Abrir PDF completo</a>' + "".join(cards) + '</html>'
    (saida / "index.html").write_text(pagina, encoding="utf-8")
    (saida / "dados_graficos.json").write_text(json.dumps(tabelas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gerados {len(tabelas)} gráficos em {saida.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planilha", type=Path)
    parser.add_argument("--saida", type=Path, help="Pasta dos arquivos gerados")
    parser.add_argument("--layout", choices=["paineis", "conjunto"], default="paineis", help="Uma série por painel (padrão) ou todas no mesmo gráfico")
    args = parser.parse_args()
    pasta_padrao = "graficos_paineis" if args.layout == "paineis" else "graficos"
    saida = args.saida or ROOT / "output" / "legado" / pasta_padrao
    gerar(args.planilha, saida, args.layout)
