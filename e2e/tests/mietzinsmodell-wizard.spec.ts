import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// MIETZINSMODELL IM VERTRAGSASSISTENTEN (27.10.2026)
//
// Der Block «Mietzinsmodell» im Schritt «Mietzins» gilt für alle Mietarten: drei Kacheln als Radiogruppe,
// darunter Ampel der festen Dauer, Staffel- und Index-Panel. Die Regeln stehen nicht im Skript, sondern in
// core/services/mietzinsmodell.py; der Browser fragt sie am Live-Endpunkt ab. Hier wird gemessen, was ein
// Django-Test nicht sieht: ob die Kacheln sich ausschliessen, ob Ampel und Fix im Browser wirken, ob «Weiter»
// gesperrt bleibt, ob der Zeilengenerator die richtigen Daten setzt, ob nichts quer scrollt (390 px) und ob
// der Dunkelmodus lesbar bleibt.
//
// Die Beispielzahlen (LIK 108.3, Basis 107.0, Netto 2000) stehen auch in
// core/tests/test_mietzinsmodell_wizard.py::BeispielrechnungTests — dort aus dem Server gerechnet.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

const schritt = (page: Page) => page.locator('.fw-assistent-leiste li.hier');

async function objektWaehlen(page: Page) {
  const lg = await page.$$eval('#s_lg option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
  await page.selectOption('#s_lg', lg[0]);
  const ob = await page.evaluate(() => {
    const lg = JSON.parse(document.getElementById('lg-data')!.textContent!);
    const l = lg.find((x: any) => String(x.id) === (document.getElementById('s_lg') as HTMLSelectElement).value);
    return l.objekte.filter((o: any) => !o.ist_einstellplatz).map((o: any) => String(o.id));
  });
  expect(ob.length, 'Seed: kein freies Objekt mit Nebenkosten').toBeGreaterThan(0);
  await page.selectOption('#s_obj', ob[0]);
}

/** Bis in den Schritt «Mietzins» mit Mietbeginn und Netto. */
async function zumMietzins(page: Page, beginn = '2027-01-01', netto = '2000') {
  await login(page);
  await goto(page, '/neu/vertraege/neu/');
  await objektWaehlen(page);
  await page.locator('#btn-next').click();
  const mieter = await page.$$eval('#s_mieter option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
  await page.selectOption('#s_mieter', mieter[0]);
  await page.locator('#btn-next').click();
  await expect(schritt(page)).toContainText('Konditionen');
  await page.fill('#s_beginn', beginn);
  await page.locator('#btn-next').click();
  await expect(schritt(page)).toContainText('Mietzins');
  await page.fill('#s_netto', netto);
}

/** Eine Kachel wählen, wie ein Mensch: auf die Kachel klicken. */
async function modell(page: Page, wert: 'fest' | 'staffel' | 'index') {
  await page.locator(`#mzm_${wert}`).click();
  await expect(page.locator(`#mzm_${wert}`)).toBeChecked();
}

/** Wartet, bis die Prüfung des Servers zu den Eingaben geantwortet hat. */
async function geprueft(page: Page) {
  await page.waitForResponse((r) => r.url().includes('/mietzinsmodell/pruefen/'), { timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(150);
}

const weiter = (page: Page) => page.locator('#btn-next');
const ampel = (page: Page) => page.locator('#mzm-ampel');
const zeilen = (page: Page) => page.locator('#mzm-staffel-zeilen .fw-mzm-zeile');

async function formDatenSchluessel(page: Page): Promise<string[]> {
  return page.evaluate(() => Array.from(new Set(Array.from(new FormData(document.getElementById('vform') as HTMLFormElement).keys()))));
}

for (const b of BREITEN) {
  test.describe(`Mietzinsmodell ${b.name}`, () => {
    test.use({ viewport: b.viewport });

    test('Kacheln sind eine Radiogruppe: eine gewählt, die anderen nicht, Tastatur und Hilfe', async ({ page }) => {
      const fehler: string[] = [];
      page.on('pageerror', (e) => fehler.push(String(e)));
      await zumMietzins(page);
      await expect(page.locator('#mzm input[name="mietzins_modell"]')).toHaveCount(3);
      await expect(page.locator('#mzm_fest')).toBeChecked();
      await expect(page.locator('#mzm-panel-staffel')).toBeHidden();
      await expect(page.locator('#mzm-panel-index')).toBeHidden();
      await expect(ampel(page)).toBeHidden();

      await modell(page, 'staffel');
      await expect(page.locator('#mzm_fest')).not.toBeChecked();
      await expect(page.locator('#mzm_index')).not.toBeChecked();
      await expect(page.locator('#mzm-panel-staffel')).toBeVisible();
      await expect(page.locator('#mzm-panel-index')).toBeHidden();
      await modell(page, 'index');
      await expect(page.locator('#mzm_staffel')).not.toBeChecked();
      await expect(page.locator('#mzm-panel-index')).toBeVisible();
      await expect(page.locator('#mzm-panel-staffel')).toBeHidden();
      // Die gewählte Kachel trägt den Akzent, die anderen nicht
      await expect(page.locator('.fw-mzm-kachel.akzent')).toHaveCount(1);
      await expect(page.locator('.fw-mzm-kachel.akzent input')).toHaveAttribute('value', 'index');

      // Tastatur: Pfeiltasten wandern in der Gruppe, das Radio zeigt den Fokus an der Kachel
      await page.locator('#mzm_index').focus();
      await page.keyboard.press('ArrowLeft');
      await expect(page.locator('#mzm_staffel')).toBeChecked();
      await expect(page.locator('#mzm_staffel')).toBeFocused();
      const ring = await page.locator('#mzm_staffel').evaluate((e) => getComputedStyle(e.closest('.fw-mzm-kachel')!).outlineStyle);
      expect(ring, 'Fokus an der Kachel sichtbar').not.toBe('none');
      await page.keyboard.press('ArrowLeft');
      await expect(page.locator('#mzm_fest')).toBeChecked();

      // Gruppe mit Beschriftung für Screenreader
      await expect(page.locator('fieldset.fw-mzm-wahl legend')).toContainText('Mietzinsmodell');

      // ⓘ erreichbar: Blase mit der Regel und dem Artikel, innerhalb des Bildschirms
      for (const [wert, art] of [['staffel', 'Art. 269c OR'], ['index', 'Art. 269b OR']] as const) {
        const knopf = page.locator('.fw-mzm-kachel').filter({ has: page.locator(`#mzm_${wert}`) }).locator('.fw-hilfe-knopf');
        await knopf.click();
        const blase = page.locator('#fwHilfeBlase');
        await expect(blase).toBeVisible();
        await expect(blase).toContainText(art);
        const r = (await blase.boundingBox())!;
        expect(r.x).toBeGreaterThanOrEqual(0);
        expect(r.x + r.width).toBeLessThanOrEqual(b.viewport.width);
        await page.keyboard.press('Escape');
        await expect(blase).toBeHidden();
        // Der Klick aufs ⓘ wählt die Kachel nicht
        await expect(page.locator('#mzm_fest')).toBeChecked();
      }
      await keinQuerscrollen(page, 'Mietzinsmodell');
      expect(fehler).toEqual([]);
    });

    test('Wechsel räumt das andere Modell, nichts davon wird gesendet', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'staffel');
      await page.fill('#mzm-gen-betrag', '50');
      await page.fill('#mzm-gen-anzahl', '2');
      await page.click('#mzm-gen-knopf');
      await expect(zeilen(page)).toHaveCount(2);
      let keys = await formDatenSchluessel(page);
      expect(keys).toContain('staffel_ab');
      expect(keys).toContain('staffel_erhoehung');
      expect(keys.filter((k) => k.startsWith('index_') || k.startsWith('basis_lik'))).toEqual([]);

      // Staffel → Index: Stufen weg, Rückmeldung ohne Rückfrage
      await modell(page, 'index');
      await expect(page.locator('#mzm-rueck')).toHaveText('Staffelstufen entfernt');
      await expect(zeilen(page)).toHaveCount(0);
      keys = await formDatenSchluessel(page);
      expect(keys.filter((k) => k.startsWith('staffel'))).toEqual([]);
      expect(keys).toContain('index_weitergabe_prozent');
      expect(keys).toContain('basis_lik_punkte');

      // Index mit eigenen Eingaben → Staffel: Index-Angaben weg
      await page.fill('#s_weitergabe', '80');
      await modell(page, 'staffel');
      await expect(page.locator('#mzm-rueck')).toHaveText('Index-Angaben entfernt');
      keys = await formDatenSchluessel(page);
      expect(keys.filter((k) => k.startsWith('index_') || k.startsWith('basis_lik'))).toEqual([]);
      await modell(page, 'index');
      await expect(page.locator('#s_weitergabe')).toHaveValue('100');
      await expect(page.locator('#mzm-rueck')).toBeHidden();   // nichts zu räumen: keine Meldung

      // Fest: von beidem nichts
      await modell(page, 'fest');
      keys = await formDatenSchluessel(page);
      expect(keys.filter((k) => k.startsWith('staffel') || k.startsWith('index_') || k.startsWith('basis_lik'))).toEqual([]);
      expect(keys).toContain('mietzins_modell');
    });

    test('Ampel der festen Dauer: Befund, Fix behebt, Weiter gesperrt bis gültig', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'index');
      await geprueft(page);
      // Unbefristet ohne Kündigungsverzicht: nicht fest
      await expect(ampel(page)).toHaveClass(/krit/);
      await expect(page.locator('#mzm-ampel-chip')).toHaveText('Mindestdauer nicht erfüllt');
      await expect(page.locator('#mzm-ampel-text')).toContainText('Art. 269b OR');
      await expect(weiter(page)).toBeDisabled();
      // Der Grund steht am Fuss, nicht nur in der Karte
      const fuss = page.locator('#mzm-fuss');
      await expect(fuss).toBeVisible();
      await expect(fuss).toContainText('Gesperrt');
      await expect(fuss).toContainText('Vermieter');
      expect(await page.locator('#mzm_index').evaluate((e: HTMLInputElement) => e.validationMessage)).toContain('Die Dauer ist nicht fest');
      const fussBox = (await page.locator('.fw-assistent-fuss').boundingBox())!;
      expect(fussBox.x + fussBox.width).toBeLessThanOrEqual(b.viewport.width + 1);
      await keinQuerscrollen(page, 'Ampel rot');

      // Fix: Kündigungsverzicht bis Mietbeginn + 5 Jahre - 1 Tag
      await page.locator('#mzm-ampel-fix .fw-btn').click();
      await expect(page.locator('#s_verzicht')).toHaveValue('2031-12-31');
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/gut/);
      await expect(page.locator('#mzm-ampel-chip')).toHaveText('Mindestdauer erfüllt');
      await expect(page.locator('#mzm-ampel-text')).toContainText('31.12.2031');
      await expect(weiter(page)).toBeEnabled();
      await expect(fuss).toBeHidden();

      // Einen Tag weniger: wieder gesperrt (Gegenprobe zur Grenze)
      // (das Feld steht im Schritt «Konditionen», hier unsichtbar: wie eine Eingabe dort setzen)
      await page.evaluate(() => { const e = document.getElementById('s_verzicht') as HTMLInputElement; e.value = '2031-12-30'; e.dispatchEvent(new Event('input', { bubbles: true })); });
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/krit/);
      await expect(weiter(page)).toBeDisabled();
      await page.locator('#mzm-ampel-fix .fw-btn').click();
      await geprueft(page);
      await expect(weiter(page)).toBeEnabled();
      await page.locator('#btn-next').click();
      await expect(schritt(page)).toContainText('Kaution');
    });

    test('Befristung: Laufzeit ändern führt zu Konditionen, Fix setzt das Ende', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'staffel');
      await page.locator('#mzm-zu-laufzeit').click();
      await expect(schritt(page)).toContainText('Konditionen');
      await expect(page.locator('#s_verzicht')).toBeFocused();
      // Befristet: Verzicht verschwindet (und wird nicht gesendet), das Ende gilt
      await page.uncheck('#unbefristet');
      await expect(page.locator('#verzicht-box')).toBeHidden();
      await page.fill('#s_ende', '2028-12-31');
      expect(await formDatenSchluessel(page)).not.toContain('vermieter_kuendigungsverzicht_bis');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/krit/);   // Beginn 2027-01-01 + 3 Jahre = bis 31.12.2029
      await page.locator('#mzm-ampel-fix .fw-btn').click();
      await expect(page.locator('#s_ende')).toHaveValue('2029-12-31');
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/gut/);
    });

    test('Staffelgenerator: erste Stufe 12 Monate nach Beginn, Erhöhung in CHF, neuer Mietzins vom Server', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'staffel');
      await expect(page.locator('#mzm-start')).toHaveText("CHF 2'000.00");
      await expect(zeilen(page)).toHaveCount(1);   // eine leere Zeile zum Anfangen
      await page.fill('#mzm-gen-betrag', '50');
      await page.fill('#mzm-gen-anzahl', '3');
      await page.click('#mzm-gen-knopf');
      await expect(zeilen(page)).toHaveCount(3);
      await geprueft(page);
      const daten = await zeilen(page).evaluateAll((z) => z.map((r) => [
        (r.querySelector('[name=staffel_ab]') as HTMLInputElement).value,
        (r.querySelector('[name=staffel_erhoehung]') as HTMLInputElement).value,
        (r.querySelector('[name=staffel_ab]') as HTMLInputElement).min,
        r.querySelector('output')!.textContent,
      ]));
      expect(daten).toEqual([
        ['2028-01-01', '50.00', '2028-01-01', "2'050.00"],
        ['2029-01-01', '50.00', '2029-01-01', "2'100.00"],
        ['2030-01-01', '50.00', '2030-01-01', "2'150.00"],
      ]);
      // Kein Prozentfeld, nur Datum und Erhöhung in CHF
      await expect(page.locator('#mzm [name*="prozent"]:not(#s_weitergabe)')).toHaveCount(0);
      await expect(page.locator('#mzm-staffel-zeilen [name]')).toHaveCount(6);
      // Gültig (Beginn 2027 + 3 Jahre, unbefristet ohne Verzicht ist es nicht): Dauer ist die einzige Sperre
      await expect(page.locator('#mzm-ampel')).toHaveClass(/krit/);
      // Zeilen hinzufügen und entfernen
      await page.click('#mzm-stufe-neu');
      await expect(zeilen(page)).toHaveCount(4);
      await expect(zeilen(page).nth(3).locator('[name=staffel_ab]')).toHaveAttribute('min', '2031-01-01');
      await zeilen(page).nth(3).locator('.fw-mzm-weg').click();
      await expect(zeilen(page)).toHaveCount(3);
      await zeilen(page).nth(0).locator('.fw-mzm-weg').click();
      await expect(zeilen(page)).toHaveCount(2);
      await expect(zeilen(page).first().locator('.fw-mzm-zeile-titel')).toHaveText('Stufe 1');
      // Ohne Mietbeginn oder Betrag meldet der Generator, was fehlt
      await page.fill('#mzm-gen-betrag', '');
      await page.click('#mzm-gen-knopf');
      await expect(page.locator('#mzm-gen-hinweis')).toContainText('Betrag');
      await keinQuerscrollen(page, 'Staffelzeilen');
    });

    test('Schalttag: Jahrestag des 29. Februar ist der 1. März, Kette statt Abstand zum Beginn', async ({ page }) => {
      await zumMietzins(page, '2028-02-29');
      await modell(page, 'staffel');
      await page.fill('#mzm-gen-betrag', '10');
      await page.fill('#mzm-gen-anzahl', '4');
      await page.click('#mzm-gen-knopf');
      const ab = await zeilen(page).evaluateAll((z) => z.map((r) => (r.querySelector('[name=staffel_ab]') as HTMLInputElement).value));
      expect(ab).toEqual(['2029-03-01', '2030-03-01', '2031-03-01', '2032-03-01']);
      await geprueft(page);
      // Keine Zeile wird vom Server beanstandet: Die Kette hält die zwölf Monate genau ein
      await expect(page.locator('.fw-mzm-zeile[data-fehler]')).toHaveCount(0);
    });

    test('Zeilenfehler hängt an der Zeile, der Fix legt die Stufe auf den frühesten Tag', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'staffel');
      await page.fill('#mzm-gen-betrag', '50');
      await page.fill('#mzm-gen-anzahl', '2');
      await page.click('#mzm-gen-knopf');
      await geprueft(page);
      await expect(page.locator('.fw-mzm-zeile .fw-feldfehler')).toHaveCount(0);
      // Zweite Stufe nur sechs Monate nach der ersten
      await zeilen(page).nth(1).locator('[name=staffel_ab]').fill('2028-07-01');
      await geprueft(page);
      await expect(zeilen(page).nth(1)).toHaveAttribute('data-fehler', '');
      await expect(zeilen(page).nth(0)).not.toHaveAttribute('data-fehler', '');
      const meldung = zeilen(page).nth(1).locator('.fw-feldfehler');
      await expect(meldung).toContainText('Stufe 2');
      await expect(meldung).toContainText('Art. 269c lit. b OR');
      await expect(zeilen(page).nth(1).locator('[name=staffel_ab]')).toHaveAttribute('aria-invalid', 'true');
      await expect(weiter(page)).toBeDisabled();
      await zeilen(page).nth(1).locator('.fw-mzm-zeilenbefund .fw-btn').click();
      await expect(zeilen(page).nth(1).locator('[name=staffel_ab]')).toHaveValue('2029-01-01');
      await geprueft(page);
      await expect(zeilen(page).nth(1)).not.toHaveAttribute('data-fehler', '');
      // Erhöhung 0: Meldung an der Zeile, der Rest bleibt
      await zeilen(page).nth(0).locator('[name=staffel_erhoehung]').fill('0');
      await geprueft(page);
      await expect(zeilen(page).nth(0).locator('.fw-feldfehler')).toContainText('Frankenbetrag über 0');
      await keinQuerscrollen(page, 'Zeilenfehler');
    });

    test('Index: Basis ist der Vormonat zum Mietbeginn, nicht der aktuelle Stand', async ({ page }) => {
      await zumMietzins(page, '2025-01-01');
      await modell(page, 'index');
      await geprueft(page);
      // Dezember 2024 (106.9 Punkte), nicht der neueste Stand der Tabelle
      await expect(page.locator('#s_lik_stand')).toHaveValue('2024-12');
      await expect(page.locator('#s_lik')).toHaveValue('106.9');
      await expect(page.locator('#mzm-vorschlag')).toContainText('12.2024');
      await expect(page.locator('#mzm-vorschlag-knopf')).toBeHidden();
      await expect(page.locator('#mzm-panel-index')).toContainText('Landesindex der Konsumentenpreise (BFS)');
      await expect(page.locator('#mzm-panel-index select')).toHaveCount(0);   // fester Text, kein Auswahlfeld
      await expect(page.locator('#s_lik_stand')).toHaveAttribute('type', 'month');

      // Anderer Beginn: Der Vorschlag folgt, solange niemand die Felder selbst angefasst hat
      await page.locator('.fw-assistent-leiste li', { hasText: 'Konditionen' }).locator('button').click();
      await page.fill('#s_beginn', '2024-06-15');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await geprueft(page);
      await expect(page.locator('#s_lik_stand')).toHaveValue('2024-05');
      await expect(page.locator('#s_lik')).toHaveValue('107.7');

      // Eigene Eingabe bleibt: Der Vorschlag überschreibt sie nicht, bietet sich aber an
      await page.fill('#s_lik', '110');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Konditionen' }).locator('button').click();
      await page.fill('#s_beginn', '2025-01-01');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await geprueft(page);
      await expect(page.locator('#s_lik')).toHaveValue('110');
      await expect(page.locator('#mzm-vorschlag-knopf')).toBeVisible();
      await page.click('#mzm-vorschlag-knopf');
      await expect(page.locator('#s_lik')).toHaveValue('106.9');
      await expect(page.locator('#s_lik_stand')).toHaveValue('2024-12');
      await expect(page.locator('#mzm-vorschlag-knopf')).toBeHidden();
    });

    test('Index: Weitergabe über 100 wird nicht gekappt, sondern gesperrt; Fix und Grenzen', async ({ page }) => {
      await zumMietzins(page, '2025-01-01');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Konditionen' }).locator('button').click();
      await page.uncheck('#unbefristet');
      await page.fill('#s_ende', '2029-12-31');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await modell(page, 'index');
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/gut/);   // genau fünf Jahre: Beginn 1.1.2025, Ende 31.12.2029
      await expect(weiter(page)).toBeEnabled();
      const regeln: Array<[string, boolean]> = [['101', true], ['100', false], ['0', true], ['-5', true], ['60.5', false]];
      for (const [wert, gesperrt] of regeln) {
        await page.fill('#s_weitergabe', wert);
        await geprueft(page);
        if (gesperrt) {
          await expect(weiter(page), `Weitergabe ${wert}`).toBeDisabled();
          await expect(page.locator('#mzm-befunde')).toContainText('Art. 269b OR, Art. 17 Abs. 1 VMWG');
          await expect(page.locator('#s_weitergabe')).toHaveAttribute('aria-invalid', 'true');
        } else {
          await expect(weiter(page), `Weitergabe ${wert}`).toBeEnabled();
          await expect(page.locator('#s_weitergabe')).not.toHaveAttribute('aria-invalid', 'true');
        }
      }
      await page.fill('#s_weitergabe', '150');
      await geprueft(page);
      await page.locator('#mzm-befunde .fw-btn', { hasText: '100' }).first().click();
      await expect(page.locator('#s_weitergabe')).toHaveValue('100');
      await geprueft(page);
      await expect(weiter(page)).toBeEnabled();
      // Ein Tag zu kurz bei der Befristung: gesperrt (Gegenprobe zu «genau fünf Jahre»)
      await page.locator('.fw-assistent-leiste li', { hasText: 'Konditionen' }).locator('button').click();
      await page.fill('#s_ende', '2029-12-30');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/krit/);
      await expect(weiter(page)).toBeDisabled();
    });

    test('Index: Beispielrechnung aus dem aktuellen LIK, auf 5 Rappen abgerundet', async ({ page }) => {
      await zumMietzins(page, '2025-01-01', '2000');
      await modell(page, 'index');
      await geprueft(page);
      await page.fill('#s_lik', '107');
      await page.fill('#s_weitergabe', '100');
      const bsp = page.locator('#mzm-beispiel');
      await expect(bsp).toBeVisible();
      await expect(bsp).toContainText('LIK 108.3');
      await expect(bsp).toContainText("CHF 2'024.25");
      await expect(bsp).toContainText("heute CHF 2'000.00");
      await page.fill('#s_weitergabe', '60');
      await expect(bsp).toContainText("CHF 2'014.55");
      // Gleicher Stand: bleibt beim Mietzins
      await page.fill('#s_lik', '108.3');
      await expect(bsp).toContainText("bliebe der Mietzins bei CHF 2'000.00");
      // Ohne Basis keine Rechnung
      await page.fill('#s_lik', '');
      await expect(bsp).toBeHidden();
    });

    test('Sperre am Fuss: Weiter, Leiste und Vertrag erstellen bleiben gesperrt', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'staffel');
      await geprueft(page);
      await expect(weiter(page)).toBeDisabled();
      // Über die Leiste nach vorne: hält im Schritt «Mietzins» an
      await page.locator('.fw-assistent-leiste li', { hasText: 'Abschluss' }).locator('button').click();
      await expect(schritt(page)).toContainText('Mietzins');
      await page.waitForTimeout(400);   // die Meldung des Browsers zur Gültigkeit und das Scrollen setzen sich
      // Ein Klick auf den Grund im Fuss zeigt das Modell
      await page.locator('.fw-mzm-fuss-text').click();
      await expect(page.locator('#mzm_staffel')).toBeFocused();

      // Gültig machen: Verzicht, eine Stufe
      await page.locator('#mzm-ampel-fix .fw-btn').click();
      await page.fill('#mzm-gen-betrag', '50');
      await page.fill('#mzm-gen-anzahl', '1');
      await page.click('#mzm-gen-knopf');
      await geprueft(page);
      await expect(weiter(page)).toBeEnabled();
      for (const t of ['Kaution', 'Nebenkosten', 'Abschluss']) {
        await weiter(page).click();
        await expect(schritt(page)).toContainText(t);
      }
      await expect(page.locator('#btn-save')).toBeEnabled();
      await expect(page.locator('#summary')).toContainText('Staffelmiete');
      await expect(page.locator('#summary')).toContainText('31.12.2029');
      // Wird es im Abschluss ungültig, bleibt «Vertrag erstellen» gesperrt
      await page.evaluate(() => {
        (document.getElementById('unbefristet') as HTMLInputElement).checked = false;
        (document.getElementById('unbefristet') as HTMLInputElement).dispatchEvent(new Event('change', { bubbles: true }));
        const e = document.getElementById('s_ende') as HTMLInputElement; e.value = '2027-06-01'; e.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await geprueft(page);
      await expect(page.locator('#btn-save')).toBeDisabled();
      await expect(page.locator('#mzm-fuss')).toBeVisible();
      await keinQuerscrollen(page, 'Abschluss gesperrt');
    });

    test('Der Server lehnt auch ab, was der Browser nicht mehr verhindert', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'staffel');
      await page.fill('#mzm-gen-betrag', '50');
      await page.fill('#mzm-gen-anzahl', '2');
      await page.click('#mzm-gen-knopf');
      await geprueft(page);
      // Das Skript umgehen: Formular ohne den Assistenten abschicken
      await Promise.all([
        page.waitForResponse((r) => r.url().includes('/neu/vertraege/neu/speichern/') && r.status() === 400),
        page.evaluate(() => (document.getElementById('vform') as HTMLFormElement).submit()),
      ]);
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('.fw-formfehler')).toBeVisible();
      // Eingaben und Modell kommen zurück, die Befunde stehen wieder in der Ampel
      await expect(page.locator('#mzm_staffel')).toBeChecked();
      await expect(zeilen(page)).toHaveCount(2);
      await expect(zeilen(page).first().locator('[name=staffel_erhoehung]')).toHaveValue('50.00');
      // Der Assistent beginnt beim Schritt des ersten Fehlers: die Dauer steht in «Konditionen»
      await expect(schritt(page)).toContainText('Konditionen');
      await expect(page.locator('#s_verzicht')).toHaveAttribute('aria-invalid', 'true');
      await page.locator('.fw-assistent-leiste li', { hasText: 'Mietzins' }).locator('button').click();
      await geprueft(page);
      await expect(ampel(page)).toHaveClass(/krit/);
      await expect(weiter(page)).toBeDisabled();
      await keinQuerscrollen(page, 'Rückgabe vom Server');
    });

    test('Objekt-Staffelvorlage wird in Erhöhungen umgerechnet', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/vertraege/neu/');
      await objektWaehlen(page);
      // Das Objekt trägt keine Vorlage: Skript hineinreichen wie objChange() es tut
      await page.evaluate(() => {
        const o = (window as any).curObj();
        o.kategorie = 'gewerbe';
        o.staffelvorlage = [{ ab: '2028-01-01', netto: 2100 }, { ab: '2029-01-01', netto: 2250.5 }];
        (document.getElementById('s_netto') as HTMLInputElement).value = '2000';
        (window as any).applyStaffelVorlage();
      });
      await expect(page.locator('#mzm_staffel')).toBeChecked();
      const daten = await zeilen(page).evaluateAll((z) => z.map((r) => [
        (r.querySelector('[name=staffel_ab]') as HTMLInputElement).value,
        (r.querySelector('[name=staffel_erhoehung]') as HTMLInputElement).value,
      ]));
      expect(daten).toEqual([['2028-01-01', '100.00'], ['2029-01-01', '150.50']]);
    });

    test('Telefon und Dunkelmodus: nichts quer, Ampel lesbar, Fuss mit Grund bleibt im Bild', async ({ page }) => {
      await zumMietzins(page);
      await modell(page, 'index');
      await geprueft(page);
      await page.locator('#mzm').scrollIntoViewIfNeeded();
      await keinQuerscrollen(page, 'Index-Panel');
      for (const sel of ['.fw-mzm-kachel', '#mzm-ampel', '#mzm-panel-index', '.fw-assistent-fuss']) {
        const r = (await page.locator(sel).first().boundingBox())!;
        expect(r.x + r.width, sel).toBeLessThanOrEqual(b.viewport.width + 1);
      }
      if (b.viewport.width <= 400) {
        // Kacheln untereinander, jede mit Tippfläche ≥ 44 px
        const hoehen = await page.locator('.fw-mzm-kachel').evaluateAll((k) => k.map((e) => Math.round(e.getBoundingClientRect().height)));
        for (const h of hoehen) expect(h).toBeGreaterThanOrEqual(44);
        const fuss = (await page.locator('.fw-assistent-fuss').boundingBox())!;
        console.log(`MESSUNG ${b.name}: Fuss mit Sperre ${Math.round(fuss.height)} px hoch, Kacheln ${hoehen.join('/')} px`);
        expect(fuss.height, 'Fuss mit Grund nimmt nicht mehr als ein Drittel des Bildschirms').toBeLessThan(b.viewport.height / 3);
      }
      // Staffel mit Zeilen und Fehler
      await modell(page, 'staffel');
      await page.fill('#mzm-gen-betrag', '50');
      await page.fill('#mzm-gen-anzahl', '2');
      await page.click('#mzm-gen-knopf');
      await zeilen(page).nth(1).locator('[name=staffel_ab]').fill('2028-07-01');
      await geprueft(page);
      await keinQuerscrollen(page, 'Staffel mit Fehler');
      const felder = await zeilen(page).nth(1).locator('.fw-mzm-zeile-felder > *').evaluateAll((k) => k.map((e) => Math.round(e.getBoundingClientRect().width)));
      console.log(`MESSUNG ${b.name}: Zeilenfelder ${felder.join(' + ')} px`);
      const weg = (await zeilen(page).first().locator('.fw-mzm-weg').boundingBox())!;
      expect(weg.width).toBeGreaterThanOrEqual(40);
      expect(weg.height).toBeGreaterThanOrEqual(40);

      // Dunkelmodus: Ampel, Kachel und Befund bleiben lesbar (WCAG AA 4.5:1)
      await page.evaluate(() => (window as any).fwSetTheme('dark'));
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
      const kontrast = await page.evaluate(() => {
        const lum = (c: string) => {
          const m = c.match(/[\d.]+/g)!.map(Number);
          if (m.length >= 4 && m[3] === 0) throw new Error('durchsichtig: ' + c);
          const k = m.slice(0, 3).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); });
          return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
        };
        const grund = (e: Element) => {
          for (let x: Element | null = e; x; x = x.parentElement) {
            const c = getComputedStyle(x).backgroundColor;
            const m = c.match(/[\d.]+/g)!.map(Number);
            if (!(m.length >= 4 && m[3] === 0)) return c;
          }
          return 'rgb(0,0,0)';
        };
        const messen = (sel: string) => {
          const e = document.querySelector(sel)!;
          const a = lum(getComputedStyle(e).color), g = lum(grund(e));
          return (Math.max(a, g) + 0.05) / (Math.min(a, g) + 0.05);
        };
        return {
          ampel: messen('#mzm-ampel-text'), kachel: messen('.fw-mzm-kachel.akzent .fw-mzm-titel'),
          zeile: messen('.fw-mzm-zeile-titel'), start: messen('.fw-mzm-start'),
        };
      });
      for (const [name, wert] of Object.entries(kontrast)) expect(wert, `Dunkelmodus ${name}`).toBeGreaterThanOrEqual(4.5);
      await keinQuerscrollen(page, 'Dunkelmodus');
      await page.evaluate(() => (window as any).fwSetTheme('light'));
    });
  });
}
