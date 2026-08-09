import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Money-Flow G: Die NK-Periode enthält eine Einheit ohne Fläche + einen
// m²-Beleg → die Abrechnung muss vor der fehlenden Fläche warnen (Warnbanner).
// Validiert die `warnungen`-Ausgabe der kanonischen Engine im echten Rendering.

test('NK-Abrechnung warnt vor fehlender Fläche', async ({ page }) => {
  await login(page);
  // Von der NK-Übersicht zur gesäten Periode navigieren. Die Zeile ist eine
  // klickbare <tr onclick="window.location=…"> (kein <a>), also den Text klicken.
  await goto(page, '/neu/nebenkosten/');
  await page.getByText('NK E2E 2024').first().click();
  await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
  // Warnbanner sichtbar (Text aus core/utils/billing.py: „Fläche (m²) fehlt bei").
  await expect(page.locator('body')).toContainText(/Fläche.*(fehlt|nicht)/i);
  await expect(page.locator('body')).toContainText(/Keller E2E/);   // die flächenlose Einheit
});
