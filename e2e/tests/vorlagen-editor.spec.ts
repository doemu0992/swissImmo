import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// MODUL 5 — DER VORLAGEN-EDITOR (27.10.2026)
//
// Was nur der Browser zeigt: Der Chip setzt den Platzhalter an der
// CURSORPOSITION ein (Skript), die Vorschau lädt nach (fetch an
// /neu/vorlagen/vorschau/), der Sprachumschalter setzt das versteckte Feld,
// und bei 390 px stehen Editor und Vorschau untereinander ohne waagrechtes
// Rollen. Ein Django-Test sieht davon nichts.
//
// Die Daten kommen aus `seed_e2e` (ein aktiver Vertrag der E2E-Verwaltung);
// die Vorlage legt der Test selbst über die Regelkachel an.

async function keinWaagrechtesRollen(page: Page) {
  const breite = await page.evaluate(() => document.documentElement.scrollWidth);
  const fenster = await page.evaluate(() => window.innerWidth);
  expect(breite, `Die Seite ist ${breite} px breit bei ${fenster} px Fenster.`).toBeLessThanOrEqual(fenster + 1);
}

test.describe('Vorlagen-Editor', () => {
  test('Regel anlegen: Chip an der Cursorposition, Vorschau, Sprache, Speichern', async ({ page }) => {
    const fehler: string[] = [];
    page.on('pageerror', (e) => fehler.push(String(e)));
    await login(page);

    // Regeln: je Ereignis eine Kachel
    await goto(page, '/neu/vorlagen/');
    await expect(page.locator('.fw-regel')).toHaveCount(6);
    const kachel = page.locator('.fw-regel[data-ereignis="kuendigung_erfasst"]');
    await expect(kachel.locator('.fw-kachel-kopf .fw-chip')).toHaveText('aus');
    await kachel.getByRole('link', { name: /Vorlage anlegen/ }).click();
    await page.waitForURL('**/neu/vorlagen/neu/?ereignis=kuendigung_erfasst');

    // Mustertext steht da; Cursor an den Anfang, Chip einfügen
    const inhalt = page.locator('#vf-inhalt');
    await expect(inhalt).toHaveValue(/\{mieter\.anrede\}/);
    await inhalt.evaluate((el: HTMLTextAreaElement) => { el.focus(); el.setSelectionRange(0, 0); });
    await page.locator('[data-einfuegen="{objekt.adresse}"]').click();
    await expect(inhalt).toHaveValue(/^\{objekt\.adresse\}\{mieter\.anrede\}/);

    // Live-Vorschau: mit dem Vertrag aus dem Seed, Platzhalter ersetzt
    const vorschau = page.locator('#vf-vorschau .fw-vl-blatt');
    await expect(vorschau).toBeVisible();
    await expect(vorschau).not.toContainText('{objekt.adresse}');

    // Unbekannter Platzhalter: Hinweis in der Vorschau, Speichern abgelehnt
    await inhalt.fill('Hallo {mieter.lieblingsfarbe}');
    await expect(page.locator('#vf-vorschau')).toContainText('{mieter.lieblingsfarbe}');
    await page.locator('#vf-form button.fw-primary[type="submit"]').click();
    await expect(page.locator('body')).toContainText('Unbekannte Platzhalter');

    // Sprache FR über das Segment
    await page.locator('#vf-inhalt').fill('{mieter.anrede}\n\nTexte');
    await page.locator('#vf-sprachen [data-sprache="fr"]').click();
    await expect(page.locator('#vf-sprache')).toHaveValue('fr');
    await expect(page.locator('#vf-sprachen [data-sprache="fr"]')).toHaveAttribute('aria-pressed', 'true');

    await page.locator('#vf-form button.fw-primary[type="submit"]').click();
    await page.waitForURL('**/neu/vorlagen/');
    await expect(page.locator('.fw-regel[data-ereignis="kuendigung_erfasst"] .fw-kachel-kopf .fw-chip')).toHaveText('aktiv');

    expect(fehler).toEqual([]);
  });

  test.describe('am Telefon', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('Editor und Vorschau untereinander, ohne waagrechtes Rollen', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/vorlagen/');
      await keinWaagrechtesRollen(page);

      await goto(page, '/neu/vorlagen/neu/?ereignis=bewerber_zugesagt');
      await expect(page.locator('#vf-vorschau .fw-vl-blatt')).toBeVisible();
      await keinWaagrechtesRollen(page);

      const editor = await page.locator('#vf-form > .fw-card').first().boundingBox();
      const karte = await page.locator('.fw-vl-vorschau-karte').boundingBox();
      expect(editor && karte).toBeTruthy();
      expect(karte!.y, 'Die Vorschau steht unter dem Editor.').toBeGreaterThanOrEqual(editor!.y + editor!.height - 1);
    });
  });
});
