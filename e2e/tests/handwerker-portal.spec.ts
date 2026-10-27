import { test, expect, Browser, Page } from '@playwright/test';
import { login, goto } from './helpers';

// HANDWERKERPORTAL (Modul 3, E6) — DER GANZE WEG, AM TELEFON
//
// 1. Die Verwaltung erzeugt im Reiter «Handwerker» des Schadens einen Link.
//    Der Klartext steht nur auf dieser einen Antwortseite; die Spec liest ihn
//    dort ab, so wie ihn ein Mensch kopieren würde. Ein fester Token im Seed
//    wäre ein Geheimnis im Quelltext.
// 2. Der Handwerker öffnet ihn OHNE Anmeldung in einem eigenen Browser-
//    Kontext bei 390 × 844: Auftrag sehen, Termin bestätigen, Offerte und
//    Rechnung hochladen, «erledigt» melden.
// 3. Ein falscher Link ergibt 404, die Schutzköpfe stehen in der Antwort.
//
// Daten aus `seed_e2e` (Block «Modul 3»): Meldung «E2E Wasserhahn tropft» mit
// Auftrag an «E2E Sanitär Huber» und vereinbartem Termin.

const TELEFON = { width: 390, height: 844 };
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n');

test.describe.configure({ mode: 'serial' });

let link = '';

async function quer(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
}

/** Öffnet den Reiter «Handwerker» der Seed-Meldung. Die Liste öffnet Akten
 *  im Modal (`fwModalOpenUrl`); die Id steht im `onclick` der Zeile. */
async function handwerkerReiter(page: Page) {
  await goto(page, '/neu/schaeden/');
  const zeile = page.locator('.fw-zeile.klick', { hasText: 'E2E Wasserhahn tropft' }).first();
  const id = /\/neu\/schaeden\/(\d+)\//.exec((await zeile.getAttribute('onclick')) || '')![1];
  await goto(page, `/neu/schaeden/${id}/?tab=handwerker`);
}

async function handwerkerSeite(browser: Browser) {
  const kontext = await browser.newContext({ viewport: TELEFON, locale: 'de-CH',
    extraHTTPHeaders: { 'Accept-Language': 'de-CH,de;q=0.9' } });
  return { kontext, page: await kontext.newPage() };
}

test('Verwaltung erzeugt den Link im Reiter «Handwerker»', async ({ page }) => {
  await login(page);
  await handwerkerReiter(page);
  const block = page.locator('[data-link-status]').first();
  await expect(block).toHaveAttribute('data-link-status', 'kein');
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    block.getByRole('button', { name: /Link erzeugen/ }).click()]);
  link = await page.locator('#hw-link').inputValue();
  expect(link).toMatch(/\/auftrag\/[A-Za-z0-9_-]{43}\/$/);
});

test('Handwerker sieht den Auftrag ohne Anmeldung, bei 390 Pixel', async ({ browser }) => {
  const { kontext, page } = await handwerkerSeite(browser);
  const pfad = new URL(link).pathname;
  const antwort = await page.goto(pfad, { waitUntil: 'domcontentloaded' });
  expect(antwort!.status()).toBe(200);
  expect(antwort!.headers()['x-robots-tag']).toContain('noindex');
  expect(antwort!.headers()['referrer-policy']).toBe('no-referrer');
  expect(antwort!.headers()['cache-control']).toContain('no-store');
  await expect(page.locator('#hw-titel')).toHaveText('E2E Wasserhahn tropft');
  await expect(page.getByText('E2E-Weg 1, 8000 Zürich')).toBeVisible();
  await expect(page.getByText('079 000 11 22')).toBeVisible();
  await expect(page.locator('nav')).toHaveCount(0);               // keine Navigation
  expect(await quer(page)).toBeLessThanOrEqual(0);
  await kontext.close();
});

test('Termin bestätigen, Offerte und Rechnung hochladen, erledigt melden', async ({ browser }) => {
  const { kontext, page } = await handwerkerSeite(browser);
  const pfad = new URL(link).pathname;
  await page.goto(pfad, { waitUntil: 'domcontentloaded' });

  await Promise.all([page.waitForLoadState('domcontentloaded'),
    page.getByRole('button', { name: 'Termin bestätigen' }).click()]);
  await expect(page.getByRole('status')).toContainText('Termin bestätigt');

  const offerte = page.locator('[data-karte="offerte"]');
  await offerte.locator('input[name="betrag"]').fill('1840');
  await offerte.locator('input[name="datei"]').setInputFiles({ name: 'offerte.pdf', mimeType: 'application/pdf', buffer: PDF });
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    offerte.getByRole('button', { name: 'Offerte senden' }).click()]);
  await expect(page.getByRole('status')).toContainText('Freigabe der Eigentümerschaft');

  // Falscher Dateityp: abgelehnt, keine Rechnung.
  const rechnung = page.locator('[data-karte="rechnung"]');
  await rechnung.locator('input[name="betrag"]').fill('1840');
  await rechnung.locator('input[name="datei"]').setInputFiles({ name: 'rechnung.html', mimeType: 'text/html', buffer: Buffer.from('<b>x</b>') });
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    rechnung.getByRole('button', { name: 'Rechnung senden' }).click()]);
  await expect(page.getByRole('alert')).toBeVisible();

  await rechnung.locator('input[name="betrag"]').fill('1840');
  await rechnung.locator('input[name="datei"]').setInputFiles({ name: 'rechnung.pdf', mimeType: 'application/pdf', buffer: PDF });
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    rechnung.getByRole('button', { name: 'Rechnung senden' }).click()]);
  await expect(page.getByRole('status')).toContainText('Rechnung erhalten');
  await expect(rechnung).toContainText('Die Rechnung ist eingegangen');

  await Promise.all([page.waitForLoadState('domcontentloaded'),
    page.getByRole('button', { name: 'Arbeit erledigt melden' }).click()]);
  await expect(page.getByRole('status')).toContainText('Verwaltung ist informiert');
  expect(await quer(page)).toBeLessThanOrEqual(0);
  await kontext.close();
});

test('Ein falscher Link ergibt 404', async ({ browser }) => {
  const { kontext, page } = await handwerkerSeite(browser);
  const falsch = await page.goto('/auftrag/' + 'x'.repeat(43) + '/', { waitUntil: 'domcontentloaded' });
  expect(falsch!.status()).toBe(404);
  await kontext.close();
});

test('Widerrufen macht den Link tot', async ({ page, browser }) => {
  await login(page);
  await handwerkerReiter(page);
  await page.locator('[data-link-status]').first().getByRole('button', { name: 'Link widerrufen' }).click();
  // Rückfrage über den gestalteten Dialog (fw/_bestaetigen.html).
  const dialog = page.locator('#fwBestaetigen');
  await dialog.waitFor({ state: 'visible' });
  await Promise.all([page.waitForEvent('framenavigated'), dialog.locator('#fwBestaetigenJa').click()]);
  await page.waitForLoadState('domcontentloaded');

  const { kontext, page: hw } = await handwerkerSeite(browser);
  const antwort = await hw.goto(new URL(link).pathname, { waitUntil: 'domcontentloaded' });
  expect(antwort!.status()).toBe(404);
  await kontext.close();
});
