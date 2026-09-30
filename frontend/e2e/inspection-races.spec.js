import { expect, test } from "@playwright/test";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtures = join(projectRoot, "tests", "fixtures");
const scenarios = [
  {
    name: "anual para anual",
    first: "dados_ficticios_variacao_01.xlsx",
    second: "dados_ficticios_variacao_02.xlsx",
  },
  {
    name: "regional para regional",
    first: "taxa_sc_macrorregioes_FICTICIA.csv",
    second: "regionais_sc_parcial_FICTICIA.csv",
  },
  {
    name: "anual para regional",
    first: "dados_ficticios_variacao_01.xlsx",
    second: "regionais_sc_parcial_FICTICIA.csv",
  },
];

async function installResponseGates(page) {
  await page.addInitScript(() => {
    window.__responseGates = [];
    const originalFetch = window.fetch.bind(window);
    window.__registerResponseGate = (pathname, id) => {
      let release;
      const wait = new Promise((resolve) => {
        release = resolve;
      });
      window.__responseGates.push({
        pathname,
        id,
        captured: false,
        delivered: false,
        wait,
        release,
      });
    };
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      const requestUrl = typeof args[0] === "string" ? args[0] : args[0].url;
      const pathname = new URL(requestUrl, window.location.href).pathname;
      const gate = window.__responseGates.find(
        (candidate) => candidate.pathname === pathname && !candidate.captured,
      );
      if (gate) {
        gate.captured = true;
        await gate.wait;
        gate.delivered = true;
      }
      return response;
    };
  });
}

async function holdNextResponse(page, pathname, id) {
  await page.evaluate(
    ({ path, gateId }) => window.__registerResponseGate(path, gateId),
    { path: pathname, gateId: id },
  );
}

async function waitForCapturedResponse(page, pathname, id) {
  await page.waitForFunction(
    ({ path, gateId }) =>
      window.__responseGates.some(
        (gate) => gate.pathname === path && gate.id === gateId && gate.captured,
      ),
    { path: pathname, gateId: id },
  );
}

async function releaseResponse(page, pathname, id) {
  const released = await page.evaluate(
    ({ path, gateId }) => {
      const gate = window.__responseGates.find(
        (candidate) =>
          candidate.pathname === path &&
          candidate.id === gateId &&
          candidate.captured,
      );
      if (!gate) return false;
      gate.release();
      return true;
    },
    { path: pathname, gateId: id },
  );
  if (!released) return;
  await page.waitForFunction(
    ({ path, gateId }) =>
      window.__responseGates.some(
        (gate) =>
          gate.pathname === path && gate.id === gateId && gate.delivered,
      ),
    { path: pathname, gateId: id },
  );
}

async function installBlobConversionGateAndUrlSpies(page) {
  await page.addInitScript(() => {
    window.__blobConversionGates = [];
    window.__urlObjectCalls = { created: [], revoked: [] };

    const originalBlob = Response.prototype.blob;
    Response.prototype.blob = function (...args) {
      const pathname = this.url
        ? new URL(this.url, window.location.href).pathname
        : "";
      const gate = window.__blobConversionGates.find(
        (candidate) => candidate.pathname === pathname && !candidate.captured,
      );
      if (!gate) return originalBlob.apply(this, args);

      gate.captured = true;
      return originalBlob.apply(this, args).then((blob) => {
        gate.blobReady = true;
        return gate.wait.then(() => {
          gate.delivered = true;
          return blob;
        });
      });
    };

    const originalCreateObjectURL = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (...args) => {
      const url = originalCreateObjectURL(...args);
      window.__urlObjectCalls.created.push(url);
      return url;
    };

    const originalRevokeObjectURL = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = (url) => {
      window.__urlObjectCalls.revoked.push(url);
      return originalRevokeObjectURL(url);
    };
  });
}

async function holdNextBlobConversion(page, id) {
  await page.evaluate((gateId) => {
    let release;
    const wait = new Promise((resolve) => {
      release = resolve;
    });
    window.__blobConversionGates.push({
      pathname: "/api/generate",
      id: gateId,
      captured: false,
      blobReady: false,
      delivered: false,
      wait,
      release,
    });
  }, id);
}

async function waitForBlobConversionReady(page, id) {
  await page.waitForFunction(
    (gateId) =>
      window.__blobConversionGates.some(
        (gate) => gate.id === gateId && gate.captured && gate.blobReady,
      ),
    id,
  );
}

async function releaseBlobConversion(page, id) {
  const released = await page.evaluate((gateId) => {
    const gate = window.__blobConversionGates.find(
      (candidate) => candidate.id === gateId && candidate.captured,
    );
    if (!gate) return false;
    gate.release();
    return true;
  }, id);
  if (!released) return;
  await page.waitForFunction(
    (gateId) =>
      window.__blobConversionGates.some(
        (gate) => gate.id === gateId && gate.delivered,
      ),
    id,
  );
}

for (const scenario of scenarios) {
  test(`a inspeção mais recente vence: ${scenario.name}`, async ({ page }) => {
    const secondName = basename(scenario.second);
    await installResponseGates(page);

    try {
      await page.goto("/");
      await holdNextResponse(page, "/api/inspect", "inspect-A");
      const upload = page.locator('input[type="file"]');
      await upload.setInputFiles(join(fixtures, scenario.first));
      await waitForCapturedResponse(page, "/api/inspect", "inspect-A");

      await expect(page.locator(".dropzone .secondary-button")).toBeEnabled();
      await holdNextResponse(page, "/api/inspect", "inspect-B");
      await upload.setInputFiles(join(fixtures, scenario.second));
      await waitForCapturedResponse(page, "/api/inspect", "inspect-B");

      await releaseResponse(page, "/api/inspect", "inspect-B");
      await expect(
        page.getByRole("heading", { name: "Confira o que encontramos" }),
      ).toBeVisible();
      await expect(page.locator(".file-pill")).toContainText(secondName);
      await expect(page.locator(".dropzone")).toHaveCount(0);

      await releaseResponse(page, "/api/inspect", "inspect-A");
      await expect(
        page.getByRole("heading", { name: "Confira o que encontramos" }),
      ).toBeVisible();
      await expect(page.locator(".file-pill")).toContainText(secondName);
      await expect(page.locator(".dropzone")).toHaveCount(0);
      await expect(page.getByText("Lendo planilha…")).toHaveCount(0);
    } finally {
      await releaseResponse(page, "/api/inspect", "inspect-A").catch(() => {});
      await releaseResponse(page, "/api/inspect", "inspect-B").catch(() => {});
    }
  });
}

test("o erro de uma inspeção antiga não substitui a leitura em andamento", async ({
  page,
}) => {
  await installResponseGates(page);
  let inspectionCount = 0;
  await page.route("**/api/inspect", (route) => {
    inspectionCount += 1;
    if (inspectionCount === 1) {
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Erro da planilha antiga" }),
      });
    }
    return route.continue();
  });

  try {
    await page.goto("/");
    await holdNextResponse(page, "/api/inspect", "inspect-error");
    const upload = page.locator('input[type="file"]');
    await upload.setInputFiles(
      join(fixtures, "dados_ficticios_variacao_01.xlsx"),
    );
    await waitForCapturedResponse(page, "/api/inspect", "inspect-error");

    await holdNextResponse(page, "/api/inspect", "inspect-current");
    await upload.setInputFiles(
      join(fixtures, "taxa_sc_macrorregioes_FICTICIA.csv"),
    );
    await waitForCapturedResponse(page, "/api/inspect", "inspect-current");

    await releaseResponse(page, "/api/inspect", "inspect-current");
    await expect(
      page.getByRole("heading", { name: "Confira o que encontramos" }),
    ).toBeVisible();
    await expect(page.locator(".file-pill")).toContainText(
      "taxa_sc_macrorregioes_FICTICIA.csv",
    );

    await releaseResponse(page, "/api/inspect", "inspect-error");
    await expect(page.getByText("Erro da planilha antiga")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Confira o que encontramos" }),
    ).toBeVisible();
    await expect(page.locator(".file-pill")).toContainText(
      "taxa_sc_macrorregioes_FICTICIA.csv",
    );
  } finally {
    await releaseResponse(page, "/api/inspect", "inspect-error").catch(
      () => {},
    );
    await releaseResponse(page, "/api/inspect", "inspect-current").catch(
      () => {},
    );
  }
});

test("a geração antiga não substitui o arquivo inspecionado depois", async ({
  page,
}) => {
  await installResponseGates(page);

  try {
    await page.goto("/");
    await holdNextResponse(page, "/api/generate", "generate-old");
    await page
      .locator('input[type="file"]')
      .setInputFiles(join(fixtures, "dados_ficticios_variacao_01.xlsx"));
    await page.getByRole("button", { name: "Continuar" }).click();
    await page.getByRole("button", { name: "Gerar prévia" }).click();
    await waitForCapturedResponse(page, "/api/generate", "generate-old");

    await page.getByRole("button", { name: "Importar" }).click();
    await page
      .locator('input[type="file"]')
      .setInputFiles(join(fixtures, "dados_ficticios_variacao_02.xlsx"));
    await expect(
      page.getByRole("heading", { name: "Confira o que encontramos" }),
    ).toBeVisible();
    await expect(page.locator(".file-pill")).toContainText(
      "dados_ficticios_variacao_02.xlsx",
    );

    await releaseResponse(page, "/api/generate", "generate-old");
    await expect(
      page.getByRole("heading", { name: "Revise o resultado" }),
    ).toHaveCount(0);
    await expect(page.locator(".file-pill")).toContainText(
      "dados_ficticios_variacao_02.xlsx",
    );
  } finally {
    await releaseResponse(page, "/api/generate", "generate-old").catch(
      () => {},
    );
  }
});

test("um erro de geração obsoleto não apaga o estado atual", async ({
  page,
}) => {
  await installResponseGates(page);

  await page.route("**/api/generate", (route) => {
    return route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Erro antigo" }),
    });
  });

  try {
    await page.goto("/");
    await holdNextResponse(page, "/api/generate", "generate-error");
    await page
      .locator('input[type="file"]')
      .setInputFiles(join(fixtures, "dados_ficticios_variacao_01.xlsx"));
    await page.getByRole("button", { name: "Continuar" }).click();
    await page.getByRole("button", { name: "Gerar prévia" }).click();
    await waitForCapturedResponse(page, "/api/generate", "generate-error");

    await page.getByLabel("Título").fill("Título atualizado durante geração");
    await releaseResponse(page, "/api/generate", "generate-error");
    await expect(page.getByText("Erro antigo")).toHaveCount(0);

    await expect(page.getByLabel("Título")).toHaveValue(
      "Título atualizado durante geração",
    );
    await expect(
      page.getByRole("button", { name: "Gerar prévia" }),
    ).toBeEnabled();
  } finally {
    await releaseResponse(page, "/api/generate", "generate-error").catch(
      () => {},
    );
  }
});

test("uma geração que fica obsoleta durante Blob não cria prévia nem limpa a próxima carga", async ({
  page,
}) => {
  await installResponseGates(page);
  await installBlobConversionGateAndUrlSpies(page);

  try {
    await page.goto("/");
    await holdNextBlobConversion(page, "generate-old-blob");
    await page
      .locator('input[type="file"]')
      .setInputFiles(join(fixtures, "dados_ficticios_variacao_01.xlsx"));
    await page.getByRole("button", { name: "Continuar" }).click();
    const generateButton = page.locator(".card-actions .primary-button");
    await generateButton.click();
    await waitForBlobConversionReady(page, "generate-old-blob");
    await expect(generateButton).toHaveText("Gerando relatório…");

    await page.getByLabel("Título").fill("Título da geração atualizada");
    await expect(page.getByLabel("Título")).toHaveValue(
      "Título da geração atualizada",
    );
    await expect(generateButton).toHaveText("Gerar prévia");

    await holdNextResponse(page, "/api/generate", "generate-current");
    await generateButton.click();
    await waitForCapturedResponse(page, "/api/generate", "generate-current");
    await expect(generateButton).toHaveText("Gerando relatório…");

    await releaseBlobConversion(page, "generate-old-blob");
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );

    await expect(generateButton).toHaveText("Gerando relatório…");
    await expect(
      page.getByRole("heading", { name: "Revise o resultado" }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Título")).toHaveValue(
      "Título da geração atualizada",
    );
    expect(await page.evaluate(() => window.__urlObjectCalls)).toEqual({
      created: [],
      revoked: [],
    });

    await releaseResponse(page, "/api/generate", "generate-current");
    await expect(
      page.getByRole("heading", { name: "Revise o resultado" }),
    ).toBeVisible();
    const urlCalls = await page.evaluate(() => window.__urlObjectCalls);
    expect(urlCalls.created).toHaveLength(1);
    expect(urlCalls.revoked).toHaveLength(0);
  } finally {
    await releaseBlobConversion(page, "generate-old-blob").catch(() => {});
    await releaseResponse(page, "/api/generate", "generate-current").catch(
      () => {},
    );
  }
});

test("a etapa de conferência não transborda em uma tela de 320 px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/");
  await page
    .locator('input[type="file"]')
    .setInputFiles(join(fixtures, "regionais_sc_parcial_FICTICIA.csv"));

  await expect(
    page.getByRole("heading", { name: "Confira o que encontramos" }),
  ).toBeVisible();
  const widths = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));

  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  await expect(page.locator(".recognition-grid strong").first()).toBeVisible();
});
