import { test, expect } from '@playwright/test';

// «Aus einem Guss» auf den Aussenseiten: was Mieter, Bewerber und Gäste ohne Anmeldung sehen, trägt dieselben Bausteine
// wie Verwaltung und Portale. Gemessen 23.11.2026: Startseite und Passwort-Seiten mit Titel in Inter, Karten mit Schatten,
// Feld 46 px. Die Fehlerseiten zeigt der Testserver (DEBUG) nicht: sie prüft core/tests/test_guss_aussen.py.
const SEITEN = ['/', '/passwort/vergessen/', '/passwort/gesendet/', '/passwort/fertig/', '/schaden/melden/', '/report/1/', '/bewerben/1/', '/datenschutz/'];

for (const breite of [1280, 390]) {
  test(`Guss auf den Aussenseiten bei ${breite} px: Titel, Karten, Knöpfe, Felder`, async ({ page }) => {
    await page.setViewportSize({ width: breite, height: 900 });
    const befunde: string[] = [];
    for (const u of SEITEN) {
      await page.goto(u, { waitUntil: 'load' });
      const f = await page.evaluate(() => {
        const cs = (e: Element) => getComputedStyle(e);
        const sichtbar = (e: any) => e.offsetWidth > 0 && e.offsetHeight > 0;
        const f: string[] = [];
        const h1 = [...document.querySelectorAll('h1')].filter(sichtbar)[0];
        if (!h1) f.push('kein Titel');
        else if (!cs(h1).fontFamily.startsWith('Sora') || cs(h1).fontWeight !== '700') f.push('Titel ' + cs(h1).fontFamily.slice(0, 12) + ' ' + cs(h1).fontWeight);
        for (const b of [...document.querySelectorAll('.fw-btn')].filter(sichtbar)) {
          const c = cs(b);
          if (parseFloat(c.borderTopLeftRadius) < 100 || parseFloat(c.minHeight) < 36) { f.push('Knopf ' + c.minHeight + '/' + c.borderTopLeftRadius); break; }
        }
        for (const e of [...document.querySelectorAll('body *')] as HTMLElement[]) {
          if (e.offsetWidth < 250 || e.offsetHeight < 90) continue;
          const c = cs(e);
          if (c.backgroundColor !== 'rgb(255, 255, 255)' || parseFloat(c.borderTopLeftRadius) < 8) continue;
          // Der klebende Fuss des Assistenten schwebt bewusst (wie in der Verwaltung)
          if (e.closest('.fw-assistent-fuss, .fw-sk-fuss, [class*="fuss"]')) continue;
          if (c.boxShadow !== 'none') { f.push('Karte mit Schatten: ' + e.className.toString().slice(0, 40)); break; }
          if (parseFloat(c.borderTopLeftRadius) !== 24) { f.push('Kartenradius ' + c.borderTopLeftRadius + ': ' + e.className.toString().slice(0, 40)); break; }
        }
        for (const e of [...document.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=range]):not([type=hidden]), select')].filter(sichtbar)) {
          if (Math.round(e.getBoundingClientRect().height) !== 40) { f.push('Feldhöhe ' + Math.round(e.getBoundingClientRect().height)); break; }
        }
        if (document.documentElement.scrollWidth > innerWidth) f.push('scrollt quer');
        return f;
      });
      for (const x of f) befunde.push(u + ': ' + x);
    }
    expect(befunde, befunde.join('\n')).toEqual([]);
  });
}
