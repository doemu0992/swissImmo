import { test, expect, Browser, Page } from '@playwright/test';
import { login, goto, warteAufURL } from './helpers';

// DIREKTKANAL MIETER <-> HANDWERKER UND TERMINABSTIMMUNG — DER GANZE WEG, BEI 390 PIXEL
//
// Daten aus `seed_e2e_direkt`: Ticket «E2E Direkt Heizung» (von e2e-mieter gemeldet) mit Auftrag an
// «E2E Direkt Sanitär» und einer Nachricht des Handwerkers; «E2E Fremd Ticket» einer anderen Mieterin.
//
// 1. Die Verwaltung erzeugt den Handwerker-Link (wie in handwerker-portal.spec.ts; ein fester Token im Seed
//    wäre ein Geheimnis im Quelltext).
// 2. Die Mieterin schreibt im Portal eine Nachricht — sie erscheint.
// 3. Der Handwerker liest sie auf /auftrag/<token>/ und schlägt einen Termin vor (noch NICHT vereinbart).
// 4. Die Mieterin bestätigt im Portal: «Vereinbart» ist sichtbar, auch auf der Seite des Handwerkers.
// 5. Das Ticket der anderen Mieterin ergibt 404.
//
// Name «zz-…», weil die Spec den Bestand ändert und auf den Seed-Daten besteht; serial, weil die Schritte
// aufeinander aufbauen. Beim zweiten Lauf auf derselben Datenbank steht der Termin schon: die Spec setzt
// eine frische Datenbank voraus (run-server.sh legt sie jedes Mal neu an).

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON });
test.describe.configure({ mode: 'serial' });

let link = '';
let fremdId = '';
const NACHRICHT = 'Ich bin am Dienstag zuhause, Schluessel liegt beim Nachbarn.';

async function quer(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
}

async function ticketId(page: Page, titel: string) {
  await goto(page, '/neu/schaeden/');
  const zeile = page.locator('.fw-zeile.klick', { hasText: titel }).first();
  return /\/neu\/schaeden\/(\d+)\//.exec((await zeile.getAttribute('onclick')) || '')![1];
}

async function mieterLogin(page: Page) {
  await goto(page, '/portal/login/');
  await page.fill('input[name="username"]', 'e2e-mieter');
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([
    warteAufURL(page, '**/mieter/**'),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
}

async function handwerkerSeite(browser: Browser) {
  const kontext = await browser.newContext({ viewport: TELEFON, locale: 'de-CH',
    extraHTTPHeaders: { 'Accept-Language': 'de-CH,de;q=0.9' } });
  return { kontext, page: await kontext.newPage() };
}

/** Das Ticket der Mieterin im Portal öffnen (über die Liste, wie ein Mensch). */
async function mieterTicket(page: Page) {
  await goto(page, '/mieter/tickets/');
  await Promise.all([warteAufURL(page, '**/mieter/ticket/*/'),
    page.getByText('E2E Direkt Heizung').first().click()]);
  return page.locator('[data-karte="direkt"]');
}

test('Verwaltung erzeugt den Handwerker-Link', async ({ page }) => {
  await login(page);
  fremdId = await ticketId(page, 'E2E Fremd Ticket');
  const id = await ticketId(page, 'E2E Direkt Heizung');
  await goto(page, `/neu/schaeden/${id}/?tab=handwerker`);
  const block = page.locator('[data-link-status]').first();
  await expect(block).toHaveAttribute('data-link-status', 'kein');
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    block.getByRole('button', { name: /Link erzeugen/ }).click()]);
  link = await page.locator('#hw-link').inputValue();
  expect(link).toMatch(/\/auftrag\/[A-Za-z0-9_-]{43}\/$/);
});

test('Mieterin schreibt im Portal eine Nachricht, sie erscheint', async ({ page }) => {
  await mieterLogin(page);
  const karte = await mieterTicket(page);
  await expect(karte.locator('[data-block="chat"]')).toContainText('Guten Tag, wann passt es Ihnen?');
  await expect(karte.locator('[data-block="terminabstimmung"]')).toContainText('Noch kein Termin vereinbart');
  await karte.locator('textarea[name="text"]').fill(NACHRICHT);
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    karte.getByRole('button', { name: 'Senden', exact: true }).click()]);
  await expect(page.getByRole('status')).toContainText('Nachricht gesendet');
  const chat = page.locator('[data-karte="direkt"] [data-block="chat"]');
  await expect(chat).toContainText(NACHRICHT);
  await expect(chat.locator('[data-seite="mieter"]')).toHaveCount(1);
  expect(await quer(page)).toBeLessThanOrEqual(0);
});

test('Handwerker liest die Nachricht und schlägt einen Termin vor', async ({ browser }) => {
  const { kontext, page } = await handwerkerSeite(browser);
  await page.goto(new URL(link).pathname, { waitUntil: 'domcontentloaded' });
  const karte = page.locator('[data-karte="direkt"]');
  await expect(karte.locator('[data-block="chat"]')).toContainText(NACHRICHT);

  const wann = new Date(Date.now() + 3 * 24 * 3600 * 1000);
  wann.setHours(10, 0, 0, 0);
  const p = (n: number) => String(n).padStart(2, '0');
  const wert = `${wann.getFullYear()}-${p(wann.getMonth() + 1)}-${p(wann.getDate())}T10:00`;
  await karte.locator('input[name="termin"]').fill(wert);
  await karte.locator('input[name="hinweis"]').fill('Bitte Zugang zum Heizungsraum.');
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    karte.getByRole('button', { name: 'Vorschlag senden' }).click()]);
  const abstimmung = page.locator('[data-karte="direkt"] [data-block="terminabstimmung"]');
  await expect(abstimmung).toContainText('Terminvorschlag');
  await expect(abstimmung).toContainText('Antwort der Gegenseite steht aus');
  await expect(abstimmung).not.toContainText('Vereinbart');          // ein Vorschlag ist noch kein Termin
  expect(await quer(page)).toBeLessThanOrEqual(0);
  await kontext.close();
});

test('Mieterin bestätigt im Portal: Termin vereinbart, auch beim Handwerker', async ({ page, browser }) => {
  await mieterLogin(page);
  const karte = await mieterTicket(page);
  const abstimmung = karte.locator('[data-block="terminabstimmung"]');
  await expect(abstimmung).toContainText('Terminvorschlag');
  await expect(abstimmung).toContainText('Bitte Zugang zum Heizungsraum.');
  await Promise.all([page.waitForLoadState('domcontentloaded'),
    abstimmung.getByRole('button', { name: 'Termin bestätigen' }).click()]);
  const danach = page.locator('[data-karte="direkt"] [data-block="terminabstimmung"]');
  await expect(danach).toContainText('Vereinbart:');
  await expect(danach.getByRole('button', { name: 'Termin bestätigen' })).toHaveCount(0);
  expect(await quer(page)).toBeLessThanOrEqual(0);

  const { kontext, page: hw } = await handwerkerSeite(browser);
  await hw.goto(new URL(link).pathname, { waitUntil: 'domcontentloaded' });
  await expect(hw.locator('[data-karte="direkt"] [data-block="terminabstimmung"]')).toContainText('Vereinbart:');
  await kontext.close();
});

test('Das Ticket einer anderen Mieterin ergibt 404', async ({ page }) => {
  await mieterLogin(page);
  const antwort = await page.goto(`/mieter/ticket/${fremdId}/`, { waitUntil: 'domcontentloaded' });
  expect(antwort!.status()).toBe(404);
  await expect(page.getByText('E2E Fremd Ticket')).toHaveCount(0);
});
