import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild «Bankabgleich im Zielbild»: Zeile mit Farbbalken, Betrag und einem Knopf; Assistent mit Karten.
async function zumAssistenten(page) {
  await goto(page, '/neu/bankabgleich/?spur=klaerung');
  await page.locator('[data-zuordnen]').first().click();
  await page.locator('#fwZuordnen .fw-zopt[data-opt="split"]').click();
  await Promise.all([page.waitForURL(/aufteilen/), page.locator('#fwZuordnenOk').click()]);
}

for (const [name, vp] of [['Telefon', { width: 390, height: 844 }], ['Desktop', { width: 1280, height: 800 }]] as const) {
  test(`Bankabgleich ${name}: Klärungszeile und Assistent ohne Überlauf`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: vp, hasTouch: name === 'Telefon' });
    const page = await ctx.newPage();
    await login(page);
    await goto(page, '/neu/bankabgleich/?spur=klaerung');
    const zeile = page.locator('.fw-bzeile').first();
    await expect(zeile.locator('.fw-bbalken')).toBeVisible();
    await expect(zeile.locator('.fw-betrag')).toBeVisible();
    await expect(zeile.locator('[data-zuordnen]')).toBeVisible();
    const kn = await zeile.locator('[data-zuordnen]').boundingBox();
    if (name === 'Telefon') expect(kn!.height).toBeGreaterThanOrEqual(36);
    expect(kn!.x + kn!.width).toBeLessThanOrEqual(vp.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    await zumAssistenten(page);
    await expect(page.locator('h1')).toContainText('Zahlung aufteilen');
    const karte = page.locator('.fw-posten-karte').first();
    await expect(karte).toBeVisible();
    await expect(karte.locator('.fw-posten-offen')).toContainText('alles zuteilen');
    await expect(page.locator('.fw-split-fuss')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (name === 'Desktop') {
      // Posten links, Zahlung und Summenkarte rechts.
      const posten = await page.locator('.fw-split-posten').boundingBox();
      const fuss = await page.locator('.fw-split-fuss').boundingBox();
      expect(fuss!.x).toBeGreaterThan(posten!.x + posten!.width - 2);
    }
    await ctx.close();
  });
}
