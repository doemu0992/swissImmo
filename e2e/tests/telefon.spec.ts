import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// «HEUTE» AM TELEFON — GEMESSEN, NICHT GESCHÄTZT
//
// E2.68 hat die Startseite fürs Telefon umgebaut, weil bei 1280 Pixel alles
// nach Konzept aussah und bei 390 nicht: Die Reiterzeile stand in DREI Reihen
// (130 Pixel hoch), und in der Vorratszeile drängte sich der Farbmarker auf
// eine eigene Zeile — ein roter Strich über leerem Grund.
//
// WARUM DAS HIER STEHT UND NICHT IM DJANGO-TEST
//
// Der einzige bisherige Wächter dafür (`test_inbox_titel_bekommt_mobil_die_
// volle_breite`) liest die AUSGELIEFERTE ZEICHENKETTE der Stilschicht. Er
// merkt, wenn eine Regel verschwindet — aber nicht, ob sie wirkt. Ob drei
// Reiter in eine Reihe passen, entscheidet der Browser aus Schriftgrad,
// Innenabstand und `gap`; das lässt sich nicht aus dem Quelltext ablesen.
//
// Genau daran ist die Etappe zweimal vorbeigelaufen: Ein Entwurf zog 11 Pixel
// ab statt 15 — vier zu wenig, und die Zeile brach trotzdem um. Eine Zahl, die
// nur im Browser stimmt oder nicht stimmt.

const TELEFON = { width: 390, height: 844 };

test.use({ viewport: TELEFON });

test('Die Reiterzeile bleibt eine Reihe', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/');

  const reiter = page.locator('.fw-reiter').first();
  await expect(reiter).toBeVisible();

  const hoehe = await reiter.evaluate((el) => el.getBoundingClientRect().height);
  // Eine Reihe misst rund 43 Pixel; drei waren es 130. Die Grenze liegt
  // dazwischen und lässt Luft für einen anderen Schriftgrad.
  expect(hoehe, `Die Reiterzeile ist ${Math.round(hoehe)} px hoch — bei mehr ` +
    'als einer Reihe bricht sie um, und Konzept v7 zeigt eine.').toBeLessThan(70);

  // Und sie ist wirklich rollbar, statt die Reiter abzuschneiden.
  const rollbar = await reiter.evaluate(
    (el) => el.scrollWidth > el.clientWidth || getComputedStyle(el).overflowX === 'auto');
  expect(rollbar, 'Die Reiterzeile rollt nicht — dann sind die hinteren ' +
    'Reiter am Telefon unerreichbar.').toBeTruthy();
});

// WAS HIER NICHT STEHT: DIE VORRATSZEILE SELBST
//
// Der zweite gemeldete Fehler war der Marker, der sich in der Vorratszeile auf
// eine eigene Zeile drängte. Ein Test dafür ist hier NICHT möglich: Der
// E2E-Bestand sät keinen fälligen Fallschritt, die Arbeitsvorrat-Karte enthält
// also gar keine `.fw-zeile`. Gemessen — die Auswahl ist leer.
//
// Ein Test, der sich bei leerer Menge selbst überspringt, ist keiner. Die Regel
// bleibt deshalb von `test_inbox_titel_bekommt_mobil_die_volle_breite`
// gedeckt, der die ausgelieferte Zeichenkette prüft (`calc(100% - 15px)`) —
// schwächer, aber ehrlich benannt.
//
// DER NEBENBEFUND VON E2.68 IST IN E2.73 ENTSCHIEDEN WORDEN.
//
// Damals hier festgehalten: In der Karte «Aufgaben» steht zwischen Marker und
// Text eine `.fw-chip`; Marker und Chip teilen sich die erste Zeile, der Titel
// rückt auf die zweite, die Zeile wird 157 Pixel hoch. Das war bewusst nicht
// nebenbei entschieden. Jetzt ist es entschieden — und deshalb steht hier
// statt der Notiz ein Test.
//
// Anders als die Vorratszeile HAT die Aufgaben-Karte im E2E-Bestand Zeilen
// (nachgemessen: vier). Der Test ist also möglich, wo der andere es nicht war.

test('Die Aufgabenzeile kommt mit zwei Zeilen aus', async ({ page }) => {
  // GEMESSEN, BEIDE STÄNDE (390 × 844, `/neu/`):
  //
  //   mit  `order:4`   Zeile 113 px — Titel oben, darunter Betrag/Chip/Knopf
  //   ohne `order:4`   Zeile 157 px — Marker+Chip, Titel, Betrag/Knopf
  //
  // Die 44 Pixel sind eine ganze Zeile, die nur ein Wort trägt («Geld»).
  await login(page);
  await goto(page, '/neu/');

  // Seit dem zweiten Durchgang v8 stehen die Aufgaben als Reiter in der Karte
  // «Ausserdem» unter dem Arbeitsvorrat — die Zeilen sind dieselben.
  const karte = page.locator('#ausserdem-aufgaben');
  const zeile = karte.locator('.fw-zeile').first();
  await expect(zeile, 'Die Aufgaben-Karte hat keine Zeilen — dann misst ' +
    'dieser Test nichts.').toBeVisible();

  const hoehe = (await zeile.boundingBox())!.height;
  expect(hoehe, `Die Aufgabenzeile ist ${Math.round(hoehe)} Pixel hoch. ` +
    'Ohne `order:4` sind es 157: Marker und Chip belegen dann eine eigene ' +
    'erste Zeile.').toBeLessThan(130);

  // Und der Grund dafür, nicht nur die Folge: Der Chip steht UNTER dem Titel.
  // Ohne diese zweite Zusicherung bliebe der Test auch grün, wenn die Zeile
  // aus einem ganz anderen Grund kürzer würde.
  const chip = (await zeile.locator('> .fw-chip').boundingBox())!;
  const mitte = (await zeile.locator('.fw-mitte').boundingBox())!;
  expect(chip.y, 'Der Chip steht nicht unter dem Titel — dann wirkt `order` ' +
    'nicht, und die Höhe oben stimmt aus einem anderen Grund.')
    .toBeGreaterThan(mitte.y);
});

test('Die zwei Filter sind Kapseln und bleiben flach', async ({ page }) => {
  // GEMESSEN, BEIDE STÄNDE:
  //
  //   mit Kapseln    Zeile 29 px, Rahmen 1 px, Radius 999 px
  //   ohne Kapseln   Zeile 39 px, Rahmen 0,    Radius 0
  //
  // Ein erster Entwurf dieses Tests prüfte nur, ob die zwei Kapseln auf
  // derselben Höhe BEGINNEN. Das blieb bei der Gegenprobe grün — sie standen
  // auch vorher nebeneinander, weil der E2E-Bestand kurze Mandatsnamen hat.
  // Ein Test, der mit und ohne die Änderung besteht, misst nicht die Änderung.
  //
  // Die zwei Reihen aus dem Bericht entstehen erst bei einem langen Namen
  // («Muster Immobilien AG» machte die Kapsel 235 px breit). Den sät dieser
  // Bestand nicht — deshalb ist die HÖHE hier die belastbare Grösse, nicht die
  // Zeilenzahl.
  await login(page);
  await goto(page, '/neu/');

  // Seit dem zweiten Durchgang v8 stehen Zuständigkeit und Mandat im Kopf des
  // Arbeitsvorrats (`fw-vorrat-wahl`), am Telefon als eigene Zeile darunter.
  const zeile = page.locator('.fw-vorrat-wahl');
  const hoehe = await zeile.evaluate((el) => el.getBoundingClientRect().height);
  expect(hoehe, `Die Filterzeile ist ${Math.round(hoehe)} px hoch (gemessen: ` +
    '29 mit Kapseln, 39 ohne).').toBeLessThan(34);

  const kapseln = page.locator('.fw-vorrat-wahl select');
  await expect(kapseln).toHaveCount(2);
  const form = await kapseln.evaluateAll((els) => els.map((e) => {
    const cs = getComputedStyle(e);
    return { rand: parseFloat(cs.borderTopWidth), radius: parseFloat(cs.borderTopLeftRadius) };
  }));
  for (const [nr, k] of form.entries()) {
    expect(k.rand, `Kapsel ${nr + 1} hat keinen Rahmen — dann ist sie keine.`).toBeGreaterThan(0);
    expect(k.radius, `Kapsel ${nr + 1} ist nicht rund.`).toBeGreaterThan(20);
  }
});

// DIE KENNZAHLENLEISTE DER AKTE (E2.76)
//
// Bei 390 Pixel steht sie als 2x2-Raster, und der volle Innenabstand der Zelle
// zählt ZWEIMAL — einmal je Reihe. Zusammen mit der Fusszeile, die in 129
// Pixel Spaltenbreite ohnehin umbricht, wird die Zelle 104 Pixel hoch.
//
// GEMESSEN, BEIDE STÄNDE (390 × 844, Vertragsakte):
//
//   mit  `padding:8px 14px`   Leiste 182 px, Aktenkopf 544
//   ohne (12px 20px)          Leiste 206 px, Aktenkopf 568
//
// Was das NICHT ist: eine gelöste Falzfrage. 844 ist der CSS-Viewport dieses
// Tests; echtes Mobile-Safari zeigt mit Adressleiste weniger. Der Gewinn ist
// kürzerer Scrollweg auf jeder Akte, und so steht es auch im Stil.

test('Die Kennzahlenleiste bleibt am Telefon flach', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/vertraege/1/');

  // Seit konzept-v8 (30.09.2026, Tranche A) steht die Leiste als `fw-kpis
  // fw-stats` zwischen Seitenkopf und Reitern, nicht mehr im Aktenkopf.
  // Gemessen 390 x 844, Vertragsakte 1: 183 px mit den Telefon-Regeln
  // (`.fw-kpis.fw-stats` in der Stilschicht, Abschnitt Tranche A), 236 px ohne.
  const leiste = page.locator('.fw-kpis.fw-stats');
  await expect(leiste, 'Die Vertragsakte zeigt keine Kennzahlenleiste — ' +
    'dann misst dieser Test nichts.').toBeVisible();

  // Die drei Regeln tragen ungleich viel bei — einzeln nachgemessen, weil
  // eine Meldung, die den falschen Stand benennt, beim nächsten Fehlschlag
  // in die Irre führt:
  //
  //   alle drei aktiv                182 px
  //   ohne `padding:8px 14px`        198 px  (die zwei Abstände tragen 8)
  //   ohne alle drei                 206 px
  const hoehe = (await leiste.boundingBox())!.height;
  expect(hoehe, `Die Kennzahlenleiste ist ${Math.round(hoehe)} Pixel hoch — ` +
    'erwartet unter 195. Gemessen (v8): 183 mit den Telefon-Regeln, 236 ohne.').toBeLessThan(195);

  // Der Grund, nicht nur die Folge. Ohne diese Zusicherung bliebe der Test
  // grün, wenn die Leiste aus einem anderen Grund kürzer würde — etwa weil
  // eine Zelle verschwunden ist.
  const zellen = await leiste.locator('> .fw-kpi').count();
  expect(zellen, 'Die Leiste führt nicht mehr vier Kennzahlen — dann ist sie ' +
    'nicht flacher, sondern ärmer.').toBe(4);
});

// FINANZEN UND BERICHTE (konzept-v8, zweiter Durchgang, Tranche C)
//
// Zwei Zahlen, die nur der Browser kennt: Ob «CHF 579'959.50» in eine halbe
// Kennzahlkachel passt (Mockup: nein — der Betrag lief über den Rand), und ob
// die Monatsbeschriftung der Zahlungsquote bei 390 Pixel lesbar bleibt (im
// Mockup schrumpft sie mit dem SVG auf rund sechs Pixel).

test('Finanzen: Beträge passen in die Kacheln, Betrag neben dem Absender', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/finanzen/');

  const kacheln = await page.locator('.fw-fin-kpis .fw-v').evaluateAll((els) =>
    els.map((el) => ({ t: el.textContent, h: el.getBoundingClientRect().height,
      ueber: el.scrollWidth - el.clientWidth })));
  expect(kacheln.length).toBeGreaterThan(0);
  for (const k of kacheln) {
    expect(k.ueber, `«${k.t}» läuft über die Kachel hinaus`).toBeLessThanOrEqual(0);
    expect(k.h, `«${k.t}» bricht auf zwei Zeilen um (${Math.round(k.h)} px)`).toBeLessThan(30);
  }

  const zeile = page.locator('.fw-gs').first();
  await expect(zeile).toBeVisible();
  const [wer, betrag] = await Promise.all([
    zeile.locator('.fw-gs-wer').evaluate((el) => el.getBoundingClientRect().top),
    zeile.locator('.fw-betrag').evaluate((el) => el.getBoundingClientRect().top)]);
  expect(Math.abs(wer - betrag), 'Der Betrag steht nicht mehr auf der Zeile des Absenders')
    .toBeLessThan(8);

  const quer = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(quer).toBeLessThanOrEqual(0);
});

test('Berichte: Achsenbeschriftung lesbar und ohne Überlappung', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/berichte/');

  const achse = page.locator('.fw-kurve-achse');
  // Der E2E-Bestand hat Sollstellungen in mehreren Monaten — ohne Linie wäre
  // dieser Test leer und damit keiner.
  await expect(achse).toBeVisible();
  const x = await page.locator('.fw-kurve-x').evaluateAll((els) => els
    .filter((el) => getComputedStyle(el).display !== 'none')
    .map((el) => { const r = el.getBoundingClientRect();
      return { l: r.left, r: r.right, fs: parseFloat(getComputedStyle(el).fontSize) }; }));
  expect(x.length).toBeGreaterThan(3);
  for (let i = 1; i < x.length; i++) {
    expect(x[i].l, `Monatsbeschriftung ${i} überlappt die vorige`).toBeGreaterThanOrEqual(x[i - 1].r);
  }
  for (const b of x) expect(b.fs).toBeGreaterThanOrEqual(10);

  const karte = await page.locator('.fw-diagramm-balken').evaluate((el) => el.getBoundingClientRect().right);
  const werte = await page.locator('.fw-hbar-v').evaluateAll((els) => els.map((el) => el.getBoundingClientRect().right));
  for (const r of werte) expect(r).toBeLessThanOrEqual(karte);

  const quer = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(quer).toBeLessThanOrEqual(0);
});

test('Läufe: eine Spalte, Stufenband in einer Reihe, Knopf neben dem Kontext', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/laeufe/');

  const karten = page.locator('.fw-laeufe > .fw-lauf');
  // Der E2E-Bestand plant Läufe (laeufe_planen) — ohne Karte wäre das keiner.
  await expect(karten.first()).toBeVisible();
  const m = await karten.evaluateAll((els) => els.map((k) => {
    const r = k.getBoundingClientRect();
    const stufen = [...k.querySelectorAll('.fw-stufen li')].map((l) => l.getBoundingClientRect());
    return {
      l: Math.round(r.left), r: r.right,
      reihen: new Set(stufen.map((s) => Math.round(s.top))).size,
      stufeHoch: Math.max(...stufen.map((s) => s.height)),
      fuss: k.querySelector('.fw-lauf-fuss')!.getBoundingClientRect().height,
    };
  }));
  // Eine Spalte: alle Karten beginnen an derselben Kante und bleiben im Bild.
  expect(new Set(m.map((k) => k.l)).size).toBe(1);
  for (const k of m) {
    expect(k.r).toBeLessThanOrEqual(390);
    // Segment + eine Zeile Beschriftung misst 27 px; bricht die Beschriftung
    // um, wird es über 40.
    expect(k.reihen, 'Das Stufenband bricht in mehrere Reihen').toBe(1);
    expect(k.stufeHoch).toBeLessThan(40);
    // Kontext und Knopf in einer Zeile: 43 px; untereinander wären es über 70.
    expect(k.fuss).toBeLessThan(60);
  }
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(quer).toBeLessThanOrEqual(0);
});

test('Sollstellung: die Freigabeleiste verdeckt am Telefon nicht die halbe Seite', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/sollstellung/');
  const leiste = page.locator('.fw-freigabe');
  await expect(leiste).toBeVisible();
  // Mit der langen Erklärung waren es gemessen rund 200 px über der Tab-Leiste;
  // sie steht jetzt im Fuss der Positionen, die Leiste misst ~120.
  const hoch = await leiste.evaluate((el) => el.getBoundingClientRect().height);
  expect(hoch).toBeLessThan(160);
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(quer).toBeLessThanOrEqual(0);
});

// ---- Tranche D (v8, zweiter Durchgang): gemessen bei 390 × 844 -------------

test('Kreditoren: das Menü «Mehr» bleibt am Telefon im Bild', async ({ page }) => {
  // VORHER GEMESSEN: rechts verankert, 288 px breit, Knopf endet bei x = 272
  // → linke Kante bei x = -16. Jetzt hängt es an der Knopfzeile (x = 16).
  await login(page);
  await goto(page, '/neu/kreditoren/');
  await page.locator('main .fw-phead [data-menu-btn]').first().click();
  const liste = page.locator('main .fw-phead [data-menu-list]').first();
  await expect(liste).toBeVisible();
  const r = await liste.evaluate((el) => {
    const b = el.getBoundingClientRect();
    return { l: b.left, r: b.right, w: b.width };
  });
  expect(r.l, `Menü beginnt bei x = ${Math.round(r.l)}`).toBeGreaterThanOrEqual(0);
  expect(r.r).toBeLessThanOrEqual(390);
  // Nicht zusammengestaucht: die Einträge brauchen ihre 288 px.
  expect(r.w).toBeGreaterThan(250);
});

test('Mieterspiegel: die Summenzeile steht beschriftet unter der Tabelle', async ({ page }) => {
  // VORHER: «Soll-Total» rechtsbündig ohne Gewicht, die Netto-Summe als fette
  // Kartenüberschrift OHNE Beschriftung links, «Ist belegt» rechts.
  await login(page);
  await goto(page, '/neu/mieterspiegel/');
  await page.locator('main a[href^="/neu/mieterspiegel/?lg="]').first().click();
  await page.waitForLoadState('networkidle');
  const fuss = page.locator('main table tfoot tr').first();
  await expect(fuss).toBeVisible();
  const m = await fuss.evaluate((tr) => {
    const zellen = Array.from(tr.querySelectorAll('td')) as HTMLElement[];
    const titel = zellen[0];
    const erste = zellen[1];
    const wert = titel.querySelector('.fw-wert') as HTMLElement;
    return {
      titelLinks: wert.getBoundingClientRect().left - tr.getBoundingClientRect().left,
      zweiteLabel: getComputedStyle(erste, '::before').content,
      zweiteGewicht: getComputedStyle(erste).fontSize,
    };
  });
  // Titel an der linken Kante (Innenabstand 16 px), nicht rechts gerückt.
  expect(m.titelLinks).toBeLessThan(30);
  // Die Netto-Summe trägt ihre Spaltenbeschriftung wie die folgenden.
  expect(m.zweiteLabel).not.toBe('none');
  expect(m.zweiteGewicht).not.toBe('16px');
});

test('Dateifeld: Knopf und Rahmen passen ins Telefon', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/kreditoren/');
  await page.evaluate(() => document.getElementById('kredform')!.classList.remove('hidden'));
  const feld = page.locator('#kr-beleg');
  await expect(feld).toBeVisible();
  const m = await feld.evaluate((el) => {
    const b = el.getBoundingClientRect();
    return { r: b.right, h: b.height, rand: getComputedStyle(el).borderTopWidth };
  });
  expect(m.r).toBeLessThanOrEqual(390 - 16);
  // Eine Zeile: Knopf 30 px + Rand/Innenabstand = 40 px.
  expect(m.h).toBeLessThan(48);
  expect(m.rand).toBe('1px');
});

test('Seitenkopf: Brotkrume klein über dem Titel, auch auf Unterseiten', async ({ page }) => {
  await login(page);
  for (const pfad of ['/neu/mandate/', '/neu/kreditoren/', '/neu/nebenkosten/', '/neu/zulauf/']) {
    await goto(page, pfad);
    const m = await page.evaluate(() => {
      const k = document.querySelector('main .fw-phead .fw-krumen') as HTMLElement;
      const h = document.querySelector('main .fw-phead h1') as HTMLElement;
      return k && h ? { krume: k.getBoundingClientRect().bottom, h1: h.getBoundingClientRect().top,
        schrift: getComputedStyle(k).fontSize } : null;
    });
    expect(m, `${pfad}: keine Brotkrume im Seitenkopf`).not.toBeNull();
    expect(m!.krume).toBeLessThanOrEqual(m!.h1);
    expect(m!.schrift).toBe('12.5px');
  }
});

// AKTEN NACH KONZEPT-V8 (Tranche A, 30.09.2026): Liegenschaften und
// Mietverhältnisse als EINE Karte mit Reitern. Die Reiterzeile muss am
// Telefon EINE Reihe bleiben (gemessen 46 px), und die Tabelle darf die Seite
// nicht quer schieben — die Unterzeile «PLZ Ort · Baujahr» ist `nowrap`.
test('Akten: Reiter einreihig, nichts quer', async ({ page }) => {
  await login(page);
  for (const pfad of ['/neu/liegenschaften/', '/neu/vertraege/']) {
    await goto(page, pfad);
    const reiter = page.locator('.fw-akten-karte > .fw-reiter');
    await expect(reiter, `${pfad}: keine Reiterzeile in der Aktenkarte`).toBeVisible();
    const h = (await reiter.boundingBox())!.height;
    expect(h, `${pfad}: Reiterzeile ${Math.round(h)} px — umgebrochen?`).toBeLessThan(60);
    const quer = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(quer, `${pfad}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
  }
});
