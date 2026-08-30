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
// EIN NEBENBEFUND AUS DERSELBEN MESSUNG: In der Karte «Aufgaben» steht
// zwischen Marker und Text eine `.fw-chip`. Dort teilen sich Marker und Chip
// die erste Zeile und der Titel rückt auf die zweite — die Zeile wird 157
// Pixel hoch. Das ist eine ANDERE Zusammensetzung als die Vorratszeile, die
// diese Etappe umgebaut hat, und ob sie auch gekürzt werden soll, ist eine
// eigene Frage. Hier festgehalten, nicht nebenbei entschieden.

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

  const zeile = page.locator('.fw-kopffilter');
  const hoehe = await zeile.evaluate((el) => el.getBoundingClientRect().height);
  expect(hoehe, `Die Filterzeile ist ${Math.round(hoehe)} px hoch (gemessen: ` +
    '29 mit Kapseln, 39 ohne).').toBeLessThan(34);

  const kapseln = page.locator('.fw-kopffilter label');
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
