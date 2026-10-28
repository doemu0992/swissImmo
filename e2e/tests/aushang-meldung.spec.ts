import { test, expect, Page } from '@playwright/test';
import { goto } from './helpers';

// Der QR-Aushang im Treppenhaus (`/report/<id>/`) prüft jetzt auf dem SERVER
// (SICH-08, ROUTE-04, Audit 28.10.2026).
//
// Vorher legte ein leeres Formular das Ticket «None ()» an, eine fremde oder
// nicht-numerische `einheit_id` ging durch (oder ergab 500), und 30 Absendungen
// in Folge ergaben 30 Tickets mit Bestätigungsmail. Der Browser verhindert das
// mit `required` nur für Menschen mit einem Browser. Diese Spec entfernt die
// Browser-Prüfung ausdrücklich und sieht nach, was der Server tut — und dass
// die Seite nach einem Fehler benutzbar bleibt: Meldung sichtbar, Eingaben
// da, Formularschritt offen statt zurück auf der Startkachel.
//
// Höchstens drei Absendungen je Lauf: Die Drossel zählt zehn je IP und Stunde
// und lebt so lange wie der Serverprozess.

async function zumFormular(page: Page) {
  await goto(page, '/report/1/');
  // Der Ladevorhang geht spätestens nach 3 s (Notausgang im Template).
  await page.waitForTimeout(3500);
  await page.getByText('Allgemeine Anfrage', { exact: true }).click();
  await expect(page.locator('textarea[name="beschreibung"]')).toBeVisible();
}

async function ausfuellen(page: Page, ueberschreibe: Record<string, string> = {}) {
  const werte: Record<string, string> = {
    vorname: 'Vera', nachname: 'Muster', email: 'vera@example.ch', telefon: '0791234567',
    beschreibung: 'Die Tür im Treppenhaus schliesst nicht mehr.', ...ueberschreibe,
  };
  for (const [name, wert] of Object.entries(werte)) {
    await page.locator(`[name="${name}"]`).fill(wert);
  }
}

/** Nimmt dem Browser die eigene Prüfung — wie ein Skript, das nur POSTet. */
async function browserpruefungAus(page: Page) {
  await page.evaluate(() => {
    document.querySelectorAll('form [required]').forEach((el) => el.removeAttribute('required'));
    const form = document.querySelector('form');
    if (form) form.setAttribute('novalidate', '');
  });
}

test('Ohne Pflichtfelder meldet der Server den Fehler, die Eingaben bleiben', async ({ page }) => {
  await zumFormular(page);
  await browserpruefungAus(page);
  await ausfuellen(page, { beschreibung: '', email: '' });
  await page.getByRole('button', { name: /Meldung absenden/ }).click();

  await expect(page.getByText('Ihre Meldung wurde noch nicht gesendet.')).toBeVisible();
  await expect(page.getByText('Bitte füllen Sie das Feld «Beschreibung» aus.')).toBeVisible();
  await expect(page.getByText('Bitte füllen Sie das Feld «E-Mail» aus.')).toBeVisible();
  // Nicht zurück auf der ersten Kachel, sondern im Formular — mit dem, was getippt war.
  await expect(page.locator('input[name="vorname"]')).toHaveValue('Vera');
  await expect(page.locator('input[name="telefon"]')).toHaveValue('0791234567');
  await expect(page.locator('input[name="nachname"]')).toBeVisible();
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
  await page.getByRole('button', { name: /Meldung absenden/ }).click();
  await expect(page.getByText('Die gewählte Einheit gibt es in dieser Liegenschaft nicht.')).toBeVisible();
});

test('Eine vollständige Meldung geht durch', async ({ page }) => {
  await zumFormular(page);
  await ausfuellen(page);
  await page.getByRole('button', { name: /Meldung absenden/ }).click();
  await expect(page.getByText('Vielen Dank!')).toBeVisible();
});
