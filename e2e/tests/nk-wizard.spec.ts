import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// Nebenkosten-Wizard (Modul 1, 27.10.2026): durch die sechs Schritte klicken, ohne etwas
// auszuführen (kein Speichern, kein Verbuchen). Gegen die Seed-Periode «NK E2E 2024»
// (seed_e2e: eine Einheit ohne Fläche → Schritt 1 meldet sie).
// Am Telefon scrollt der Stepper waagrecht, die Seite selbst nie.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

const SCHRITTE = [
  { titel: 'Periode & Objekte', text: /Für welchen Zeitraum wird abgerechnet/ },
  { titel: 'Kosten', text: /Welche Kosten gehören in diese Abrechnung/ },
  { titel: 'Verteilung', text: /Wie wird jede Kostenart verteilt/ },
  { titel: 'Heizung & Zähler', text: /Wie werden die Heizkosten geteilt/ },
  { titel: 'Prüfen', text: /Geht die Abrechnung auf/ },
  { titel: 'Verbuchen & Zustellen', text: /Verbuchen stellt Nachzahlungen und Guthaben/ },
];

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Durch die sechs Schritte, oben steht was fehlt', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByText('NK E2E 2024').first().click();
      await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
      const leiste = page.locator('.fw-nkw-leiste');
      await expect(leiste.locator('li')).toHaveCount(6);

      // Schritt 1 direkt: die flächenlose Einheit steht unter «Was fehlt» und als Kachel.
      await leiste.getByRole('link', { name: /Periode & Objekte/ }).click();
      await page.waitForURL(/\/periode\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('.fw-nkw-fehlt')).toContainText('Keller E2E');
      await expect(page.locator('form.fw-kachel').filter({ hasText: 'Keller E2E' })).toBeVisible();
      await keinQuerscrollen(page);

      // Mit «Weiter» durch alle Schritte.
      for (let i = 0; i < SCHRITTE.length; i++) {
        const s = SCHRITTE[i];
        await expect(page.locator('.fw-nkw-kopf h2')).toHaveText(s.titel);
        await expect(page.locator('.fw-nkw-kopf')).toContainText(s.text);
        await expect(leiste.locator('li.an')).toHaveCount(1);
        await expect(leiste.locator('li.an')).toBeInViewport();
        await keinQuerscrollen(page);
        if (i < SCHRITTE.length - 1) {
          await page.locator('.fw-assistent-fuss a.fw-primary').click();
          await page.waitForLoadState('domcontentloaded');
        }
      }
      // Verbuchen bleibt ungeklickt; der Versand steht erst nach dem Verbuchen bereit.
      await expect(page.getByRole('button', { name: 'Verbuchen' })).toBeVisible();
      await expect(page.getByRole('button', { name: /PDF erstellen/ })).toHaveCount(0);
    });

    test('Neue Periode: Schritt 1 als Seite, höchstens 12 Monate', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByRole('link', { name: /Periode anlegen/ }).first().click();
      await page.waitForURL(/\/nebenkosten\/neu\//, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('input[name="start_datum"]')).toBeVisible();
      await page.locator('[data-nk-schnell] [data-von="heiz"]').click();
      await expect(page.locator('input[name="bezeichnung"]')).toHaveValue(/Heizperiode/);
      await keinQuerscrollen(page);
    });

    test('Heizung: Zählerstände und CSV-Import öffnen sich, ohne etwas zu speichern', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByText('NK E2E 2024').first().click();
      await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
      await page.locator('.fw-nkw-leiste').getByRole('link', { name: /Heizung & Zähler/ }).click();
      await page.waitForURL(/\/heizung\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('input[name="hkvo_grundkosten_prozent"]')).toBeVisible();
      await expect(page.getByText(/Kantonale Vorgabe prüfen/)).toBeVisible();
      await page.getByRole('link', { name: /CSV einlesen/ }).click();
      await page.waitForURL(/\/import\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('input[type="file"][name="datei"]')).toBeVisible();
      await keinQuerscrollen(page);
    });
  });
}
