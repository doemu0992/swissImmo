import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: Einstellungen mit Suche. Die Eingabe filtert die Einträge; Gruppen ohne Treffer verschwinden.
test('Einstellungen: Suche filtert Einträge und blendet leere Gruppen aus', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/');
  const alle = page.locator('#einstListe [data-zeile]');
  const gruppen = page.locator('#einstListe [data-gruppe]');
  const n = await alle.count();
  const g = await gruppen.count();
  expect(n).toBeGreaterThan(5);
  const titel = (await alle.first().locator('.fw-t').innerText()).trim();
  await page.locator('#einstSuche').fill(titel.slice(0, 5));
  await expect(alle.locator(':scope:visible')).not.toHaveCount(0);
  expect(await page.locator('#einstListe [data-zeile]:visible').count()).toBeLessThan(n + 1);
  await page.locator('#einstSuche').fill('zzzzkeintreffer');
  await expect(page.locator('#einstListe [data-zeile]:visible')).toHaveCount(0);
  await expect(page.locator('#einstListe [data-gruppe]:visible')).toHaveCount(0);
  await expect(page.locator('#einstListe [data-keine]')).toBeVisible();
  await page.locator('#einstSuche').fill('');
  await expect(page.locator('#einstListe [data-zeile]:visible')).toHaveCount(n);
  await expect(page.locator('#einstListe [data-gruppe]:visible')).toHaveCount(g);
  await expect(page.locator('#einstListe [data-keine]')).toBeHidden();
});
