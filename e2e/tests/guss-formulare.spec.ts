import { test, expect } from '@playwright/test';
import { login } from './helpers';

// «Aus einem Guss» in den Seitenformularen der Verwaltung: ein Fuss (`.fw-formular-fuss`), Abbrechen links davon,
// Hauptknopf rechts aussen, eine Lesebreite. Gemessen 23.11.2026: Hauptknopf in 25 Formularen links, in 8 rechts;
// Breiten 672, 768 und 920 px.
const FORMULARE = ['/neu/vertraege/1/verzug/', '/neu/vertraege/1/schlussabrechnung/', '/neu/vertraege/1/abnahme/neu/', '/neu/objekte/neu/',
  '/neu/vertraege/1/verfahren/', '/neu/vertraege/1/bearbeiten/', '/neu/faelle/neu/', '/neu/abnahme-texte/', '/neu/regelwerk/neu/'];

test('Seitenformulare: Hauptknopf rechts aussen, Abbrechen davor, höchstens Lesebreite', async ({ page }) => {
  test.setTimeout(300000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  const befunde: string[] = [];
  for (const u of FORMULARE) {
    const r = await page.goto(u, { waitUntil: 'load' });
    expect(r!.status(), u).toBe(200);
    const m = await page.evaluate(() => {
      const sichtbar = (e: any) => e.offsetWidth > 0 && e.offsetHeight > 0;
      const fuss = [...document.querySelectorAll('main .fw-formular-fuss')].filter(sichtbar).pop() as HTMLElement;
      if (!fuss) return null;
      const kinder = ([...fuss.children].filter(sichtbar) as HTMLElement[]).sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
      const fb = fuss.getBoundingClientRect(), letzter = kinder[kinder.length - 1];
      return { hauptRechts: letzter.classList.contains('fw-primary') && Math.abs(fb.right - letzter.getBoundingClientRect().right) < 2,
        abbrechenZuerst: !kinder.some(k => k.classList.contains('fw-geist')) || kinder[0].classList.contains('fw-geist'), breite: Math.round(fb.width) };
    });
    if (!m) { befunde.push(u + ': kein .fw-formular-fuss'); continue; }
    if (!m.hauptRechts) befunde.push(u + ': Hauptknopf nicht rechts aussen');
    if (!m.abbrechenZuerst) befunde.push(u + ': Abbrechen steht nicht zuerst');
    if (m.breite > 920) befunde.push(u + ': Formular breiter als die Lesebreite (' + m.breite + ' px)');
  }
  expect(befunde, befunde.join('\n')).toEqual([]);
});

test('Zahlungsverzug: Enter im Feld löst «Frist ansetzen» aus, nicht den PDF-Knopf', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto('/neu/vertraege/1/verzug/', { waitUntil: 'load' });
  // Der erste Absendeknopf im Quelltext ist der Hauptknopf, auch wenn er im Bild rechts aussen steht
  const erster = await page.evaluate(() => { const f = document.querySelector('main .fw-formular-fuss')!.closest('form')!; const k = f.querySelector('button[type=submit], button:not([type])')!; return [k.classList.contains('fw-primary'), k.getAttribute('name')]; });
  expect(erster).toEqual([true, null]);
});
