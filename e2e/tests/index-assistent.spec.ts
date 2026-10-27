import { test, expect, Page } from '@playwright/test';
import { assistentAbsenden, goto, imAssistent, login } from './helpers';

// INDEX-ASSISTENT (Auftrag C, 27.10.2026): Art. 269b OR, Art. 17 und 19 Abs. 2 VMWG.
//
// Der Assistent der Mietzinsanpassung bei einer Indexmiete:
//   * bietet nur veröffentlichte LIK-Monate an (Annahme: «in der Tabelle» = bekannt gegeben),
//   * begrenzt den neuen Netto auf Zunahme × Weitergabe — im Browser vorab, auf dem Server hart,
//   * lässt als Wirksamkeitstermin nur Monatserste zu, die die 30 Tage wahren,
//   * zeigt Weitergabe, Mindestintervall und letzte Anpassung als VERTRAGLICHE Grenzen,
//   * bietet keinen Referenzzins, keine Kostensteigerung und keinen Vorbehalt an,
//   * nennt die Lücke, wenn der Kanton kein Originalformular hat (kein Ersatzformular).
//
// Testdaten: `seed_e2e_mietzins` (Ida Indexmiete, Kanton ZH, Basis-LIK 100.0; Ilse Indexluecke, Kanton LU).
// Gemessen wird bei 1280 und bei 390 px: Die Seite scrollt nie quer.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

async function indexAssistent(page: Page, mieter: string) {
  await login(page);
  await goto(page, '/neu/vertraege/');
  const link = page.locator('a[href*="/neu/vertraege/"]').filter({ hasText: mieter }).first();
  await expect(link, `Seed fehlt: kein Vertrag für ${mieter}`).toBeVisible();
  const id = ((await link.getAttribute('href')) || '').match(/\/neu\/vertraege\/(\d+)\//)![1];
  await goto(page, `/neu/mietzins/${id}/anpassung/`);
  await expect(page.locator('select[name="lik_stand"]')).toBeVisible();
  return id;
}

// Bildschirmfotos nur auf Wunsch: E2E_SHOTS=/pfad/zum/ordner
const SHOTS = process.env.E2E_SHOTS;
async function foto(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

const hoechst = (page: Page) => page.evaluate(() => (window as any).IZ_HOECHST as number | null);

for (const b of BREITEN) {
  test.describe(`Index-Assistent ${b.name}`, () => {
    test.use({ viewport: b.viewport });

    test('nur veröffentlichte Monate, keine ordentlichen Gründe, nichts quer', async ({ page }) => {
      const fehler: string[] = [];
      page.on('pageerror', (e) => fehler.push(String(e)));
      await indexAssistent(page, 'Indexmiete');

      // Schritt 1: Indexstand. Der neueste Monat der Tabelle ist vorgewählt; es gibt keinen in der Zukunft.
      await expect(page.locator('[data-schritt].zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Indexstand');
      const optionen = await page.locator('select[name="lik_stand"] option').allTextContents();
      expect(optionen.length, 'keine veröffentlichten Monate angeboten').toBeGreaterThan(0);
      expect(optionen[0], 'der neueste Monat steht zuerst').toMatch(/\d{4} · [\d.]+ Punkte/);
      const heuteMonat = new Date().toISOString().slice(0, 7);
      const werte = await page.locator('select[name="lik_stand"] option').evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
      for (const w of werte) expect(w <= heuteMonat, `Monat ${w} liegt in der Zukunft`).toBeTruthy();

      // Keine Gründe, die es bei der Indexmiete nicht gibt.
      for (const name of ['neu_zins', 'kosten_pct', 'mit_vorbehalt', 'basis_zins']) {
        await expect(page.locator(`[name="${name}"]`), `${name} darf bei der Indexmiete nicht angeboten werden`).toHaveCount(0);
      }
      // Die vertraglichen Grenzen stehen als solche da.
      const grenzen = page.locator('#iz-grenzen');
      await expect(grenzen).toContainText('Vertragliche Grenzen');
      await expect(grenzen).toContainText('nicht aus dem Gesetz');
      await expect(grenzen).toContainText('12 Monate');
      // Höchstbetrag und Vorschlag sind da und plausibel.
      const max = await hoechst(page);
      expect(max, 'kein Höchstbetrag berechnet').not.toBeNull();
      await expect(page.locator('#iz-hoechst')).toContainText('CHF');
      await keinQuerscrollen(page, 'Schritt 1');
      await foto(page, `index-schritt1-${b.name}`);

      // Schritt 2: Netto neu wird vorab auf den Höchstbetrag begrenzt, Termine nur ab dem frühesten.
      const neu = await imAssistent(page, '#mz_neu');
      await neu.fill('99999');
      await expect(neu).toHaveValue((max as number).toFixed(2));
      await expect(page.locator('#mz-warn')).toContainText('Höchstbetrag zurückgesetzt');
      const termine = await page.locator('#mz_wirksam option').evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
      expect(termine.length).toBeGreaterThan(6);
      for (const t of termine) expect(t.endsWith('-01'), `Termin ${t} ist kein Monatserster`).toBeTruthy();
      const frueh = new Date(Date.now() + 37 * 86400000).toISOString().slice(0, 10);   // 30 Tage + 7 Zustellung
      expect(termine[0] > frueh, `erster Termin ${termine[0]} wahrt die 30 Tage nicht (frühestens nach ${frueh})`).toBeTruthy();
      await keinQuerscrollen(page, 'Schritt 2');
      await foto(page, `index-schritt2-${b.name}`);

      // Der Versand heute früher als der Zugang wirkt: ein späteres Versanddatum gibt es nicht (max = heute),
      // ein bestätigter Zugang vor dem Puffer rückt den frühesten Termin vor oder lässt ihn gleich.
      expect(fehler, `Skriptfehler: ${fehler.join(' | ')}`).toEqual([]);
    });

    test('der Wechsel des Monats rechnet neu, ein höherer Betrag wird auf dem Server abgelehnt', async ({ page }) => {
      await indexAssistent(page, 'Indexmiete');
      const vorher = await hoechst(page);
      const werte = await page.locator('select[name="lik_stand"] option').evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
      expect(werte.length).toBeGreaterThan(2);
      await page.selectOption('select[name="lik_stand"]', werte[2]);
      await expect.poll(() => hoechst(page), { message: 'Höchstbetrag folgt dem Monat nicht' }).not.toBe(vorher);

      // Server-Gegenprobe: Das Feld wird am Skript vorbei überschrieben (kein input-Ereignis).
      const neu = await imAssistent(page, '#mz_neu');
      const max = (await hoechst(page)) as number;
      await neu.evaluate((el, v) => { (el as HTMLInputElement).value = v; }, (max + 0.01).toFixed(2));
      await assistentAbsenden(page);   // «Entwurf speichern» ist der erste Absende-Knopf
      await expect(page.locator('body')).toContainText('Art. 17 Abs. 1 VMWG');
      await expect(page.locator('body')).not.toContainText('Entwurf gespeichert');
    });

    test('mit dem Höchstbetrag wird der Entwurf gespeichert', async ({ page }) => {
      await indexAssistent(page, 'Indexmiete');
      const max = (await hoechst(page)) as number;
      const neu = await imAssistent(page, '#mz_neu');
      await neu.fill(max.toFixed(2));
      await assistentAbsenden(page);
      await expect(page.locator('body')).toContainText('Entwurf gespeichert');
      await keinQuerscrollen(page, 'nach dem Speichern');
      // Beim Wiederöffnen steht der Entwurf da, mit dem gespeicherten Netto.
      await expect(page.locator('.fw-hinweis', { hasText: 'Offener' })).toBeVisible();
      await expect(page.locator('#mz_neu')).toHaveValue(max.toFixed(2));
    });

    test('ohne Kantonsoriginal steht die Lücke da, ein Ersatzformular gibt es nicht', async ({ page }) => {
      await indexAssistent(page, 'Indexluecke');
      await imAssistent(page, '#iz-luecke');
      const luecke = page.locator('#iz-luecke');
      await expect(luecke).toContainText('Lücke');
      await expect(luecke).toContainText('Luzern');
      await expect(luecke).toContainText('kein Ersatzformular');
      await expect(page.locator('button[name="aktion"][value="pdf"]')).toHaveCount(0);
      await keinQuerscrollen(page, 'Lücke');
      await foto(page, `index-luecke-${b.name}`);
    });
  });
}
