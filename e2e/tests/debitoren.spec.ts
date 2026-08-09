import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Money-Flow: Die gesäte offene Debitorenrechnung (CHF 1'700, fällig 05.2024 →
// längst überfällig) muss in der Debitorenliste mit Betrag + Mieter erscheinen
// und im Mahnwesen als überfällig auftauchen. Validiert die offener_betrag-
// Berechnung und die Aging/Mahn-Darstellung im echten Rendering.

test('offene Rechnung erscheint in Debitoren und Mahnwesen', async ({ page }) => {
  await login(page);

  await goto(page, '/neu/debitoren/');
  await expect(page.locator('body')).toContainText(/E2E/);           // Mieter Erika E2E
  await expect(page.locator('body')).toContainText(/1['’]700/);      // offener Betrag (chf-Format)

  await goto(page, '/neu/mahnwesen/');
  await expect(page.locator('body')).toContainText(/E2E/);           // überfälliger Mieter gelistet
});
