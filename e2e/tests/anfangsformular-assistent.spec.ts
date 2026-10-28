import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// ANFANGSMIETZINS-FORMULAR UND NEBENKOSTENARTEN IM VERTRAGSASSISTENTEN (MIET-04, MIET-11)
//
// Ohne amtliches Formular ist die Mietzinsvereinbarung nichtig (Art. 270 Abs. 2 OR, BGE 140 III 583). Wo es kein
// Kantonsoriginal gibt (der E2E-Bestand hat PLZ 8000 ohne erfassten Kanton), weist der Assistent beim Aktivieren
// ab, solange kein Nachweis vorliegt; die Nebenkostenarten stehen einzeln im Vertrag (Art. 257a Abs. 2 OR).
//
// Geprüft wird im Browser, was ein Django-Test nicht sieht: dass Hinweis und Nachweis im richtigen Schritt
// erscheinen, dass die Meldung des Servers ihren Schritt öffnet und dass bei 390 px nichts quer scrollt.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

async function objektWaehlen(page: Page) {
  const lg = await page.$$eval('#s_lg option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
  await page.selectOption('#s_lg', lg[0]);
  const ob = await page.evaluate(() => {
    const lg = JSON.parse(document.getElementById('lg-data')!.textContent!);
    const l = lg.find((x: any) => String(x.id) === (document.getElementById('s_lg') as HTMLSelectElement).value);
    return l.objekte.filter((o: any) => !o.ist_einstellplatz && o.af && o.af.erforderlich && !o.af.original)
      .map((o: any) => String(o.id));
  });
  expect(ob.length, 'Seed: kein freies Objekt in einem Pflichtkanton ohne Original').toBeGreaterThan(0);
  await page.selectOption('#s_obj', ob[0]);
}

async function bisKonditionen(page: Page) {
  await objektWaehlen(page);
  await page.locator('#btn-next').click();
  const mieter = await page.$$eval('#s_mieter option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
  await page.selectOption('#s_mieter', mieter[0]);
  await page.locator('#btn-next').click();
  await page.fill('#s_beginn', '2026-12-01');
}

for (const b of BREITEN) {
  test.describe(`Anfangsmietzins-Formular im Assistenten ${b.name}`, () => {
    test.use({ viewport: b.viewport });

    test('Hinweis im Schritt Mietzins, Nebenkostenarten einzeln, Aktivieren braucht den Nachweis', async ({ page }) => {
      const fehler: string[] = [];
      page.on('pageerror', (e) => fehler.push(String(e)));
      await login(page);
      await goto(page, '/neu/vertraege/neu/');
      await bisKonditionen(page);
      await page.locator('#btn-next').click();               // → Mietzins
      await expect(page.locator('#af-hinweis')).toBeVisible();
      await expect(page.locator('#af-hinweis-text')).toContainText('BGE 140 III 583');
      await expect(page.locator('#af-hinweis-text')).toContainText('amtliche Formular');
      await page.fill('#s_netto', '1234');
      await keinQuerscrollen(page, 'Mietzins');
      await page.locator('#btn-next').click();               // → Kaution
      await page.locator('#btn-next').click();               // → Nebenkosten

      // Opt-in: zehn Arten aus dem Katalog, die typischen vorgewählt, das Verwaltungshonorar nicht
      const arten = page.locator('input[name="nk_kostenarten"]');
      await expect(arten).toHaveCount(10);
      await expect(page.locator('input[name="nk_kostenarten"][value="heizung"]')).toBeChecked();
      await expect(page.locator('input[name="nk_kostenarten"][value="verwaltung"]')).not.toBeChecked();
      await keinQuerscrollen(page, 'Nebenkosten');

      await page.locator('#btn-next').click();               // → Abschluss
      await expect(page.locator('#af-nachweis')).toBeVisible();
      await expect(page.locator('#summary')).toContainText('Nebenkostenarten');
      await expect(page.locator('#summary')).toContainText('Heizkosten');
      await keinQuerscrollen(page, 'Abschluss');

      // Aktiv setzen ohne Nachweis: Der Server lehnt ab, die Meldung öffnet ihren Schritt, nichts wurde gespeichert
      await expect(page.locator('input[name="aktiv_setzen"]')).toBeChecked();
      await page.locator('#btn-save').click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('p.fw-feldfehler[id^="fe_"]').first()).toContainText('BGE 140 III 583');
      await expect(page.locator('#af-nachweis')).toBeVisible();
      await keinQuerscrollen(page, 'Fehlerseite');

      expect(fehler).toEqual([]);
    });

    test('ohne Nebenkostenarten wird der Vertrag nicht gespeichert', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/vertraege/neu/');
      await bisKonditionen(page);
      await page.locator('#btn-next').click();               // → Mietzins
      await page.fill('#s_netto', '1234');
      await page.fill('#s_nk', '150');
      await page.locator('#btn-next').click();               // → Kaution
      await page.locator('#btn-next').click();               // → Nebenkosten
      const arten = page.locator('input[name="nk_kostenarten"]');
      for (let i = 0; i < (await arten.count()); i++) await arten.nth(i).uncheck();
      await page.locator('#btn-next').click();               // → Abschluss
      await page.locator('input[name="aktiv_setzen"]').uncheck();
      await page.locator('#btn-save').click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('p.fw-feldfehler[id^="fe_"]').first()).toContainText('Art. 257a Abs. 2 OR');
      // Die Meldung öffnet den Schritt der Nebenkosten
      await expect(page.locator('input[name="nk_kostenarten"]').first()).toBeVisible();
    });
  });
}

// Zuletzt und nur einmal: Der Vertrag wird wirklich angelegt und belegt das Objekt im E2E-Bestand.
test.describe('Anfangsmietzins-Formular: Aktivieren mit Nachweis', () => {
  test.use({ viewport: BREITEN[0].viewport });

  test('mit Nachweis (extern verwendet, Datum) wird der Vertrag aktiv, die Akte meldet keinen fehlenden Nachweis', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/vertraege/neu/');
    await bisKonditionen(page);
    for (let i = 0; i < 4; i++) await page.locator("#btn-next").click();   // → Abschluss
    await expect(page.locator('#af-nachweis')).toBeVisible();
    await page.selectOption('#s_af_nachweis', 'extern');
    await page.fill('#s_af_datum', '2026-11-20');
    await page.fill('#s_af_notiz', 'Formular der kantonalen Behörde, Einschreiben');
    await page.locator('#btn-save').click();
    await page.waitForURL(/\/neu\/vertraege\/\d+\/$/, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('body')).not.toContainText('Formular-Nachweis fehlt');
    await expect(page.locator('.fw-chip', { hasText: 'Aktiv' }).first()).toBeVisible();
  });
});
