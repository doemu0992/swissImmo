import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Deeper Flow: Die Buchhaltungsseite muss den gesäten Mietertrag 2024 in der
// Erfolgsrechnung ausweisen und den Jahresabschluss-Bereich anbieten. Das
// prüft die kanonische Erfolg/Bilanz-Berechnung (Fix H5/H6) im echten Rendering.

test('Erfolgsrechnung zeigt den gesäten Mietertrag 2024', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/buchhaltung/?jahr=2024');
  await expect(page.locator('body')).toContainText(/Erfolgsrechnung|Ertrag/i);
  // Der Seed bucht CHF 1'500 Mietertrag auf Konto 3000 im Jahr 2024
  // (chf-Filter nutzt Schweizer Apostroph als Tausendertrenner).
  await expect(page.locator('body')).toContainText(/1['’]500/);
  // Der Jahresabschluss-Bereich ist vorhanden (Bilanz-Panel).
  await expect(page.locator('body')).toContainText(/Jahresabschluss/i);
});
