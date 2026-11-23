import { test, expect } from '@playwright/test';
import { login } from './helpers';

// «Aus einem Guss»: Jeder Baustein hat auf allen Seiten der Navigation EINE Form. Der Test misst sie am gerenderten Bild,
// nicht am Quelltext: Wer auf einer Seite eine eigene Knopfgrösse, Kachelform oder einen anderen linken Rand einführt, fällt hier auf.
const SEITEN: string[] = [
  '/konto/zwei-faktor/',
  '/neu/',
  '/neu/ablesung/',
  '/neu/abnahme-texte/',
  '/neu/abonnement/',
  '/neu/abwesenheiten/',
  '/neu/account/',
  '/neu/anfragen/',
  '/neu/anlagen/',
  '/neu/archiv/',
  '/neu/auftraege/',
  '/neu/auswertung/',
  '/neu/auswertung/eigene/',
  '/neu/bankabgleich/',
  '/neu/bankkonten/',
  '/neu/benutzer/',
  '/neu/berichte/',
  '/neu/buchhaltung/',
  '/neu/debitoren/',
  '/neu/dienstleister/',
  '/neu/dokumente/',
  '/neu/einstellungen/',
  '/neu/einstellungen/daten/',
  '/neu/einstellungen/zahlungsfreigabe/',
  '/neu/ersatzplanung/',
  '/neu/faelle/neu/',
  '/neu/finanzen/',
  '/neu/fristen/',
  '/neu/hypotheken/',
  '/neu/integrationen/',
  '/neu/kautionen/',
  '/neu/kommunikation/',
  '/neu/kontenplan/',
  '/neu/kreditoren/',
  '/neu/laeufe/',
  '/neu/lebensdauer/',
  '/neu/lieferantenkonten/',
  '/neu/liegenschaften/',
  '/neu/logbuch/',
  '/neu/mahnwesen/',
  '/neu/mandate/',
  '/neu/mieterkonten/',
  '/neu/mieterwechsel/',
  '/neu/mietzins/',
  '/neu/mwst/',
  '/neu/nebenkosten/',
  '/neu/objekte/',
  '/neu/pendenzen/',
  '/neu/personen/',
  '/neu/portfolio/',
  '/neu/postfaecher/',
  '/neu/rechtsgrundlagen/',
  '/neu/regelwerk/',
  '/neu/schaeden/',
  '/neu/sollstellung/',
  '/neu/stweg/',
  '/neu/team/',
  '/neu/termine/',
  '/neu/vertraege/',
  '/neu/vorlagen/',
  '/neu/zahllauf/',
  '/neu/zulauf/'
];

// Detailseiten und Formulare (Akte, Assistent): dieselben Bausteine, dieselben Masse.
const DETAIL: string[] = ['/neu/liegenschaften/1/', '/neu/vertraege/1/', '/neu/personen/1/', '/neu/einheiten/1/', '/neu/schaeden/1/', '/neu/mandate/1/',
  '/neu/dienstleister/1/', '/neu/personen/neu/', '/neu/liegenschaften/neu/', '/neu/faelle/neu/', '/neu/vertraege/neu/', '/neu/benutzer/neu/',
  '/neu/einstellungen/daten/import/', '/neu/einstellungen/daten/export/'];

test('Guss: Knöpfe, Karten, Kennzahlen, Felder und linker Rand sind auf allen Seiten gleich', async ({ page }) => {
  test.setTimeout(600000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  const befunde: string[] = [];
  const raender = new Map<number, string[]>();
  for (const u of [...SEITEN, ...DETAIL]) {
    const r = await page.goto(u, { waitUntil: 'domcontentloaded' });
    if (!r || r.status() !== 200) continue; // gesperrte Seite (Rolle, Abo) wird hier nicht geprüft
    const m = await page.evaluate(() => {
      const main = document.querySelector('main')!;
      const sichtbar = (e: any) => e.offsetWidth > 0 && e.offsetHeight > 0;
      const alle = (sel: string) => [...main.querySelectorAll(sel)].filter(sichtbar) as HTMLElement[];
      const cs = (e: Element) => getComputedStyle(e);
      const f: string[] = [];
      for (const b of alle('.fw-btn:not(.fw-mzm-weg)')) {
        if (b.closest('.fw-sk-absenden')) continue;
        const c = cs(b);
        if (c.minHeight !== '36px' || c.fontSize !== '14px' || c.paddingLeft !== '16px') { f.push('Knopf ' + c.minHeight + '/' + c.fontSize + '/' + c.paddingLeft + ' «' + (b.textContent || '').trim().slice(0, 30) + '»'); break; }
      }
      for (const k of alle('.fw-card')) {
        const c = cs(k);
        const ohne = parseFloat(c.borderTopWidth) === 0;
        if (!ohne && c.borderTopColor === 'rgba(0, 0, 0, 0)') { f.push('Karte ohne Linie: ' + k.className); break; }
        if (c.boxShadow !== 'none') { f.push('Karte mit Schatten: ' + k.className); break; }
      }
      for (const k of alle('.fw-kpis:not(.fw-gross) > .fw-kpi')) {
        const c = cs(k);
        if (parseFloat(c.borderTopLeftRadius) !== 0 || c.paddingLeft !== '18px') { f.push('Kennzahl nicht als Band: ' + c.borderTopLeftRadius + '/' + c.paddingLeft); break; }
      }
      for (const e of alle('input.fw-feld:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=range]), select.fw-feld')) {
        if (e.closest('.fw-kopffilter')) continue;
        if (Math.round(e.getBoundingClientRect().height) !== 40) { f.push('Feldhöhe ' + Math.round(e.getBoundingClientRect().height)); break; }
      }
      const h1 = alle('h1')[0];
      return { f, links: h1 ? Math.round(h1.getBoundingClientRect().left) : -1, einst: !!document.querySelector('.fw-einst-spalten'),
               quer: document.documentElement.scrollWidth > innerWidth };
    });
    for (const x of m.f) befunde.push(u + ': ' + x);
    if (m.quer) befunde.push(u + ': scrollt quer');
    if (m.links >= 0 && !m.einst && !DETAIL.includes(u)) raender.set(m.links, [...(raender.get(m.links) || []), u]);
  }
  expect(befunde, befunde.join('\n')).toEqual([]);
  // Ein linker Rand für alle Seiten ausserhalb der Einstellungen (dort steht die Seitenliste davor)
  expect([...raender.keys()], JSON.stringify([...raender.entries()].filter(([, s]) => s.length < 10))).toHaveLength(1);
});

test('Guss am Telefon: nichts scrollt quer, Knöpfe haben Fingergrösse, Karten tragen die Linie', async ({ page }) => {
  test.setTimeout(600000);
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  const befunde: string[] = [];
  for (const u of [...SEITEN, ...DETAIL]) {
    const r = await page.goto(u, { waitUntil: 'domcontentloaded' });
    if (!r || r.status() !== 200) continue;
    const f = await page.evaluate(() => {
      const main = document.querySelector('main')!;
      const sichtbar = (e: any) => e.offsetWidth > 0 && e.offsetHeight > 0;
      const alle = (sel: string) => [...main.querySelectorAll(sel)].filter(sichtbar) as HTMLElement[];
      const f: string[] = [];
      if (document.documentElement.scrollWidth > innerWidth) f.push('scrollt quer');
      const hoehen = new Set(alle('.fw-btn:not(.fw-mzm-weg)').filter(b => !b.closest('.fw-sk-absenden')).map(b => getComputedStyle(b).minHeight));
      if (hoehen.size > 1) f.push('Knopfhöhen ' + [...hoehen].join(', '));
      for (const k of alle('.fw-card')) {
        const c = getComputedStyle(k);
        if (parseFloat(c.borderTopWidth) > 0 && c.borderTopColor === 'rgba(0, 0, 0, 0)') { f.push('Karte ohne Linie: ' + k.className); break; }
      }
      return f;
    });
    for (const x of f) befunde.push(u + ': ' + x);
  }
  expect(befunde, befunde.join('\n')).toEqual([]);
});
