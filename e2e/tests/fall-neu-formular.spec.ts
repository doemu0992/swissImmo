import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: «Neuer Fall» ohne riskante Vorbelegung. Keine Art vorgewählt, Frist per Chip,
// «Fall anlegen» erst bei gültigen Eingaben.
test('Neuer Fall: Knopf erst bei gültigen Eingaben, Frist-Chips setzen das Datum', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/faelle/neu/');
  const knopf = page.locator('form.fw-fallneu button[type="submit"]');
  await expect(page.locator('form.fw-fallneu input[name="fallart"]:checked')).toHaveCount(0);
  await expect(knopf).toBeDisabled();

  await page.locator('form.fw-fallneu .fw-fchip:has(input[name="fallart"])').first().click();
  await page.locator('#nfT').fill('Heizung ausgefallen');
  await expect(knopf).toBeDisabled();           // Akte fehlt noch
  const akte = page.locator('#nfA');
  await akte.selectOption({ index: 1 });
  await expect(knopf).toBeEnabled();

  await page.locator('[data-frist-tage="1"]').click();
  const morgen = new Date(); morgen.setDate(morgen.getDate() + 1);
  const iso = `${morgen.getFullYear()}-${String(morgen.getMonth() + 1).padStart(2, '0')}-${String(morgen.getDate()).padStart(2, '0')}`;
  await expect(page.locator('#nfD')).toHaveValue(iso);

  await page.locator('#nfT').fill('ab');
  await expect(knopf).toBeDisabled();
});
