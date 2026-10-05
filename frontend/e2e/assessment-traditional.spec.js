import { expect, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const pythonPath = fileURLToPath(
  new URL("../../.venv/bin/python", import.meta.url),
);

function traditionalAssessmentXlsx() {
  const python = `
import base64, io, sys
from openpyxl import Workbook

counts = [20, 19, 19, 17, 17, 17, 17, 17, 17, 17, 17, 17]
workbook = Workbook()
sheet = workbook.active
sheet.title = "Avaliacoes"
sheet.append(["Avaliação diagnóstica"])
sheet.append([])
sheet.append(["Questão", "Respostas", "Acertos", "Erros", "% Acerto", "% Erro"])
for number, correct in enumerate(counts, start=1):
    sheet.append([number, 20, correct, 20 - correct, None, None])
sheet.append(["TOTAL", 240, 211, 29, None, None])
buffer = io.BytesIO()
workbook.save(buffer)
sys.stdout.write(base64.b64encode(buffer.getvalue()).decode("ascii"))
`;
  const result = spawnSync(pythonPath, ["-c", python], { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(
      `Não foi possível montar a planilha sintética: ${result.stderr}`,
    );
  }
  return Buffer.from(result.stdout, "base64");
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

test("importa avaliação única tradicional, confere contagens e baixa o PDF", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "avaliacao_tradicional.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: traditionalAssessmentXlsx(),
  });

  await expect(
    page.getByRole("heading", { name: "Confira o que encontramos" }),
  ).toBeVisible();
  await expect(
    page.getByText("Avaliação única · 12 questões · 20 respostas por questão"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "211 acertos · 29 erros · 240 respostas no total · 87,92% de acertos",
    ),
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
  const previewPdf = Buffer.from(previewBase64, "base64");
  const previewPages = extractPdfPages(previewPdf);
  expect(previewPages).toHaveLength(2);
  expect(previewPages.join("\n")).toContain("Avaliação única");
  expect(previewPages.join("\n")).toContain("12 questões");
  expect(previewPages.join("\n")).toContain("87,92%");
  expect(previewPages.join("\n")).toContain("20/20");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Baixar PDF" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  const downloadedPdf = await collectDownload(download);
  expect(downloadedPdf.equals(previewPdf)).toBe(true);
  expect(extractPdfPages(downloadedPdf)).toEqual(previewPages);
});
