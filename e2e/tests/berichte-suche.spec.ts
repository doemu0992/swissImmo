import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: Berichte mit Suche im Katalog; Gruppen ohne Treffer verschwinden.
test('Berichte: Suche filtert den Katalog und blendet leere Gruppen aus', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/berichte/');
  const zeilen = page.locator('#berichtListe [data-zeile]');
  const gruppen = page.locator('#berichtListe [data-gruppe]');
  const n = await zeilen.count();
  const g = await gruppen.count();
  expect(n).toBeGreaterThan(3);
  const titel = (await zeilen.first().locator('.fw-t').innerText()).trim();
  await page.locator('#berichtSuche').fill(titel.slice(0, 6));
  expect(await page.locator('#berichtListe [data-zeile]:visible').count()).toBeGreaterThan(0);
  await page.locator('#berichtSuche').fill('zzzzkeintreffer');
  await expect(page.locator('#berichtListe [data-zeile]:visible')).toHaveCount(0);
  await expect(page.locator('#berichtListe [data-gruppe]:visible')).toHaveCount(0);
  await expect(page.locator('#berichtListe [data-keine]')).toBeVisible();
  await page.locator('#berichtSuche').fill('');
  await expect(page.locator('#berichtListe [data-zeile]:visible')).toHaveCount(n);
  await expect(page.locator('#berichtListe [data-gruppe]:visible')).toHaveCount(g);
});
