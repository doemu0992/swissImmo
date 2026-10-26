import { test, expect, Page } from '@playwright/test';
import { assistentAbsenden, goto, imAssistent, login } from './helpers';

// Bausteine V11 (UI-Analyse 26.10.2026): Assistent, In-App-Hilfe, Prozessleiste.
// Am Desktop UND am Telefon — eine Schrittleiste, die nur bei 1440 Pixel passt,
// ist am Telefon kaputt.
const BREITEN = [
  { name: 'Desktop', viewport: { width: 1440, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Person erfassen: Schritt für Schritt, Pflichtfeld hält an, Prüfen zeigt die Angaben', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/personen/neu/');
      const assistent = page.locator('.fw-assistent.an');
      await expect(assistent, 'Der Assistent ist nicht aktiv').toBeVisible();
      await expect(page.locator('[data-assistent-absenden]')).toBeHidden();
      await keinQuerscrollen(page);

      // Ohne Nachname geht es nicht weiter.
      await page.locator('[data-assistent-weiter]:visible').click();
      await expect(page.locator('input[name="nachname"]')).toBeVisible();
      await expect(page.locator('input[name="email"]')).toBeHidden();
      expect(await page.locator('input[name="nachname"]').evaluate((f: HTMLInputElement) => f.validity.valid)).toBe(false);

      const name = `Schritt${Date.now() % 100000}`;
      await page.fill('input[name="vorname"]', 'Ada');
      await page.fill('input[name="nachname"]', name);
      await (await imAssistent(page, 'input[name="ort"]')).fill('Bern');
      await page.fill('input[name="plz"]', '3011');

      // Prüfen fasst zusammen, bevor gespeichert wird.
      await imAssistent(page, '[data-assistent-absenden]');
      await expect(page.locator('.fw-assistent-pruefen')).toContainText(name);
      await expect(page.locator('.fw-assistent-pruefen')).toContainText('Bern');
      await keinQuerscrollen(page);
      await assistentAbsenden(page);
      await page.waitForURL(/\/neu\/personen\/\d+\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('main').getByText(name).first()).toBeVisible();
    });

    test('Zurück behält die Eingaben', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/liegenschaften/neu/');
      await page.fill('input[name="strasse"]', 'Rückweg 3');
      await page.fill('input[name="plz"]', '8000');
      await page.fill('input[name="ort"]', 'Zürich');
      await imAssistent(page, 'select[name="status"]');
      await page.locator('[data-assistent-zurueck]:visible').click();
      await expect(page.locator('input[name="strasse"]')).toHaveValue('Rückweg 3');
    });

    test('Hilfe: das ⓘ öffnet eine Erklärung, Escape schliesst sie', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/mahnwesen/');
      const knopf = page.locator('.fw-hilfe-knopf:visible').first();
      await knopf.click();
      const blase = page.locator('#fwHilfeBlase');
      await expect(blase).toBeVisible();
      await expect(knopf).toHaveAttribute('aria-expanded', 'true');
      const kasten = await blase.boundingBox();
      expect(kasten!.x).toBeGreaterThanOrEqual(0);
      expect(kasten!.x + kasten!.width).toBeLessThanOrEqual(b.viewport.width);
      await page.keyboard.press('Escape');
      await expect(blase).toBeHidden();
    });

    test('Nebenkosten: Prozessleiste mit aktuellem Schritt, Periode per Schnellwahl', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByRole('button', { name: /Periode anlegen/ }).click();
      await page.locator('[data-nk-schnell] [data-von]').first().click();
      await expect(page.locator('input[name="start_datum"]')).not.toHaveValue('');
      await expect(page.locator('input[name="ende_datum"]')).not.toHaveValue('');
      await expect(page.locator('input[name="bezeichnung"]')).not.toHaveValue('');

      await page.getByText('NK E2E 2024').first().click();
      await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
      const leiste = page.locator('.fw-prozess');
      await expect(leiste).toBeVisible();
      await expect(leiste.locator('li')).toHaveCount(7);
      const hier = leiste.locator('li.hier');
      await expect(hier).toHaveCount(1);
      await expect(hier).toBeInViewport();
      await keinQuerscrollen(page);
    });
  });
}
