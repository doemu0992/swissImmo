import { test, expect } from '@playwright/test';
import { goto, login } from './helpers';

// Die Platzhalter der Vorlagen ({mieter.anrede}, {objekt.adresse}, {verwaltung.name}, {frist}) lösen sich in der Live-Vorschau auf.
// Anlass (23.11.2026): Die Vorschau kannte nur die alten Kurznamen; die Abmahnung stand mit allen Klammern im Vorschaufeld.

const TEXT = '{mieter.anrede}\n\nwir haben festgestellt, dass Sie Ihre Pflichten aus dem Mietvertrag für {objekt.bezeichnung}, {objekt.adresse} verletzen.\n\n'
  + 'Wir fordern Sie auf, diesen Zustand bis spätestens {frist} zu beheben.\n\nFreundliche Grüsse\n{verwaltung.name}';

test('Live-Vorschau ersetzt die neuen Platzhalter mit den Werten des ersten Empfängers', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  await goto(page, '/neu/kommunikation/');
  const text = page.locator('#nachricht');
  const vorschau = page.locator('#pv-text');

  // Ohne Empfänger: Beschriftung in eckigen Klammern statt roher Platzhalter
  await page.evaluate((t) => { const el = document.getElementById('nachricht') as HTMLTextAreaElement; el.value = t; el.dispatchEvent(new Event('input', { bubbles: true })); }, TEXT);
  await expect(vorschau).toContainText('[Briefanrede]');
  await expect(vorschau).not.toContainText('{mieter.anrede}');

  // Mit Empfänger: echte Werte
  await page.locator('.emp-row', { hasText: 'Erika E2E' }).first().locator('.emp-check').check();
  await expect(vorschau).toContainText(/Sehr geehrte|Guten Tag/);
  await expect(vorschau).toContainText('E2E-Weg 1');
  await expect(vorschau).not.toContainText('{mieter.anrede}');
  await expect(vorschau).not.toContainText('{objekt.');
  await expect(vorschau).not.toContainText('{verwaltung.');

  // Die Frist: Das Feld erscheint, weil der Text {frist} nennt; ohne Datum bleibt der Platzhalter stehen, mit Datum steht es im Brief
  await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click(); // Schritt «Mitteilung»: dort stehen die Fristfelder
  await expect(page.locator('#mk-frist')).toBeVisible();
  await expect(vorschau).toContainText('{frist}');
  await page.evaluate(() => { const el = document.getElementById('mk-frist-datum') as HTMLInputElement; el.value = '2026-12-15'; el.dispatchEvent(new Event('input', { bubbles: true })); });
  await expect(vorschau).toContainText('15. Dezember 2026');
  await expect(vorschau).not.toContainText('{');

  // Die alten Kurznamen gelten weiter
  await page.evaluate(() => { const el = document.getElementById('nachricht') as HTMLTextAreaElement; el.value = 'Guten Tag {name}, Objekt {objekt}'; el.dispatchEvent(new Event('input', { bubbles: true })); });
  await expect(vorschau).toContainText('Guten Tag Erika E2E');
  await expect(page.locator('#mk-frist')).toHaveClass(/hidden/);
});

test('Einschreiben ist wählbar: Vermerk in der Vorschau, «Als Brief drucken» schickt den formatierten Brief ans PDF-Ziel', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  await goto(page, '/neu/kommunikation/');
  await page.locator('.emp-row', { hasText: 'Erika E2E' }).first().locator('.emp-check').check();
  await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
  await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();   // Schritt «Versand»
  const haken = page.locator('#mk-einschreiben');
  await expect(haken).toBeVisible();
  await expect(page.locator('#pv-vermerk')).toBeHidden();
  await haken.check();
  await expect(page.locator('#pv-vermerk')).toBeVisible();
  await expect(page.locator('#pv-vermerk')).toHaveText('Einschreiben');

  // «Als Brief drucken» nutzt dasselbe Formular wie das Serienbrief-PDF (formatierter Brief), im Browser geöffnet
  await page.locator('input[name="mk-art"][value="druck"]').check();
  const felder = await page.evaluate(() => {
    const f = document.getElementById('pdfForm') as HTMLFormElement;
    let gesendet: Record<string, string> = {};
    f.submit = () => { new FormData(f).forEach((v, k) => { gesendet[k] = String(v); }); };
    (window as any).druckeVorschau();
    return gesendet;
  });
  expect(felder.einschreiben).toBe('1');
  expect(felder.anzeigen).toBe('1');
  expect(felder.empfaenger_id).toBeTruthy();
});
