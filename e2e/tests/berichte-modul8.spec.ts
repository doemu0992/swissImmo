import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Berichte (Mockup Modul 8): die Kennzahlen stehen als ein Band; auf der Übersicht sind die Zellen Verweise.

const SEITEN = ['/neu/berichte/', '/neu/portfolio/', '/neu/auswertung/', '/neu/team/'];

for (const [name, viewport] of [['Desktop', { width: 1440, height: 900 }], ['Telefon', { width: 390, height: 844 }]] as const) {
  test(`Berichte ${name}: Kennzahlen als Band, Werte im Bild, nichts quer`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport });
    const page = await ctx.newPage();
    await login(page);
    for (const url of SEITEN) {
      await goto(page, url);
      const band = page.locator('.fw-kpis.fw-ber-band');
      await expect(band, url).toBeVisible();
      // Jeder Wert liegt ganz in seiner Zelle (vorher schnitt eine ältere Regel die Werte ab).
      const ok = await band.locator('.fw-kpi').evaluateAll((zellen) => zellen.every((z) => {
        const v = z.querySelector('.fw-v'); if (!v) return false;
        const a = z.getBoundingClientRect(), b = v.getBoundingClientRect();
        return b.height > 0 && b.top >= a.top - 1 && b.bottom <= a.bottom + 1;
      }));
      expect(ok, `${url}: ein Wert ragt aus seiner Zelle`).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), url).toBe(true);
    }
    await ctx.close();
  });
}

test('Berichte-Übersicht: die Zellen des Bands führen auf Auswertung, Debitoren-Aging und Portfolio', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await goto(page, '/neu/berichte/');
  const band = page.locator('.fw-kpis.fw-ber-band');
  await expect(band.locator('a.fw-kpi')).toHaveCount(3);
  await expect(band.locator('a.fw-kpi[href^="/neu/auswertung/"]')).toBeVisible();
  await expect(band.locator('a.fw-kpi[href^="/neu/mahnwesen/aging/"]')).toBeVisible();
  await band.locator('a.fw-kpi[href^="/neu/portfolio/"]').click();
  await expect(page).toHaveURL(/\/neu\/portfolio\//);
});
