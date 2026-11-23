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

// Die fünfte Zelle «älteste N Tage» erscheint im Bankabgleich erst, wenn eine ungeklärte Zahlung einen Tag alt ist — also
// nie am Tag des Seeds. In der CI lief der Test über Mitternacht und fand 70 statt 51 px: Der Text brach in den Zellen um.
// Hier wird die Zelle gesetzt, damit der Fall an jedem Tag geprüft ist.
test('Statuszeile mit fünf Zellen: der Text bricht nie in der Zelle um', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await login(page);
  await goto(page, '/neu/bankabgleich/');
  const hoehen = await page.evaluate(() => {
    const zeile = document.querySelector('.fw-statuszeile')!;
    const zellen = () => [...zeile.querySelectorAll('.fw-sz')] as HTMLElement[];
    zellen()[0].textContent = "3 ungeklärt · CHF 12'350.00";
    if (zellen().length < 5) { const neu = zellen()[0].cloneNode(true) as HTMLElement; neu.textContent = 'älteste 14 Tage'; zellen()[0].after(neu); }
    zellen()[zellen().length - 2].textContent = "2 Teilzahlungen · Rest CHF 11'350.00";
    return zellen().map(z => Math.round(z.getBoundingClientRect().height));
  });
  expect(hoehen.length).toBeGreaterThanOrEqual(5);
  for (const h of hoehen) expect(h, 'Zelle zweizeilig: ' + hoehen.join(',')).toBeLessThan(60);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
