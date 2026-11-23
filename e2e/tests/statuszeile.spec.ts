import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: Statuszeile (schmale Zellen, seit «Aus einem Guss» als Band) statt grosser Kennzahl-Kacheln auf Schäden, Liegenschaften, Bankabgleich.
for (const [name, vp] of [['Telefon', { width: 390, height: 844 }], ['Desktop', { width: 1280, height: 800 }]] as const) {
  test(`Statuszeile ${name}: Kapseln statt Kacheln, kein Überlauf`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: vp, hasTouch: name === 'Telefon' });
    const page = await ctx.newPage();
    await login(page);
    for (const url of ['/neu/schaeden/', '/neu/liegenschaften/', '/neu/bankabgleich/']) {
      await goto(page, url);
      const zeile = page.locator('.fw-statuszeile');
      await expect(zeile, `${url}: Statuszeile fehlt`).toBeVisible();
      await expect(page.locator('.fw-kpis'), `${url}: Kennzahl-Kacheln stehen noch`).toHaveCount(0);
      const hoehen = await zeile.locator('.fw-sz').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
      expect(hoehen.length).toBeGreaterThan(1);
      for (const h of hoehen) expect(h, `${url}: Kapsel zu hoch (Kachel?)`).toBeLessThan(60);
      if (name === 'Telefon') for (const h of hoehen) expect(h).toBeGreaterThanOrEqual(36);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${url}: Überlauf`).toBe(true);
    }
    await ctx.close();
  });
}
