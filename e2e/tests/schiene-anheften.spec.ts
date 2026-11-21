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

  test('Rahmen: Arbeitsbereich wählt den Bestand, die Kopfleiste trägt nur Brotkrume, «Neu» und Mitteilungen', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/objekte/');
    // Kopfleiste: Bestand, Dunkelmodus, Zahnrad und Avatar sind in die Spalte umgezogen
    await expect(page.locator('.fw-kopfleiste .fw-bestand')).toBeHidden();
    await expect(page.locator('.fw-werkzeug-kapsel .fw-wz-einst')).toBeHidden();
    await expect(page.locator('.fw-werkzeug-kapsel .fw-wz-neu')).toBeVisible();
    await expect(page.locator('.fw-kopf-z1 > .fw-krumen')).toContainText('Objekte');
    // Arbeitsbereich: Liste mit Suche; die Wahl setzt denselben Filter `lg` wie die Auswahl der Kopfzeile
    await page.locator('#fwArbeit').click();
    const pop = page.locator('#fwArbeitPop');
    await expect(pop).toBeVisible();
    await expect(page.locator('#fwArbeitSuche')).toBeFocused();
    const wahl = pop.locator('#fwArbeitListe a[href^="?lg="]:not([href="?lg="])');
    const name = (await wahl.first().textContent())!.trim();
    await page.locator('#fwArbeitSuche').fill(name.slice(0, 5));
    await expect(wahl.first()).toBeVisible();
    await wahl.first().click();
    await page.waitForURL(/[?&]lg=\d+/);
    await expect(page.locator('#fwArbeit small')).toContainText(name.split(',')[0]);
    // Esc schliesst und gibt den Fokus zurück
    await page.locator('#fwArbeit').click();
    await page.keyboard.press('Escape');
    await expect(pop).toBeHidden();
    await expect(page.locator('#fwArbeit')).toBeFocused();
  });

  test('Rahmen: Suchzeile und Strg+K öffnen die Suche als mittige Palette; das Profil sitzt im Fuss', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const os = page.locator('#fwOs');
    await expect(os).toHaveCSS('opacity', '0');
    await page.locator('#fwSchieneSuche').click();
    await expect(page.locator('#fwOsEingabe')).toBeFocused();
    await expect(os).toHaveCSS('opacity', '1');
    const b = (await os.boundingBox())!;
    expect(Math.abs(b.x + b.width / 2 - 720), 'Die Palette steht nicht mittig').toBeLessThan(4);
    await page.keyboard.press('Escape');
    await page.locator('h1').first().click();
    await page.keyboard.press('Control+k');
    await expect(page.locator('#fwOsEingabe')).toBeFocused();
    await page.keyboard.press('Escape');
    await page.locator('h1').first().click();
    // Profil im Fuss: Menü mit Darstellung und Abmelden, ohne Mandant und «Zuletzt» (beides steht in der Spalte)
    await page.locator('.fw-schiene-profil').click();
    const profil = page.locator('#fwProfil');
    await expect(profil).toBeVisible();
    await expect(profil.locator('[data-theme-btn="dark"]')).toBeVisible();
    await expect(profil.locator('#fwZuletztProfilAbschnitt')).toBeHidden();
    const pb = (await profil.boundingBox())!;
    expect(pb.x).toBeLessThan(40);
  });

  test('Rahmen: «Zuletzt» steht in der Spalte, die Taste [ schaltet schmal und breit, nichts scrollt quer', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.locator('table.fw-table tbody tr a').first().click();
    await page.waitForLoadState('domcontentloaded');
    await expect(page.locator('#fwSchiene > .fw-fach-zuletzt a').first()).toBeVisible();
    for (const w of [1280, 1440, 1920]) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.waitForTimeout(120);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), `${w} px scrollt quer`).toBeLessThanOrEqual(0);
    }
    await page.locator('h1').first().click();
    await page.keyboard.press('[');
    expect(Math.round((await page.locator('#fwSchiene').boundingBox())!.width)).toBe(88);
    await expect(page.locator('.fw-kopfleiste .fw-bestand')).toBeVisible();
    await page.keyboard.press('[');
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
