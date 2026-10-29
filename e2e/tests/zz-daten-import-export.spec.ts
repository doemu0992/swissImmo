import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// DATEN: IMPORT FÜR WECHSELKUNDEN UND EXPORT (FUNK-09, FUNK-13) AM TELEFON
//
// Der Name beginnt mit «zz-»: Die Specs laufen alphabetisch in EINER Datenbank, und der Import
// legt eine Liegenschaft an. Läge das Spec weiter vorn, sähen Listen-Specs danach eine
// Liegenschaft mehr.
//
// Gemessen wird bei 390 x 844 (Telefon): Keine der Seiten darf seitwärts rollen. Das lässt sich
// nicht aus dem Quelltext lesen, es hängt an Schriftgrad, Abständen und der Länge der Fehlertexte.

test.use({ viewport: { width: 390, height: 844 } });

async function keinQuerscroll(page: Page, was: string) {
  const [breite, fenster] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(breite, `${was}: Die Seite ist ${breite} px breit bei ${fenster} px Fenster (Querscroll).`)
    .toBeLessThanOrEqual(fenster + 1);
}

const LIEGENSCHAFT_OK =
  'schluessel;strasse;plz;ort;kanton\nE2EIMP1;E2E-Importweg 1;8001;Zürich;ZH\n';
const LIEGENSCHAFT_FEHLER =
  'schluessel;strasse;plz;ort\nE2EIMP2;E2E-Fehlerweg 2;80;Zürich\n';

async function hochladen(page: Page, art: string, inhalt: string) {
  await page.setInputFiles(`#datei_${art}`, {
    name: `${art}.csv`, mimeType: 'text/csv', buffer: Buffer.from(inhalt, 'utf-8'),
  });
  await Promise.all([
    page.waitForURL(/\/neu\/einstellungen\/daten\/import\/\d+\/$/, { waitUntil: 'domcontentloaded' }),
    page.click('[data-testid="daten-import-pruefen"]'),
  ]);
}

test('Die Datenseite führt zu Import und Export', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/');
  await page.click('a[href="/neu/einstellungen/daten/"]');
  await expect(page.locator('h1')).toHaveText('Daten');
  await expect(page.locator('[data-testid="daten-import-link"]')).toBeVisible();
  await expect(page.locator('[data-testid="daten-export-link"]')).toBeVisible();
  await keinQuerscroll(page, 'Daten');
});

test('Eine fehlerhafte Datei zeigt die Fehlerliste und legt nichts an', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/daten/import/');
  await keinQuerscroll(page, 'Import');
  await hochladen(page, 'liegenschaften', LIEGENSCHAFT_FEHLER);
  await expect(page.locator('[data-testid="daten-import-status"]')).toContainText('Fehler');
  const fehler = page.locator('[data-testid="daten-import-fehler"]');
  await expect(fehler).toContainText('Zeile 2');
  await expect(fehler).toContainText('vier Ziffern');
  await expect(page.locator('[data-testid="daten-import-ausfuehren"]')).toHaveCount(0);
  await keinQuerscroll(page, 'Fehlerliste');
  // Nichts angelegt
  await goto(page, '/neu/liegenschaften/');
  await expect(page.locator('body')).not.toContainText('E2E-Fehlerweg 2');
});

test('Vorschau, dann Import: erst danach steht die Liegenschaft in der Liste', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/daten/import/');
  await hochladen(page, 'liegenschaften', LIEGENSCHAFT_OK);
  await expect(page.locator('[data-testid="daten-import-status"]')).toContainText('Vorschau');
  await expect(page.locator('[data-testid="daten-import-zaehler"]').first()).toContainText('1 neu');
  await keinQuerscroll(page, 'Vorschau');
  // Die Vorschau hat nichts geschrieben.
  await goto(page, '/neu/liegenschaften/');
  await expect(page.locator('body')).not.toContainText('E2E-Importweg 1');
  await page.goBack();
  await Promise.all([
    page.waitForURL(/\/neu\/einstellungen\/daten\/import\/\d+\/$/, { waitUntil: 'domcontentloaded' }),
    page.click('[data-testid="daten-import-ausfuehren"]'),
  ]);
  await expect(page.locator('[data-testid="daten-import-status"]')).toContainText('Importiert');
  await keinQuerscroll(page, 'Protokoll');
  await goto(page, '/neu/liegenschaften/');
  await expect(page.locator('body')).toContainText('E2E-Importweg 1');
});

test('Die Exportseite passt aufs Telefon und liefert Journal und Mandatspaket', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/daten/export/');
  await keinQuerscroll(page, 'Export');

  // Einstellungen speichern: eigene Überschrift
  await page.fill('#spalte_text', 'Beschreibung');
  await Promise.all([
    page.waitForURL(/\/daten\/export\/$/, { waitUntil: 'domcontentloaded' }),
    page.click('[data-testid="daten-einstellung-speichern"]'),
  ]);
  await expect(page.locator('#spalte_text')).toHaveValue('Beschreibung');

  // Journal (CSV)
  await page.fill('#exp-von', '2000-01-01');
  await page.fill('#exp-bis', '2099-12-31');
  const [journal] = await Promise.all([
    page.waitForEvent('download'),
    page.click('[data-testid="daten-journal-export"]'),
  ]);
  expect(journal.suggestedFilename()).toMatch(/^Buchungsjournal_.*\.csv$/);
  const pfad = await journal.path();
  const text = require('fs').readFileSync(pfad, 'utf-8');
  expect(text.replace('﻿', '').split('\r\n')[0]).toBe('Buchungsdatum;Belegnummer;Soll;Haben;Betrag;Beschreibung;MWST-Code');

  // Mandatsexport (ZIP)
  const [zip] = await Promise.all([
    page.waitForEvent('download'),
    page.click('[data-testid="daten-mandat-export"]'),
  ]);
  expect(zip.suggestedFilename()).toMatch(/^Mandatsexport_.*\.zip$/);
  const bytes = require('fs').readFileSync(await zip.path());
  expect(bytes.subarray(0, 2).toString()).toBe('PK');
});

test('Die Buchhaltung sieht nur das Journal, nicht den Import und nicht das Mandatspaket', async ({ page }) => {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', 'e2e-buchhaltung');
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([
    page.waitForURL('**', { waitUntil: 'domcontentloaded' }),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  const export_ = await page.goto('/neu/einstellungen/daten/export/', { waitUntil: 'domcontentloaded' });
  expect(export_?.status()).toBe(200);
  await expect(page.locator('[data-testid="daten-journal-export"]')).toBeVisible();
  await expect(page.locator('[data-testid="daten-mandat-export"]')).toHaveCount(0);
  await keinQuerscroll(page, 'Export (Buchhaltung)');
  const import_ = await page.goto('/neu/einstellungen/daten/import/', { waitUntil: 'domcontentloaded' });
  expect(import_?.status()).toBe(403);
});
