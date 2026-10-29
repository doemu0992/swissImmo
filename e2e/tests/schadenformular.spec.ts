import { test, expect, Page } from '@playwright/test';

// Das öffentliche Schadenformular — die Seite vom Aushang im Treppenhaus und der Weg über die Website.
//
// ES GIBT DAS FORMULAR NUR NOCH EINMAL (Etappe 3, 29.10.2026)
//
// Bis dahin standen zwei Alpine-Vorlagen nebeneinander (`/report/<id>/` und `/schaden/melden/`),
// und eine Korrektur traf immer nur eine — «Dieser Test läuft deshalb über BEIDE» stand hier.
// Jetzt rendern beide dieselbe Vorlage mit dem Assistenten der Anwendung; die Räume und
// Gegenstände kommen aus `core/templatetags/raumkatalog.py`. Der Test läuft trotzdem über beide
// Wege: Er prüft, was nur der Browser zeigt — dass die Karten ein auflösbares Zeichen tragen, dass
// die Wahl des Anliegens die Schritte ein- und ausblendet, was je Raum angeboten wird, und dass
// die Anzeige übersetzt, der gespeicherte Wert aber deutsch bleibt.
const FORMULARE = [
  { pfad: '/report/1/', name: 'Aushang' },
  { pfad: '/schaden/melden/', name: 'Website' },
];

const karte = (page: Page, text: string | RegExp) =>
  page.locator('label.fw-wahl', { hasText: typeof text === 'string' ? new RegExp(`^\\s*${text}\\s*$`) : text });

async function oeffnen(page: Page, pfad: string) {
  await page.goto(pfad, { waitUntil: 'load' });
}

/** Wählt «Schadensmeldung» und gibt die Räume mit ihren Gegenständen zurück (Wert = deutsch, gespeichert). */
async function katalog(page: Page) {
  await karte(page, 'Schadensmeldung').click();
  return page.evaluate(() => {
    const raeume = Array.from(document.querySelectorAll('#meldungRaum input[name="raum"]')).map((i) => {
      const el = i as HTMLInputElement;
      const zeichen = el.closest('label')!.querySelector('use')?.getAttribute('href') || '';
      return { wert: el.value, zeichen, aufgeloest: !!(zeichen && document.querySelector(zeichen)) };
    });
    const objekte: Record<string, string[]> = {};
    document.querySelectorAll('#meldungObjekt fieldset[data-raum]').forEach((f) => {
      objekte[f.getAttribute('data-raum')!] = Array.from(f.querySelectorAll('input[name="objekt"]')).map(
        (i) => (i as HTMLInputElement).value);
    });
    return { raeume, objekte };
  });
}

for (const f of FORMULARE) {
  test(`${f.name}: Jeder Raum trägt ein eigenes, auflösbares Zeichen`, async ({ page }) => {
    await oeffnen(page, f.pfad);
    const { raeume } = await katalog(page);
    expect(raeume.length, 'Keine Raumkarten.').toBeGreaterThan(10);
    // Ein Tippfehler im Zeichen zeichnet nichts und meldet nichts: gemessen wird, ob es im Sprite steht.
    expect(raeume.filter((r) => !r.aufgeloest).map((r) => `${r.wert} → ${r.zeichen}`)).toEqual([]);
    // Zwölf gleiche Zeichen wären so gut wie keine.
    expect(new Set(raeume.map((r) => r.zeichen)).size).toBe(raeume.length);
  });

  test(`${f.name}: Kein Raum bietet an, was es dort nicht gibt`, async ({ page }) => {
    await oeffnen(page, f.pfad);
    const { raeume, objekte } = await katalog(page);
    // 1. Jeder Raum hat eine eigene Liste, nichts doppelt, jeder bietet etwas an.
    for (const r of raeume) {
      const liste = objekte[r.wert] || [];
      expect(liste.length, `${r.wert} bietet nichts an`).toBeGreaterThan(1);
      expect(liste.filter((p, i) => liste.indexOf(p) !== i), `${r.wert} bietet doppelt an`).toEqual([]);
    }
    // 2. Der Briefkasten hat weder Decke noch Boden noch Fenster — wer «Decke» meldet, schickt einen
    //    Handwerker zu etwas, das es nicht gibt (E2.51).
    for (const unmoeglich of ['Decke', 'Boden', 'Wand', 'Steckdose', 'Fenster', 'Storen/Markise']) {
      expect(objekte['Briefkasten'], `Briefkasten bietet «${unmoeglich}» an`).not.toContain(unmoeglich);
    }
    expect(objekte['Balkon/Terrasse']).not.toContain('Decke');
  });

  test(`${f.name}: Nur die Schadensmeldung fragt nach Raum und Gegenstand`, async ({ page }) => {
    await oeffnen(page, f.pfad);
    // Anfangs: Anliegen, Beschreibung, Kontakt, Prüfen — vier Schritte.
    await expect(page.locator('.fw-assistent-stand')).toHaveText('Schritt 1 von 4');
    await karte(page, 'Schadensmeldung').click();
    await expect(page.locator('.fw-assistent-stand')).toHaveText('Schritt 2 von 6');
    await expect(page.locator('.fw-assistent-leiste li.hier')).toContainText('Raum');
    // Zurück und ein anderes Anliegen: die zwei Schritte entfallen wieder, ihre Felder werden nicht gesendet.
    await page.getByRole('button', { name: 'Zurück' }).click();
    await karte(page, 'Allgemeine Anfrage').click();
    await expect(page.locator('.fw-assistent-leiste li.hier')).toContainText('Beschreibung');
    await expect(page.locator('.fw-assistent-leiste li')).toHaveCount(4);
    expect(await page.locator('input[name="raum"]:enabled').count()).toBe(0);
  });

  test(`${f.name}: Telefon 390 px, DM Sans, kein Querscroll`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await oeffnen(page, f.pfad);
    const m = await page.evaluate(() => ({
      breit: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      schrift: getComputedStyle(document.body).fontFamily,
      plex: Array.from(document.querySelectorAll('body *')).some((e) => /IBM Plex Sans/.test(getComputedStyle(e).fontFamily.split(',')[0])),
    }));
    expect(m.breit).toBeLessThanOrEqual(0);
    expect(m.schrift).toContain('DM Sans');
    expect(m.plex, 'IBM Plex Sans steht noch auf einem Element').toBe(false);
    for (const wahl of ['Schadensmeldung', 'Küche']) {
      await karte(page, wahl).click();
      const breit = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(breit, `Querscroll nach «${wahl}»`).toBeLessThanOrEqual(0);
    }
  });
}

// DIE FORMULARE BIETEN DIESELBEN RÄUME AN
//
// Beide Wege lesen aus einem Katalog; wer ihn ändert, ändert beide. Der Test hält fest, dass das
// auch im Browser so ankommt (früher liefen zwei Listen langsam auseinander).
test('Beide Formulare bieten dieselben Räume an', async ({ page }) => {
  const je: string[][] = [];
  for (const f of FORMULARE) {
    await oeffnen(page, f.pfad);
    je.push((await katalog(page)).raeume.map((r) => `${r.wert} (${r.zeichen})`));
  }
  expect(je[1]).toEqual(je[0]);
});

// ANZEIGE ÜBERSETZT, WERT BLEIBT DEUTSCH (29.09.2026)
//
// Die Karten zeigen die Sprache des Besuchers («Cuisine», «Réfrigérateur»), gespeichert wird das
// deutsche Wort: Es landet als `raum`/`objekt`/`kategorie` bzw. im Titel der Meldung, und die
// Verwaltung filtert und wertet danach aus. Gegenprobe: in der Vorlage `value="{{ r.wert }}"` auf
// `{{ r.anzeige }}` stellen — dieser Test wird rot.
for (const f of FORMULARE) {
  test(`${f.name}: Französisch angezeigt, deutsch gespeichert`, async ({ page, baseURL }) => {
    await page.context().addCookies([{ name: 'django_language', value: 'fr', url: baseURL! }]);
    await oeffnen(page, f.pfad);
    await karte(page, 'Annonce de dommage').click();
    await karte(page, 'Cuisine').click();
    await karte(page, 'Réfrigérateur').click();
    const werte = await page.evaluate(() => {
      const v = (n: string) => (document.querySelector(`input[name="${n}"]:checked`) as HTMLInputElement | null)?.value ?? null;
      return { kategorie: v('kategorie'), raum: v('raum'), objekt: v('objekt') };
    });
    expect(werte).toEqual({ kategorie: 'Schadensmeldung', raum: 'Küche', objekt: 'Kühlschrank' });
    expect(await page.locator('body').innerText()).not.toContain('Kühlschrank');
  });
}
