import { test, expect } from '@playwright/test';
import { bestaetigen, goto, login } from './helpers';

// Verteilschlüssel der Liegenschaft: Schlüssel anlegen, Prozentraster mit Summenprüfung,
// Fehler am Feld. Läuft gegen die Seed-Liegenschaft (E2E-Weg 1) und räumt vorher auf, damit
// ein wiederverwendeter Server nicht an einem alten Schlüssel scheitert.

const SEITE = '/neu/liegenschaften/1/verteilschluessel/';

test('Schlüssel anlegen, Prozentraster prüfen, Fehler am Feld', async ({ page }) => {
  await login(page);
  await goto(page, SEITE);
  await expect(page.getByRole('heading', { name: 'Verteilschlüssel' })).toBeVisible();

  // Aufräumen: vorhandene Schlüssel löschen (mit der Rückfrage der Anwendung).
  while ((await page.locator('table form button.gefahr').count()) > 0) {
    await page.locator('table form button.gefahr').first().click();
    await bestaetigen(page);
  }

  // Fehler am Feld: Heizkosten sind nicht wählbar, «Verteilung» fehlt → HTTP 400 und Meldung am Feld.
  await page.locator('form:has(select[name="kostenart"]) button.fw-primary').click();
  await expect(page.locator('#id_kostenart_fehler')).toBeVisible();
  await expect(page.locator('#id_typ_fehler')).toBeVisible();

  // Gültigen Schlüssel anlegen: Prozent je Objekt.
  await page.selectOption('select[name="kostenart"]', 'hauswartung');
  await page.selectOption('select[name="typ"]', 'prozent');
  await page.fill('input[name="gueltig_ab"]', '2025-01-01');
  await page.locator('form:has(select[name="kostenart"]) button.fw-primary').click();
  await page.waitForLoadState('domcontentloaded');
  await expect(page.getByText('Prozentanteile —').first()).toBeVisible();

  const felder = page.locator('input[name^="pct_"]');
  expect(await felder.count()).toBeGreaterThanOrEqual(2);
  // Summe 90 → Fehler, Eingabe bleibt stehen.
  await felder.nth(0).fill('60');
  await felder.nth(1).fill('30');
  for (let i = 2; i < (await felder.count()); i++) await felder.nth(i).fill('0');
  await page.getByRole('button', { name: 'Prozentanteile speichern' }).click();
  await expect(page.getByText(/ergeben 90 statt 100/)).toBeVisible();
  await expect(page.locator('input[name^="pct_"]').nth(0)).toHaveValue('60');

  // Korrigieren → gespeichert.
  await page.locator('input[name^="pct_"]').nth(1).fill('40');
  await page.getByRole('button', { name: 'Prozentanteile speichern' }).click();
  await expect(page.getByText('Prozentanteile gespeichert.')).toBeVisible();
});

test('Das Kennzeichen steht im Liegenschaftsformular', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/liegenschaften/1/bearbeiten/');
  await expect(page.locator('input[name="verteilschluessel_aktiv"]')).toBeVisible();
});
