import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild «Schäden»: Titel, Reiter mit Zahl in der Karte, Statuschip und nächste Aktion je Zeile.
for (const [name, vp] of [['Desktop', { width: 1280, height: 800 }], ['Telefon', { width: 390, height: 844 }]] as const) {
  test(`Schäden ${name}: Reiter, Statuschip und Aktionsknopf`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: vp, hasTouch: name === 'Telefon' });
    const page = await ctx.newPage();
    await login(page);
    await goto(page, '/neu/schaeden/');
    await expect(page.locator('h1')).toHaveText('Schäden');
    await expect(page.locator('.fw-card > .fw-reiter a')).toHaveCount(5);
    const zeile = page.locator('.fw-schadenzeile').first();
    await expect(zeile.locator('.fw-schaden-tags .fw-chip').first()).toBeVisible();
    await expect(zeile.locator('.fw-seit')).toContainText('seit');
    const knopf = zeile.locator('.fw-btn');
    await expect(knopf).toBeVisible();
    expect(['Auftrag erteilen', 'Handeln', 'Nachfassen', 'Ansehen', 'Öffnen']).toContain((await knopf.innerText()).trim());
    if (name === 'Telefon') expect((await knopf.boundingBox())!.height).toBeGreaterThanOrEqual(36);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await ctx.close();
  });
}
