"use client";

import { useEffect, useRef, useState } from "react";

const modelLabels = {
  paineis: [
    "Evolução por região",
    "Um painel de linhas para cada macrorregião. Melhor para acompanhar mudanças ao longo dos anos.",
  ],
  linhas: [
    "Comparação em linhas",
    "Todas as regiões no mesmo gráfico para comparar trajetórias.",
  ],
  mapa: [
    "Mapa por macrorregião",
    "Distribuição da cobertura no mapa de SC, para os anos escolhidos.",
  ],
  mapa_regional: [
    "Mapa das Regionais de Saúde",
    "Uma figura com as 17 Regionais, escala de valores e tabela de consulta.",
  ],
};

async function apiError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    /* resposta sem JSON */
  }
  const detail = payload?.detail;
  if (typeof detail === "string") return { message: detail, diagnostics: [] };
  if (detail && typeof detail === "object")
    return {
      message: detail.message || "Confira os dados da planilha.",
      diagnostics: detail.diagnostics || [],
    };
  return {
    message: `Não foi possível concluir a operação (${response.status}).`,
    diagnostics: [],
  };
}

function Icon({ name, size = 20 }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };
  if (name === "upload")
    return (
      <svg {...common}>
        <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" />
        <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
      </svg>
    );
  if (name === "file")
    return (
      <svg {...common}>
        <path d="M5 3h9l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3Z" />
        <path d="M14 3v5h5M8 13h8M8 17h5" />
      </svg>
    );
  if (name === "check")
    return (
      <svg {...common}>
        <path d="m5 12 4 4L19 6" />
      </svg>
    );
  if (name === "arrow")
    return (
      <svg {...common}>
        <path d="M4 12h16m-6-6 6 6-6 6" />
      </svg>
    );
  if (name === "download")
    return (
      <svg {...common}>
        <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v3h16v-3" />
      </svg>
    );
  if (name === "lock")
    return (
      <svg {...common}>
        <rect x="5" y="10" width="14" height="11" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      </svg>
    );
  if (name === "back")
    return (
      <svg {...common}>
        <path d="M20 12H4m6-6-6 6 6 6" />
      </svg>
    );
  return null;
}

function Diagnostics({ error }) {
  if (!error) return null;
  return (
    <div className="error-panel" role="alert">
      <strong>{error.message}</strong>
      {!!error.diagnostics?.length && (
        <ul>
          {error.diagnostics.slice(0, 8).map((item, index) => (
            <li key={`${item.code}-${index}`}>
              {item.location ? `${item.location}: ` : ""}
              {item.message}
              {item.suggestion ? ` ${item.suggestion}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ModelCard({ value, selected, disabled, onChoose }) {
  const [title, description] = modelLabels[value];
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChoose(value)}
      className={`model-card ${selected ? "selected" : ""}`}
      aria-pressed={selected}
    >
      <span className={`model-visual ${value}`} aria-hidden="true">
        {value === "paineis" && (
          <>
            <i />
            <i />
            <i />
            <i />
          </>
        )}
        {value === "linhas" && (
          <svg viewBox="0 0 140 58">
            <path d="M2 46 28 27 53 34 79 10 105 24 137 6" />
            <path d="M2 51 28 45 53 19 79 33 105 14 137 21" />
          </svg>
        )}
        {(value === "mapa" || value === "mapa_regional") && (
          <svg viewBox="0 0 140 58">
            <path d="M15 14 40 6 72 13 91 9 123 24 107 49 73 51 53 43 31 52 12 35Z" />
            <path d="M40 6 48 25 31 52M72 13 65 38 73 51M91 9 88 30l19 19M15 14l33 11 40 5 35-6" />
          </svg>
        )}
      </span>
      <span className="model-copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </span>
      <span className="model-check">
        <Icon name="check" size={15} />
      </span>
    </button>
  );
}

export default function App() {
  const [file, setFile] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [years, setYears] = useState([]);
  const [model, setModel] = useState("paineis");
  const [search, setSearch] = useState("");
  const [confirmExclusions, setConfirmExclusions] = useState(false);
  const [meta, setMeta] = useState({
    title: "",
    authors: "",
    source: "",
    unit: "",
    period: "",
  });
  const [preview, setPreview] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);
  const previewRef = useRef(null);

  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    },
    [],
  );

  const tables = inspection?.kind === "annual" ? inspection.import.tabelas : [];
  const selectedTables = tables.filter((table) =>
    selectedIds.includes(table.id),
  );
  const invalidTables = tables.filter((table) => !table.valida);
  const commonYears = selectedTables.length
    ? selectedTables.reduce(
        (common, table) => common.filter((year) => table.anos.includes(year)),
        selectedTables[0].anos,
      )
    : [];
  const mapReady =
    selectedTables.length === 1 && selectedTables[0].mapa_disponivel;

  function clearPreview() {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = null;
    setPreview(null);
  }

  async function inspectFile(chosen) {
    if (!chosen) return;
    setFile(chosen);
    setInspection(null);
    setStep(1);
    setError(null);
    clearPreview();
    setBusy("inspect");
    const form = new FormData();
    form.append("file", chosen);
    try {
      const response = await fetch("/api/inspect", {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw await apiError(response);
      const data = await response.json();
      setInspection(data);
      setMeta({
        title:
          data.kind === "regional"
            ? data.suggested_title
            : "Relatório de indicadores de Santa Catarina",
        authors: "",
        source: "",
        unit: "",
        period: "",
      });
      if (data.kind === "annual") {
        const first = data.import.tabelas.find((table) => table.valida);
        setSelectedIds(first ? [first.id] : []);
        setYears(first?.anos || []);
        setModel("paineis");
      } else {
        setSelectedIds([]);
        setYears([]);
        setModel("mapa_regional");
      }
      setConfirmExclusions(false);
      setStep(2);
    } catch (problem) {
      setError(problem);
    } finally {
      setBusy("");
    }
  }

  function toggleTable(id) {
    const next = selectedIds.includes(id)
      ? selectedIds.filter((item) => item !== id)
      : [...selectedIds, id];
    const nextTables = tables.filter((table) => next.includes(table.id));
    const available = nextTables.length
      ? nextTables.reduce(
          (common, table) => common.filter((year) => table.anos.includes(year)),
          nextTables[0].anos,
        )
      : [];
    setSelectedIds(next);
    setYears((previous) =>
      previous.filter((year) => available.includes(year)).length
        ? previous.filter((year) => available.includes(year))
        : available,
    );
    if (
      model === "mapa" &&
      !(nextTables.length === 1 && nextTables[0].mapa_disponivel)
    )
      setModel("paineis");
  }

  function updateMeta(field, value) {
    setMeta((current) => ({ ...current, [field]: value }));
    clearPreview();
  }

  function options(format = "pdf") {
    const base = {
      kind: inspection.kind,
      title: meta.title.trim(),
      authors: meta.authors.trim(),
      source: meta.source.trim(),
      unit: meta.unit.trim(),
    };
    if (inspection.kind === "regional")
      return { ...base, period: meta.period.trim(), format };
    return {
      ...base,
      table_ids: selectedIds,
      years,
      model,
      confirmed_exclusions: confirmExclusions
        ? invalidTables.map((table) => table.id)
        : [],
    };
  }

  async function generate(format = "pdf", downloadImmediately = false) {
    if (!file || !inspection) return;
    setBusy(format === "png" ? "png" : "generate");
    setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("options", JSON.stringify(options(format)));
    try {
      const response = await fetch("/api/generate", {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw await apiError(response);
      const blob = await response.blob();
      const filename =
        response.headers
          .get("Content-Disposition")
          ?.match(/filename="([^"]+)"/)?.[1] || `relatorio.${format}`;
      const url = URL.createObjectURL(blob);
      if (downloadImmediately) {
        download(url, filename);
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      } else {
        clearPreview();
        previewRef.current = url;
        setPreview({ url, filename });
        setStep(4);
      }
    } catch (problem) {
      setError(problem);
    } finally {
      setBusy("");
    }
  }

  function download(url, filename) {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-symbol" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span>
              Gerador de Relatórios <b>SC</b>
            </span>
          </div>
          <div className="header-right">
            <span className="version">VERSÃO 0.1.0</span>
          </div>
        </div>
      </header>

      <main className="workspace">
        <div className="page-intro">
          <div>
            <span className="eyebrow">RELATÓRIOS DE SANTA CATARINA</span>
            <h1>Gerar relatório</h1>
            <p>
              Um caminho claro entre os números da planilha e a figura final.
            </p>
          </div>
          <div className="intro-aside">
            <span className="aside-number">02</span>
            <span>
              formatos de planilha
              <br />
              disponíveis no piloto
            </span>
          </div>
        </div>

        <nav className="stepper" aria-label="Etapas do relatório">
          {["Importar", "Conferir dados", "Montar", "Prévia"].map(
            (label, index) => (
              <button
                key={label}
                type="button"
                className={`step ${step === index + 1 ? "active" : ""} ${step > index + 1 ? "complete" : ""}`}
                disabled={index + 1 > step || (index + 1 > 1 && !inspection)}
                onClick={() => {
                  setError(null);
                  setStep(index + 1);
                }}
              >
                <span>
                  {step > index + 1 ? (
                    <Icon name="check" size={15} />
                  ) : (
                    String(index + 1).padStart(2, "0")
                  )}
                </span>
                {label}
              </button>
            ),
          )}
        </nav>

        <Diagnostics error={error} />

        {step === 1 && (
          <section className="work-card import-layout">
            <div className="section-heading">
              <span className="eyebrow">ETAPA 01 · IMPORTAR</span>
              <h2>Escolha a planilha</h2>
              <p>
                Use um arquivo Excel (.xlsx) ou CSV com os indicadores que
                deseja visualizar.
              </p>
            </div>
            <div
              className="dropzone"
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                inspectFile(event.dataTransfer.files?.[0]);
              }}
              data-dragging={dragging}
            >
              <div className="upload-icon">
                <Icon name="upload" size={30} />
              </div>
              <strong>Arraste o arquivo para cá</strong>
              <span>ou escolha uma planilha no computador</span>
              <button
                className="secondary-button"
                type="button"
                onClick={() => inputRef.current?.click()}
                disabled={!!busy}
              >
                {busy === "inspect" ? "Lendo planilha…" : "Escolher arquivo"}
              </button>
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx,.csv"
                hidden
                onChange={(event) => {
                  const chosen = event.target.files?.[0];
                  event.target.value = "";
                  inspectFile(chosen);
                }}
              />
              <small>Arquivos de até 10 MB · .xlsx ou .csv</small>
            </div>
            <div className="import-note">
              <Icon name="lock" size={17} />
              <p>
                A planilha é enviada ao servidor apenas para gerar o relatório.
                O arquivo temporário é removido após o processamento.
              </p>
            </div>
          </section>
        )}

        {step === 2 && inspection && (
          <section className="work-card">
            <div className="section-heading with-file">
              <div>
                <span className="eyebrow">ETAPA 02 · CONFERIR DADOS</span>
                <h2>Confira o que encontramos</h2>
                <p>A geração usa somente o que você confirmar nesta etapa.</p>
              </div>
              <div className="file-pill">
                <Icon name="file" size={18} />
                <span title={inspection.filename}>{inspection.filename}</span>
                <button
                  type="button"
                  onClick={() => {
                    setStep(1);
                    setInspection(null);
                    setFile(null);
                  }}
                >
                  Trocar
                </button>
              </div>
            </div>
            {inspection.kind === "annual" ? (
              <>
                <div className="recognition-grid">
                  <div>
                    <span>Formato reconhecido</span>
                    <strong>Séries anuais</strong>
                  </div>
                  <div>
                    <span>Abas</span>
                    <strong>{inspection.import.abas.length}</strong>
                  </div>
                  <div>
                    <span>Tabelas encontradas</span>
                    <strong>{tables.length}</strong>
                  </div>
                  <div>
                    <span>Fórmulas no arquivo</span>
                    <strong>{inspection.import.formulas}</strong>
                  </div>
                </div>
                <div className="subheading">
                  <div>
                    <h3>Escolha as tabelas</h3>
                    <p>
                      Cada tabela gera uma página. Selecione uma ou mais para o
                      PDF.
                    </p>
                  </div>
                  <input
                    className="search-input"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Buscar vacina ou aba"
                    aria-label="Buscar tabela"
                  />
                </div>
                <div className="table-list">
                  {tables
                    .filter((table) =>
                      `${table.titulo} ${table.aba}`
                        .toLowerCase()
                        .includes(search.toLowerCase()),
                    )
                    .map((table) => (
                      <label
                        key={table.id}
                        className={`table-row ${!table.valida ? "invalid" : ""}`}
                      >
                        <input
                          type="checkbox"
                          disabled={!table.valida}
                          checked={selectedIds.includes(table.id)}
                          onChange={() => toggleTable(table.id)}
                        />
                        <span className="table-title">
                          <strong>{table.titulo}</strong>
                          <small>
                            {table.aba} · {table.anos[0]}–{table.anos.at(-1)} ·{" "}
                            {table.series.length} séries
                          </small>
                          {!table.valida && (
                            <small className="warn-text">
                              {
                                table.diagnosticos.find(
                                  (item) => item.severity === "error",
                                )?.message
                              }
                            </small>
                          )}
                        </span>
                        {table.mapa_disponivel && (
                          <span className="table-tag">MAPA DISPONÍVEL</span>
                        )}
                      </label>
                    ))}
                </div>
                {!!invalidTables.length && (
                  <label className="exclusion-check">
                    <input
                      type="checkbox"
                      checked={confirmExclusions}
                      onChange={(event) =>
                        setConfirmExclusions(event.target.checked)
                      }
                    />
                    Confirmo que {invalidTables.length} tabela(s) com problema
                    ficarão fora do relatório.
                  </label>
                )}
              </>
            ) : (
              <>
                <div className="recognition-grid">
                  <div>
                    <span>Formato reconhecido</span>
                    <strong>17 Regionais</strong>
                  </div>
                  <div>
                    <span>Aba</span>
                    <strong>{inspection.sheet}</strong>
                  </div>
                  <div>
                    <span>Indicador</span>
                    <strong>{inspection.indicator}</strong>
                  </div>
                  <div>
                    <span>Valor de SC</span>
                    <strong>
                      {inspection.state_value.toLocaleString("pt-BR")}
                    </strong>
                  </div>
                </div>
                <div className="subheading">
                  <div>
                    <h3>Valores reconhecidos</h3>
                    <p>
                      Confira se as Regionais e a taxa correspondem ao seu
                      arquivo.
                    </p>
                  </div>
                </div>
                <div className="regional-grid">
                  {inspection.regions.map((item) => (
                    <div key={item.name}>
                      <span>{item.name}</span>
                      <strong>{item.value.toLocaleString("pt-BR")}</strong>
                    </div>
                  ))}
                </div>
                <p className="hint-line">
                  A planilha não informa o período e a unidade. Você pode
                  preenchê-los na próxima etapa, se souber.
                </p>
              </>
            )}
            <div className="card-actions">
              <button
                className="text-button"
                type="button"
                onClick={() => setStep(1)}
              >
                <Icon name="back" size={17} />
                Voltar
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={
                  inspection.kind === "annual" &&
                  (!selectedIds.length ||
                    (invalidTables.length && !confirmExclusions))
                }
                onClick={() => {
                  setError(null);
                  setStep(3);
                }}
              >
                Continuar
                <Icon name="arrow" size={17} />
              </button>
            </div>
          </section>
        )}

        {step === 3 && inspection && (
          <section className="work-card">
            <div className="section-heading">
              <span className="eyebrow">ETAPA 03 · MONTAR</span>
              <h2>Como você quer mostrar os dados?</h2>
              <p>
                Os modelos disponíveis dependem do formato reconhecido na
                planilha.
              </p>
            </div>
            <div className="model-grid">
              {(inspection.kind === "regional"
                ? ["mapa_regional"]
                : ["paineis", "linhas", "mapa"]
              ).map((value) => (
                <ModelCard
                  key={value}
                  value={value}
                  selected={model === value}
                  disabled={value === "mapa" && !mapReady}
                  onChoose={(value) => {
                    setModel(value);
                    clearPreview();
                  }}
                />
              ))}
            </div>
            {inspection.kind === "annual" && !mapReady && (
              <p className="hint-line">
                O mapa exige uma única tabela com as 8 macrorregiões de saúde de
                SC.
              </p>
            )}
            {inspection.kind === "annual" && (
              <div className="field-section">
                <h3>Anos do relatório</h3>
                <p>Use os anos comuns às tabelas escolhidas.</p>
                <div className="year-chips">
                  {commonYears.map((year) => (
                    <label
                      key={year}
                      className={years.includes(year) ? "checked" : ""}
                    >
                      <input
                        type="checkbox"
                        checked={years.includes(year)}
                        onChange={() => {
                          setYears((current) =>
                            current.includes(year)
                              ? current.filter((item) => item !== year)
                              : [...current, year].sort(),
                          );
                          clearPreview();
                        }}
                      />
                      {year}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="field-section">
              <h3>Informações do relatório</h3>
              <p>
                Esses campos ajudam quem receber o PDF a entender sua origem.
              </p>
              <div className="form-grid">
                <label className="wide">
                  Título{" "}
                  <input
                    value={meta.title}
                    maxLength={120}
                    onChange={(event) =>
                      updateMeta("title", event.target.value)
                    }
                    placeholder="Título da figura ou relatório"
                  />
                </label>
                <label>
                  Autores{" "}
                  <input
                    value={meta.authors}
                    maxLength={180}
                    onChange={(event) =>
                      updateMeta("authors", event.target.value)
                    }
                    placeholder="Quem elaborou o relatório"
                  />
                </label>
                <label>
                  Fonte dos dados{" "}
                  <input
                    value={meta.source}
                    maxLength={180}
                    onChange={(event) =>
                      updateMeta("source", event.target.value)
                    }
                    placeholder="Ex.: planilha da pesquisa"
                  />
                </label>
                {inspection.kind === "regional" && (
                  <>
                    <label>
                      Unidade{" "}
                      <input
                        value={meta.unit}
                        maxLength={80}
                        onChange={(event) =>
                          updateMeta("unit", event.target.value)
                        }
                        placeholder="Ex.: por 1.000 habitantes"
                      />
                    </label>
                    <label>
                      Período{" "}
                      <input
                        value={meta.period}
                        maxLength={80}
                        onChange={(event) =>
                          updateMeta("period", event.target.value)
                        }
                        placeholder="Ex.: 2025"
                      />
                    </label>
                  </>
                )}
              </div>
            </div>
            <div className="card-actions">
              <button
                className="text-button"
                type="button"
                onClick={() => setStep(2)}
              >
                <Icon name="back" size={17} />
                Voltar
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={
                  !!busy ||
                  !meta.title.trim() ||
                  (inspection.kind === "annual" &&
                    (!selectedIds.length || !years.length))
                }
                onClick={() => generate()}
              >
                {busy === "generate" ? "Gerando relatório…" : "Gerar prévia"}
                <Icon name="arrow" size={17} />
              </button>
            </div>
          </section>
        )}

        {step === 4 && preview && (
          <section className="work-card">
            <div className="section-heading">
              <span className="eyebrow">ETAPA 04 · PRÉVIA</span>
              <h2>Revise o resultado</h2>
              <p>
                Confira o título, as regiões e a legenda antes de compartilhar.
              </p>
            </div>
            <div className="preview-frame">
              <iframe title="Prévia do relatório em PDF" src={preview.url} />
            </div>
            <div className="card-actions">
              <button
                className="text-button"
                type="button"
                onClick={() => setStep(3)}
              >
                <Icon name="back" size={17} />
                Ajustar relatório
              </button>
              <div className="download-actions">
                {inspection.kind === "regional" && (
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={!!busy}
                    onClick={() => generate("png", true)}
                  >
                    {busy === "png" ? "Gerando PNG…" : "Baixar PNG"}
                  </button>
                )}
                <button
                  className="primary-button"
                  type="button"
                  onClick={() => download(preview.url, preview.filename)}
                >
                  <Icon name="download" size={18} />
                  Baixar PDF
                </button>
              </div>
            </div>
          </section>
        )}

        <footer className="site-footer">
          <span>Gerador de Relatórios SC · versão piloto</span>
          <span>
            Gráficos produzidos em Python a partir dos dados confirmados.
          </span>
        </footer>
      </main>
    </div>
  );
}
