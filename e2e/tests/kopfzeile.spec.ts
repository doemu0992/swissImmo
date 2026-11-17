import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// DIE KOPFZEILE v2 — GEMESSEN IM BROWSER (27.10.2026), SEIT 17.11.2026 NUR NOCH UNTER 1024 PX
//
// Ab 1024 px stehen die Bereiche in der Schiene am linken Rand (`schiene.spec.ts`); Kapsel und Menüband der Kopfzeile
// entfallen dort. Unter 1024 px bleiben sie: Zeile 1 mit Marke, Bestand, Bereichen, Suche und Werkzeugen, Zeile 2
// das Menüband des aktiven Bereichs, was nicht passt, läuft in «Mehr» über. Was hier steht, lässt sich nicht aus dem
// Quelltext lesen: wie viele Punkte bei einer Breite passen, ob der aktive Punkt wirklich sichtbar bleibt, ob «Mehr»
// den Fokus zurückgibt, ob das Band ohne Skript scrollt.
//
// Prüfband ist «Finanzen» (11 Punkte): Es läuft bei 1000 px über. «Heute» (7 Punkte) passt noch.

const FINANZEN = ['finanzen', 'mieterkonten', 'debitoren', 'kautionen', 'kreditoren', 'lieferantenkonten', 'bankkonten',
  'buchhaltung', 'kontenplan', 'anlagen', 'hypotheken'];
const HEUTE = ['', 'zulauf', 'termine', 'pendenzen', 'fristen', 'abwesenheiten', 'kommunikation'];
const TABLET = { width: 1000, height: 800 };

type Band = { sichtbar: string[]; versteckt: string[]; mehr: boolean; mehrN: string; aktiv: string | null; aktivX: number; letzterX: number };

/** Der Zustand des Bandes: welche Punkte stehen sichtbar im Band, welche sind versteckt. */
async function band(page: Page): Promise<Band> {
  return page.evaluate(() => {
    const b = document.querySelector('.fw-bereichsreiter')!;
    const name = (a: Element) => new URL((a as HTMLAnchorElement).href).pathname.split('/')[2] || '';
    const alle = Array.from(b.querySelectorAll(':scope > a'));
    const sichtbar = alle.filter((a) => (a as HTMLElement).getBoundingClientRect().width > 0);
    const versteckt = alle.filter((a) => (a as HTMLElement).getBoundingClientRect().width === 0);
    const mehr = document.getElementById('fwMehr')!;
    const aktiv = b.querySelector('a.hier');
    const xs = sichtbar.map((a) => (a as HTMLElement).getBoundingClientRect().left);
    return {
      sichtbar: sichtbar.map(name), versteckt: versteckt.map(name),
      mehr: mehr.getBoundingClientRect().width > 0, mehrN: (mehr.querySelector('.fw-mehr-n')!.textContent || '').trim(),
      aktiv: aktiv ? name(aktiv) : null,
      aktivX: aktiv ? (aktiv as HTMLElement).getBoundingClientRect().left : -1, letzterX: Math.max(...xs),
    };
  });
}
const mehrEintraege = (page: Page) => page.locator('#fwMehrPop a').evaluateAll((l) =>
  l.map((a) => new URL((a as HTMLAnchorElement).href).pathname.split('/')[2]));

test.describe('Menüband mit Überlauf «Mehr» (1000 px)', () => {
  test.use({ viewport: TABLET });

  test('Die vorderen Punkte stehen im Band, «Mehr» enthält den Rest, nichts geht verloren', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    const z = await band(page);

    expect(z.aktiv).toBe('debitoren');
    // Sichtbar sind die VORDEREN Punkte, lückenlos von «Übersicht» an; der Rest steht im Überlauf
    const k = z.sichtbar.length;
    expect(k, `Bei 1000 px passen ${k} von ${FINANZEN.length} Punkten`).toBeGreaterThanOrEqual(4);
    expect(k).toBeLessThan(FINANZEN.length);
    expect(z.sichtbar).toEqual(FINANZEN.slice(0, k));
    expect(z.versteckt).toEqual(FINANZEN.slice(k));
    // «Mehr» zeigt die Zahl der versteckten Punkte und führt genau diese auf
    expect(z.mehr, '«Mehr» fehlt, obwohl Punkte versteckt sind').toBe(true);
    expect(z.mehrN).toBe(String(FINANZEN.length - k));
    await page.locator('#fwMehr').click();
    await expect(page.locator('#fwMehrPop')).toBeVisible();
    expect(await mehrEintraege(page)).toEqual(FINANZEN.slice(k));
    // Die Einträge sind echte Links mit dem Bestandsfilter-Anhang der Seite, nicht Attrappen
    const ziele = await page.locator('#fwMehrPop a').evaluateAll((l) => l.map((a) => (a as HTMLAnchorElement).getAttribute('href')));
    for (const h of ziele) expect(h!.startsWith('/neu/')).toBe(true);
    // Das Fenster liegt im Bild und über dem Inhalt
    const f = (await page.locator('#fwMehrPop').boundingBox())!;
    expect(f.x).toBeGreaterThanOrEqual(0);
    expect(f.x + f.width).toBeLessThanOrEqual(TABLET.width);
    const oben = await page.evaluate(() => {
      const e = document.querySelector('#fwMehrPop a')!.getBoundingClientRect();
      const t = document.elementFromPoint(e.left + 20, e.top + e.height / 2);
      return !!t && !!t.closest('#fwMehrPop');
    });
    expect(oben, 'Das Überlauf-Fenster liegt unter dem Inhalt').toBe(true);
  });

  test('Passt alles («Heute», 7 Punkte), stehen alle im Band und «Mehr» bleibt unsichtbar', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/zulauf/');
    const z = await band(page);
    expect(z.sichtbar).toEqual(HEUTE);
    expect(z.versteckt).toEqual([]);
    expect(z.mehr, '«Mehr» steht da, obwohl nichts überläuft').toBe(false);
  });

  test('Der aktive Punkt wird nie versteckt, sondern rückt ans Ende der sichtbaren Reihe', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    const vorher = await band(page);
    const k = vorher.sichtbar.length;

    // Ein Punkt weit hinten: «Hypotheken» (der letzte) würde sonst im Überlauf stehen
    await goto(page, '/neu/hypotheken/');
    const z = await band(page);
    expect(z.aktiv).toBe('hypotheken');
    expect(z.sichtbar, 'Der aktive Punkt steht nicht im Band').toContain('hypotheken');
    expect(z.aktivX, 'Der aktive Punkt steht nicht am Ende der Reihe').toBeGreaterThanOrEqual(z.letzterX);
    // Er nimmt den Platz des letzten sichtbaren Punkts: einer weniger von vorn, nichts doppelt
    expect(new Set(z.sichtbar).size).toBe(z.sichtbar.length);
    expect(z.sichtbar.slice(0, -1)).toEqual(FINANZEN.slice(0, z.sichtbar.length - 1));
    expect(z.sichtbar.length).toBeLessThanOrEqual(k);
    // Im Überlauf steht er nicht mehr, aber alle anderen versteckten
    await page.locator('#fwMehr').click();
    const im = await mehrEintraege(page);
    expect(im).not.toContain('hypotheken');
    expect([...z.sichtbar, ...im].sort()).toEqual([...FINANZEN].sort());
    expect(z.mehrN).toBe(String(im.length));
    // Trenner: der aufgerückte Punkt trägt keinen Strich vor sich, die Reihe bleibt in einer Zeile
    const hoehe = (await page.locator('.fw-bereichsreiter').boundingBox())!.height;
    expect(hoehe).toBeLessThan(60);
  });

  test('Tastatur: Pfeile öffnen und führen, Esc schliesst und gibt den Fokus zurück, Tab verlässt', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    const mehr = page.locator('#fwMehr');
    const pop = page.locator('#fwMehrPop');
    await expect(mehr).toHaveAttribute('aria-expanded', 'false');
    await expect(mehr).toHaveAttribute('aria-controls', 'fwMehrPop');

    await mehr.focus();
    await page.keyboard.press('ArrowDown');
    await expect(pop).toBeVisible();
    await expect(mehr).toHaveAttribute('aria-expanded', 'true');
    const eintraege = pop.locator('a');
    await expect(eintraege.first()).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(eintraege.nth(1)).toBeFocused();
    await page.keyboard.press('End');
    await expect(eintraege.last()).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(eintraege.first(), 'Die Pfeile führen nicht im Kreis').toBeFocused();
    await page.keyboard.press('ArrowUp');
    await expect(eintraege.last()).toBeFocused();
    await page.keyboard.press('Home');
    await expect(eintraege.first()).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(pop).toBeHidden();
    await expect(mehr).toHaveAttribute('aria-expanded', 'false');
    await expect(mehr, 'Esc gibt den Fokus nicht an «Mehr» zurück').toBeFocused();

    // Enter öffnet (ein Knopf), ein Tab aus der Liste heraus schliesst sie
    await page.keyboard.press('Enter');
    await expect(pop).toBeVisible();
    await eintraege.last().focus();
    await page.keyboard.press('Tab');
    await expect(pop).toBeHidden();

    // Ein Klick daneben schliesst
    await mehr.click();
    await expect(pop).toBeVisible();
    await page.mouse.click(300, 600);
    await expect(pop).toBeHidden();
    await expect(mehr).toHaveAttribute('aria-expanded', 'false');
  });

  test('Ein Eintrag im Überlauf führt auf seine Seite, dort ist er der aktive Punkt', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/debitoren/');
    await page.locator('#fwMehr').click();
    // Welcher Punkt zuerst im Überlauf steht, hängt von der Breite des Bandes ab: der erste nehmen
    const erster = page.locator('#fwMehrPop a').first();
    const name = new URL((await erster.getAttribute('href'))!, 'http://x').pathname.split('/')[2];
    await erster.click();
    await page.waitForURL(`**/neu/${name}/**`);
    const z = await band(page);
    expect(z.aktiv).toBe(name);
    expect(z.sichtbar, 'Der gewählte Punkt steht auf seiner Seite nicht im Band').toContain(name);
  });
});

// ───────────────────────── Bestandsfilter ─────────────────────────
test.describe('Bestandsfilter `lg` in Zeile 1', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  async function waehle(page: Page, nr: number) {
    const werte = await page.locator('.fw-bestand select option').evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
    expect(werte[0], 'Die erste Wahl ist «Ganzer Bestand»').toBe('');
    expect(werte.length, 'Der E2E-Bestand hat keine Liegenschaft zur Wahl').toBeGreaterThan(1);
    await Promise.all([page.waitForURL(/[?&]lg=\d+/), page.locator('.fw-bestand select').selectOption(werte[nr])]);
    return werte[nr];
  }

  test('Die Wahl filtert weiter: Adresse trägt lg, der Chip ist aktiv und zeigt den Namen', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await expect(page.locator('.fw-bestand')).not.toHaveClass(/aktiv/);
    const id = await waehle(page, 1);
    expect(new URL(page.url()).searchParams.get('lg')).toBe(id);
    await expect(page.locator('.fw-bestand')).toHaveClass(/aktiv/);
    await expect(page.locator('.fw-bestand select')).toHaveValue(id);
    // Der Filter gilt überall: Bereichs- und Bandlinks tragen ihn weiter
    const ohne = await page.locator('#fwHauptnav a, .fw-bereichsreiter > a, #fwSchiene a[data-fach], #fwFach a').evaluateAll((l) =>
      l.filter((a) => !(a as HTMLAnchorElement).getAttribute('href')!.includes('lg=')).length);
    expect(ohne, 'Ein Link der Kopfzeile verliert den Bestandsfilter').toBe(0);
    // Der Name steht sichtbar im Chip (nicht nur das Symbol) und ist nicht die Überzeile
    const name = await page.locator('.fw-bestand select').evaluate((el) => (el as HTMLSelectElement).selectedOptions[0].textContent!.trim());
    expect(name.length).toBeGreaterThan(3);
    const b = (await page.locator('.fw-bestand').boundingBox())!;
    expect(b.width, 'Der Chip zeigt am PC nur das Symbol').toBeGreaterThan(120);
    // Zurück auf «Ganzer Bestand»
    await Promise.all([page.waitForURL((u) => u.searchParams.get('lg') === ''), page.locator('.fw-bestand select').selectOption('')]);
    await expect(page.locator('.fw-bestand')).not.toHaveClass(/aktiv/);
  });

  test('Ein Tipp irgendwo auf den Chip trifft die Auswahl (Symbol, Überzeile, Name)', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const trifft = await page.evaluate(() => {
      const c = document.querySelector('.fw-bestand')!.getBoundingClientRect();
      return [c.left + 20, c.left + c.width / 2, c.right - 10].map((x) => {
        const e = document.elementFromPoint(x, c.top + c.height / 2);
        return e && e.tagName;
      });
    });
    expect(trifft, 'Ein Teil des Chips trifft die Auswahl nicht').toEqual(['SELECT', 'SELECT', 'SELECT']);
  });

  test.describe('am Telefon', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

    test('Das Symbol trägt einen Punkt bei aktivem Filter, die Auswahl filtert', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/liegenschaften/');
      const punkt = () => page.locator('.fw-bestand').evaluate((el) => getComputedStyle(el, '::after').content);
      expect(await punkt(), 'Ohne Filter steht kein Punkt').toBe('none');
      await waehle(page, 1);
      expect(await punkt(), 'Bei aktivem Filter fehlt der Punkt am Symbol').not.toBe('none');
      const b = (await page.locator('.fw-bestand').boundingBox())!;
      expect(b.width).toBeLessThan(60);
    });
  });
});

// ───────────────────────── am Telefon: nichts wird unerreichbar ─────────────────────────
test.describe('Telefon: «Neuer Fall» und das Menü stehen im Profilmenü', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('Das Profilmenü öffnet die Schublade (Mandant, Zuletzt geöffnet) und «Neuer Fall»', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    // In Zeile 1 gibt es weder «+» noch den Menüknopf
    await expect(page.locator('.fw-werkzeug-kapsel a[href="/neu/faelle/neu/"]')).toBeHidden();
    await expect(page.locator('.fw-werkzeug-kapsel button[data-bei-klick="fwMenueOeffnen"]')).toHaveCount(0);

    await page.locator('.fw-avatar-knopf').tap();
    const profil = page.locator('#fwProfil');
    await expect(profil).toBeVisible();
    const menue = profil.locator('button[data-bei-klick="fwMenueOeffnen"]');
    await expect(menue).toBeVisible();
    // Der Eintrag liegt im Bild
    const r = (await profil.boundingBox())!;
    expect(r.x).toBeGreaterThanOrEqual(0);
    expect(r.x + r.width).toBeLessThanOrEqual(390);
    expect(r.y + r.height).toBeLessThanOrEqual(844);
    await menue.tap();
    await expect(page.locator('#fwSidebar')).toHaveClass(/offen/);
    await expect(profil, 'Das Profilmenü bleibt hinter der Schublade offen').toBeHidden();
    await expect(page.locator('#fwSidebar #fwZuletztTitel, #fwSidebar .fw-nav')).not.toHaveCount(0);
    await page.evaluate(() => (window as any).fwCloseMobileNav());

    // «Neuer Fall» öffnet das Fenster wie früher das «+» (auf Seiten mit Fenster, z. B. «Heute»; sonst führt
    // der Link auf die Seite selbst — wie das «+» am PC)
    await goto(page, '/neu/');
    await page.locator('.fw-avatar-knopf').tap();
    await profil.locator('a[href="/neu/faelle/neu/"]').tap();
    await expect(page.locator('#fwModal')).toBeVisible();
    await expect(profil).toBeHidden();
  });
});

// ───────────────────────── Tablet und PC: das Profilmenü trägt sie nicht ─────────────────────────
test.describe('PC: «Neuer Fall» steht in Zeile 1, nicht im Profilmenü', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('Zeile 1 trägt «+» und Einstellungen; das Profilmenü die Schnellzeile nicht', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await expect(page.locator('.fw-werkzeug-kapsel a[href="/neu/faelle/neu/"]')).toBeVisible();
    await expect(page.locator('.fw-werkzeug-kapsel a[href^="/neu/einstellungen/"]')).toBeVisible();
    await page.locator('.fw-avatar-knopf').click();
    await expect(page.locator('#fwProfil')).toBeVisible();
    await expect(page.locator('#fwProfil .fw-profil-schnell'), 'Die Schnellzeile steht am PC doppelt').toBeHidden();
    // Einstellungen bleiben im Profilmenü erreichbar (dort stehen sie immer)
    await expect(page.locator('#fwProfil a[href="/neu/einstellungen/"]')).toBeVisible();
  });
});

// ───────────────────────── ohne JavaScript ─────────────────────────
async function ohneSkriptAnmelden(page: Page) {
  // ohne Skript kein `login()` mit Hilfe von expect auf Seiten-Skripte: Formular direkt
  await page.goto('/login/', { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="username"]', 'e2e');
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([page.waitForURL((u) => !u.pathname.startsWith('/login/'), { waitUntil: 'domcontentloaded' }),
    page.click('button[type="submit"], input[type="submit"]')]);
}

test.describe('Ohne JavaScript (PC)', () => {
  test.use({ javaScriptEnabled: false, viewport: { width: 1280, height: 800 } });

  test('Die Schiene besteht aus Links auf die Bereichsköpfe; der Bestand sendet über «Übernehmen»', async ({ page }) => {
    await ohneSkriptAnmelden(page);
    await page.goto('/neu/liegenschaften/', { waitUntil: 'domcontentloaded' });

    // Sechs Bereiche und die Einstellungen, alle sichtbar und anklickbar; das Aufklappfeld bleibt zu
    const links = page.locator('#fwSchiene a[data-fach]');
    await expect(links).toHaveCount(7);
    await expect(page.locator('#fwFach')).toBeHidden();
    // Die hinteren Bereiche erreicht man trotzdem: der Link führt zum Bereichskopf
    await page.locator('#fwSchiene a[data-fach="finanzen"]').click();
    await page.waitForURL('**/neu/finanzen/**', { waitUntil: 'domcontentloaded' });

    // Bestand: die Auswahl sendet nicht von selbst; beim Fokus erscheint «Übernehmen»
    const ok = page.locator('.fw-bestand-ok');
    await expect(ok).toBeHidden();
    const werte = await page.locator('.fw-bestand select option').evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
    await page.locator('.fw-bestand select').focus();
    await page.locator('.fw-bestand select').selectOption(werte[1]);
    await expect(ok, '«Übernehmen» erscheint ohne Skript nicht').toBeVisible();
    await Promise.all([page.waitForURL(/[?&]lg=\d+/, { waitUntil: 'domcontentloaded' }), ok.click()]);
    await expect(page.locator('.fw-bestand')).toHaveClass(/aktiv/);
  });
});

test.describe('Ohne JavaScript (Tablet)', () => {
  test.use({ javaScriptEnabled: false, viewport: TABLET });

  test('Das Menüband scrollt in sich, alle Punkte sind Links', async ({ page }) => {
    await ohneSkriptAnmelden(page);
    await page.goto('/neu/debitoren/', { waitUntil: 'domcontentloaded' });

    const b = await page.locator('.fw-bereichsreiter').evaluate((el) => ({
      scrollt: el.scrollWidth > el.clientWidth, overflow: getComputedStyle(el).overflowX,
      links: el.querySelectorAll(':scope > a').length,
      mehr: (document.getElementById('fwMehr') as HTMLElement).getBoundingClientRect().width,
      verdeckt: Array.from(el.querySelectorAll(':scope > a')).filter((a) => (a as HTMLElement).hidden).length,
    }));
    expect(b.links).toBe(FINANZEN.length);
    expect(b.verdeckt, 'Ohne Skript ist nichts versteckt').toBe(0);
    expect(b.mehr, '«Mehr» ist ohne Skript sichtbar, aber ohne Inhalt').toBe(0);
    expect(b.overflow).toBe('auto');
    expect(b.scrollt, 'Das Band scrollt ohne Skript nicht — die hinteren Punkte wären unerreichbar').toBe(true);
    // Die hinteren Punkte erreicht man trotzdem: der Link bleibt anwählbar
    await page.locator('.fw-bereichsreiter a[href^="/neu/hypotheken/"]').click();
    await page.waitForURL('**/neu/hypotheken/**', { waitUntil: 'domcontentloaded' });
  });
});
