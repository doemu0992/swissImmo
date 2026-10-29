import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// MIETVERTRAG IM ASSISTENTEN-STANDARD (27.10.2026)
//
// Der Mietvertrag lief mit eigenem System (step-nav, vstep, eigenes Skript).
// Jetzt: der gemeinsame `fw-assistent` mit Leiste, Schrittkopf «Schritt i von n»
// und klebendem Fuss, dazu die Live-Vorschau als gemeinsame Ergänzung
// `.fw-assistent-vorschau` — breit rechts als dritte Spalte, am Telefon unter
// dem Inhalt und einklappbar.
//
// Geprüft wird im Browser, was ein Django-Test nicht sieht: dass die Schritte
// wechseln, dass «Weiter» bei fehlendem Objekt / Mieter anhält, dass die
// Vorschau den Eingaben folgt, dass eine Meldung des Servers ihren Schritt
// öffnet — und dass bei 390 px nichts quer scrollt.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

// Die Schrittzahl ist überall dieselbe: Überzeile, Fuss, Leiste.
async function schrittIst(page: Page, i: number, n: number, titel: string) {
  const text = `Schritt ${i} von ${n}`;
  const kopf = page.locator('[data-schritt].zeigt .fw-assistent-schritt-kopf');
  await expect(kopf.locator('.fw-ueber')).toHaveText(text);
  await expect(kopf.locator('h2')).toHaveText(titel);
  await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText(text);
  await expect(page.locator('.fw-assistent-leiste li.hier')).toContainText(titel);
  await expect(page.locator('.fw-assistent-leiste li')).toHaveCount(n);
}

const vorschau = (page: Page) => page.frameLocator('#pvFrame').locator('body');

async function objektWaehlen(page: Page) {
  const lg = await page.$$eval('#s_lg option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
  await page.selectOption('#s_lg', lg[0]);
  // Ein Objekt mit Nebenkosten (kein Einstellplatz), damit es sieben Schritte sind.
  const ob = await page.evaluate(() => {
    const lg = JSON.parse(document.getElementById('lg-data')!.textContent!);
    const l = lg.find((x: any) => String(x.id) === (document.getElementById('s_lg') as HTMLSelectElement).value);
    return l.objekte.filter((o: any) => !o.ist_einstellplatz).map((o: any) => ({ id: String(o.id), name: o.bezeichnung }));
  });
  expect(ob.length, 'Seed: kein freies Objekt mit Nebenkosten').toBeGreaterThan(0);
  await page.selectOption('#s_obj', ob[0].id);
  return ob[0].name as string;
}

for (const b of BREITEN) {
  test.describe(`Mietvertrag-Assistent ${b.name}`, () => {
    test.use({ viewport: b.viewport });

    test('durch alle sieben Schritte, Vorschau folgt, nichts quer', async ({ page }) => {
      const fehler: string[] = [];
      page.on('pageerror', (e) => fehler.push(String(e)));
      await login(page);
      await goto(page, '/neu/vertraege/neu/');

      await expect(page.locator('.fw-assistent.an.fw-assistent-mit-vorschau')).toBeVisible();
      await schrittIst(page, 1, 7, 'Objekt');
      await expect(page.locator('#btn-save')).toBeHidden();
      await expect(page.locator('#btn-back')).toBeDisabled();
      await keinQuerscrollen(page, 'Objekt');

      // Vorschau: breit rechts neben dem Inhalt, am Telefon darunter und einklappbar
      const inhalt = (await page.locator('.fw-assistent-inhalt').boundingBox())!;
      const panel = (await page.locator('.fw-assistent-vorschau').boundingBox())!;
      const knopf = page.locator('[data-vorschau-knopf]');
      if (b.viewport.width >= 1200) {
        expect(panel.x).toBeGreaterThanOrEqual(inhalt.x + inhalt.width);
        expect(Math.abs(panel.y - inhalt.y)).toBeLessThan(40);
        // Eine eigene Spalte, so breit wie der Inhalt — nicht ein Rest am Rand
        expect(Math.abs(panel.width - inhalt.width)).toBeLessThan(2);
        await expect(knopf).toBeHidden();
      } else {
        expect(panel.y).toBeGreaterThanOrEqual(inhalt.y + inhalt.height);
        await expect(knopf).toBeVisible();
        await expect(page.locator('#pvFrame')).toBeVisible();
        await knopf.click();
        await expect(page.locator('#pvFrame')).toBeHidden();
        await expect(knopf).toHaveAttribute('aria-expanded', 'false');
        await knopf.click();
        await expect(page.locator('#pvFrame')).toBeVisible();
      }

      // Ohne Objekt geht es nicht weiter
      await page.locator('#btn-next').click();
      await schrittIst(page, 1, 7, 'Objekt');
      expect(await page.locator('#s_obj').evaluate((f: HTMLSelectElement) => f.validity.valid)).toBe(false);

      const objekt = await objektWaehlen(page);
      await expect(vorschau(page)).toContainText(objekt);
      await page.locator('#btn-next').click();
      await schrittIst(page, 2, 7, 'Personen');
      await keinQuerscrollen(page, 'Personen');

      // Ohne Mieter geht es nicht weiter
      await page.locator('#btn-next').click();
      await schrittIst(page, 2, 7, 'Personen');
      const mieter = await page.$$eval('#s_mieter option', (o) => (o as HTMLOptionElement[]).filter((x) => x.value).map((x) => [x.value, x.textContent!.trim()]));
      await page.selectOption('#s_mieter', mieter[0][0]);
      await expect(vorschau(page)).toContainText(mieter[0][1]);
      await page.locator('#btn-next').click();

      await schrittIst(page, 3, 7, 'Konditionen');
      await page.fill('#s_beginn', '2026-12-01');
      await expect(vorschau(page)).toContainText('01.12.2026');
      await keinQuerscrollen(page, 'Konditionen');
      await page.locator('#btn-next').click();

      await schrittIst(page, 4, 7, 'Mietzins');
      await page.fill('#s_netto', '1234');
      await expect(vorschau(page)).toContainText(/1.?234\.00/);
      await keinQuerscrollen(page, 'Mietzins');
      await page.locator('#btn-next').click();

      await schrittIst(page, 5, 7, 'Kaution');
      await page.locator('#btn-next').click();
      await schrittIst(page, 6, 7, 'Nebenkosten');
      await page.locator('#btn-next').click();

      await schrittIst(page, 7, 7, 'Abschluss');
      await expect(page.locator('#btn-next')).toBeHidden();
      await expect(page.locator('#btn-save')).toBeVisible();
      await expect(page.locator('#summary')).toContainText(mieter[0][1]);
      await expect(page.locator('#summary')).toContainText('01.12.2026');
      await keinQuerscrollen(page, 'Abschluss');
      if (b.viewport.width <= 900) {
        // Die waagrechte Leiste holt den aktuellen (letzten) Schritt ins Bild
        const nav = (await page.locator('.fw-assistent-leiste').boundingBox())!;
        const hier = (await page.locator('.fw-assistent-leiste li.hier').boundingBox())!;
        expect(hier.x, 'Abschluss links aus der Leiste').toBeGreaterThanOrEqual(nav.x - 1);
        expect(hier.x + hier.width, 'Abschluss rechts aus der Leiste').toBeLessThanOrEqual(nav.x + nav.width + 1);
      }

      // Zurück und über die Leiste springen behalten die Eingaben
      await page.locator('#btn-back').click();
      await schrittIst(page, 6, 7, 'Nebenkosten');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await schrittIst(page, 4, 7, 'Mietzins');
      // Das Betragsfeld schreibt beim Verlassen «1'234.00» (DESIGN-28); der Server liest das ein.
      await expect(page.locator('#s_netto')).toHaveValue("1'234.00");

      expect(fehler).toEqual([]);
    });

    test('Meldung des Servers öffnet ihren Schritt', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/vertraege/neu/');
      await objektWaehlen(page);
      await page.locator('#btn-next').click();
      const mieter = await page.$$eval('#s_mieter option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
      await page.selectOption('#s_mieter', mieter[0]);
      await page.locator('#btn-next').click();
      // Ende vor Beginn: Das lässt der Browser durch, der Server lehnt ab.
      await page.fill('#s_beginn', '2026-12-01');
      await page.uncheck('#unbefristet');
      await page.fill('#s_ende', '2026-01-31');
      for (let i = 0; i < 4; i++) await page.locator('#btn-next').click();
      await schrittIst(page, 7, 7, 'Abschluss');
      await Promise.all([
        page.waitForResponse((r) => r.url().includes('/neu/vertraege/neu/speichern/')),
        page.locator('#btn-save').click(),
      ]);
      await page.waitForLoadState('domcontentloaded');

      // Zurück mit Meldung: der Assistent beginnt beim Schritt des Fehlers
      await expect(page.locator('.fw-formfehler')).toBeVisible();
      await schrittIst(page, 3, 7, 'Konditionen');
      await expect(page.locator('#s_ende')).toHaveAttribute('aria-invalid', 'true');
      await expect(page.locator('#s_ende')).toHaveValue('2026-01-31');
      await keinQuerscrollen(page, 'Fehler');

      // Woanders hingehen, dann die Meldung anklicken: öffnet wieder Konditionen
      await page.locator('.fw-assistent-leiste li', { hasText: 'Objekt' }).locator('button').click();
      await schrittIst(page, 1, 7, 'Objekt');
      await page.locator('.fw-formfehler li button').first().click();
      await schrittIst(page, 3, 7, 'Konditionen');
      await expect(page.locator('#s_ende')).toBeFocused();
    });
  });
}
