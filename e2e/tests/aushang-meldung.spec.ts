import { test, expect, Page } from '@playwright/test';

// Der QR-Aushang im Treppenhaus (`/report/<id>/`) prüft auf dem SERVER
// (SICH-08, ROUTE-04, Audit 28.10.2026).
//
// Vorher legte ein leeres Formular das Ticket «None ()» an, eine fremde oder
// nicht-numerische `einheit_id` ging durch (oder ergab 500), und 30 Absendungen
// in Folge ergaben 30 Tickets mit Bestätigungsmail. Der Browser verhindert das
// mit `required` nur für Menschen mit einem Browser. Diese Spec entfernt die
// Browser-Prüfung ausdrücklich und sieht nach, was der Server tut — und dass
// die Seite nach einem Fehler benutzbar bleibt: Meldung sichtbar, Eingaben
// da, das Formular auf der Zusammenfassung statt zurück auf der ersten Karte.
//
// Etappe 3: das Formular ist der Assistent der Anwendung (Anliegen, Beschreibung, Kontakt,
// Prüfen). Höchstens drei Absendungen je Lauf: Die Drossel zählt zehn je IP und Stunde und
// lebt so lange wie der Serverprozess.

const weiter = (page: Page) => page.locator('[data-assistent-weiter]');

async function zumFormular(page: Page) {
  await page.goto('/report/1/', { waitUntil: 'load' });
  await page.locator('label.fw-wahl', { hasText: 'Allgemeine Anfrage' }).click();
  await expect(page.locator('textarea[name="beschreibung"]')).toBeVisible();
}

/** Füllt Beschreibung und Kontakt (zwei Schritte) und steht danach auf der Zusammenfassung. */
async function ausfuellen(page: Page, ueberschreibe: Record<string, string> = {}) {
  const werte: Record<string, string> = {
    vorname: 'Vera', nachname: 'Muster', email: 'vera@example.ch', telefon: '0791234567',
    beschreibung: 'Die Tür im Treppenhaus schliesst nicht mehr.', ...ueberschreibe,
  };
  // Die Felder liegen in zwei Schritten; gesetzt wird direkt, nicht durch Blättern.
  await page.evaluate((w) => {
    for (const [name, wert] of Object.entries(w)) {
      (document.querySelector(`[name="${name}"]`) as HTMLInputElement).value = wert;
    }
  }, werte);
}

/** Nimmt dem Browser und dem Assistenten die eigene Prüfung — wie ein Skript, das nur POSTet. */
async function browserpruefungAus(page: Page) {
  await page.evaluate(() => {
    document.querySelectorAll('form [required]').forEach((el) => el.removeAttribute('required'));
    document.querySelectorAll('form [data-pflicht]').forEach((el) => el.removeAttribute('data-pflicht'));
    const form = document.querySelector('form');
    if (form) form.setAttribute('novalidate', '');
  });
}

async function zurPruefung(page: Page) {
  await weiter(page).click();   // Beschreibung → Kontakt
  await weiter(page).click();   // Kontakt → Prüfen
}

test('Ohne Pflichtfelder meldet der Server den Fehler, die Eingaben bleiben', async ({ page }) => {
  await zumFormular(page);
  await browserpruefungAus(page);
  await ausfuellen(page, { beschreibung: '', email: '' });
  await zurPruefung(page);
  await page.getByRole('button', { name: /Meldung absenden/ }).click();

  await expect(page.getByText('Ihre Meldung wurde noch nicht gesendet.')).toBeVisible();
  await expect(page.getByText('Bitte füllen Sie das Feld «Beschreibung» aus.')).toBeVisible();
  await expect(page.getByText('Bitte füllen Sie das Feld «E-Mail» aus.')).toBeVisible();
  // Nicht zurück auf der ersten Karte: das Formular steht auf der Zusammenfassung, mit dem, was getippt war.
  await expect(page.locator('.fw-assistent-leiste li.hier')).toContainText('Prüfen');
  await expect(page.locator('input[name="vorname"]')).toHaveValue('Vera');
  await expect(page.locator('input[name="telefon"]')).toHaveValue('0791234567');
  await expect(page.locator('input[name="kategorie"]:checked')).toHaveValue('Allgemeine Anfrage');
  await expect(page.locator('.fw-assistent-pruefen')).toContainText('Vera');
});

test('Eine Einheit, die es in diesem Haus nicht gibt, wird abgelehnt', async ({ page }) => {
  await zumFormular(page);
  await ausfuellen(page);
  // Eine manipulierte Auswahl: eine ID, die zu keiner Einheit dieser Liegenschaft gehört.
  await page.evaluate(() => {
    const auswahl = document.querySelector('select[name="einheit_id"]') as HTMLSelectElement;
    const o = document.createElement('option');
    o.value = '99999999'; o.text = 'fremd'; auswahl.appendChild(o);
    auswahl.value = '99999999';
  });
  await zurPruefung(page);
  await page.getByRole('button', { name: /Meldung absenden/ }).click();
  await expect(page.getByText('Die gewählte Einheit gibt es in dieser Liegenschaft nicht.')).toBeVisible();
});

test('Eine vollständige Meldung geht durch', async ({ page }) => {
  await zumFormular(page);
  await ausfuellen(page);
  await zurPruefung(page);
  await page.getByRole('button', { name: /Meldung absenden/ }).click();
  await expect(page.getByText('Vielen Dank!')).toBeVisible();
});
