import { test, expect, Page } from '@playwright/test';
import { login, goto, warteAufURL } from './helpers';

// Money-Flow H5/H6: Jahresabschluss im echten Klick-Flow — buchen → «Abgeschlossen»
// → zurücknehmen → wieder abschliessbar. Validiert die kanonische Erfolg/Bilanz-
// Berechnung + die Periodensperre-Rücknahme End-to-End (nicht nur im Django-Test).

// Mehrschrittiger Flow (Login + mehrere Navigationen + 2 POST-Rundläufe) — mehr
// Zeit als der 30-s-Default.
test.setTimeout(90_000);

const BILANZ = '/neu/buchhaltung/?jahr=2024&tab=bilanz';

async function gotoBilanz(page: Page) {
  await goto(page, BILANZ);
  await expect(page.locator('#bh-bilanz')).toBeVisible();
}

test('Jahresabschluss: buchen, Abgeschlossen-Status, zurücknehmen, wieder offen', async ({ page }) => {
  page.on('dialog', (d) => d.accept());   // confirm()-Dialoge automatisch bestätigen
  await login(page);
  await gotoBilanz(page);

  const abschliessen = () => page.getByRole('button', { name: /Jahr abschliessen/ });
  const zuruecknehmen = () => page.getByRole('button', { name: /Zurücknehmen/ });

  // Idempotenz bei lokal wiederverwendetem Server: falls schon abgeschlossen,
  // zuerst zurücknehmen, damit wir vom offenen Zustand starten.
  if (await zuruecknehmen().isVisible().catch(() => false)) {
    await zuruecknehmen().click();
    await warteAufURL(page, '**/buchhaltung/**');
    await gotoBilanz(page);
  }

  // --- Abschliessen ---
  await expect(abschliessen()).toBeVisible();
  await abschliessen().click();
  await warteAufURL(page, '**/buchhaltung/**');
  await gotoBilanz(page);

  // Jetzt abgeschlossen: Badge da, «Jahr abschliessen» weg, «Zurücknehmen» da.
  await expect(page.locator('#bh-bilanz')).toContainText(/Abgeschlossen/);
  await expect(abschliessen()).toHaveCount(0);
  await expect(zuruecknehmen()).toBeVisible();

  // --- Zurücknehmen ---
  await zuruecknehmen().click();
  await warteAufURL(page, '**/buchhaltung/**');
  await gotoBilanz(page);

  // Wieder offen: «Jahr abschliessen» erneut vorhanden.
  await expect(abschliessen()).toBeVisible();
});
