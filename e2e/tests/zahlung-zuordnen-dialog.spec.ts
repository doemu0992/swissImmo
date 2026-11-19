import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: «Zahlung zuordnen» ist ein Dialog mit vier Wegen (Mietzins, Kaution, Aufteilen, Zurückweisen).
test('Bankabgleich: Zuordnen öffnet den Dialog mit vier Wegen und stellt die Felder um', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/bankabgleich/?spur=klaerung');
  await page.locator('[data-zuordnen]').first().click();
  const dlg = page.locator('#fwZuordnen');
  await expect(dlg).toBeVisible();
  await expect(dlg.locator('.fw-zopt')).toHaveCount(4);
  await expect(dlg.locator('#fwZuordnenSub')).toContainText('1\'234.50');
  // Vorgewählt ist «Mietzins zuordnen» mit Rechnungswahl, die anderen Wege zeigen keine Felder.
  await expect(dlg.locator('#fwZuordnenRechnung')).toBeVisible();
  await expect(dlg.locator('#fwZuordnenVertrag')).toBeHidden();
  await dlg.locator('.fw-zopt[data-opt="kaution"]').click();
  await expect(dlg.locator('#fwZuordnenForm')).toHaveAttribute('action', /\/kaution\/$/);
  await dlg.locator('.fw-zopt[data-opt="back"]').click();
  await expect(dlg.locator('#fwZuordnenForm')).toHaveAttribute('action', /rueckerstatten/);
  // «Aufteilen» führt in den Assistenten.
  await dlg.locator('.fw-zopt[data-opt="split"]').click();
  await Promise.all([page.waitForURL(/\/aufteilen\/$/), dlg.locator('#fwZuordnenOk').click()]);
  // Abbrechen schliesst.
  await goto(page, '/neu/bankabgleich/?spur=klaerung');
  await page.locator('[data-zuordnen]').first().click();
  await dlg.locator('#fwZuordnenAbbrechen').click();
  await expect(dlg).toBeHidden();
});
