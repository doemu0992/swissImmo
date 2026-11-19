import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: Monatsabschluss als Schrittliste («Schritte in dieser Reihenfolge»).
for (const [name, vp] of [['Desktop', { width: 1280, height: 800 }], ['Telefon', { width: 390, height: 844 }]] as const) {
  test(`Monatsabschluss ${name}: Schrittliste mit aktuellem und gesperrtem Schritt`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: vp, hasTouch: name === 'Telefon' });
    const page = await ctx.newPage();
    await login(page);
    await goto(page, '/neu/laeufe/');
    await expect(page.locator('h1')).toHaveText('Monatsabschluss');
    const schritte = page.locator('.fw-schrittliste .fw-schritt');
    expect(await schritte.count()).toBeGreaterThan(2);
    await expect(page.locator('.fw-schrittliste .fw-schritt.jetzt')).toHaveCount(1);   // genau ein aktueller Schritt
    await expect(schritte.last()).toHaveClass(/gesperrt/);                              // Periodenabschluss wartet
    await expect(schritte.last()).toContainText('Möglich, sobald');
    // Kein horizontaler Überlauf, Knöpfe nennen die Aufgabe.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.locator('.fw-schritt.jetzt .fw-btn.fw-primary')).toBeVisible();
    await ctx.close();
  });
}
