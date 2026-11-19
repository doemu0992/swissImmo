import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: Bestandsfilter am Handy zeigt die gewählte Liegenschaft im Knopf, die Kopfzeile bricht nie um.
test.use({ viewport: { width: 390, height: 844 } });
test('Handy: gewählter Bestand steht im Knopf, kein Überlauf', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/liegenschaften/');
  const bestand = page.locator('.fw-bestand');
  await expect(page.locator('.fw-bestand-name')).toHaveCount(0);
  const wert = await page.locator('.fw-bestand select option').nth(1).getAttribute('value');
  await goto(page, `/neu/liegenschaften/?lg=${wert}`);
  await expect(page.locator('.fw-bestand-name')).toBeVisible();
  const breite = await bestand.evaluate((e) => e.getBoundingClientRect().width);
  expect(breite).toBeGreaterThan(60);
  expect(breite).toBeLessThanOrEqual(160);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/bestand-name-390.png', clip: { x: 0, y: 0, width: 390, height: 140 } });
});
