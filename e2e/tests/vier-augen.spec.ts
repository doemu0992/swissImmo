import { test, expect, Page } from '@playwright/test';
import { goto, warteAufURL } from './helpers';

// DIE BUCHHALTUNG UND DAS VIER-AUGEN-PRINZIP (Etappe 2)
//
// Die Buchhaltung (e2e-buchhaltung) sieht nur Finanzen. Eine Lieferantenzahlung
// ab CHF 5'000 («E2E Bau AG», CHF 12'000) löst sie nicht allein aus: Sie legt
// die Zahlung vor, ein zweiter Verwalter (e2e-zweiter) gibt sie frei, erst dann
// erscheint «Bezahlen». Prüfbreite ist das Telefon (390 px).
//
// Der Seed (`seed_e2e`) legt beide Konten und die Rechnung an.

async function anmelden(page: Page, name: string) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', name);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

async function keinQuerscrollen(page: Page) {
  const breiter = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(breiter, 'Die Seite scrollt quer').toBeLessThanOrEqual(1);
}

test.describe('Die Buchhaltung am Telefon (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('Startseite sind die Finanzen, Stammdaten sind zu', async ({ page }) => {
    await anmelden(page, 'e2e-buchhaltung');
    await expect(page).toHaveURL(/\/neu\/finanzen\//);
    await keinQuerscrollen(page);
    // Keine Akten-Bereiche in der Navigation, keine Einstellungen
    await expect(page.locator('#fwHauptnav a', { hasText: 'Akten' })).toHaveCount(0);
    const antwort = await page.goto('/neu/personen/', { waitUntil: 'domcontentloaded' });
    expect(antwort?.status()).toBe(403);
  });

  test('Zahlung ab dem Limit: vorlegen, zweite Person gibt frei, dann bezahlen', async ({ page }) => {
    await anmelden(page, 'e2e-buchhaltung');
    await goto(page, '/neu/kreditoren/?q=E2E+Bau');
    const zeile = page.locator('tr', { hasText: 'E2E Bau AG' }).first();
    await expect(zeile).toContainText('Freigabe nötig');
    await expect(zeile.locator('form[action="/neu/kreditoren/bezahlen/"]')).toHaveCount(0);
    await keinQuerscrollen(page);

    await zeile.getByRole('button', { name: 'Zur Freigabe vorlegen' }).click();
    await expect(page.locator('tr', { hasText: 'E2E Bau AG' }).first()).toContainText('wartet auf eine zweite Person');
    // Die vorlegende Person kann nicht selbst freigeben
    await expect(page.getByRole('button', { name: 'Zahlung freigeben' })).toHaveCount(0);

    // Zweite Person
    await page.context().clearCookies();
    await anmelden(page, 'e2e-zweiter');
    await goto(page, '/neu/kreditoren/?q=E2E+Bau');
    await expect(page.locator('.fw-hinweis', { hasText: 'wartet auf Ihre Freigabe' })).toBeVisible();
    const freigeben = page.locator('tr', { hasText: 'E2E Bau AG' }).first().getByRole('button', { name: 'Zahlung freigeben' });
    await freigeben.click();
    // Bestätigungsdialog der App
    await page.getByRole('button', { name: 'Bestätigen' }).click();
    await expect(page.locator('tr', { hasText: 'E2E Bau AG' }).first()).toContainText('Zahlung freigegeben');

    // Erst jetzt ist «Bezahlen» da (für die Buchhaltung)
    await page.context().clearCookies();
    await anmelden(page, 'e2e-buchhaltung');
    await goto(page, '/neu/kreditoren/?q=E2E+Bau');
    await expect(page.locator('tr', { hasText: 'E2E Bau AG' }).first()
      .locator('form[action="/neu/kreditoren/bezahlen/"]')).toHaveCount(1);
  });
});
