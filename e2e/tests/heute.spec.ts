import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// «Heute» nach der Dashboard-Reduktion (26.10.2026): höchstens vier
// Aufgabenkacheln, die erste im Ember-Akzent, der Schwerpunkt im Kopf
// umschaltbar — am Desktop und am Telefon, ohne Querscrollen.
const BREITEN = [
  { name: 'Desktop', viewport: { width: 1440, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

async function schwerpunkt(page: Page, name: RegExp) {
  await page.locator('.fw-schwerpunkt > summary').click();
  const knopf = page.locator('.fw-schwerpunkt-wahl button', { hasText: name });
  await expect(knopf).toBeVisible();
  const box = (await knopf.boundingBox())!;
  const breite = page.viewportSize()!.width;
  expect(box.x, 'Die Auswahl ragt links aus dem Bild').toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, 'Die Auswahl ragt rechts aus dem Bild').toBeLessThanOrEqual(breite);
  await Promise.all([page.waitForURL(/\/neu\/(\?.*)?$/, { waitUntil: 'domcontentloaded' }), knopf.click()]);
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Aufgabenkacheln je Schwerpunkt, keine Ember-Grafiken', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/');

      // Buchhaltung: Der E2E-Bestand hat eine überfällige Miete.
      await schwerpunkt(page, /Buchhaltung/);
      await expect(page.locator('.fw-schwerpunkt > summary')).toContainText('Buchhaltung');
      const kacheln = page.locator('.fw-heute-kacheln > .fw-kachel');
      await expect(kacheln.first()).toBeVisible();
      expect(await kacheln.count()).toBeLessThanOrEqual(4);
      await expect(kacheln.first()).toHaveClass(/akzent/);
      await expect(page.locator('[data-kachel="rueckstand"]')).toBeVisible();
      // Weg: Ember-Reihe, eigene Suche, «Ausserdem».
      await expect(page.locator('.fw-ember-bento, .fw-ember-intro, .fw-ausserdem')).toHaveCount(0);
      await expect(page.locator('#h-vorrat')).toBeVisible();
      await keinQuerscrollen(page);

      // Übersicht: der Kennzahlenstreifen statt der Kacheln.
      await schwerpunkt(page, /Übersicht/);
      await expect(page.locator('.fw-lage')).toBeVisible();
      await expect(page.locator('.fw-heute-kacheln')).toHaveCount(0);
      await keinQuerscrollen(page);

      // Zurück auf Bewirtschaftung — andere Tests erwarten den Standard.
      await schwerpunkt(page, /Bewirtschaftung/);
      await expect(page.locator('.fw-schwerpunkt > summary')).toContainText('Bewirtschaftung');
      await keinQuerscrollen(page);
    });
  });
}
