import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// «Heute» nach der Dashboard-Reduktion (26.10.2026) und dem UI-Zielbild (19.11.2026): höchstens vier
// Kapseln der Statuszeile (vorher Aufgabenkacheln), der Schwerpunkt als Segment im Kopf
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
  // UI-Zielbild: Der Schwerpunkt ist ein sichtbares Segment, kein Aufklappfeld.
  const knopf = page.locator('.fw-schwerpunkt-segment button', { hasText: name });
  await expect(knopf).toBeVisible();
  const box = (await knopf.boundingBox())!;
  const breite = page.viewportSize()!.width;
  expect(box.x, 'Das Segment ragt links aus dem Bild').toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, 'Das Segment ragt rechts aus dem Bild').toBeLessThanOrEqual(breite);
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
      await expect(page.locator('.fw-schwerpunkt-segment button.an')).toContainText('Buchhaltung');
      // Statuszeile statt Aufgabenkacheln (UI-Zielbild): höchstens vier Kapseln, die dringendste zuerst.
      const kapseln = page.locator('.fw-statuszeile > .fw-sz');
      await expect(kapseln.first()).toBeVisible();
      expect(await kapseln.count()).toBeLessThanOrEqual(4);
      await expect(page.locator('.fw-heute-kacheln')).toHaveCount(0);
      await expect(page.locator('[data-kachel="rueckstand"]')).toBeVisible();
      // Weg: Ember-Reihe, eigene Suche, «Ausserdem».
      await expect(page.locator('.fw-ember-bento, .fw-ember-intro, .fw-ausserdem')).toHaveCount(0);
      await expect(page.locator('#h-vorrat')).toBeVisible();
      await keinQuerscrollen(page);

      // Übersicht: der Kennzahlenstreifen statt der Kacheln.
      await schwerpunkt(page, /Übersicht/);
      await expect(page.locator('.fw-lage')).toBeVisible();
      await expect(page.locator('.fw-statuszeile')).toHaveCount(0);
      await keinQuerscrollen(page);

      // Zurück auf Bewirtschaftung — andere Tests erwarten den Standard.
      await schwerpunkt(page, /Bewirtschaftung/);
      await expect(page.locator('.fw-schwerpunkt-segment button.an')).toContainText('Bewirtschaftung');
      await keinQuerscrollen(page);
    });
  });
}
