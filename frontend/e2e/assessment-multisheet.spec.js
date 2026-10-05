import { expect, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const pythonPath = fileURLToPath(
  new URL("../../.venv/bin/python", import.meta.url),
);

function workbookFromPython(python, args = []) {
  const result = spawnSync(pythonPath, ["-c", python, ...args], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(
      `Não foi possível montar a planilha sintética: ${result.stderr}`,
    );
  }
  return Buffer.from(result.stdout, "base64");
}

function multiSheetAssessmentXlsx(includeAlternative = false) {
  const python = `
import base64, io, sys
from openpyxl import Workbook

workbook = Workbook()
workbook.remove(workbook.active)
base_rows = [
    (101, "A", 1, 21, 3), (102, "A", 2, 24, 0), (103, "A", 3, 20, 4),
    (104, "A", 4, 18, 6), (105, "A", 5, 23, 1), (106, "A", 6, 19, 5),
    (107, "A", 7, 22, 2), (201, "B", 1, 13, 2), (202, "B", 2, 15, 0),
    (203, "B", 3, 12, 3), (204, "B", 4, 14, 1), (205, "B", 5, 9, 6),
    (206, "B", 6, 15, 0), (207, "B", 7, 11, 4), (208, "B", 8, 14, 1),
]
def add_base(name, rows):
    sheet = workbook.create_sheet(name)
    sheet.append(["ID", "Prova", "Pergunta", "Corretas", "Incorretas"])
    for row in rows:
        sheet.append(row)
add_base("Base", base_rows)
if sys.argv[1] == "true":
    add_base("OutraBase", [(901, "C", 1, 8, 2), (902, "C", 2, 7, 3)])
summary = workbook.create_sheet("Resumo")
summary.append(["Resumo geral das provas"])
summary.append(["Avaliação", "Acertos", "Erros", "Percentual"])
summary.append(["Prova A", 147, 21, 0.875])
summary.append(["Prova B", 103, 17, 0.8583333333333333])
summary.append(["Observação", "Valor", "Tipo"])
summary.append(["Participantes", 24, "número"])
buffer = io.BytesIO()
workbook.save(buffer)
sys.stdout.write(base64.b64encode(buffer.getvalue()).decode("ascii"))
`;
  return workbookFromPython(python, [String(includeAlternative)]);
}

function sideBySideAssessmentXlsx(separatorValue = "") {
  const python = `
import base64, io, sys
from openpyxl import Workbook

workbook = Workbook()
sheet = workbook.active
sheet.title = "Comparativo"
sheet.append([])
sheet.append([None, "COMPARATIVO FICTÍCIO"])
sheet.append([])
sheet.append([None, "ITEM", "ERROS", "ACERTOS", "TOTAL", None, "ITEM", "TOTAL", "ACERTOS", "ERROS"])
left = [
    ("Q1", 2, 14, 16), ("Q2", 1, 15, 16), ("Q3", 3, 13, 16),
    ("Q4", 0, 16, 16), ("Q5", 4, 12, 16), ("Q6", 1, 15, 16),
    ("Q7", 5, 11, 16), ("Q8", 0, 16, 16), ("Q9", 2, 14, 16),
    ("Q10", 3, 13, 16),
]
right = [
    ("Questão 1", 12, 10, 2), ("Questão 2", 12, 12, 0),
    ("Questão 3", 12, 11, 1), ("Questão 4", 12, 9, 3),
    ("Questão 5", 12, 12, 0), ("Questão 6", 12, 8, 4),
    ("Questão 7", 12, 11, 1), ("Questão 8", 12, 12, 0),
    ("Questão 9", 12, 10, 2),
]
for index in range(max(len(left), len(right))):
    left_row = left[index] if index < len(left) else (None,) * 4
    right_row = right[index] if index < len(right) else (None,) * 4
    sheet.append([None, *left_row, None, *right_row])
sheet.append([])
sheet.append([None, None, None, None, None, None, "TOTAL", 108, 95, 13])
sheet.append([None, "Resumo", 21, 139, 160])
sheet.append([None, "Indicador", "Valor"])
sheet.append([None, "Taxa de acerto A", 0.86875])
sheet.append([None, "Taxa de acerto B", 0.8796296296296297])
if len(sys.argv) > 1 and sys.argv[1]:
    sheet["F5"] = sys.argv[1]
buffer = io.BytesIO()
workbook.save(buffer)
sys.stdout.write(base64.b64encode(buffer.getvalue()).decode("ascii"))
`;
  return workbookFromPython(python, separatorValue ? [separatorValue] : []);
}

function extractPdfPages(pdf) {
  const python = `
import base64, io, json, sys
from pypdf import PdfReader

pdf = base64.b64decode(sys.stdin.read())
reader = PdfReader(io.BytesIO(pdf))
print(json.dumps([page.extract_text() or "" for page in reader.pages]))
`;
  const result = spawnSync(pythonPath, ["-c", python], {
    encoding: "utf8",
    input: pdf.toString("base64"),
  });
  if (result.status !== 0) {
    throw new Error(`Não foi possível ler o PDF gerado: ${result.stderr}`);
  }
  return JSON.parse(result.stdout);
}

async function collectDownload(download) {
  const stream = await download.createReadStream();
  if (!stream) throw new Error("O fluxo do download não ficou disponível.");
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks);
}

async function importWorkbook(page, includeAlternative = false) {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "provas_multiplas_abas.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: multiSheetAssessmentXlsx(includeAlternative),
  });
}

test("confere Base e Resumo e gera PDF com as provas separadas", async ({
  page,
}) => {
  await importWorkbook(page);

  await expect(
    page.getByRole("heading", { name: "Confira o que encontramos" }),
  ).toBeVisible();
  await expect(
    page.getByText("Prova A · 7 questões · 24 respostas por questão"),
  ).toBeVisible();
  await expect(
    page.getByText("Prova B · 8 questões · 15 respostas por questão"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "147 acertos · 21 erros · 168 respostas no total · 87,5% de acertos",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "103 acertos · 17 erros · 120 respostas no total · 85,83% de acertos",
    ),
  ).toBeVisible();
  await expect(page.getByText(/Participantes/)).toHaveCount(0);

  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByRole("button", { name: "Gerar prévia" }).click();
  await expect(
    page.getByRole("heading", { name: "Revise o resultado" }),
  ).toBeVisible();
  const preview = page.getByTitle("Prévia do relatório em PDF");
  await expect(preview).toBeVisible();
  const previewBase64 = await preview.evaluate(async (frame) => {
    const response = await fetch(frame.src);
    const bytes = new Uint8Array(await response.arrayBuffer());
    return btoa(
      Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""),
    );
  });
  const previewPdf = Buffer.from(previewBase64, "base64");
  const previewPages = extractPdfPages(previewPdf);
  const previewText = previewPages.join("\n");
  expect(previewPages).toHaveLength(4);
  expect(previewText).toContain("Prova A");
  expect(previewText).toContain("Prova B");
  expect(previewText).toContain("87,50%");
  expect(previewText).toContain("85,83%");
  expect(previewText).toContain("15 respostas por questão");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Baixar PDF" }).click();
  const download = await downloadPromise;
  const downloadedPdf = await collectDownload(download);
  expect(downloadedPdf.equals(previewPdf)).toBe(true);
  expect(extractPdfPages(downloadedPdf)).toEqual(previewPages);
});

test("confere os blocos laterais com rótulos neutros e exporta o mesmo PDF", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "comparativo.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: sideBySideAssessmentXlsx(),
  });

  await expect(
    page.getByRole("heading", { name: "Confira o que encontramos" }),
  ).toBeVisible();
  await expect(
    page.getByText("Bloco esquerdo · 10 questões · 16 respostas por questão"),
  ).toBeVisible();
  await expect(
    page.getByText("Bloco direito · 9 questões · 12 respostas por questão"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "139 acertos · 21 erros · 160 respostas no total · 86,88% de acertos",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "95 acertos · 13 erros · 108 respostas no total · 87,96% de acertos",
    ),
  ).toBeVisible();
  await expect(page.getByText(/Avaliação A|Avaliação B/)).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText(
    "números iguais não comprovam",
  );

  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByRole("button", { name: "Gerar prévia" }).click();
  await expect(
    page.getByRole("heading", { name: "Revise o resultado" }),
  ).toBeVisible();
  const preview = page.getByTitle("Prévia do relatório em PDF");
  await expect(preview).toBeVisible();
  const previewBase64 = await preview.evaluate(async (frame) => {
    const response = await fetch(frame.src);
    const bytes = new Uint8Array(await response.arrayBuffer());
    return btoa(
      Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""),
    );
  });
  const previewPdf = Buffer.from(previewBase64, "base64");
  const previewPages = extractPdfPages(previewPdf);
  const previewText = previewPages.join("\n");
  expect(previewPages).toHaveLength(4);
  expect(previewText).toContain("Bloco esquerdo");
  expect(previewText).toContain("Bloco direito");
  expect(previewText).toContain("86,88%");
  expect(previewText).toContain("87,96%");
  expect(previewText).toContain("16 respostas por questão");
  expect(previewText).toContain("12 respostas por questão");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Baixar PDF" }).click();
  const download = await downloadPromise;
  const downloadedPdf = await collectDownload(download);
  expect(downloadedPdf.equals(previewPdf)).toBe(true);
  expect(extractPdfPages(downloadedPdf)).toEqual(previewPages);
});

test("mostra erro quando há dados na coluna entre os blocos", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "comparativo_com_dado_na_separacao.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: sideBySideAssessmentXlsx("0"),
  });

  await expect(page.locator('.error-panel[role="alert"]')).toContainText(
    "coluna separadora entre os blocos deve permanecer vazia",
  );
  await expect(
    page.getByRole("heading", { name: "Confira o que encontramos" }),
  ).toHaveCount(0);
});

test("permite escolher uma aba quando há duas bases válidas", async ({
  page,
}) => {
  await importWorkbook(page, true);

  await expect(
    page.getByRole("heading", { name: "Escolha a aba ou o bloco detalhado" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /OutraBase · cabeçalho na linha 1/ })
    .click();

  await expect(
    page.getByText("Prova C · 2 questões · 10 respostas por questão"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByRole("button", { name: "Gerar prévia" }).click();
  await expect(
    page.getByRole("heading", { name: "Revise o resultado" }),
  ).toBeVisible();
  const preview = page.getByTitle("Prévia do relatório em PDF");
  await expect(preview).toBeVisible();
  const previewBase64 = await preview.evaluate(async (frame) => {
    const response = await fetch(frame.src);
    const bytes = new Uint8Array(await response.arrayBuffer());
    return btoa(
      Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""),
    );
  });
  const previewPages = extractPdfPages(Buffer.from(previewBase64, "base64"));
  expect(previewPages.join("\n")).toContain("Prova C");
  expect(previewPages.join("\n")).toContain("15 acertos");
});
