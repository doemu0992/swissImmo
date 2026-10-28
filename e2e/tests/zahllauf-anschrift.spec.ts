import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Zahlungsdatei nach den Swiss Payment Standards 2026 (Etappe 0, FUNK-04/FIN-08):
// Ein Kreditor ohne Anschrift lehnt den Zahllauf VOR der Dateierzeugung ab, die Liste
// führt zur Adressseite, und nach dem Ergänzen entsteht die Datei mit der Anschrift.

test('Zahllauf lehnt Kreditor ohne Anschrift ab und erzeugt die Datei nach dem Ergänzen', async ({ page }) => {
  await login(page);

  // Eine freigegebene Rechnung OHNE Anschrift (Erfassen → Freigeben mit Aufwandskonto).
  await goto(page, '/neu/kreditoren/');
  await page.getByRole('button', { name: /Rechnung erfassen/ }).first().click();
  await page.fill('#kr-lieferant', 'E2E Maler ohne Anschrift');
  await page.fill('#kr-betrag', '420.50');
  await page.fill('#kr-iban', 'CH56 0483 5012 3456 7800 9');
  await page.locator('#kredform button', { hasText: 'Erfassen' }).click();
  await expect(page.locator('body')).toContainText(/E2E Maler ohne Anschrift/);

  const zeile = page.locator('tr', { hasText: 'E2E Maler ohne Anschrift' }).first();
  await expect(zeile).toContainText(/Neu \/ Prüfen/);
  // Das Aufwandskonto wird beim Erfassen oft schon vorgeschlagen (Schlüsselwort «Maler»).
  const konto = zeile.locator('select[name="konto_id"]');
  if (await konto.count()) await konto.selectOption({ index: 1 });
  await zeile.getByRole('button', { name: /Freigeben/ }).click();
  await page.locator('#fwBestaetigenJa').click();
  await expect(page.locator('tr', { hasText: 'E2E Maler ohne Anschrift' }).first()).toContainText(/Freigegeben/);

  // Zahllauf: die Beanstandung steht schon im Vorschlag, die Datei wird abgelehnt.
  await goto(page, '/neu/zahllauf/');
  await expect(page.locator('tr', { hasText: 'E2E Maler ohne Anschrift' })).toContainText(/Anschrift unvollständig/);
  await page.locator('button[name="aktion"][value="datei"]').click();
  const fehler = page.locator('#zahllauf-fehler');
  await expect(fehler).toContainText(/Zahlungsdatei wurde nicht erzeugt/);
  await expect(fehler).toContainText(/E2E Maler ohne Anschrift/);

  // Über den Link der Liste die Anschrift ergänzen und zum Zahllauf zurückkehren.
  await fehler.getByRole('link', { name: /Anschrift ergänzen/ }).click();
  await page.fill('#ka-strasse', 'Malerweg 12');
  await page.fill('#ka-plz', '3000');
  await page.fill('#ka-ort', 'Bern');
  await page.getByRole('button', { name: /Speichern/ }).click();
  await expect(page).toHaveURL(/\/neu\/zahllauf\//);

  // Jetzt entsteht die Datei, und sie trägt die Anschrift (Hausnummer abgetrennt).
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('button[name="aktion"][value="datei"]').click(),
  ]);
  const pfad = await download.path();
  const xml = require('fs').readFileSync(pfad, 'utf-8');
  expect(xml).toContain('<StrtNm>Malerweg</StrtNm>');
  expect(xml).toContain('<BldgNb>12</BldgNb>');
  expect(xml).toContain('<TwnNm>Bern</TwnNm>');
  expect(xml).toContain('<Ctry>CH</Ctry>');
});
