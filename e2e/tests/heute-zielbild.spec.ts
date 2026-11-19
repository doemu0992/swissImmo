import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild «Heute»: Segment, Statuszeile statt Kacheln, Dringlichkeitsgruppen, Aufgabenknopf.
for (const [name, vp] of [['Desktop', { width: 1280, height: 800 }], ['Telefon', { width: 390, height: 844 }]] as const) {
  test(`Heute ${name}: Segment, Statuszeile und Gruppen`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: vp, hasTouch: name === 'Telefon' });
    const page = await ctx.newPage();
    await login(page);
    await goto(page, '/neu/');
    const seg = page.locator('.fw-schwerpunkt-segment');
    await expect(seg.locator('button')).toHaveCount(3);
    await expect(seg.locator('button.an')).toHaveCount(1);
    await expect(page.locator('.fw-heute-kacheln'), 'Die Aufgabenkacheln sind einer Statuszeile gewichen').toHaveCount(0);
    await expect(page.locator('.fw-statuszeile .fw-sz').first()).toBeVisible();
    // Überfällige Vorgänge stehen unter «Überfällig», der Knopf nennt die Aufgabe.
    const gruppe = page.locator('.fw-vz-gruppe').first();
    await expect(gruppe).toContainText('Überfällig');
    const knopf = page.locator('.fw-vz .fw-vz-aktion .fw-btn').first();
    await expect(knopf).not.toHaveText('Zum Lauf');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // Schwerpunkt wechseln bleibt möglich.
    await seg.locator('button:not(.an)').first().click();
    await expect(page.locator('.fw-schwerpunkt-segment')).toBeVisible();
    await ctx.close();
  });
}
