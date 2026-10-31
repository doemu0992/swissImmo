import { test, expect, Page } from '@playwright/test';
import { login, goto, bestaetigen } from './helpers';

// VIER-AUGEN-PRINZIP FÜR AUSZAHLUNGEN, SUMMENREGEL IM ZAHLLAUF, BANANA-PRESET (Etappe 4) AM TELEFON
//
// Der Name beginnt mit «zz-»: Die Specs laufen alphabetisch in EINER Datenbank, und die Summenregel-Probe legt
// drei Lieferantenrechnungen an, die später in Zahllauf-Listen stünden.
//
// Gemessen wird bei 390 x 844: keine der Seiten darf seitwärts rollen.

test.use({ viewport: { width: 390, height: 844 } });

async function keinQuerscroll(page: Page, was: string) {
  const [breite, fenster] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(breite, `${was}: Die Seite ist ${breite} px breit bei ${fenster} px Fenster (Querscroll).`)
    .toBeLessThanOrEqual(fenster + 1);
  const zuBreit = await page.evaluate(() => [...document.querySelectorAll(
    '.fw-phead, .fw-phead *, .fw-card, .fw-card *, .fw-hinweis, .fw-hinweis *')]
    .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
    .map((el) => el.tagName + '.' + el.className).slice(0, 3));
  expect(zuBreit, `${was}: Inhalt ragt über den Rand: ${zuBreit.join(', ')}`).toEqual([]);
}

async function rechnungErfassen(page: Page, lieferant: string, betrag: string, referenz: string) {
  await goto(page, '/neu/kreditoren/');
  await page.getByRole('button', { name: /Rechnung erfassen/ }).first().click();
  await page.fill('#kr-lieferant', lieferant);
  await page.fill('#kr-betrag', betrag);
  await page.fill('#kr-iban', 'CH66 0076 2011 6238 5295 8');   // eigene IBAN: Der Seed zahlt dieselbe IBAN (CH93…) an eine andere Rechnung
  await page.fill('#kr-referenz', referenz);
  await page.locator('#kredform button', { hasText: 'Erfassen' }).click();
  await expect(page.locator('body')).toContainText(referenz);
  const zeile = page.locator('tr', { hasText: referenz }).first();
  const konto = zeile.locator('select[name="konto_id"]');
  if (await konto.count()) await konto.selectOption({ index: 1 });
  await zeile.getByRole('button', { name: /Freigeben/ }).click();
  await bestaetigen(page);
  await expect(page.locator('tr', { hasText: referenz }).first()).toContainText(/Freigegeben/);
}

test('Auszahlungen: leerer Zustand, Erklärung, kein Querscroll', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/zahlungsfreigabe/');
  await expect(page.locator('body')).toContainText('Auszahlungen warten auf Freigabe');
  await keinQuerscroll(page, 'Zahlungsfreigabe');
  await page.getByRole('link', { name: /Auszahlung(en)? warte/ }).click();
  await expect(page).toHaveURL(/\/zahlungsfreigabe\/auszahlungen\/$/);
  await expect(page.locator('body')).toContainText('Keine Auszahlung wartet auf Freigabe');
  await expect(page.locator('body')).toContainText('Wer die Auszahlung ausgelöst hat, darf sie nicht selbst freigeben');
  await keinQuerscroll(page, 'Auszahlungen freigeben');
});

test('Eine Eigentümerauszahlung ohne Eingang bucht nichts und legt nichts vor', async ({ page }) => {
  // Der Seed hat nichts eingenommen: Die Deckungsprüfung kommt vor der Freigabe (kein Antrag für Geld, das fehlt).
  await login(page);
  await goto(page, '/neu/mandate/');
  const href = (await page.locator('a[href^="/neu/mandate/"]', { hasText: 'E2E Eigentümer AG' }).first()
    .getAttribute('href')) || '';
  const id = href.match(/mandate\/(\d+)/)?.[1];
  expect(id).toBeTruthy();
  await goto(page, `/neu/mandate/${id}/kontokorrent/`);
  await page.evaluate(() => {
    document.querySelector('button[disabled]')?.removeAttribute('disabled');
    (document.querySelector('input[name="betrag"]') as HTMLInputElement).value = '20000';
  });
  await page.getByRole('button', { name: 'Auszahlung verbuchen' }).click();
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('body')).toContainText('Auszahlbar sind höchstens CHF 0');
  await goto(page, '/neu/einstellungen/zahlungsfreigabe/auszahlungen/');
  await expect(page.locator('body')).toContainText('Keine Auszahlung wartet auf Freigabe');
});

test('Summenregel: drei Rechnungen à CHF 2000 desselben Kreditors brauchen die Freigabe', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  for (const nr of ['SUM-1', 'SUM-2', 'SUM-3']) {
    await rechnungErfassen(page, 'E2E Summen AG', '2000', nr);
  }
  await goto(page, '/neu/zahllauf/');
  const hinweis = page.locator('#zahllauf-summenregel');
  await expect(hinweis).toContainText('Summenregel');
  for (const nr of ['SUM-1', 'SUM-2', 'SUM-3']) await expect(hinweis).toContainText(nr);
  await expect(hinweis).toContainText("6'000.00");
  await keinQuerscroll(page, 'Zahllauf mit Summenregel');

  // Nur die drei Rechnungen auswählen und die Zahlungsdatei verlangen: Es gibt keine Datei, sondern die Erklärung.
  await page.evaluate(() => {
    document.querySelectorAll('input[name="rechnung_ids"]').forEach((el) => {
      const zeile = el.closest('tr');
      (el as HTMLInputElement).checked = !!zeile && /SUM-[123]/.test(zeile.textContent || '');
    });
  });
  await page.locator('button[name="aktion"][value="datei"]').click();
  await page.waitForLoadState('domcontentloaded');
  const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
  expect(text).toContain('ergeben zusammen CHF 6\'000.00');
  expect(text).toContain("Freigabelimit von CHF 5'000.00");
  await keinQuerscroll(page, 'Zahllauf nach der Sperre');
});

test('Banana-Preset: Auswahl, Importweg und Datei nach Spezifikation', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/einstellungen/daten/export/');
  await expect(page.locator('[data-testid="daten-banana-hinweis"]'))
    .toContainText('Aktionen > In Buchhaltung importieren > Text file with column headers');
  await keinQuerscroll(page, 'Datenexport');
  await page.locator('[data-testid="daten-preset-banana"]').check();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.click('[data-testid="daten-journal-export"]'),
  ]);
  expect(download.suggestedFilename()).toMatch(/^Banana_Buchungen_\d{8}_\d{8}\.txt$/);
  const inhalt = require('fs').readFileSync(await download.path(), 'utf-8') as string;
  const zeilen = inhalt.split('\r\n').filter((z) => z);
  expect(zeilen[0]).toBe(
    ['Date', 'Doc', 'Description', 'AccountDebit', 'AccountCredit', 'Amount', 'VatCode', 'ExternalReference'].join('\t'));
  for (const z of zeilen.slice(1)) {
    const f = z.split('\t');
    expect(f.length).toBe(8);
    expect(f[0]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(f[7]).toMatch(/^immoswiss-\d{4}-\d+$/);
  }
  const refs = zeilen.slice(1).map((z) => z.split('\t')[7]);
  expect(new Set(refs).size).toBe(refs.length);
});
