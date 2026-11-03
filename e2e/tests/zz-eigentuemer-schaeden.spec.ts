import { test, expect, Page } from '@playwright/test';
import { goto, warteAufURL } from './helpers';

// EIGENTÜMERPORTAL: SCHÄDEN UND AUFTRÄGE — BEI 390 PIXEL, HELL UND DUNKEL
//
// Daten aus `seed_e2e_eigentuemer` (Schäden an Portalweg 1: «Portal Wasserhahn tropft» erledigt mit
// Rechnung und freigegebenem Auftrag, «Portal Dach undicht» offen mit ausstehender Freigabe; an der
// Fremdgasse 7 «Fremdgasse Schaden»). Die Spec ändert NICHTS am Bestand (kein Freigabe-Klick, damit
// sie wiederholbar bleibt; der Entscheid ist in den Django-Tests belegt). Name «zz-…», weil sie auf
// den Daten des Seeds besteht.

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON });

const GEHEIM = ['GEHEIME-BESCHREIBUNG', 'GEHEIME-BEMERKUNG', 'GEHEIME-NACHRICHT', 'Geheimmelder',
  'geheimmelder-e2e', '079 111 22 33', 'CH9300762011623852957'];

async function anmelden(page: Page, name: string) {
  await goto(page, '/portal/login/');
  await page.fill('input[name="username"]', name);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([
    warteAufURL(page, '**/portal/**'),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
}

async function quer(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

test.describe('Schäden und Aufträge', () => {
  test('Liste, Filter, Detail mit Verlauf; nichts Fremdes, nichts Geheimes', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/schaeden/');
    await expect(page.locator('[data-schaden]', { hasText: 'Portal Wasserhahn tropft' })).toContainText('Erledigt');
    await expect(page.locator('[data-schaden]', { hasText: 'Portal Dach undicht' })).toContainText('Freigabe ausstehend');
    await expect(page.getByText('Fremdgasse Schaden')).toHaveCount(0);       // Gegenprobe: anderer Eigentümer
    expect(await quer(page)).toBeLessThanOrEqual(0);

    // Filter: Status offen.
    await page.getByLabel('Status').selectOption('offen');
    await Promise.all([warteAufURL(page, '**/portal/schaeden/?*'), page.getByRole('button', { name: 'Filtern' }).click()]);
    await expect(page.getByText('Portal Dach undicht')).toBeVisible();
    await expect(page.getByText('Portal Wasserhahn tropft')).toHaveCount(0);

    // Detail des erledigten Schadens.
    await goto(page, '/portal/schaeden/?status=erledigt');
    await Promise.all([warteAufURL(page, '**/portal/schaeden/*/'), page.locator('[data-schaden]').first().click()]);
    const auftrag = page.locator('[data-block="auftraege"]');
    await expect(auftrag).toContainText('Portal Sanitär AG');
    await expect(auftrag).toContainText('Freigegeben');
    await expect(auftrag).toContainText('Bitte zügig.');
    await expect(auftrag).toContainText('CHF 480');
    const verlauf = page.locator('[data-block="verlauf"]');
    for (const art of ['meldung', 'auftrag', 'freigabe', 'arbeit', 'rechnung', 'abschluss']) {
      await expect(verlauf.locator(`[data-ereignis="${art}"]`).first(), art).toBeVisible();
    }
    expect(await quer(page)).toBeLessThanOrEqual(0);
    const html = await page.content();
    for (const g of GEHEIM) expect(html, g).not.toContain(g);
  });

  test('Offener Schaden zeigt die Freigabe zum Entscheiden', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/schaeden/?status=offen');
    await Promise.all([warteAufURL(page, '**/portal/schaeden/*/'), page.locator('[data-schaden]').first().click()]);
    await expect(page.locator('[data-block="freigabe"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Freigeben' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Ablehnen' })).toBeVisible();
    expect(await quer(page)).toBeLessThanOrEqual(0);
  });

  test('Reparaturhistorie auf der Liegenschaftsseite, fremder Schaden 404', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/liegenschaften/');
    await Promise.all([warteAufURL(page, '**/portal/liegenschaften/*/'), page.locator('[data-block="aktiv"] a').first().click()]);
    await expect(page.locator('[data-block="reparaturen"]')).toContainText('CHF 480');
    expect(await quer(page)).toBeLessThanOrEqual(0);

    // Die Nummern des fremden Eigentümers erraten: nur eigene dürfen 200 geben.
    const ids = await (async () => {
      await goto(page, '/portal/schaeden/');
      return page.locator('[data-schaden]').evaluateAll((a) => a.map((x) => Number(x.getAttribute('data-schaden'))));
    })();
    const hoechste = Math.max(...ids);
    for (let n = Math.max(1, hoechste - 6); n <= hoechste + 3; n++) {
      const r = await page.request.get(`/portal/schaeden/${n}/`);
      expect(r.status() === 200 ? ids.includes(n) : r.status() === 404, `Nr. ${n}: ${r.status()}`).toBeTruthy();
    }
  });

  test('Fremder Eigentümer sieht nur seinen Schaden', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer-fremd');
    await goto(page, '/portal/schaeden/');
    await expect(page.getByText('Fremdgasse Schaden')).toBeVisible();
    await expect(page.getByText('Portal Wasserhahn tropft')).toHaveCount(0);
  });

  test('Mandat beendet: ohne Schäden, leerer Zustand', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer-ende');
    await goto(page, '/portal/schaeden/');
    await expect(page.locator('[data-block="mandatsende"]')).toContainText('Mandat beendet');
    await expect(page.locator('[data-block="leer"]')).toContainText('Noch keine Schäden');
  });

  for (const modus of ['light', 'dark'] as const) {
    test(`Querscrollen und Lesbarkeit bei 390 px (${modus})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: modus });
      await anmelden(page, 'e2e-eigentuemer');
      await goto(page, '/portal/schaeden/');
      const ids = await page.locator('[data-schaden]').evaluateAll((a) => a.map((x) => x.getAttribute('data-schaden')));
      for (const pfad of ['/portal/schaeden/', ...ids.map((i) => `/portal/schaeden/${i}/`)]) {
        await goto(page, pfad);
        await page.waitForTimeout(500);
        expect(await quer(page), `${pfad}: Querscrollen`).toBeLessThanOrEqual(0);
        // Lesbar: kein Text in einer Zeile breiter als der Bildschirm (Umbruch statt Abschneiden).
        const zuBreit = await page.evaluate(() => Array.from(document.querySelectorAll('main *'))
          .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1).map((e) => e.tagName));
        expect(zuBreit, `${pfad}: ragt über den Rand`).toEqual([]);
      }
    });
  }
});
