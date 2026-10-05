import { test, expect } from '@playwright/test';
import { goto, login } from './helpers';

// Phase 4: kaputte Links, Fehlerseiten und JS-Fehler finden, bevor es ein Mensch tut.
// Ausgehend von den Einstiegsseiten werden alle internen Links (/neu/…) einmal geöffnet.
// Ausgenommen: Aktionen mit Nebenwirkung, Downloads und Löschwege — ein GET auf diese
// Adressen soll nichts auslösen und gehört nicht in einen Crawl.

const EINSTIEG = [
  '/neu/', '/neu/liegenschaften/', '/neu/objekte/', '/neu/personen/', '/neu/vertraege/',
  '/neu/mandate/', '/neu/schaeden/', '/neu/finanzen/', '/neu/debitoren/', '/neu/kreditoren/',
  '/neu/laeufe/', '/neu/berichte/', '/neu/einstellungen/', '/neu/mahnwesen/', '/neu/betreibungen/',
  '/neu/nebenkosten/', '/neu/kautionen/', '/neu/sollstellung/',
];
const AUSGENOMMEN = /\/(loeschen|starten|abschliessen|zuruecksetzen|ueberspringen|stornieren|abschreiben|freigeben|verbuchen|versand|pdf|qr-pdf|export|download|logout|abmelden|mail)(\/|$)|\.(pdf|zip|csv|xml)(\?|$)|^\/neu\/mandant\/|setlang|\/foto\//;

test.describe('Navigation', () => {
  test.setTimeout(240_000);

  test('Kein interner Link führt auf eine Fehlerseite', async ({ page }) => {
    const jsFehler: string[] = [];
    page.on('pageerror', (e) => jsFehler.push(`${page.url()} — ${e.message}`));
    await login(page);

    const ziele = new Set<string>(EINSTIEG);
    for (const start of EINSTIEG) {
      await goto(page, start);
      const links = await page.$$eval('a[href^="/neu/"]', (as) => as.map((a) => (a as HTMLAnchorElement).getAttribute('href')!));
      links.map((l) => l.split('#')[0]).filter((l) => l && !AUSGENOMMEN.test(l)).forEach((l) => ziele.add(l));
    }

    const defekt: string[] = [];
    for (const ziel of ziele) {
      const antwort = await page.goto(ziel, { waitUntil: 'domcontentloaded' }).catch(() => null);
      if (!antwort) continue;                       // Download o. ä., kein Seitenaufruf
      const status = antwort.status();
      if (status >= 400) { defekt.push(`${status}  ${ziel}`); continue; }
      const text = await page.locator('body').innerText();
      if (/Server Error|Traceback|TemplateSyntaxError|NoReverseMatch/i.test(text)) defekt.push(`Fehlertext  ${ziel}`);
    }
    console.log(`Navigation: ${ziele.size} Adressen geprüft`);
    expect(defekt, 'Links auf Fehlerseiten').toEqual([]);
    expect(jsFehler, 'JavaScript-Fehler beim Öffnen').toEqual([]);
  });
});

test.describe('Ladeanzeigen', () => {
  // Das Cockpit-Modal lädt Seiten in einem Rahmen und zeigt bis dahin «Wird geladen …».
  // Bleibt diese Anzeige stehen, sieht der Benutzer einen endlosen Spinner — auch dann,
  // wenn die Seite dahinter längst da ist. Geprüft wird: Anzeige weg, Rahmen hat Inhalt.
  const MODALE = [
    { liste: '/neu/schaeden/', zeile: '.fw-zeile.klick' },
    { liste: '/neu/debitoren/', zeile: 'table a[onclick*="fwModalOpen"]' },
  ];

  for (const m of MODALE) {
    test(`Modal von ${m.liste} lädt zu Ende`, async ({ page }) => {
      await login(page);
      await goto(page, m.liste);
      const zeile = page.locator(m.zeile).first();
      test.skip((await zeile.count()) === 0, `Keine Zeile in ${m.liste}`);
      await zeile.click();
      await expect(page.locator('#fwModal')).toBeVisible();
      await expect(page.locator('#fwModalLaedt'), 'Ladeanzeige bleibt stehen').toBeHidden({ timeout: 15_000 });
      const rahmen = page.frameLocator('#fwModalFrame');
      await expect(rahmen.locator('body')).not.toBeEmpty();
      await expect(rahmen.locator('body')).not.toContainText(/Server Error|Seite nicht gefunden/i);
    });
  }
});
