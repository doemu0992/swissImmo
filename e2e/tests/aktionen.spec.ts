import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// AKTIONEN PER DATENATTRIBUT (CSP, Roadmap Nr. 23, Etappe 3): static/js/fw-aktionen.js ersetzt die Inline-Handler.
// Gemessen im Browser: Das Verhalten ist dasselbe wie mit `onclick="…"` — nur dass es auch unter einer strengen
// Content-Security-Policy (kein Inline-Handler) läuft.

test.beforeEach(async ({ page }) => { await login(page); });

test('Umschalten: Knopf zeigt und versteckt das Formular', async ({ page }) => {
  await goto(page, '/neu/kreditoren/');
  const form = page.locator('#kredform');
  await expect(form).toBeHidden();
  await page.locator('[data-umschalten="kredform"]').first().click();
  await expect(form).toBeVisible();
  await page.locator('[data-umschalten="kredform"]').first().click();
  await expect(form).toBeHidden();
});

test('Zeilen-Verweis: ein Klick in die Zeile öffnet den Vertrag', async ({ page }) => {
  await goto(page, '/neu/vertraege/');
  const zeile = page.locator('tr[data-gehe-zu]').first();
  const ziel = await zeile.getAttribute('data-gehe-zu');
  // Auf eine Zelle ohne eigenen Verweis oder Knopf klicken.
  await zeile.locator('td:not(:has(a, button, input, select))').first().click();
  await page.waitForURL('**' + ziel);
  expect(new URL(page.url()).pathname).toBe(ziel);
});

test('data-stop: der Verweis in der Zeile gewinnt gegen den Zeilen-Verweis', async ({ page }) => {
  await goto(page, '/neu/vertraege/');
  const zeile = page.locator('tr[data-gehe-zu]').first();
  const verweis = zeile.locator('a[data-stop]').first();
  const href = new URL(await verweis.evaluate((a) => (a as HTMLAnchorElement).href)).pathname;
  await verweis.click();
  await page.waitForURL('**' + href);
  expect(new URL(page.url()).pathname).toBe(href);
});

test('Auto-Absenden: eine Auswahl schickt das Filterformular ab', async ({ page }) => {
  await goto(page, '/neu/auswertung/');
  const auswahl = page.locator('select[data-absenden]').first();
  const optionen = await auswahl.locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
  const andere = optionen.find((v) => v !== '' && v !== (new URL(page.url()).searchParams.get(''))) || optionen[optionen.length - 1];
  const name = await auswahl.getAttribute('name');
  const vorher = page.url();
  await Promise.all([page.waitForURL((u) => u.toString() !== vorher), auswahl.selectOption(andere)]);
  expect(new URL(page.url()).searchParams.has(name!)).toBeTruthy();
});

test('Keine Inline-Handler auf den wichtigsten Seiten mehr, die ein Datenattribut nutzen', async ({ page }) => {
  await goto(page, '/neu/kreditoren/');
  const verbleibend = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-umschalten],[data-absenden],[data-stop],[data-gehe-zu]'))
      .filter((e) => e.hasAttribute('onclick') || e.hasAttribute('onchange')).length);
  expect(verbleibend).toBe(0);
});
