import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild Phase 1: Tippflächen am Handy. Filter-Chips und kleine Knöpfe mindestens 40 px,
// Segmente und Schliessen-Knopf mindestens 36 px, Hilfe-«i» mit grösserer Trefferfläche.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
test('Handy: Chips und Knöpfe sind gross genug zum Tippen', async ({ page }) => {
  await login(page);
  for (const u of ['/neu/liegenschaften/', '/neu/schaeden/', '/neu/finanzen/']) {
    await goto(page, u);
    const klein = await page.evaluate(() => {
      const r: string[] = [];
      document.querySelectorAll('.fw-fchip, .fw-btn.fw-knapp').forEach((e) => {
        const b = (e as HTMLElement).getBoundingClientRect();
        if (b.width > 0 && b.height > 0 && b.height < 39.5) r.push(`${(e as HTMLElement).className} ${Math.round(b.height)}`);
      });
      document.querySelectorAll('.fw-segment .fw-seg-link').forEach((e) => {
        const b = (e as HTMLElement).getBoundingClientRect();
        if (b.width > 0 && b.height < 35.5) r.push(`seg ${Math.round(b.height)}`);
      });
      return r;
    });
    expect(klein, `${u}: zu kleine Tippflächen`).toEqual([]);
  }
  await goto(page, '/neu/bankabgleich/');
  const treffer = await page.evaluate(() => {
    const e = document.querySelector('.fw-hilfe-knopf') as HTMLElement | null;
    if (!e) return 99;
    const b = e.getBoundingClientRect();
    const mitte = document.elementFromPoint(b.left - 8, b.top + b.height / 2);
    return mitte === e ? 1 : 0;
  });
  expect(treffer, 'Hilfe-i: Fläche neben dem Zeichen trifft den Knopf').toBe(1);
});
