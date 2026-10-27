import { test, expect, Page } from '@playwright/test';
import { goto, warteAufURL } from './helpers';

// MIETERPORTAL, STARTSEITE (Modul 3, 27.10.2026) — BEI 390 PIXEL GEMESSEN
//
// Die Startseite hat drei Hauptwege als Bento («Etwas melden» mit Akzent,
// «Meine Meldungen» mit Zahl und nächstem Termin, «Dokumente») und zwei
// kleine Kacheln (Rechnungen, Schlüssel). Am Telefon steht der Akzent über
// die volle Breite, Meldungen und Dokumente nebeneinander — ob das ohne
// waagrechtes Scrollen passt, entscheidet erst der Browser.
//
// Daten aus `seed_e2e` (Block «Modul 3»): Login e2e-mieter / e2e-pass, eine
// telefonisch erfasste Meldung zur Wohnung mit Termin, ein Schlüssel E2E-S-1.

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON });

async function mieterLogin(page: Page) {
  await goto(page, '/portal/login/');
  await page.fill('input[name="username"]', 'e2e-mieter');
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([
    warteAufURL(page, '**/mieter/**'),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
}

async function quer(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
}

test('Startseite: fünf Kacheln, Akzent zuerst, kein waagrechtes Scrollen', async ({ page }) => {
  await mieterLogin(page);
  await goto(page, '/mieter/');
  for (const k of ['melden', 'meldungen', 'dokumente', 'rechnungen', 'schluessel']) {
    await expect(page.locator(`[data-kachel="${k}"]`)).toBeVisible();
  }
  await expect(page.locator('[data-kachel="melden"]')).toHaveClass(/akzent/);
  await expect(page.locator('[data-kachel="meldungen"]')).toContainText('offen');
  await expect(page.locator('[data-kachel="meldungen"]')).toContainText('Termin am');
  await expect(page.locator('[data-kachel="schluessel"]')).toContainText('E2E-S-1');
  expect(await quer(page)).toBeLessThanOrEqual(0);

  // Akzent über die volle Breite, Meldungen und Dokumente nebeneinander.
  const melden = await page.locator('[data-kachel="melden"]').boundingBox();
  const meldungen = await page.locator('[data-kachel="meldungen"]').boundingBox();
  const dokumente = await page.locator('[data-kachel="dokumente"]').boundingBox();
  expect(melden && meldungen && dokumente).toBeTruthy();
  expect(Math.abs(meldungen!.y - dokumente!.y)).toBeLessThan(2);
  expect(melden!.width).toBeGreaterThan(meldungen!.width * 1.8);
});

test('Telefonisch erfasste Meldung der Wohnung: sichtbar, mit Termin und Zutritt', async ({ page }) => {
  await mieterLogin(page);
  await goto(page, '/mieter/tickets/');
  await expect(page.getByText('E2E Wasserhahn tropft')).toBeVisible();
  expect(await quer(page)).toBeLessThanOrEqual(0);
  await Promise.all([warteAufURL(page, '**/mieter/ticket/**'), page.getByText('E2E Wasserhahn tropft').click()]);
  const block = page.locator('[data-block="termin"]');
  await expect(block).toContainText('E2E Sanitär Huber kommt am');
  await expect(block).toContainText('Zutritt:');
  expect(await quer(page)).toBeLessThanOrEqual(0);
});

test('Meldeformular fragt Kategorie, Zutritt und Erreichbarkeit', async ({ page }) => {
  await mieterLogin(page);
  await goto(page, '/mieter/schaden/neu/');
  await expect(page.locator('select[name="kategorie"]')).toBeVisible();
  await expect(page.locator('input[name="zutritt"]')).toHaveCount(2);
  await expect(page.locator('input[name="erreichbarkeit"]')).toHaveCount(4);
  expect(await quer(page)).toBeLessThanOrEqual(0);

  await page.selectOption('select[name="kategorie"]', 'Allgemeine Anfrage');
  await page.fill('input[name="titel"]', 'E2E Frage zum Veloraum');
  await page.fill('textarea[name="beschreibung"]', 'Wo ist der Schlüssel zum Veloraum?');
  await page.check('input[name="zutritt"][value="passpartout"]');
  await page.check('input[name="erreichbarkeit"][value="08:00 - 10:00"]');
  await Promise.all([warteAufURL(page, '**/mieter/'), page.click('form[action="/mieter/schaden/"] button[type="submit"]')]);
  await goto(page, '/mieter/tickets/');
  await expect(page.getByText('E2E Frage zum Veloraum')).toBeVisible();
});
