import { test, expect, Page } from '@playwright/test';
import { login, goto, warteAufURL, bestaetigen } from './helpers';

// Money-Flow H5/H6: Jahresabschluss im echten Klick-Flow — buchen → «Abgeschlossen»
// → zurücknehmen → wieder abschliessbar. Validiert die kanonische Erfolg/Bilanz-
// Berechnung + die Periodensperre-Rücknahme End-to-End (nicht nur im Django-Test).

// Mehrschrittiger Flow (Login + mehrere Navigationen + 2 POST-Rundläufe) — mehr
// Zeit als der 30-s-Default.
test.setTimeout(90_000);

const BILANZ = '/neu/buchhaltung/?jahr=2024&tab=bilanz';

async function anmeldenAls(page: Page, name: string) {
  await page.context().clearCookies();
  await goto(page, '/login/');
  await page.fill('input[name="username"]', name);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

async function gotoBilanz(page: Page) {
  await goto(page, BILANZ);
  await expect(page.locator('#bh-bilanz')).toBeVisible();
}

test('Jahresabschluss: buchen, Abgeschlossen-Status, zurücknehmen, wieder offen', async ({ page }) => {
  // Rückfragen erscheinen im Bestätigungsdialog der App (fw/_bestaetigen.html),
  // nicht mehr als Browser-confirm() — bestätigt wird per Klick, siehe bestaetigen().
  await login(page);
  await gotoBilanz(page);

  const abschliessen = () => page.getByRole('button', { name: /Jahr abschliessen/ });
  const zuruecknehmen = () => page.getByRole('button', { name: /Zurücknehmen/ });

  // Die Periodensperre zu lockern braucht eine zweite Person (Vier-Augen-Prinzip):
  // Die erste Rücknahme stellt den Antrag, e2e-zweiter (Verwalter) gibt ihn unter
  // «Anlagen & Abschluss» frei, danach gelingt die Rücknahme.
  const zuruecknehmenMitZweiterPerson = async () => {
    await zuruecknehmen().click();
    await bestaetigen(page);
    await warteAufURL(page, '**/buchhaltung/**');
    await anmeldenAls(page, 'e2e-zweiter');
    await goto(page, '/neu/anlagen/');
    await page.getByRole('button', { name: 'Freigeben' }).first().click();
    await expect(page.getByText('Entscheid gespeichert')).toBeVisible();
    await anmeldenAls(page, 'e2e');
    await gotoBilanz(page);
    await zuruecknehmen().click();
    await bestaetigen(page);
    await warteAufURL(page, '**/buchhaltung/**');
    await gotoBilanz(page);
  };

  // Idempotenz bei lokal wiederverwendetem Server: falls schon abgeschlossen,
  // zuerst zurücknehmen, damit wir vom offenen Zustand starten.
  if (await zuruecknehmen().isVisible().catch(() => false)) {
    await zuruecknehmenMitZweiterPerson();
  }

  // --- Abschliessen ---
  await expect(abschliessen()).toBeVisible();
  await abschliessen().click();
  await bestaetigen(page);
  await warteAufURL(page, '**/buchhaltung/**');
  await gotoBilanz(page);

  // Jetzt abgeschlossen: Badge da, «Jahr abschliessen» weg, «Zurücknehmen» da.
  await expect(page.locator('#bh-bilanz')).toContainText(/Abgeschlossen/);
  await expect(abschliessen()).toHaveCount(0);
  await expect(zuruecknehmen()).toBeVisible();

  // --- Zurücknehmen (mit zweiter Person) ---
  await zuruecknehmenMitZweiterPerson();

  // Wieder offen: «Jahr abschliessen» erneut vorhanden.
  await expect(abschliessen()).toBeVisible();
});
