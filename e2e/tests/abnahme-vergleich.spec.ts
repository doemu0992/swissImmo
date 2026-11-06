import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ABNAHME VOR ORT: Vergleich mit dem Vorzustand (6.11.2026)
//
// Beim Bewerten eines Bauteils steht unter der Ampel «gleich geblieben», «schlechter» oder «besser» — gerechnet im
// Browser aus dem Rang des Vorzustands (`data-vor-rang`, vom Server). Telefon (390 x 844), wo die Seite lebt.
// Daten: `seed_e2e_abnahme` (Einheit «1.5 Zi E2E Vergleich», Einzug abgeschlossen, Auszug offen).

test.use({ viewport: { width: 390, height: 844 } });

test.describe('Abnahme vor Ort: Vergleich mit dem Vorzustand', () => {
  test('Die Zeile folgt der Bewertung des Bauteils', async ({ page }) => {
    await login(page);
    await page.goto('/neu/objekte/');
    await page.locator('a', { hasText: '1.5 Zi E2E Vergleich' }).first().click();
    await page.waitForLoadState('domcontentloaded');
    await page.goto(page.url().replace(/[?#].*$/, '') + '?tab=dokumente');
    // Einzug und Auszug stehen unter «Abnahmen»; der Auszug ist der später angelegte (höhere ID).
    const ids = await page.locator('a[href^="/neu/abnahme/"]').evaluateAll((a) =>
      (a as HTMLAnchorElement[]).map((x) => (x.getAttribute('href') || '').match(/^\/neu\/abnahme\/(\d+)\/$/)?.[1])
        .filter(Boolean).map(Number));
    expect(ids.length, 'Abnahmen der Einheit nicht gefunden').toBeGreaterThanOrEqual(2);
    await page.goto(`/neu/abnahme/${Math.max(...ids)}/vorort/`);
    const karte = page.locator('.vo-karte').filter({ hasText: 'Teppich' }).first();   // Vorzustand: normale Abnutzung (Rang 1)
    const zeile = karte.locator('[data-vergleich]');
    await expect(zeile).toBeHidden();                       // noch nicht bewertet
    await karte.locator('.vo-ampel [data-zustand="uebermaessig"]').click();
    await expect(zeile).toHaveText('schlechter');
    await karte.locator('.vo-ampel [data-zustand="normal"]').click();
    await expect(zeile).toHaveText('gleich geblieben');
    await karte.locator('.vo-ampel [data-zustand="io"]').click();
    await expect(zeile).toHaveText('besser');
  });
});
