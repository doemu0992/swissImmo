import { test, expect, Page } from '@playwright/test';
import { goto, login, warteAufURL } from './helpers';

// MENÜBAND-ZUORDNUNG UND HAUSWARTUNG (29.10.2026, DESIGN-01/03/04/05, ROUTE-02)
//
// Telefon (390 x 844). Im Browser geprüft, was ein Django-Test nicht sieht:
//   * welcher Bereich und welcher Menüpunkt auf einer Seite leuchten (`aria-current`),
//   * dass STWEG den Bestandsfilter in Hauptnavigation und Menüband weiterreicht,
//   * dass die Hauswartung auf ihrer Schadenakte nur anbietet, was sie öffnen darf,
//   * dass dabei nichts quer scrollt.

test.use({ viewport: { width: 390, height: 844 } });

async function anmelden(page: Page, benutzer: string) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', benutzer);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

/** Bereich (Hauptnavigation) und Menüpunkt (Menüband), die auf der Seite als «aktuell» gesetzt sind. */
async function leuchtet(page: Page) {
  return page.evaluate(() => {
    // Ohne die Zahl der ungelesenen Meldungen, die an «Akten» bzw. «Schäden» hängt.
    const text = (el: Element | null) => (el ? (el.textContent || '').replace(/\s+/g, ' ').trim().replace(/\s*\d+$/, '') : null);
    return {
      bereich: text(document.querySelector('#fwHauptnav a[aria-current="page"]')),
      punkt: text(document.querySelector('.fw-bereichsreiter a[aria-current="page"]')),
      einstellungen: !!document.querySelector('a.fw-wz-einst.hier'),
    };
  });
}

test.describe('Menüband: jede Seite markiert einen Bereich', () => {
  test('Betreibungen, Dokumente, Kommunikation, Zählerstand und Suche liegen in einem Bereich', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const lgId = await page.locator('a[href^="/neu/liegenschaften/"]').evaluateAll((a) =>
      (a as HTMLAnchorElement[]).map((x) => x.getAttribute('href') || '').map((h) => (h.match(/liegenschaften\/(\d+)\//) || [])[1]).find(Boolean));
    expect(lgId, 'Seed: keine Liegenschaft').toBeTruthy();

    const faelle: Array<[string, string, string | null]> = [
      ['/neu/betreibungen/', 'Läufe', 'Mahnwesen'],
      // Ohne eigenen Menüpunkt: Der Bereich leuchtet, im Band ist kein Punkt aktiv (DESIGN-05 ist offen).
      ['/neu/dokumente/', 'Akten', null],
      ['/neu/kommunikation/', 'Heute', null],
      [`/neu/liegenschaften/${lgId}/zaehlerstand/`, 'Akten', 'Liegenschaften'],
      [`/neu/liegenschaften/${lgId}/verteilschluessel/`, 'Akten', 'Liegenschaften'],
      ['/neu/suche/?q=e2e', 'Heute', null],
    ];
    for (const [url, bereich, punkt] of faelle) {
      await goto(page, url);
      const ist = await leuchtet(page);
      expect(ist.bereich, `${url}: Bereich`).toBe(bereich);
      if (punkt) expect(ist.punkt, `${url}: Menüpunkt`).toBe(punkt);
      await keinQuerscrollen(page, url);
    }
  });

  test('Die Zwei-Faktor-Seite leuchtet unter den Einstellungen', async ({ page }) => {
    await login(page);
    await goto(page, '/konto/zwei-faktor/');
    expect((await leuchtet(page)).einstellungen).toBe(true);
  });

  test('Stockwerkeigentum behält den Bestandsfilter', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const lgId = await page.locator('a[href^="/neu/liegenschaften/"]').evaluateAll((a) =>
      (a as HTMLAnchorElement[]).map((x) => (x.getAttribute('href') || '').match(/liegenschaften\/(\d+)\//)).find(Boolean)?.[1]);
    await goto(page, `/neu/stweg/?lg=${lgId}`);
    const hrefs = await page.locator('#fwHauptnav a, .fw-bereichsreiter a').evaluateAll((a) =>
      (a as HTMLAnchorElement[]).map((x) => x.getAttribute('href') || ''));
    expect(hrefs.length).toBeGreaterThan(5);
    const ohne = hrefs.filter((h) => h.startsWith('/neu/') && !h.includes(`lg=${lgId}`));
    expect(ohne, 'Links ohne den gewählten Bestand').toEqual([]);
    await keinQuerscrollen(page, 'STWEG');
  });
});

test.describe('Die Hauswartung sieht nur, was sie öffnen darf', () => {
  test('Schadenakte: nur der Statuswechsel, kein Link und kein Formular in die 403', async ({ page }) => {
    const verboten: string[] = [];
    page.on('response', (r) => { if (r.status() === 403) verboten.push(r.url()); });
    await anmelden(page, 'e2e-hauswart');
    await goto(page, '/neu/schaeden/');
    // Die Zeilen der Liste öffnen die Akte in der Schublade (onclick), sie sind keine Links.
    const akte = await page.locator('.fw-zeile.klick[onclick*="/neu/schaeden/"]').first().evaluate((z) =>
      ((z.getAttribute('onclick') || '').match(/\/neu\/schaeden\/\d+\//) || [])[0]);
    expect(akte, 'Seed: keine Schadenmeldung für die Hauswartung').toBeTruthy();
    await goto(page, akte!);
    await expect(page.locator('h1')).toBeVisible();

    // Formulare: ausser dem Statuswechsel keines.
    const aktionen = await page.locator('form[method="post"]').evaluateAll((f) =>
      (f as HTMLFormElement[]).map((x) => x.getAttribute('action') || '').filter((a) => a.startsWith('/neu/')));
    expect(aktionen.every((a) => /^\/neu\/schaeden\/\d+\/status\/$/.test(a)), `Formulare: ${aktionen.join(', ')}`).toBe(true);
    expect(aktionen.length).toBeGreaterThan(0);

    // Links: keiner, den die Hauswartung nicht öffnen darf. Jeder Link wird wirklich abgerufen.
    const links = await page.locator('main a[href^="/neu/"], .fw-inhalt a[href^="/neu/"]').evaluateAll((a) =>
      Array.from(new Set((a as HTMLAnchorElement[]).map((x) => x.getAttribute('href') || '').filter((h) => !h.includes('#')))));
    for (const h of links) {
      const antwort = await page.request.get(h);
      expect(antwort.status(), `Link ${h}`).not.toBe(403);
    }
    await expect(page.locator('a[href*="/neu/auftrag/"], a[href*="/versicherung/"], a[href^="/neu/vorlagen/"]')).toHaveCount(0);
    await page.waitForTimeout(500);
    expect(verboten, '403-Antworten beim Laden der Seite').toEqual([]);
    await keinQuerscrollen(page, 'Schadenakte');
  });

  test('Schadenliste: kein Menü «Mehr» mit der Kostenübersicht', async ({ page }) => {
    await anmelden(page, 'e2e-hauswart');
    await goto(page, '/neu/schaeden/');
    await expect(page.locator('a[href^="/neu/schaeden/kosten/"]')).toHaveCount(0);
    await keinQuerscrollen(page, 'Schadenliste');
  });
});
