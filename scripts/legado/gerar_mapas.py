"""Mapas de cobertura por macrorregião de SC, com geometrias oficiais em cache."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
import matplotlib.patheffects as effects
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.geometry.polygon import orient
from shapely.ops import transform, unary_union

from gerar_graficos import extrair

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "geodados"
CORES = ["#E76F73", "#D5AE58", "#BDDA7A", "#59A64A"]
FAIXAS = ["Menor que 45%", "45% a menos de 70%", "70% a menos de 95%", "95% ou mais"]
NOMES = {
    "4213": "Grande Oeste", "4217": "Meio Oeste", "4218": "Serra Catarinense",
    "4210": "Sul", "4211": "Planalto Norte e Nordeste", "4214": "Grande Florianópolis",
    "4215": "Foz do Rio Itajaí", "4216": "Vale do Itajaí",
}
ORDEM = list(NOMES)
FONTES = {
    "malha": "https://servicodados.ibge.gov.br/api/v3/malhas/estados/42?formato=application/vnd.geo%2Bjson&qualidade=intermediaria&intrarregiao=municipio",
    "documentacao_malha": "https://servicodados.ibge.gov.br/api/docs/malhas?versao=3",
    "municipios_macrorregioes": "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/dbgeral/macroregiao_de_saude_csv.zip",
    "catalogo": "https://dadosabertos.saude.gov.br/dataset/macrorregiao-de-saude/resource/3bd28e64-0a82-44d9-8de1-4894634f2b6a",
}


def preparar_geometrias():
    with (GEO / "macrorregioes_ms.csv").open(encoding="utf-8-sig") as f:
        linhas = [r for r in csv.DictReader(f, delimiter=";") if r["sg_uf"] == "SC"]
    vinculos = {r["cod_municipio"]: r for r in linhas}
    malha = json.loads((GEO / "sc_municipios_ibge.geojson").read_text())
    ids = [f["properties"]["codarea"][:6] for f in malha["features"]]
    if len(linhas) != len(vinculos) or len(ids) != len(set(ids)) or set(ids) != set(vinculos):
        raise ValueError("Municípios duplicados ou sem correspondência entre IBGE e MS.")
    if len(ids) != 295:
        raise ValueError("O recorte esperado de SC deve conter 295 municípios.")
    grupos = {codigo: [] for codigo in ORDEM}
    for feature in malha["features"]:
        municipio = feature["properties"]["codarea"][:6]
        codigo = vinculos[municipio]["cod_macrorregiao_de_saude"]
        geometria = shape(feature["geometry"])
        if not geometria.is_valid:
            raise ValueError(f"Geometria municipal inválida: {municipio}")
        grupos[codigo].append(geometria)
    macros = {codigo: unary_union(geometrias) for codigo, geometrias in grupos.items()}
    if any(g.is_empty or not g.is_valid for g in macros.values()):
        raise ValueError("Macrorregião vazia ou inválida.")
    # Exporta a malha derivada mantendo coordenadas geográficas e a rastreabilidade.
    exportacao = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"codigo": c, "nome": NOMES[c], "municipios": len(grupos[c])}, "geometry": mapping(g)}
        for c, g in macros.items()
    ]}
    (GEO / "sc_macrorregioes_saude.geojson").write_text(json.dumps(exportacao, ensure_ascii=False), encoding="utf-8")
    projetar = Transformer.from_crs("EPSG:4674", "EPSG:5880", always_xy=True)
    projetadas = {c: transform(projetar.transform, g) for c, g in macros.items()}
    uniao = unary_union(list(projetadas.values()))
    sobreposicao = sum(g.area for g in projetadas.values()) - uniao.area
    if abs(sobreposicao) > uniao.area * 1e-8:
        raise ValueError("Sobreposição entre as macrorregiões.")
    return projetadas, projetar, {c: len(v) for c, v in grupos.items()}


def classe(valor):
    if valor is None:
        return None
    return 0 if valor < 45 else 1 if valor < 70 else 2 if valor < 95 else 3


def obter_valores(tabela, ano):
    if ano not in tabela["anos"]:
        raise ValueError(f"Ano {ano} não disponível na aba {tabela['aba']}.")
    indice = tabela["anos"].index(ano)
    valores = {}
    for serie in tabela["series"]:
        codigo = serie["nome"].split()[0]
        if codigo in valores:
            raise ValueError(f"Código repetido: {codigo}")
        valores[codigo] = serie["valores"][indice]
    if set(valores) != set(ORDEM):
        raise ValueError("A tabela deve conter as oito macrorregiões de saúde do mapa.")
    return valores


def poligonos(geometria):
    return [geometria] if geometria.geom_type == "Polygon" else list(geometria.geoms)


def desenhar_mapa(ax, geometrias, valores, identificar=True):
    for numero, codigo in enumerate(ORDEM, 1):
        categoria = classe(valores[codigo])
        cor = "#DDDDDD" if categoria is None else CORES[categoria]
        for poligono in poligonos(geometrias[codigo]):
            poligono = orient(poligono, sign=1)
            vertices, codigos = [], []
            for anel in [poligono.exterior, *poligono.interiors]:
                pontos = list(anel.coords)
                vertices.extend(pontos)
                codigos.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(pontos) - 2) + [MplPath.CLOSEPOLY])
            ax.add_patch(PathPatch(MplPath(vertices, codigos), facecolor=cor, edgecolor="#343A35", linewidth=.65, hatch="///" if categoria is None else None))
        if identificar:
            centro = max(poligonos(geometrias[codigo]), key=lambda g: g.area).representative_point()
            texto = ax.text(centro.x, centro.y, str(numero), ha="center", va="center", weight="bold", fontsize=10, color="#17251C")
            texto.set_path_effects([effects.withStroke(linewidth=2.5, foreground="white")])
    limites = unary_union(list(geometrias.values())).bounds
    ax.set_xlim(limites[0] - 15000, limites[2] + 15000)
    ax.set_ylim(limites[1] - 15000, limites[3] + 15000)
    ax.set_aspect("equal")
    ax.axis("off")


def legenda(fig, y):
    fig.legend(handles=[Patch(facecolor=cor, edgecolor="#555", label=nome) for cor, nome in zip(CORES, FAIXAS)] + [Patch(facecolor="#ddd", hatch="///", label="Sem dado")], loc="lower center", bbox_to_anchor=(.5, y), ncol=5, frameon=False, title="Cobertura vacinal (%) — faixas da imagem de referência", fontsize=10, title_fontsize=11)


def salvar(fig, pasta, nome):
    fig.savefig(pasta / f"{nome}.png", dpi=220, facecolor="white")
    fig.savefig(pasta / f"{nome}.pdf", facecolor="white")
    plt.close(fig)


def modelo(tabelas, geometrias, projetar, ano, pasta):
    fig = plt.figure(figsize=(16, 11))
    fig.text(.055, .955, f"Cobertura da vacina tríplice viral — Santa Catarina, {ano}", fontsize=21, weight="bold", color="#162B40")
    fig.text(.055, .915, "Distribuição por macrorregião de saúde • Primeira e segunda dose", fontsize=12, color="#52606D")
    ambos = [obter_valores(t, ano) for t in tabelas]
    for i, (tabela, valores) in enumerate(zip(tabelas, ambos)):
        ax = fig.add_axes([.045 + i * .49, .40, .46, .46])
        desenhar_mapa(ax, geometrias, valores)
        ax.set_title("A) Primeira dose" if i == 0 else "B) Segunda dose", loc="left", fontsize=14, weight="bold", pad=13)
        # Norte verdadeiro local: dois pontos sobre o mesmo meridiano projetados.
        p1 = projetar.transform(-49, -28)
        p2 = projetar.transform(-49, -27.5)
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        norm = (dx * dx + dy * dy) ** .5
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
        x, y = x1 - 45000, y1 - 70000
        ax.annotate("N", xy=(x + dx / norm * 40000, y + dy / norm * 40000), xytext=(x, y), ha="center", va="center", fontsize=12, weight="bold", arrowprops={"arrowstyle": "-|>", "lw": 1.5})
        x, y = x0 + 20000, y0 + 30000
        ax.plot([x, x + 100000], [y, y], color="#252525", lw=2)
        for distancia, rotulo in [(0, "0"), (50000, "50"), (100000, "100 km")]:
            ax.plot([x + distancia] * 2, [y - 4000, y + 4000], color="#252525", lw=1)
            ax.text(x + distancia, y - 10000, rotulo, ha="center", va="top", fontsize=8)
    legenda(fig, .337)
    ax = fig.add_axes([.10, .09, .80, .23]); ax.axis("off")
    linhas = [[f"{n}. {NOMES[c]}", *["Sem dado" if v[c] is None else f"{v[c]:.2f}%".replace(".", ",") for v in ambos]] for n, c in enumerate(ORDEM, 1)]
    tab = ax.table(cellText=linhas, colLabels=["Macrorregião de saúde", "Primeira dose", "Segunda dose"], colWidths=[.60, .20, .20], cellLoc="left", bbox=[0, 0, 1, 1])
    tab.auto_set_font_size(False); tab.set_fontsize(10)
    for (r, c), cell in tab.get_celld().items():
        cell.set_edgecolor("white")
        cell.set_facecolor("#E9EEF1" if r == 0 else "#F5F7F8" if r % 2 else "white")
        if r == 0:
            cell.set_text_props(weight="bold")
    fig.text(.055, .035, "Coberturas: planilha fornecida, abas TRÍPLICE VIRAL e TRÍPLICE VIRAL 2 DOSE.\nGeografia: malha municipal simplificada IBGE + composição das macrorregiões do Ministério da Saúde; consulta em 11/09/2026.\nProjeção: SIRGAS 2000 / Brazil Polyconic (EPSG:5880). Cores representam valores agregados por macrorregião, não por município.", fontsize=8, color="#52606D")
    salvar(fig, pasta, f"modelo_triplice_viral_sc_{ano}")


def evolucao(tabela, geometrias, pasta, dose):
    anos = tabela["anos"]
    fig, axes = plt.subplots(2, 5, figsize=(20, 10))
    fig.subplots_adjust(left=.025, right=.975, bottom=.20, top=.83, wspace=.10, hspace=.15)
    fig.text(.04, .935, f"Tríplice viral — {dose} dose | Santa Catarina", fontsize=22, weight="bold", color="#162B40")
    fig.text(.04, .89, f"Evolução da cobertura por macrorregião • {anos[0]}–{anos[-1]} • Mesmas faixas de cores em todos os anos", fontsize=12, color="#52606D")
    if len(anos) > len(axes.flat):
        raise ValueError("A figura de evolução comporta até dez anos.")
    for ax, ano in zip(axes.flat, anos):
        desenhar_mapa(ax, geometrias, obter_valores(tabela, ano))
        ax.set_title(str(ano), loc="left", fontsize=14, weight="bold")
    for ax in list(axes.flat)[len(anos):]:
        ax.set_visible(False)
    legenda(fig, .115)
    fig.text(.04, .075, "1 Grande Oeste   •   2 Meio Oeste   •   3 Serra Catarinense   •   4 Sul\n5 Planalto Norte e Nordeste   •   6 Grande Florianópolis   •   7 Foz do Rio Itajaí   •   8 Vale do Itajaí", fontsize=10, linespacing=1.7)
    fig.text(.04, .025, f"Fonte dos valores: planilha fornecida, aba {tabela['aba']}. Geografia: IBGE + Ministério da Saúde, consulta em 11/09/2026. EPSG:5880.\nRecorte territorial fixo nas oito macrorregiões identificadas na planilha; não reconstrói mudanças históricas dos limites. Faixas da imagem de referência.", fontsize=8, color="#52606D")
    salvar(fig, pasta, f"evolucao_triplice_viral_{dose}_dose_sc")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planilha", type=Path)
    parser.add_argument("--ano", type=int, default=2025)
    parser.add_argument("--evolucao", action="store_true")
    parser.add_argument("--saida", type=Path, default=ROOT / "output" / "legado" / "mapas_sc")
    args = parser.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    todas = extrair(args.planilha)
    tabelas = [next(t for t in todas if t["aba"].strip() == nome) for nome in ["TRÍPLICE VIRAL", "TRÍPLICE VIRAL 2 DOSE"]]
    geometrias, projetar, contagens = preparar_geometrias()
    plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42})
    modelo(tabelas, geometrias, projetar, args.ano, args.saida)
    if args.evolucao:
        for tabela, dose in zip(tabelas, ["1a", "2a"]):
            evolucao(tabela, geometrias, args.saida, dose)
    with (args.saida / "valores_mapeados.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["aba", "ano", "codigo_macro", "macrorregiao", "cobertura_percentual", "faixa"])
        for tabela in tabelas:
            for ano in tabela["anos"]:
                for codigo, valor in obter_valores(tabela, ano).items():
                    categoria = classe(valor)
                    writer.writerow([tabela["aba"], ano, codigo, NOMES[codigo], valor, "Sem dado" if categoria is None else FAIXAS[categoria]])
    arquivos = [args.planilha, GEO / "sc_municipios_ibge.geojson", GEO / "macrorregioes_ms.csv"]
    manifesto = {"gerado_em": datetime.now(timezone.utc).isoformat(), "fontes": FONTES, "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in arquivos}, "municipios_por_macro": contagens, "municipios_total": sum(contagens.values()), "projecao": "EPSG:5880", "ano_modelo": args.ano, "limites_classes": [45, 70, 95], "metodo": "União das geometrias municipais pelos códigos de macrorregião do MS. Valores da planilha associados diretamente pelo código de macrorregião. Nenhuma estimativa municipal; nenhum cálculo de abandono. Recorte territorial fixo aplicado às séries anuais."}
    (args.saida / "fontes_e_metodo.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapas gerados em {args.saida.resolve()}. 295 municípios, 8 macrorregiões.")


if __name__ == "__main__":
    main()
