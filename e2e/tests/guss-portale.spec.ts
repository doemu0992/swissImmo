import { test, expect, Page } from '@playwright/test';
import { goto, warteAufURL } from './helpers';

// «Aus einem Guss» in den Portalen: Mieter- und Eigentümerportal tragen dieselben Bausteine wie die Verwaltung.
// Gemessen am gerenderten Bild (23.11.2026: Titel in Inter 600, Karten mit 12 px und Schatten, orange Akzentkachel,
// dunkler Verlaufsblock, eigene Knopfformen). Wer im Portal wieder eine eigene Form einführt, fällt hier auf.

const PORTALE: [string, string, string[]][] = [
  ['Mieterportal', 'e2e-mieter', ['/mieter/', '/mieter/rechnungen/', '/mieter/dokumente/', '/mieter/tickets/', '/mieter/schaden/neu/',
    '/mieter/konto/', '/mieter/anfragen/', '/mieter/zaehler/', '/mieter/daten/', '/mieter/passwort/', '/mieter/kuendigung/']],
  ['Eigentümerportal', 'e2e-eigentuemer', ['/portal/', '/portal/liegenschaften/', '/portal/schaeden/', '/portal/abrechnungen/',
    '/portal/dokumente/', '/portal/mitteilungen/', '/portal/profil/']],
  // Betreiber-Portal: eigenes Konto im Seed (nur bei DEBUG), Kunde 1 ist die E2E-Verwaltung
  ['Betreiber-Portal', 'e2e-betreiber', ['/betreiber/', '/betreiber/neu/', '/betreiber/protokoll/', '/betreiber/csp/', '/betreiber/lik/',
    '/betreiber/sicherheit/', '/betreiber/1/', '/betreiber/1/bearbeiten/', '/betreiber/1/abo/']],
];

async function anmelden(page: Page, name: string) {
  await goto(page, name === 'e2e-betreiber' ? '/betreiber/login/' : '/portal/login/');
  await page.fill('input[name="username"]', name);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
}

for (const [portal, konto, seiten] of PORTALE) {
  test(`Guss im ${portal}: Titel, Karten, Knöpfe und Felder wie in der Verwaltung`, async ({ page }) => {
    test.setTimeout(300000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await anmelden(page, konto);
    const befunde: string[] = [];
    // Navigation wie in der Verwaltung: Seitenleiste links (248 px), der Inhalt daneben; die aktive Seite ist markiert
    await goto(page, seiten[0]);
    const leiste = await page.locator('#pSidebar').boundingBox();
    const inhalt = await page.locator('main').boundingBox();
    expect(Math.round(leiste!.width)).toBe(248);
    expect(leiste!.x).toBe(0);
    expect(inhalt!.x).toBeGreaterThanOrEqual(248);
    await expect(page.locator('#pSidebar .fw-nav-eintrag.hier')).toHaveCount(1);
    await expect(page.locator('#pSidebar .fw-nav-eintrag').first().locator('svg')).toBeVisible();
    for (const u of seiten) {
      const r = await page.goto(u, { waitUntil: 'domcontentloaded' });
      if (!r || r.status() !== 200) { befunde.push(u + ': Status ' + (r ? r.status() : 0)); continue; }
      const f = await page.evaluate(() => {
        const main = document.querySelector('main')!;
        const sichtbar = (e: any) => e.offsetWidth > 0 && e.offsetHeight > 0;
        const cs = (e: Element) => getComputedStyle(e);
        const f: string[] = [];
        const h1 = [...document.querySelectorAll('h1')].filter(sichtbar)[0];
        if (h1 && (!cs(h1).fontFamily.startsWith('Sora') || cs(h1).fontWeight !== '700')) f.push('Titel ' + cs(h1).fontFamily.slice(0, 12) + ' ' + cs(h1).fontWeight);
        for (const b of [...main.querySelectorAll('button, a[class*="btn"], input[type=submit]')].filter(sichtbar) as HTMLElement[]) {
          const c = cs(b);
          // Ein gefüllter Knopf ist ein `.fw-btn`: Pille, 36 px
          if (b.classList.contains('fw-btn') && (c.minHeight !== '36px' || parseFloat(c.borderTopLeftRadius) < 100)) { f.push('Knopf ' + c.minHeight + '/' + c.borderTopLeftRadius + ' «' + (b.textContent || '').trim().slice(0, 24) + '»'); break; }
          if (!b.classList.contains('fw-btn') && c.backgroundColor === 'rgb(176, 68, 22)') { f.push('Markenknopf ohne fw-btn «' + (b.textContent || '').trim().slice(0, 24) + '»'); break; }
        }
        for (const e of [...main.querySelectorAll('*')] as HTMLElement[]) {
          if (e.offsetWidth < 150 || e.offsetHeight < 40 || /INPUT|SELECT|TEXTAREA|BUTTON/.test(e.tagName)) continue;
          const c = cs(e);
          if (c.backgroundColor !== 'rgb(255, 255, 255)' || parseFloat(c.borderTopLeftRadius) < 8) continue;
          if (e.tagName === 'A' && e.offsetHeight < 60) continue;
          // Das Kennzahlenband (.fw-kzn) ist derselbe Baustein wie in den Akten der Verwaltung: 14 px, kein Kartenradius
          if (e.classList.contains('fw-kzn')) { if (parseFloat(c.borderTopLeftRadius) !== 14) { f.push('Kennzahlenband ' + c.borderTopLeftRadius); break; } continue; }
          if (c.boxShadow !== 'none') { f.push('Karte mit Schatten: ' + e.className.toString().slice(0, 40)); break; }
          if (parseFloat(c.borderTopLeftRadius) !== 24 && e.offsetHeight > 90) { f.push('Kartenradius ' + c.borderTopLeftRadius + ': ' + e.className.toString().slice(0, 40)); break; }
        }
        for (const e of [...main.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=range]):not([type=hidden]), select')].filter(sichtbar)) {
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

test('Anmeldeseiten: Titelschrift, Feldhöhe und Knopf wie im Programm', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const u of ['/login/', '/portal/login/']) {
    await goto(page, u);
    const m = await page.evaluate(() => {
      const cs = (e: Element) => getComputedStyle(e);
      const h = document.querySelector('.head h2')!, i = document.querySelector('input[name="username"]')!, k = document.querySelector('.submit')!, c = document.querySelector('.card')!;
      // Markenfläche: ruhige helle Fläche wie die Seitenleiste, kein Farbverlauf mehr; ihr Titel in der Titelschrift
      const p = document.querySelector('.brandpane')!, t = document.querySelector('.pane-mid h1')!;
      return { schrift: cs(h).fontFamily.slice(0, 4), feld: Math.round(i.getBoundingClientRect().height), knopf: parseFloat(cs(k).borderTopLeftRadius), schatten: cs(c).boxShadow,
        flaeche: cs(p).backgroundImage + ' ' + cs(p).backgroundColor, markentitel: cs(t).fontFamily.slice(0, 4) };
    });
    expect(m, u).toEqual({ schrift: 'Sora', feld: 40, knopf: 999, schatten: 'none', flaeche: 'none rgb(255, 255, 255)', markentitel: 'Sora' });
  }
});
