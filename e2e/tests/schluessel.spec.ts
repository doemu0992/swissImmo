import { test, expect, Page } from '@playwright/test';
import { login, goto, warteAufURL } from './helpers';

// SCHLÜSSEL AUSGEBEN AM TELEFON (Modul 2, 27.10.2026)
//
// Die Ausgabe ist für das Handy gebaut, nach dem Vorbild der Abnahme vor Ort:
// Empfänger wählen, Schlüssel antippen, «zurück bis», mit dem Finger
// unterschreiben. Ob das Zeichenfeld wirklich ein PNG liefert und die Seite
// bei 390 px nicht seitlich rollt, sieht nur der Browser — der Django-Test
// schickt das PNG selbst.

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON });

async function keinSeitlichesRollen(page: Page) {
  const breite = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(breite, `Die Seite ist ${breite} px breit — bei 390 px rollt sie seitlich.`).toBeLessThanOrEqual(390);
}

async function unterschreiben(page: Page) {
  const feld = page.locator('canvas[data-sk-pad]');
  await feld.scrollIntoViewIfNeeded();
  const box = await feld.boundingBox();
  if (!box) throw new Error('Zeichenfeld nicht sichtbar');
  await page.mouse.move(box.x + 30, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + 20, { steps: 8 });
  await page.mouse.move(box.x + box.width - 30, box.y + box.height - 20, { steps: 8 });
  await page.mouse.up();
}

test('Schlüssel mit Unterschrift ausgeben, Quittung in der Ablage', async ({ page }) => {
  await login(page);

  // Liegenschaft des Seed-Vertrags über dessen Akte finden (keine geratene ID)
  await goto(page, '/neu/vertraege/1/');
  const ausgabeLink = page.locator('#schluessel a[href*="/schluessel/ausgabe/"]').first();
  const href = await ausgabeLink.getAttribute('href');
  const lg = /\/neu\/liegenschaften\/(\d+)\//.exec(href || '')?.[1];
  expect(lg, 'Die Vertragsakte verlinkt die Ausgabe nicht').toBeTruthy();

  // Haustürschlüssel ohne Objekt an der Liegenschaft erfassen
  const nummer = `E2E-${Date.now()}`;
  await goto(page, `/neu/liegenschaften/${lg}/?tab=stammdaten#schliessanlage`);
  await keinSeitlichesRollen(page);
  await page.fill('#sk-typ-neu', 'Haustür');
  await page.fill('#sk-nr-neu', nummer);
  await page.fill('#sk-n-neu', '3');
  await Promise.all([warteAufURL(page, '**/neu/liegenschaften/**'),
    page.locator('form[action$="/schluessel/neu/"] button.fw-primary').click()]);
  const karte = page.locator('.fw-sk', { hasText: nummer });
  await expect(karte).toBeVisible();

  // Ausgabe: Empfänger ist der Vertrag, Schlüssel antippen, Frist setzen
  await karte.locator('a', { hasText: 'Ausgeben' }).click();
  await page.waitForURL(/\/schluessel\/ausgabe\//, { waitUntil: 'domcontentloaded' });
  await keinSeitlichesRollen(page);
  await page.selectOption('#sk-empf', 'vertrag:1');
  const wahl = page.locator('.fw-sk-wahl', { hasText: nummer });
  await expect(wahl.locator('input[type=checkbox]')).toBeChecked();      // aus ?schluessel= vorgewählt
  await wahl.locator('input[type=number]').fill('2');
  const bis = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
  await page.fill('#sk-bis', bis);

  // Ohne Unterschrift geht es nicht — die Seite sagt es, statt abzuschicken
  await page.click('[data-sk-absenden]');
  await expect(page.locator('[data-sk-pad-fehlt]')).toBeVisible();
  await expect(page).toHaveURL(/\/schluessel\/ausgabe\//);

  await page.fill('#sk-u-name', 'Erika E2E');
  await unterschreiben(page);
  await Promise.all([warteAufURL(page, '**/neu/liegenschaften/**'), page.click('[data-sk-absenden]')]);
  await expect(page.locator('body')).toContainText('Quittung in der Ablage');

  // Die Karte zeigt den Inhaber und den Bestand
  const nachher = page.locator('.fw-sk', { hasText: nummer });
  await expect(nachher).toContainText('Erika E2E');
  await expect(nachher.locator('.fw-sk-stand b')).toHaveText('1/3');

  // Die Vertragsakte führt den Schlüssel mit Quittung im Verlauf
  await goto(page, '/neu/vertraege/1/');
  const liste = page.locator('#schluessel');
  await expect(liste).toContainText(nummer);
  await liste.locator('summary').click();
  await expect(liste.locator('a', { hasText: 'Quittung' }).first()).toBeVisible();
  await keinSeitlichesRollen(page);
});
