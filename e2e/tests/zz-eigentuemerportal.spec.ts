import { test, expect, Page } from '@playwright/test';
import { goto, warteAufURL } from './helpers';

// EIGENTÜMERPORTAL v2 (Etappe 4, FUNK-10/11) — BEI 390 PIXEL, HELL UND DUNKEL
//
// Daten aus `seed_e2e_eigentuemer` (läuft in `run-server.sh` nach `seed_e2e`):
//   e2e-eigentuemer        Portal Eigentümer AG: Portalweg 1 (drei Objekte, eines leer, überfällige
//                          Posten, Erträge, eine Auszahlung, ein freigegebenes und ein internes Dokument)
//                          und das archivierte Altweg 9
//   e2e-eigentuemer-fremd  Fremder Eigentümer AG DERSELBEN Verwaltung: Fremdgasse 7
//   e2e-eigentuemer-ende   Ehemaliger Eigentümer AG: Mandat und Liegenschaft archiviert
// Alle mit Passwort e2e-pass. Die Spec ändert nichts am Bestand ausser einer Anfrage («zz-…»: sie legt
// eine Pendenz an) und der Sprache des Eigentümers.

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON });

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

/** Kontrast (WCAG) aller sichtbaren Textelemente gegen ihren Grund; Verläufe (Akzentkachel) werden übersprungen. */
async function schwacheKontraste(page: Page) {
  return page.evaluate(() => {
    const zerlegen = (f: string) => {
      const m = f.match(/[\d.]+/g)!.map(Number);
      return { r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1 };
    };
    const lum = (c: { r: number; g: number; b: number }) => {
      const k = [c.r, c.g, c.b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
      return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
    };
    const grundVon = (el: Element): { r: number; g: number; b: number } | null => {
      let e: Element | null = el;
      while (e) {
        const s = getComputedStyle(e);
        if (s.backgroundImage !== 'none') return null;
        const c = zerlegen(s.backgroundColor);
        if (c.a > 0.95) return c;
        e = e.parentElement;
      }
      return { r: 255, g: 255, b: 255 };
    };
    const schlecht: string[] = [];
    document.querySelectorAll('main *, aside *').forEach((el) => {
      const eigen = Array.from(el.childNodes).some((n) => n.nodeType === 3 && (n.textContent || '').trim().length > 0);
      if (!eigen) return;
      const r = (el as HTMLElement).getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || s.display === 'none') return;
      const grund = grundVon(el);
      if (!grund) return;
      const f = zerlegen(s.color);
      const l1 = lum(f), l2 = lum(grund);
      const kontrast = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const gross = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && parseInt(s.fontWeight) >= 700);
      if (kontrast < (gross ? 3 : 4.5)) schlecht.push(`${el.tagName.toLowerCase()}.${(el as HTMLElement).className}: «${(el.textContent || '').trim().slice(0, 40)}» ${kontrast.toFixed(2)}`);
    });
    return schlecht;
  });
}

async function menueOeffnen(page: Page) {
  await page.locator('.fw-portal-top button').click();     // Name wechselt mit der Sprache
  await expect(page.locator('#pSidebar')).toBeVisible();
}

test.describe('Eigentümer mit Liegenschaften', () => {
  test('Übersicht: vier Kennzahlen, kein Querscrollen, Wege zu allen Seiten', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/');
    for (const k of ['leerstand', 'mietertrag', 'offene-posten', 'auszahlung']) {
      await expect(page.locator(`[data-kachel="${k}"]`)).toBeVisible();
    }
    await expect(page.locator('[data-kachel="leerstand"]')).toContainText('1');
    await expect(page.locator('[data-kachel="offene-posten"]')).toContainText('überfällig');
    await expect(page.locator('[data-kachel="auszahlung"]')).toContainText('Zuletzt am');
    expect(await quer(page)).toBeLessThanOrEqual(0);
    await menueOeffnen(page);
    for (const text of ['Übersicht', 'Liegenschaften', 'Abrechnungen', 'Dokumente', 'Anfragen', 'Profil und Sprache']) {
      await expect(page.locator('#pSidebar').getByRole('link', { name: text })).toBeVisible();
    }
  });

  test('Liegenschaften: nur eigene, archivierte als solche, Belegung im Detail, fremde Adresse 404', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/liegenschaften/');
    await expect(page.getByText('Portalweg 1')).toBeVisible();
    await expect(page.locator('[data-block="archiv"]')).toContainText('Altweg 9');
    await expect(page.locator('[data-block="archiv"]')).toContainText('Archiviert am');
    await expect(page.getByText('Fremdgasse 7')).toHaveCount(0);   // Gegenprobe: anderer Eigentümer, gleiche Verwaltung
    expect(await quer(page)).toBeLessThanOrEqual(0);

    await Promise.all([warteAufURL(page, '**/portal/liegenschaften/*/'), page.locator('[data-block="aktiv"] a').first().click()]);
    await expect(page.getByText('Portal-Whg 2')).toBeVisible();
    await expect(page.locator('[data-objekt]', { hasText: 'Portal-Whg 2' })).toContainText('Leerstand');
    await expect(page.locator('[data-objekt]', { hasText: 'Portal-Whg 1' })).toContainText('Paula Portal');
    expect(await quer(page)).toBeLessThanOrEqual(0);
    // Die Dokumente: freigegeben ja, intern nein.
    await expect(page.getByText('Portal Verwaltungsvertrag')).toBeVisible();
    await expect(page.getByText('Portal interne Offerte')).toHaveCount(0);
  });

  test('Fremde Liegenschaft und fremdes Dokument sind 404', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer-fremd');
    await goto(page, '/portal/liegenschaften/');
    await expect(page.getByText('Fremdgasse 7')).toBeVisible();
    const eigene = await page.locator('[data-liegenschaft]').evaluateAll((a) => a.map((x) => x.getAttribute('data-liegenschaft')));
    expect(eigene.length).toBe(1);
    // Die Liegenschaften der anderen haben kleinere oder grössere Nummern — wir probieren die Nachbarn.
    const id = Number(eigene[0]);
    for (const fremd of [id - 1, id - 2, id + 1, id + 2].filter((n) => n > 0)) {
      const r = await page.request.get(`/portal/liegenschaften/${fremd}/`);
      expect([404, 200]).toContain(r.status());
      if (r.status() === 200) {
        // 200 nur, wenn es seine eigene ist — sonst wäre es ein Leck.
        expect(await page.locator(`[data-liegenschaft="${fremd}"]`).count()).toBe(1);
      }
    }
    await goto(page, '/portal/dokumente/');
    await expect(page.getByText('Fremder Vertrag')).toBeVisible();
    await expect(page.getByText('Portal Verwaltungsvertrag')).toHaveCount(0);
  });

  test('Abrechnungen: Jahre mit PDF, Auszahlungen, offene Posten', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/abrechnungen/');
    await expect(page.locator('[data-block="kontokorrent"]')).toBeVisible();
    await expect(page.locator('[data-block="jahre"] [data-jahr]').first()).toContainText('laufend');
    const pdf = page.locator('[data-block="jahre"] a', { hasText: 'PDF' }).first();
    await expect(pdf).toBeVisible();
    const antwort = await page.request.get((await pdf.getAttribute('href'))!);
    expect(antwort.status()).toBe(200);
    expect(antwort.headers()['content-type']).toContain('application/pdf');
    await expect(page.locator('[data-block="auszahlungen"]')).toContainText('Quartalsauszahlung');
    await expect(page.locator('[data-block="offene-posten"]')).toContainText('Portal offene Miete');
    expect(await quer(page)).toBeLessThanOrEqual(0);
  });

  test('Anfrage an die Verwaltung: Fehler, dann gesendet, dann im Verlauf', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/mitteilungen/');
    await page.getByLabel('Nachricht').fill('Bitte um Rückruf.');
    await page.getByLabel('Betreff').fill('   ');   // nur Leerzeichen: der Browser lässt es zu, der Server nicht
    await page.getByRole('button', { name: 'An die Verwaltung senden' }).click();
    await expect(page.getByRole('alert')).toContainText('Betreff');
    await page.getByLabel('Betreff').fill('zz-e2e Rückfrage Heizung');
    await page.getByLabel('Nachricht').fill('Bitte um Rückruf.');
    await Promise.all([warteAufURL(page, '**/portal/mitteilungen/'), page.getByRole('button', { name: 'An die Verwaltung senden' }).click()]);
    await expect(page.locator('[data-block="verlauf"]')).toContainText('zz-e2e Rückfrage Heizung');
    await expect(page.locator('[data-block="verlauf"]')).toContainText('In Bearbeitung');
    expect(await quer(page)).toBeLessThanOrEqual(0);
  });

  test('Profil: Darstellung wechselt, Sprache wechselt', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer');
    await goto(page, '/portal/profil/');
    await page.getByRole('button', { name: 'Dunkel' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await goto(page, '/portal/');                       // bleibt über die Seiten erhalten
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await goto(page, '/portal/profil/');
    await page.getByRole('button', { name: 'Hell' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.getByRole('button', { name: 'Automatisch' }).click();
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/);
    await menueOeffnen(page);
    await Promise.all([page.waitForURL('**/portal/profil/', { waitUntil: 'domcontentloaded' }),
      page.locator('#pSidebar').getByRole('button', { name: 'FR' }).click()]);
    await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Profil et langue');
    await menueOeffnen(page);
    await Promise.all([page.waitForURL('**/portal/profil/', { waitUntil: 'domcontentloaded' }),
      page.locator('#pSidebar').getByRole('button', { name: 'DE' }).click()]);
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  });

  for (const modus of ['light', 'dark'] as const) {
    test(`Kontrast und Querscrollen aller Seiten (${modus})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: modus });
      await anmelden(page, 'e2e-eigentuemer');
      for (const pfad of ['/portal/', '/portal/liegenschaften/', '/portal/abrechnungen/', '/portal/dokumente/',
        '/portal/mitteilungen/', '/portal/profil/']) {
        await goto(page, pfad);
        await page.waitForTimeout(700);                 // Einblendung der Inhalte abwarten
        expect(await quer(page), `${pfad}: Querscrollen`).toBeLessThanOrEqual(0);
        expect(await schwacheKontraste(page), `${pfad} (${modus}): Kontrast unter AA`).toEqual([]);
      }
    });
  }
});

test.describe('Mandat beendet', () => {
  test('Hinweis auf jeder Seite, archivierte Liegenschaft lesbar, keine Anfrage mehr', async ({ page }) => {
    await anmelden(page, 'e2e-eigentuemer-ende');
    for (const pfad of ['/portal/', '/portal/liegenschaften/', '/portal/abrechnungen/', '/portal/dokumente/']) {
      await goto(page, pfad);
      await expect(page.locator('[data-block="mandatsende"]'), pfad).toContainText('Mandat beendet');
    }
    await goto(page, '/portal/liegenschaften/');
    await expect(page.locator('[data-block="archiv"]')).toContainText('Endeweg 3');
    await goto(page, '/portal/dokumente/');
    await expect(page.getByText('Ende Schlussabrechnung')).toBeVisible();
    await goto(page, '/portal/mitteilungen/');
    await expect(page.locator('[data-block="kontakt"]')).toBeVisible();
    await expect(page.locator('[data-block="formular"]')).toHaveCount(0);
  });
});
