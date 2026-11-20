import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// HANDY-TABLEISTE (Mix-Entwurf, 20.11.2026): unten am Telefon, sonst aus. Sie ist eine zweite Tür zu denselben Zielen,
// «Mehr» öffnet die bestehende Schublade mit ALLEN Bereichen — es geht nichts verloren.

test.describe('Tableiste am Telefon', () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test('Heute, Schäden, Neu, Finanzen und Mehr stehen unten; Ziele sind gross genug', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const leiste = page.locator('#fwTabbar');
    await expect(leiste).toBeVisible();
    const box = (await leiste.boundingBox())!;
    expect(Math.round(box.y + box.height), 'Die Leiste steht nicht am unteren Rand').toBe(800);
    await expect(leiste.locator('a.fw-tab[href^="/neu/"]')).toHaveCount(4); // Heute, Schäden, Neu, Finanzen
    await expect(leiste.locator('[data-tab-mehr]')).toBeVisible();
    for (const t of await leiste.locator('.fw-tab').all()) {
      const b = (await t.boundingBox())!;
      expect(b.width, 'Tippfläche zu schmal').toBeGreaterThanOrEqual(44);
      expect(b.height, 'Tippfläche zu niedrig').toBeGreaterThanOrEqual(44);
    }
    // Die Leiste verdeckt das Seitenende nicht
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const letzte = await page.evaluate(() => {
      const h = document.querySelector('.fw-haupt')!.getBoundingClientRect();
      return h.bottom;
    });
    expect(letzte, 'Inhalt endet unter der Leiste').toBeGreaterThanOrEqual(box.y);
  });

  test('«Mehr» öffnet die Schublade mit allen Bereichen; Heute führt auf die Startseite', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.locator('[data-tab-mehr]').click();
    await expect(page.locator('#fwSchiene')).toHaveClass(/offen/);
    for (const k of ['heute', 'betrieb', 'akten', 'kontakte', 'laeufe', 'finanzen', 'berichte']) {
      await expect(page.locator(`#fwSchiene a[data-fach="${k}"]`)).toBeVisible();
    }
    await page.keyboard.press('Escape');
    await page.locator('#fwTabbar a.fw-tab', { hasText: 'Heute' }).click();
    await page.waitForURL('**/neu/');
  });

  test('Der aktive Bereich leuchtet in der Leiste', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    await expect(page.locator('#fwTabbar a.fw-tab.hier')).toHaveAttribute('href', /\/neu\/finanzen\//);
  });
});

test.describe('Tableiste am PC', () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  test('Am PC und Tablet gibt es keine Tableiste', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await expect(page.locator('#fwTabbar')).toBeHidden();
  });
});
