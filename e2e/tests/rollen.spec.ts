import { test, expect } from '@playwright/test';
import { goto, login } from './helpers';

// Funktionen für die drei Nutzergruppen — nur über die Oberfläche geprüft:
//   Bewirtschafter  Ticket-Board, Monatskalender
//   Buchhalter      Debitoren: Ampel als Filter, CSV-Export
//   Eigentümer      Portfolio: Rendite, Cashflow, Verteilung

test.describe('Rollen-Funktionen', () => {
  test.setTimeout(90_000);

  test('Ticket-Board: Spalten, Wechsel zwischen Liste und Board', async ({ page }) => {
    const fehler: string[] = [];
    page.on('pageerror', (e) => fehler.push(e.message));
    await login(page);
    await goto(page, '/neu/schaeden/');
    await page.getByRole('link', { name: 'Board' }).click();
    await page.waitForURL(/\/neu\/schaeden\/board\//, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('h1')).toContainText('Ticket-Board');
    await expect(page.locator('.fw-spalte')).toHaveCount(4);
    await page.getByRole('link', { name: 'Liste' }).click();
    await page.waitForURL(/\/neu\/schaeden\/(\?|$)/, { waitUntil: 'domcontentloaded' });
    // «Neues Ticket» vom Board öffnet das Erfassungsformular gleich.
    await goto(page, '/neu/schaeden/?neu=1');
    await expect(page.locator('#neuschaden')).toBeVisible();
    expect(fehler).toEqual([]);
  });

  test('Kalender: Monat, Vor/Zurück, Eintragsarten', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/termine/');
    await page.getByRole('link', { name: 'Monat' }).click();
    await page.waitForURL(/\/neu\/termine\/kalender\//, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.fw-kal-raster')).toBeVisible();
    await expect(page.locator('.fw-kal-tag.heute')).toHaveCount(1);
    const titel = await page.locator('h1').innerText();
    await page.getByRole('link', { name: /Nächster Monat|Next month/ }).click();
    await page.waitForURL(/monat=/, { waitUntil: 'domcontentloaded' });
    expect(await page.locator('h1').innerText()).not.toBe(titel);
    await expect(page.locator('.fw-kal-art')).toHaveCount(4);
  });

  test('Debitoren: Ampel filtert, CSV-Export lädt', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    await expect(page.locator('.fw-ampel')).toHaveCount(3);
    await page.locator('.fw-ampel.rot').click();
    await page.waitForURL(/ampel=rot/, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.fw-ampel.rot.fw-on')).toHaveCount(1);
    // Jede sichtbare Zeile ist überfällig (rot) — Zeilen mit «Bezahlt» dürfen nicht dabei sein.
    await expect(page.locator('table[data-spaltenfilter] tbody tr .fw-chip', { hasText: /Bezahlt|Paid/ })).toHaveCount(0);
    const antwort = await page.request.get('/neu/debitoren/?ampel=rot&export=csv');
    expect(antwort.ok()).toBeTruthy();
    expect(antwort.headers()['content-type']).toContain('text/csv');
    const text = await antwort.text();
    expect(text).toContain('Ampel');
    expect(text.split('\n').filter(Boolean).length).toBeGreaterThanOrEqual(2);
  });

  test('Portfolio: Kennzahlen, Zeitraum, Verteilung, Export', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/portfolio/');
    await expect(page.locator('h1')).toContainText('Portfolio');
    await expect(page.locator('.fw-kpis .fw-kpi')).toHaveCount(4);
    await page.getByRole('link', { name: /24 Mt\.|24 mo\./ }).click();
    await page.waitForURL(/monate=24/, { waitUntil: 'domcontentloaded' });
    await page.getByRole('link', { name: /Nutzung|Use/ }).click();
    await page.waitForURL(/verteilung=nutzung/, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.fw-donut')).toBeVisible();
    const csv = await page.request.get('/neu/portfolio/?export=csv');
    expect(csv.ok()).toBeTruthy();
    // Kein horizontales Überlaufen am Telefon
    await page.setViewportSize({ width: 390, height: 844 });
    await goto(page, '/neu/portfolio/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  });
});
