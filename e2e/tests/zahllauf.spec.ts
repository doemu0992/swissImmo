import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Money-Flow: Die gesäte freigegebene Kreditorenrechnung (mit IBAN) muss im
// Zahllauf-Vorschlag erscheinen. Validiert die Zahllauf-Auswahlliste + das
// IBAN-Gating im echten Rendering (H8/H9).

test('freigegebener Kreditor erscheint im Zahllauf-Vorschlag', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/zahllauf/');
  await expect(page.locator('body')).toContainText(/E2E Sanitär AG/);   // Lieferant im Vorschlag
  await expect(page.locator('body')).toContainText(/800/);              // offener Betrag
});
