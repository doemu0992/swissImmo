import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Finanzen (Mockup Modul 6): Kennzahlenband mit Verweisen, Altersbalken, Kreditoren «Tabelle | Spalten»,
// Kontoblatt neben der Liste der Mieterkonten. Alles Zugabe: die Tabellen und Zeilen bleiben, wie sie waren.

test.describe('Finanzen Modul 6', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('Übersicht: die Kennzahlen sind Verweise, der Altersbalken deckt das überfällige Total', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/finanzen/');
    await expect(page.locator('.fw-fin-kpis a.fw-kpi[href^="/neu/kreditoren/"]')).toBeVisible();
    await expect(page.locator('.fw-fin-kpis a.fw-kpi[href^="/neu/kautionen/"]')).toBeVisible();
    const breiten = await page.locator('.fw-altersbalken rect').evaluateAll((r) => r.map((x) => parseFloat(x.getAttribute('width') || '0')));
    expect(breiten.length).toBe(4);
    expect(Math.abs(breiten.reduce((a, b) => a + b, 0) - 100)).toBeLessThan(0.1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test('Kreditoren: Spalten sind eine zweite Ansicht, «In der Tabelle zeigen» führt zur Zeile zurück', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/kreditoren/');
    const tabelle = page.locator('#krTabelle');
    const spalten = page.locator('#krSpalten');
    await expect(tabelle).toBeVisible();
    await expect(spalten).toBeHidden();
    await page.locator('#krAnsicht [data-ansicht="spalten"]').click();
    await expect(spalten).toBeVisible();
    await expect(tabelle).toBeHidden();
    // Gleich viele Karten wie Zeilen: nichts fehlt in der zweiten Ansicht.
    const zeilen = await page.locator('#krTabelle tbody tr[id^="krow-"]').count();
    expect(await spalten.locator('.fw-karte').count()).toBe(zeilen);
    await spalten.locator('[data-kr-zeige]').first().click();
    await expect(tabelle).toBeVisible();
    await expect(spalten).toBeHidden();
    await expect(page.locator('#krTabelle tbody tr.sel')).toHaveCount(1);
    await page.evaluate(() => localStorage.removeItem('fwKrAnsicht'));
  });

  test('Mieterkonten: das Kontoblatt öffnet neben der Liste, die Zeile öffnet weiter die Seite', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/mieterkonten/');
    const blatt = page.locator('#mkBlatt');
    await expect(blatt).toBeHidden();
    const knopf = page.locator('[data-mk-blatt]').first();
    await knopf.click();
    await expect(page).toHaveURL(/\/neu\/mieterkonten\/$/);
    await expect(blatt).toBeVisible();
    await expect(page.frameLocator('#mkBlattRahmen').locator('h1')).toContainText('Kontoblatt');
    // Im Rahmen steht keine Kopfleiste.
    await expect(page.frameLocator('#mkBlattRahmen').locator('.fw-kopfleiste')).toBeHidden();
    await page.keyboard.press('Escape');
    await expect(blatt).toBeHidden();
    await page.locator('table.fw-table tbody tr').first().locator('td').first().click();
    await expect(page).toHaveURL(/\/neu\/mieterkonten\/\d+\//);
  });
});

test('Finanzen am Telefon: kein Schalter, kein Kontoblatt-Knopf, nichts quer', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  for (const url of ['/neu/finanzen/', '/neu/kreditoren/', '/neu/mieterkonten/']) {
    await goto(page, url);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), url).toBe(true);
  }
  await expect(page.locator('[data-mk-blatt]').first()).toBeHidden();
});
