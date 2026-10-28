import { test, expect, Page } from '@playwright/test';
import { goto, login, warteAufURL } from './helpers';

// FEHLERSEITEN UND KOPFZEILE JE ROLLE (28.10.2026, DESIGN-01/02, ROUTE-03/10/13)
//
// Im Browser geprüft, was sich nicht aus dem Quelltext lesen lässt: ob «Neuer Fall» auf einer Seite
// ohne Schublade (fwModalOpen nicht geladen) einen Fehler wirft, ob die Hauswartung im Hintergrund eine
// 403-Anfrage sendet, und wohin «Zur Übersicht» auf der 403-Seite wirklich führt.

async function anmelden(page: Page, benutzer: string) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', benutzer);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

test.describe('«Neuer Fall» im Kopf', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('auf einer Seite ohne Schublade führt der Knopf auf die Vollseite, ohne Skriptfehler', async ({ page }) => {
    const fehler: string[] = [];
    page.on('pageerror', (e) => fehler.push(e.message));
    await login(page);
    await goto(page, '/neu/personen/');
    expect(await page.evaluate(() => typeof (window as any).fwModalOpen), 'Die Seite sollte die Schublade nicht laden').toBe('undefined');
    await Promise.all([warteAufURL(page, '**/neu/faelle/neu/**'), page.locator('a.fw-wz-neu').click()]);
    await expect(page).toHaveURL(/\/neu\/faelle\/neu\//);
    expect(fehler.filter((m) => /fwModalOpen/.test(m)), 'ReferenceError: fwModalOpen').toEqual([]);
  });

  test('auf einer Seite mit Schublade öffnet derselbe Knopf die Schublade', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/vertraege/');
    expect(await page.evaluate(() => typeof (window as any).fwModalOpen)).toBe('function');
    await page.locator('a.fw-wz-neu').click();
    await expect(page.locator('#fwModal')).toBeVisible();
    await expect(page).toHaveURL(/\/neu\/vertraege\//);        // die Seite dahinter bleibt
  });
});

test.describe('Die Hauswartung', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('Die Kopfzeile bietet nur Erlaubtes an und sendet keine 403-Anfrage', async ({ page }) => {
    const verboten: string[] = [];
    page.on('response', (r) => { if (r.status() === 403) verboten.push(r.url()); });
    await anmelden(page, 'e2e-hauswart');
    await goto(page, '/neu/schaeden/');
    await page.waitForTimeout(800);                            // Zeit für die Zähler-Abfrage, falls sie käme
    expect(verboten, '403 im Hintergrund (z. B. /neu/leistenzahlen/)').toEqual([]);
    for (const sel of ['a.fw-wz-neu', 'a[href^="/neu/zulauf/"]', '.fw-werkzeug-kapsel a[href^="/neu/einstellungen/"]',
      '.fw-krumen a[href^="/neu/liegenschaften/"]']) {
      await expect(page.locator(sel), sel).toHaveCount(0);
    }
    // Das Logo führt auf die eigene Startseite, nicht in eine 403-Seite.
    await page.locator('#fwKopf .fw-logo-kapsel').click();
    await expect(page).toHaveURL(/\/neu\/schaeden\//);
    await expect(page.locator('body')).not.toContainText('Dafür fehlt Ihrer Rolle die Berechtigung');
  });

  test('Die 403-Seite führt zurück auf die Schadenliste, nicht in eine Schleife', async ({ page }) => {
    await anmelden(page, 'e2e-hauswart');
    await goto(page, '/neu/faelle/neu/');
    await expect(page.locator('body')).toContainText('Dafür fehlt Ihrer Rolle die Berechtigung');
    await Promise.all([warteAufURL(page, '**/neu/schaeden/**'), page.getByRole('link', { name: 'Zur Übersicht' }).click()]);
    await expect(page).toHaveURL(/\/neu\/schaeden\//);
    await expect(page.locator('body')).not.toContainText('Dafür fehlt Ihrer Rolle die Berechtigung');
  });
});

test.describe('Das Mieterportal', () => {
  test('Die 403-Seite führt ins Mieterportal', async ({ page }) => {
    await anmelden(page, 'e2e-mieter');
    await goto(page, '/neu/');
    await expect(page.locator('body')).toContainText('Dafür fehlt Ihrer Rolle die Berechtigung');
    await Promise.all([warteAufURL(page, '**/mieter/**'), page.getByRole('link', { name: 'Zur Übersicht' }).click()]);
    await expect(page).toHaveURL(/\/mieter\//);
    await expect(page.locator('body')).not.toContainText('Dafür fehlt Ihrer Rolle die Berechtigung');
  });
});
