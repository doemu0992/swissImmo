import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Phase 3: Karten mit mindestens 10 Zeilen werden ab 641 px dicht, der Schalter stellt um, die Wahl bleibt.
// Die Seiten des Seeds haben weniger Zeilen: Wir vervielfachen die Zeilen und rufen die Initialisierung erneut auf.
async function zehnZeilen(page) {
  await page.evaluate(() => {
    const karte = document.querySelector('.fw-card:has(.fw-zeile)') as HTMLElement;
    const zeile = karte.querySelector('.fw-zeile') as HTMLElement;
    while (karte.querySelectorAll('.fw-zeile').length < 12) zeile.parentElement!.appendChild(zeile.cloneNode(true));
    (window as any).fwDichteInit();
  });
  return page.locator('.fw-card:has(.fw-dichte-schalter)').first();
}

test('Dichte Listen: automatisch ab 10 Zeilen, Schalter, Wahl bleibt', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  await goto(page, '/neu/schaeden/');
  const karte = await zehnZeilen(page);
  await expect(karte).toHaveClass(/fw-dicht/);
  const hoch = await karte.locator('.fw-zeile').first().boundingBox();
  await karte.getByRole('button', { name: 'Bequem' }).click();
  await expect(karte).not.toHaveClass(/fw-dicht/);
  const bequem = await karte.locator('.fw-zeile').first().boundingBox();
  expect(bequem!.height).toBeGreaterThan(hoch!.height);
  await page.reload();
  const karte2 = await zehnZeilen(page);
  await expect(karte2).not.toHaveClass(/fw-dicht/);   // Wahl je Gerät gemerkt
});

test('Dichte Listen: am Handy bleibt die bequeme Zeile, kein Schalter sichtbar', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await login(page);
  await goto(page, '/neu/schaeden/');
  const karte = await zehnZeilen(page);
  await expect(karte.locator('.fw-dichte-schalter')).toBeHidden();
  const z = await karte.locator('.fw-zeile').first().boundingBox();
  expect(z!.height).toBeGreaterThan(44);
});
