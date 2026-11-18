import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { login, goto } from './helpers';

// BARRIEREFREIHEIT: Axe gegen die wichtigsten Seiten (Roadmap Nr. 21).
//
// Gemessen wird nach WCAG 2.0/2.1 A und AA. Der Test ist eine RATSCHE: `BEKANNT` hält fest, welche Regeln auf
// welcher Seite heute noch verletzt sind (mit Obergrenze der betroffenen Elemente). Er schlägt an, wenn eine
// Regel NEU verletzt wird oder mehr Elemente trifft, und ebenso, wenn etwas behoben wurde und die Liste nicht
// nachgeführt ist — damit der Fortschritt nicht verloren geht. Ziel ist eine leere Liste.

const SEITEN = [
  '/login/',
  '/neu/',
  '/neu/liegenschaften/',
  '/neu/vertraege/',
  '/neu/debitoren/',
  '/neu/kreditoren/',
  '/neu/personen/',
  '/neu/buchhaltung/',
  '/neu/einstellungen/',
];

// Seite -> Regel -> höchstens so viele betroffene Elemente
const BEKANNT: Record<string, Record<string, number>> = {};

test('Axe: keine neuen Verstösse gegen WCAG A/AA', async ({ page }) => {
  test.setTimeout(240_000);
  const gefunden: Record<string, Record<string, number>> = {};
  for (const seite of SEITEN) {
    if (seite !== '/login/' && Object.keys(gefunden).length === 1) await login(page);
    if (seite === '/login/') await page.context().clearCookies();
    await goto(page, seite);
    const ergebnis = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const regeln: Record<string, number> = {};
    for (const v of ergebnis.violations) {
      regeln[v.id] = v.nodes.length;
      if (process.env.AXE_AUSGABE) console.log(`AXE-NODE ${seite} ${v.id}: ` + v.nodes.map((n) => n.html.slice(0, 220)).join(' || '));
    }
    gefunden[seite] = regeln;
  }
  if (process.env.AXE_AUSGABE) console.log('AXE ' + JSON.stringify(gefunden, null, 1));

  const zuViel: string[] = [], behoben: string[] = [];
  for (const seite of SEITEN) {
    const ist = gefunden[seite] || {}, soll = BEKANNT[seite] || {};
    for (const [regel, n] of Object.entries(ist)) {
      if (n > (soll[regel] || 0)) zuViel.push(`${seite}: ${regel} ${soll[regel] || 0} → ${n}`);
    }
    for (const [regel, n] of Object.entries(soll)) {
      if ((ist[regel] || 0) < n) behoben.push(`${seite}: ${regel} ${n} → ${ist[regel] || 0} (BEKANNT senken)`);
    }
  }
  expect(zuViel, 'Neue oder mehr Verstösse (Axe)').toEqual([]);
  expect(behoben, 'Behoben: BEKANNT nachführen').toEqual([]);
});
