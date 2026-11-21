import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// SCHIENE ANHEFTEN (Mix-Entwurf, 21.11.2026): ab 1280 px bleibt das Seitenfeld des aktiven Bereichs offen und schiebt den Inhalt zur Seite.
// Der Wunsch bleibt im Browser. Ohne Anheften verhält sich die Schiene wie bisher (siehe schiene.spec.ts).

test.describe('Schiene anheften', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('Anheften hält das Feld offen, schiebt den Inhalt und bleibt nach dem Seitenwechsel', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const knopf = page.locator('[data-schiene-fest]');
    await expect(knopf).toBeVisible();
    await expect(page.locator('#fwFach')).toBeHidden();
    const vorher = (await page.locator('.fw-haupt').boundingBox())!.x;
    await knopf.click();
    await expect(knopf).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#fwFach')).toBeVisible();
    await expect(page.locator('#fwFach section:visible h2')).toHaveText('Liegenschaften');
    const nachher = (await page.locator('.fw-haupt').boundingBox())!.x;
    expect(nachher, 'Der Inhalt rückt nicht neben das Feld').toBeGreaterThanOrEqual(vorher + 270);
    // Klick daneben und Esc schliessen das angeheftete Feld nicht
    await page.mouse.click(900, 600);
    await page.keyboard.press('Escape');
    await expect(page.locator('#fwFach')).toBeVisible();
    // Seitenwechsel: das Feld des neuen Bereichs ist offen
    await page.locator('#fwFach a[href^="/neu/objekte/"]').first().click();
    await page.waitForURL('**/neu/objekte/**');
    await expect(page.locator('#fwFach')).toBeVisible();
    // Lösen schliesst es wieder
    await page.locator('[data-schiene-fest]').click();
    await expect(page.locator('#fwFach')).toBeHidden();
    expect((await page.locator('.fw-haupt').boundingBox())!.x).toBeLessThan(nachher - 200);
  });

  test('Unter 1280 px gibt es den Knopf nicht', async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await expect(page.locator('[data-schiene-fest]')).toBeHidden();
  });
});
