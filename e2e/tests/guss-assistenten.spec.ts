import { test, expect } from '@playwright/test';
import { login } from './helpers';

// «Aus einem Guss» in den Assistenten der Verwaltung: derselbe Aufbau überall. Gemessen 23.11.2026 bei 1440 px:
// Betreibung in einer 672-px-Spalte, Weiterverrechnen mit liegender Schrittleiste und eigener Vorschaukarte, Fuss in den
// Assistenten mit Vorschau zweizeilig (110 statt 64 px), Kommunikation und Weiterverrechnen ohne Pfadzeile.
const ASSISTENTEN: [string, boolean][] = [
  ['/neu/vertraege/neu/', true], ['/neu/kommunikation/', true], ['/neu/kreditoren/1/weiterverrechnen/', true],
  ['/neu/nebenkosten/neu/', false], ['/neu/liegenschaften/neu/', false], ['/neu/personen/neu/', false],
  ['/neu/vertraege/1/kuendigen/', false], ['/neu/mietzins/1/anpassung/', false], ['/neu/betreibungen/neu/1/', false],
];

test('Assistenten: gleiche Breite, Schrittliste links, Fuss einzeilig, Vorschau rechts, Pfadzeile', async ({ page }) => {
  test.setTimeout(300000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  const befunde: string[] = [];
  for (const [u, mitVorschau] of ASSISTENTEN) {
    await page.goto(u, { waitUntil: 'load' });
    await expect(page.locator('.fw-assistent.an')).toBeVisible();
    const m = await page.evaluate(() => {
      const r = (s: string) => { const e = document.querySelector(s) as HTMLElement; return e && e.offsetWidth ? e.getBoundingClientRect() : null; };
      const main = document.querySelector('main')!; const cs = getComputedStyle(main);
      const innen = main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const a = r('.fw-assistent')!, l = r('.fw-assistent-leiste')!, i = r('.fw-assistent-inhalt')!, f = r('.fw-assistent-fuss')!, v = r('.fw-assistent-vorschau');
      const pfad = document.querySelector('.fw-kopfleiste .fw-brotkrume, .fw-kopfleiste .fw-krumen, main .fw-brotkrume') as HTMLElement;
      const vt = document.querySelector('.fw-assistent-vorschau-titel');
      return { breite: Math.round(a.width) === Math.round(innen), leisteLinks: l.right <= i.left && l.height > 150, fuss: Math.round(f.height),
        vorschauRechts: v ? v.left >= i.right : null, vorschauTitel: vt ? getComputedStyle(vt).textTransform + ' ' + getComputedStyle(vt).fontSize : null,
        pfad: pfad ? pfad.innerText.trim().length > 3 : false };
    });
    if (!m.breite) befunde.push(u + ': Assistent nicht in voller Inhaltsbreite');
    if (!m.leisteLinks) befunde.push(u + ': Schrittliste steht nicht links neben dem Inhalt');
    if (m.fuss > 70) befunde.push(u + ': Fuss ' + m.fuss + ' px (zweizeilig)');
    if (!m.pfad) befunde.push(u + ': keine Pfadzeile');
    if (mitVorschau && (m.vorschauRechts !== true || m.vorschauTitel !== 'uppercase 12px')) befunde.push(u + ': Vorschau ' + m.vorschauRechts + ' / ' + m.vorschauTitel);
    if (!mitVorschau && m.vorschauRechts !== null) befunde.push(u + ': unerwartete Vorschau');
  }
  expect(befunde, befunde.join('\n')).toEqual([]);
});

test('Assistenten am Telefon: kein Querscrollen, Vorschau unter dem Inhalt', async ({ page }) => {
  test.setTimeout(300000);
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  for (const [u, mitVorschau] of ASSISTENTEN) {
    await page.goto(u, { waitUntil: 'load' });
    const m = await page.evaluate(() => ({ quer: document.documentElement.scrollWidth > innerWidth,
      vorschauUnten: (() => { const v = document.querySelector('.fw-assistent-vorschau') as HTMLElement, i = document.querySelector('.fw-assistent-inhalt') as HTMLElement; return v && v.offsetWidth ? v.getBoundingClientRect().top >= i.getBoundingClientRect().top : null; })() }));
    expect(m.quer, u + ' scrollt quer').toBe(false);
    if (mitVorschau) expect(m.vorschauUnten, u + ' Vorschau').toBe(true);
  }
});

test('Pfadzeile: ein Trennzeichen in beiden Bauarten', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto('/neu/faelle/neu/', { waitUntil: 'load' });
  const krumen = await page.evaluate(() => { const s = document.querySelector('.fw-krumen > span[aria-hidden="true"]')!; return getComputedStyle(s, '::before').content + ' ' + getComputedStyle(s).fontSize; });
  expect(krumen).toBe('"›" 0px');
  await page.goto('/neu/nebenkosten/neu/', { waitUntil: 'load' });
  const brot = await page.evaluate(() => Math.round(document.querySelector('.fw-brotkrume > .fw-zeichen')!.getBoundingClientRect().width));
  expect(brot).toBe(11);
});
