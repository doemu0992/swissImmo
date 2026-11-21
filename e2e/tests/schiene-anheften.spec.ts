import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// BREITE NAVIGATION (Mix-Entwurf, 21.11.2026): ab 1280 px steht links eine Spalte mit Beschriftung; die Seiten des Bereichs, in dem man steht,
// hängen als Baum darunter. «Schmal» stellt Symbolschiene und Seitenfeld wieder her (siehe schiene.spec.ts). Der Wunsch bleibt im Browser.

test.describe('Breite Navigation', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('Vorgabe: breit, mit Baum des aktiven Bereichs; ein Klick auf einen Bereich führt dorthin', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const schiene = page.locator('#fwSchiene');
    expect(Math.round((await schiene.boundingBox())!.width)).toBe(248);
    await expect(page.locator('#fwFach')).toBeHidden();
    const baum = page.locator('#fwSchiene [data-fach-bereich="akten"]');
    await expect(baum).toBeVisible();
    await expect(baum.locator('a[href^="/neu/objekte/"]')).toBeVisible();
    // Die Beschriftung steht neben dem Symbol
    await expect(schiene.locator('a[data-fach="finanzen"] span').first()).toBeVisible();
    // Der Inhalt beginnt rechts der Spalte
    expect((await page.locator('.fw-haupt').boundingBox())!.x).toBeGreaterThanOrEqual(247);
    await schiene.locator('a[data-fach="finanzen"]').click();
    await page.waitForURL('**/neu/finanzen/**');
    await expect(page.locator('#fwSchiene [data-fach-bereich="finanzen"]')).toBeVisible();
    await expect(page.locator('#fwSchiene [data-fach-bereich="akten"]')).toBeHidden();
  });

  test('Tastatur: G dann F öffnet Finanzen, 1 wählt die erste Seite des Baums', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.keyboard.press('g');
    await page.keyboard.press('f');
    await page.waitForURL('**/neu/finanzen/**');
    await page.keyboard.press('2');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.locator('#fwSchiene [data-fach-bereich="finanzen"] a.hier')).toBeVisible();
  });

  test('«Schmal» stellt Symbole und Seitenfeld her und merkt sich die Wahl', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.locator('[data-schiene-fest]').click();
    expect(Math.round((await page.locator('#fwSchiene').boundingBox())!.width)).toBe(88);
    await page.locator('#fwSchiene a[data-fach="finanzen"]').click();
    await expect(page.locator('#fwFach')).toBeVisible();
    await goto(page, '/neu/debitoren/');
    expect(Math.round((await page.locator('#fwSchiene').boundingBox())!.width)).toBe(88);
    await page.locator('[data-schiene-fest]').click();
    expect(Math.round((await page.locator('#fwSchiene').boundingBox())!.width)).toBe(248);
  });

  test('Unter 1280 px gibt es den Knopf und die breite Spalte nicht', async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await expect(page.locator('[data-schiene-fest]')).toBeHidden();
    expect(Math.round((await page.locator('#fwSchiene').boundingBox())!.width)).toBe(88);
  });
});
