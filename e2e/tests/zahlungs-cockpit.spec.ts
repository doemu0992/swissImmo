import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// Zahlungs-Cockpit V12 (26.10.2026): Eine Zahlung ohne Referenz wird zum
// Klärungsfall, im Split-Screen-Assistenten einem Posten zugeteilt, und der
// Rest der Rechnung erscheint unter «Teilzahlungen». Am Desktop und am Telefon.
//
// Läuft bewusst als letzte Datei (Name «z…»): Sie bucht auf die gesäte
// «E2E offene Miete», die debitoren.spec.ts mit CHF 1'700 offen erwartet.
const BREITEN = [
  { name: 'Desktop', viewport: { width: 1440, height: 900 }, ref: 'E2E-KLAER-D', betrag: '200.00' },
  { name: 'Telefon', viewport: { width: 390, height: 844 }, ref: 'E2E-KLAER-M', betrag: '150.00' },
];

// Jeder Test mit eigenem Absender: Nach einer Zuordnung merkt sich das
// Programm den Absender und bucht seine nächste Zahlung selbst — sie würde
// dann gar nicht erst zum Klärungsfall.
function camt(ref: string, betrag: string, name: string) {
  const heute = new Date().toISOString().slice(0, 10);
  return '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
    + '<CdtDbtInd>CRDT</CdtDbtInd>'
    + `<Amt Ccy="CHF">${betrag}</Amt><BookgDt><Dt>${heute}</Dt></BookgDt>`
    + `<NtryDtls><TxDtls><Refs><AcctSvcrRef>${ref}</AcctSvcrRef></Refs>`
    + `<RltdPties><Dbtr><Nm>${name}</Nm></Dbtr></RltdPties>`
    + '<RmtInf><Ustrd>Zahlung ohne Referenz</Ustrd></RmtInf>'
    + '</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>';
}

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Klärungsfall zuordnen: Split-Screen, Teilzahlung, Spuren', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/bankabgleich/');
      await page.setInputFiles('input[name="camt_datei"]', {
        name: 'klaerung.xml', mimeType: 'text/xml', buffer: Buffer.from(camt(b.ref, b.betrag, `Zahler ${b.name} AG`)),
      });
      await Promise.all([page.waitForURL(/bankabgleich/, { waitUntil: 'domcontentloaded' }),
        page.locator('form[action="/neu/bankabgleich/camt-import/"] button[type="submit"]').click()]);

      // Die Klärungsfälle-Spur ist offen und zeigt den Absender.
      const klaerung = page.locator('[data-spur-inhalt="klaerung"]');
      await expect(klaerung).toBeVisible();
      await expect(page.locator('[data-spur-inhalt="posten"]')).toBeHidden();
      const zeile = klaerung.locator('.fw-klaerung', { hasText: `Zahler ${b.name} AG` }).first();
      await expect(zeile).toBeVisible();
      await keinQuerscrollen(page);

      // Kachel «Teilzahlungen» wechselt die Spur ohne Neuladen.
      await page.locator('[data-spur-link="teil"]').click();
      await expect(page.locator('[data-spur-inhalt="teil"]')).toBeVisible();
      await expect(klaerung).toBeHidden();
      await page.locator('[data-spur="klaerung"]').click();

      // Assistent: Suche, «offen» antippen, Rest live, buchen.
      await zeile.getByRole('link', { name: /Zuordnen \/ Aufteilen/ }).click();
      await page.waitForURL(/aufteilen/, { waitUntil: 'domcontentloaded' });
      await keinQuerscrollen(page);
      await page.fill('input[form="suchform"]', 'E2E');
      await page.press('input[form="suchform"]', 'Enter');
      const posten = page.locator('[data-treffer] [data-posten]', { hasText: 'E2E offene Miete' });
      await expect(posten).toBeVisible();
      await posten.locator('[data-voll]').click();
      // Höchstens, was von der Zahlung übrig ist — nicht der ganze offene Posten.
      await expect(posten.locator('input[data-teil]')).toHaveValue(b.betrag);
      await expect(page.locator('[data-rest]')).toHaveText('0.00');
      await expect(page.locator('[data-split-absenden]')).toBeEnabled();
      await page.locator('summary', { hasText: 'Diese Buchungen entstehen' }).click();
      await expect(page.locator('[data-pruefung]')).toContainText('1190 → 1100');
      await Promise.all([page.waitForURL(/bankabgleich\/(\?.*)?$/, { waitUntil: 'domcontentloaded' }),
        page.locator('[data-split-absenden]').click()]);
      await expect(page.locator('body')).toContainText(/auf 1 Posten verbucht/);

      // Die Rechnung ist jetzt teilweise bezahlt und steht in der Spur.
      await page.locator('[data-spur="teil"]').click();
      await expect(page.locator('[data-spur-inhalt="teil"]')).toContainText('E2E offene Miete');
      await keinQuerscrollen(page);
    });

    test('Zu viel zugeteilt sperrt «Buchen»', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/bankabgleich/');
      await page.setInputFiles('input[name="camt_datei"]', {
        name: 'zuviel.xml', mimeType: 'text/xml', buffer: Buffer.from(camt(`${b.ref}-X`, '50.00', `Fremd ${b.name} GmbH`)),
      });
      await Promise.all([page.waitForURL(/bankabgleich/, { waitUntil: 'domcontentloaded' }),
        page.locator('form[action="/neu/bankabgleich/camt-import/"] button[type="submit"]').click()]);
      await page.locator('.fw-klaerung', { hasText: `Fremd ${b.name} GmbH` }).first()
        .getByRole('link', { name: /Zuordnen \/ Aufteilen/ }).click();
      await page.waitForURL(/aufteilen/, { waitUntil: 'domcontentloaded' });
      await page.fill('input[form="suchform"]', 'E2E');
      await page.press('input[form="suchform"]', 'Enter');
      const feld = page.locator('[data-treffer] input[data-teil]').first();
      await feld.fill('999999');
      await expect(page.locator('[data-split-absenden]')).toBeDisabled();
      await expect(page.locator('[data-split-meldung]')).toBeVisible();
    });
  });
}
