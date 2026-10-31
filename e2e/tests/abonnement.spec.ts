import { test, expect, Page } from '@playwright/test';
import { goto, warteAufURL } from './helpers';

// Funktionsfreigabe (Etappe 4): Sperrseite statt 403, Daten bleiben lesbar, Lesemodus sperrt das
// Schreiben, Abo-Seite bei 390 px ohne horizontales Scrollen. Die Daten kommen aus
// `manage.py seed_e2e_abo` (run-server.sh).

async function anmelden(page: Page, benutzer: string) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', benutzer);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

async function ohneQuerlauf(page: Page) {
  const breiter = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(breiter, 'horizontales Scrollen bei 390 px').toBeFalsy();
}

async function postMitCsrf(page: Page, pfad: string) {
  return page.evaluate(async (p) => {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    const r = await fetch(p, { method: 'POST', headers: { 'X-CSRFToken': m ? m[1] : '' }, body: new URLSearchParams({}), credentials: 'same-origin' });
    return { status: r.status, text: await r.text() };
  }, pfad);
}

test.describe('Funktionsfreigabe', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('Stufe Start: Modul gesperrt mit Hinweis, Daten lesbar, Abo-Seite ohne Querlauf', async ({ page }) => {
    await anmelden(page, 'e2e-abo');

    // Lesen geht, mit Hinweis und Weg zum Upgrade.
    await goto(page, '/neu/stweg/');
    await expect(page.getByText('nicht im Abonnement').first()).toBeVisible();
    await expect(page.locator('a[href="/neu/abonnement/"]').first()).toBeVisible();

    // Schreiben im Modul: klare Seite, kein 403-Rätsel.
    const schreiben = await postMitCsrf(page, '/neu/stweg/1/aufgabe/neu/');
    expect(schreiben.status).toBe(402);
    expect(schreiben.text).toContain('nicht im Abonnement');

    // Import ist ganz gesperrt, der Export bleibt offen.
    await goto(page, '/neu/einstellungen/daten/import/');
    await expect(page.getByRole('heading', { name: /nicht im Abonnement/ })).toBeVisible();
    await ohneQuerlauf(page);
    await page.getByRole('link', { name: 'Zum Abonnement' }).click();
    await expect(page).toHaveURL(/\/neu\/abonnement\//);
    await expect(page.getByRole('heading', { name: 'Ihr Abonnement' })).toBeVisible();
    await expect(page.getByText('vom Betreiber festzulegen').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Nutzung' })).toBeVisible();
    await ohneQuerlauf(page);

    // Downgrade-Folgen werden gezeigt, bevor etwas geschieht (Plan ist bereits Start: Team -> Start
    // gibt es hier nicht; die Bestätigung kommt beim Wechsel von einer höheren Stufe).
    await goto(page, '/neu/einstellungen/daten/export/');
    await expect(page).toHaveURL(/\/export\//);
  });

  test('Lesemodus: Hinweis, Lesen geht, Schreiben gesperrt, Abo-Seite bleibt bedienbar', async ({ page }) => {
    await anmelden(page, 'e2e-lese');
    await goto(page, '/neu/liegenschaften/');
    await expect(page.getByText('schreibgeschützt').first()).toBeVisible();
    await ohneQuerlauf(page);

    const schreiben = await postMitCsrf(page, '/neu/personen/neu/');
    expect(schreiben.status).toBe(402);
    expect(schreiben.text).toContain('schreibgeschützt');

    await goto(page, '/neu/abonnement/');
    await expect(page.getByRole('heading', { name: 'Rechnungen' })).toBeVisible();
    await expect(page.getByRole('link', { name: /PDF mit QR-Rechnung/ }).first()).toBeVisible();
    await ohneQuerlauf(page);
  });
});
