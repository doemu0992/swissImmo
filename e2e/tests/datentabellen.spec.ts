import { test, expect } from '@playwright/test';
import { goto, login } from './helpers';

// Phase 3: dichte Datentabellen — Spaltenfilter, stehender Kopf, Glas, Breite.
// Die Seed-Daten haben wenige Debitoren; der Filter erscheint erst ab drei Zeilen,
// darum werden Zeilen im DOM vervielfacht (kein Eingriff in die Datenbank).

test.describe('Datentabellen', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    await page.evaluate(() => {
      const tb = document.querySelector('table[data-spaltenfilter] tbody')!;
      const zeilen = Array.from((tb as HTMLTableSectionElement).rows);
      for (let i = 0; i < 20; i++) zeilen.forEach((r) => tb.appendChild(r.cloneNode(true)));
    });
  });

  test('Filterzeile filtert, meldet den Stand und setzt zurück', async ({ page }) => {
    // Das Skript lief vor dem Vervielfachen; für den Test neu aufbauen.
    await page.evaluate(() => {
      const t = document.querySelector('table[data-spaltenfilter]') as HTMLElement;
      t.querySelector('tr.fw-filterzeile')?.remove();
      document.querySelector('.fw-filterstand')?.remove();
      delete t.dataset.filterBereit;
      (window as any).fwSpaltenfilter();
    });
    const sichtbar = () => page.locator('table[data-spaltenfilter] tbody tr:not(.fw-gefiltert)').count();
    const alle = await sichtbar();
    expect(alle).toBeGreaterThan(20);
    await page.locator('input.fw-filterfeld').first().fill('zzz-gibt-es-nicht');
    expect(await sichtbar()).toBe(0);
    await expect(page.locator('.fw-filterstand')).toContainText('0 von');
    await page.locator('.fw-filterstand button').click();
    expect(await sichtbar()).toBe(alle);
    await expect(page.locator('.fw-filterstand')).toBeHidden();
  });

  test('Der Tabellenkopf bleibt beim Scrollen stehen', async ({ page }) => {
    const wrap = page.locator('.fw-tablewrap.fw-sticky').first();
    const kopfOben = () => wrap.evaluate((w) => {
      const th = w.querySelector('thead th') as HTMLElement;
      return Math.round(th.getBoundingClientRect().top - w.getBoundingClientRect().top);
    });
    expect(await wrap.evaluate((w) => w.scrollHeight > w.clientHeight)).toBe(true);
    const vorher = await kopfOben();
    await wrap.evaluate((w) => { w.scrollTop = 500; });
    expect(await kopfOben()).toBe(vorher);
  });

  test('Seitenleiste ist verglast, der Inhalt nutzt grosse Bildschirme', async ({ page }) => {
    expect(await page.evaluate(() => getComputedStyle(document.querySelector('.fw-side')!).backdropFilter)).toContain('blur');
    await page.setViewportSize({ width: 2560, height: 1300 });
    const breite = await page.evaluate(() => document.querySelector('.fw-inhalt')!.getBoundingClientRect().width);
    expect(breite).toBeGreaterThan(1500);
  });

  test('Am Telefon läuft die Seite nicht quer', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
});
