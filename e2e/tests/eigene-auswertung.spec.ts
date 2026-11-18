import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Eigene Auswertungen (Modul «Erweitertes Reporting»): Vorlage anlegen, ausführen, CSV.
// Das Skript der Seite zeigt nur die Spalten der gewählten Datenquelle — mit scharfer CSP geprüft.
test('Eigene Auswertung: anlegen, Spalten je Quelle, ausführen, CSV', async ({ page }) => {
  const jsFehler: string[] = [];
  page.on('pageerror', (e) => jsFehler.push(String(e)));
  await login(page);
  await goto(page, '/neu/auswertung/eigene/');
  const name = `E2E Objektliste ${Date.now()}`;
  await page.fill('#aw-name', name);
  await page.selectOption('#aw-quelle', 'objekte');
  // Nur die Spalten der gewählten Quelle sind sichtbar.
  await expect(page.locator('[data-auswertung-spalten="objekte"]')).toBeVisible();
  await expect(page.locator('[data-auswertung-spalten="debitoren"]')).toBeHidden();
  await page.check('input[name="spalten"][value="objekte:liegenschaft"]');
  await page.check('input[name="spalten"][value="objekte:bezeichnung"]');
  await page.selectOption('#aw-zeitraum', 'alle');
  await page.click('button:has-text("Vorlage speichern")');
  await expect(page.locator('h1')).toHaveText(name);
  const tabelle = page.locator('[data-testid="auswertung-tabelle"]');
  await expect(tabelle.locator('thead th')).toHaveText(['Liegenschaft', 'Bezeichnung']);
  expect(await tabelle.locator('tbody tr').count()).toBeGreaterThan(0);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.click('a:has-text("CSV herunterladen")'),
  ]);
  const inhalt = require('fs').readFileSync(await download.path(), 'utf-8') as string;
  expect(inhalt.replace(/^﻿/, '').split('\r\n')[0]).toBe('Liegenschaft;Bezeichnung');
  // Die Vorlage steht in der Liste und im Menü «Berichte».
  await goto(page, '/neu/auswertung/eigene/');
  await expect(page.locator('[data-testid="auswertung-vorlage"]', { hasText: name })).toBeVisible();
  expect(jsFehler).toEqual([]);
});
