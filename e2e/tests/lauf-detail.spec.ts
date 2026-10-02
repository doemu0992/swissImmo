import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// LAUF-DETAIL AM TELEFON — GEMESSEN
//
// Die Detailansicht eines Laufs (`/neu/laeufe/<pk>/`) ist der Ort, an dem der
// Buchhalter vor dem Quittieren prüft, was der Lauf verarbeitet hat. Dominik
// arbeitet am Telefon (390 × 844): Gemessen wird, ob die Seite seitlich
// überläuft und ob die Knöpfe erreichbar sind — nicht, ob der Quelltext gut aussieht.

test.use({ viewport: { width: 390, height: 844 } });

test('Lauf-Detail: kein seitliches Rollen, Knöpfe erreichbar', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/laeufe/');

  const detail = page.locator('a[href^="/neu/laeufe/"][href$="/"]', { hasText: 'Details' }).first();
  await expect(detail, 'Auf «Läufe» steht keine Karte mit «Details» — der E2E-Bestand sät keine offenen Läufe.').toBeVisible();
  await detail.click();
  await expect(page).toHaveURL(/\/neu\/laeufe\/\d+\/$/);

  // Die Seite läuft nicht über die Bildschirmbreite hinaus.
  const breiten = await page.evaluate(() => ({
    inhalt: document.documentElement.scrollWidth, fenster: window.innerWidth }));
  expect(breiten.inhalt, `Die Seite ist ${breiten.inhalt} px breit bei ${breiten.fenster} px Fenster — ` +
    'am Telefon rollt sie seitlich.').toBeLessThanOrEqual(breiten.fenster);

  // Öffnen und Abschliessen sind sichtbar, liegen im Fenster und sind gross genug zum Tippen.
  for (const id of ['#lauf-oeffnen', '#lauf-abschliessen']) {
    const knopf = page.locator(id);
    await expect(knopf, `${id} fehlt`).toBeVisible();
    const box = await knopf.boundingBox();
    expect(box, `${id} hat keine Box`).not.toBeNull();
    expect(box!.x, `${id} ragt links hinaus`).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, `${id} ragt rechts hinaus`).toBeLessThanOrEqual(390);
    expect(box!.height, `${id} ist zu niedrig zum Tippen`).toBeGreaterThanOrEqual(36);
  }
});
