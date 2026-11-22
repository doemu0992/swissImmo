import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Liegenschaftsliste (Mockup Modul 2): Vorschau rechts neben der Liste und Ansicht «Karten».
// Beides ist Zugabe: die Zeile öffnet weiter die Akte.

test('Vorschau zeigt die Eckdaten, ohne die Akte zu öffnen, und schliesst mit Esc', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await goto(page, '/neu/liegenschaften/');
  const vorschau = page.locator('#lgVorschau');
  await expect(vorschau).toBeHidden();
  const knopf = page.locator('[data-lg-vorschau]').first();
  await knopf.click();
  await expect(page).toHaveURL(/\/neu\/liegenschaften\/$/);
  await expect(vorschau).toBeVisible();
  await expect(knopf).toHaveAttribute('aria-expanded', 'true');
  const akte = vorschau.locator('a.fw-primary');
  await expect(akte).toHaveAttribute('href', /\/neu\/liegenschaften\/\d+\/$/);
  await expect(vorschau.locator('a[href^="/neu/objekte/?lg="]')).toBeVisible();
  await expect(vorschau.locator('a[href^="/neu/vertraege/?lg="]')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(vorschau).toBeHidden();
  await expect(knopf).toHaveAttribute('aria-expanded', 'false');
  // Gegenprobe: die Zeile selbst öffnet weiter die Akte.
  await page.locator('#lgListe tbody tr').first().locator('td').nth(2).click();
  await expect(page).toHaveURL(/\/neu\/liegenschaften\/\d+\/$/);
});

test('Ansicht «Karten» bleibt je Gerät erhalten und lässt sich zurückstellen', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await goto(page, '/neu/liegenschaften/');
  const liste = page.locator('#lgListe');
  await expect(liste).not.toHaveClass(/fw-karten/);
  await page.locator('[data-ansicht="karten"]').click();
  await expect(liste).toHaveClass(/fw-karten/);
  await expect(page.locator('[data-ansicht="karten"]')).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.reload();
  await expect(page.locator('#lgListe')).toHaveClass(/fw-karten/);
  await page.locator('[data-ansicht="liste"]').click();
  await expect(page.locator('#lgListe')).not.toHaveClass(/fw-karten/);
});

test('Telefon: kein Schalter, keine Vorschau, nichts quer', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await goto(page, '/neu/liegenschaften/');
  await expect(page.locator('#lgAnsicht')).toBeHidden();
  await expect(page.locator('[data-lg-vorschau]').first()).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
