import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// Etappe 0 (FUNK-01/FIN-03): Die Auszahlungsmaske nennt «auszahlbar» aus dem
// tatsächlich eingegangenen Geld, nicht aus der Sollbasis. Der Seed bucht EINE
// fällige Miete (1100 an 3000, CHF 1'500) und keine Zahlung — auszahlbar ist
// also 0, während das Kontokorrent 1'500 «offen» nennt.
//
// Die Spec ist lesend: Sie verändert keinen Seed-Zustand (die Folge-Specs
// verlassen sich darauf). Die abgewiesene Auszahlung unten bucht nichts.

async function kontokorrentOeffnen(page: Page) {
  await login(page);
  await goto(page, '/neu/mandate/');
  const link = page.locator('a[href^="/neu/mandate/"]', { hasText: 'E2E Eigentümer AG' }).first();
  const href = (await link.getAttribute('href')) || '';
  const id = href.match(/mandate\/(\d+)/)?.[1];
  expect(id, 'Mandat «E2E Eigentümer AG» im Seed').toBeTruthy();
  await goto(page, `/neu/mandate/${id}/kontokorrent/`);
  return id as string;
}

test('Maske nennt auszahlbar ehrlich: 0, solange nichts eingegangen ist', async ({ page }) => {
  await kontokorrentOeffnen(page);
  const body = page.locator('body');
  await expect(body).toContainText('Auszahlbar (eingegangene Mittel)');
  await expect(body).toContainText('Zurzeit ist nichts auszahlbar.');
  // Die Sollbasis steht daneben, aber nicht als Auszahlungsvorschlag im Feld.
  await expect(body).toContainText('Offen an Eigentümer');
  await expect(page.locator('input[name="betrag"]')).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Auszahlung verbuchen' })).toBeDisabled();
});

test('Das Kautionssperrkonto 1015 steht nicht zur Wahl, 1020 ist vorgewählt', async ({ page }) => {
  await kontokorrentOeffnen(page);
  const optionen = await page.locator('select[name="konto_nummer"] option').evaluateAll(
    (os) => os.map((o) => (o as HTMLOptionElement).value));
  expect(optionen).not.toContain('1015');
  expect(optionen).toContain('1020');
  await expect(page.locator('select[name="konto_nummer"]')).toHaveValue('1020');
});

test('Eine erzwungene Auszahlung ohne Eingang wird abgewiesen und bucht nichts', async ({ page }) => {
  await kontokorrentOeffnen(page);
  // Wie ein Skript oder ein manipuliertes Formular: Sperre im Browser aufheben.
  await page.evaluate(() => {
    document.querySelector('button[disabled]')?.removeAttribute('disabled');
    (document.querySelector('input[name="betrag"]') as HTMLInputElement).value = '15000';
  });
  await page.getByRole('button', { name: 'Auszahlung verbuchen' }).click();
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('body')).toContainText('Auszahlbar sind höchstens CHF 0');
  await expect(page.locator('body')).toContainText('Noch keine Auszahlungen erfasst.');
});

test('Die Maske läuft bei 390 px ohne horizontales Scrollen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await kontokorrentOeffnen(page);
  const breiten = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth, sicht: document.documentElement.clientWidth }));
  expect(breiten.scroll).toBeLessThanOrEqual(breiten.sicht + 1);
});
