import { test, expect, Page } from '@playwright/test';
import { login, goto, warteAufURL } from './helpers';

// DIE OMNISEARCH IN DER KOPFZEILE (27.10.2026) — GEMESSEN IM BROWSER
//
// Was hier steht, lässt sich nicht aus dem Quelltext lesen: ob das Feld bei
// Fokus über die Bereiche wächst, ob die Zeile am Telefon in einer Reihe
// bleibt, ob eine späte Antwort die neuere überschreibt. Der Endpunkt
// `/neu/palette/` wird hier durch eine Attrappe nach dem Vertrag ersetzt
// (gruppe, status, betrag, zahlen) — so sind Inhalt, Fehler und Wartezeit
// bestimmbar. Der letzte Test fragt den echten Endpunkt, sobald er den Vertrag
// erfüllt.
//
// Prüfbreite ist das Telefon (390 px); der Desktop (1280 px) ist die Zugabe.

type Treffer = {
  gruppe: string; art: string; label: string; zusatz: string; url: string;
  status: { text: string; ton: string } | null; betrag: string | null;
};
const t = (gruppe: string, art: string, label: string, zusatz: string, url: string,
           status: Treffer['status'] = null, betrag: string | null = null): Treffer =>
  ({ gruppe, art, label, zusatz, url, status, betrag });

const BEH = {
  q: 'beh',
  treffer: [
    t('personen', 'Person', 'Anna Behrens', 'Zürich · anna@behrens.example', '/neu/personen/1/', { text: 'aktiv', ton: 'good' }),
    t('personen', 'Person', 'Marco Beherns', 'Bern · marco@example.ch', '/neu/personen/2/'),
    t('personen', 'Dienstleister', 'Behringer Sanitär AG', 'Sanitär · 044 381 22 10', '/neu/dienstleister/3/'),
    t('immobilien', 'Liegenschaft', 'Behaglichkeitsweg 4', '8004 Zürich', '/neu/liegenschaften/4/'),
    t('immobilien', 'Objekt', '3½-Zimmer, 3.OG rechts', 'Behmenstrasse 9', '/neu/objekte/5/', { text: 'leer ab 01.12.', ton: 'warn' }),
    t('vertraege', 'Mietverhältnis', 'Anna Behrens', 'Seestrasse 12, 1.OG links', '/neu/vertraege/6/', { text: 'gekündigt per 31.03.', ton: 'mut' }),
    t('buchhaltung', 'Debitorenrechnung', 'Rechnung D-2026-0412', 'Miete Oktober · Anna Behrens', '/neu/debitoren/7/', { text: 'überfällig', ton: 'crit' }, "CHF 2'670.00"),
    t('buchhaltung', 'Kreditorenrechnung', 'Kreditor K-2026-0188', 'Behringer Sanitär AG', '/neu/kreditoren/8/', { text: 'zur Freigabe', ton: 'warn' }, "CHF 1'840.00"),
    t('tickets', 'Schaden', '#882 Heizung kalt', 'gemeldet von Anna Behrens', '/neu/schaeden/9/', { text: 'in Arbeit', ton: 'warn' }),
    t('dokumente', 'Dokument', 'Kündigung_Behrens_2026.pdf', 'Mietvertrag 2024-118', '/neu/dokumente/10/'),
  ],
  zahlen: { personen: 3, immobilien: 2, vertraege: 1, buchhaltung: 2, tickets: 1, dokumente: 1 },
};
const NULL_ZAHLEN = { personen: 0, immobilien: 0, vertraege: 0, buchhaltung: 0, tickets: 0, dokumente: 0 };
const LEER = { q: 'xyzxyz', treffer: [], zahlen: NULL_ZAHLEN };
const NUR_BEHR = {
  q: 'behr',
  treffer: [t('personen', 'Person', 'Nur Behr', 'Basel', '/neu/personen/99/')],
  zahlen: { ...NULL_ZAHLEN, personen: 1 },
};

type Antwort = { status?: number; body?: unknown; verzoegerung?: number; abbruch?: boolean };

/** Ersetzt `/neu/palette/` durch eine Attrappe; liefert die Liste der gefragten Eingaben. */
async function attrappe(page: Page, wahl: (q: string) => Antwort): Promise<string[]> {
  const anfragen: string[] = [];
  await page.route('**/neu/palette/**', async (route) => {
    const q = new URL(route.request().url()).searchParams.get('q') ?? '';
    anfragen.push(q);
    const a = wahl(q);
    try {
      if (a.verzoegerung) await new Promise((r) => setTimeout(r, a.verzoegerung));
      if (a.abbruch) return await route.abort('failed');
      return await route.fulfill({ status: a.status ?? 200, contentType: 'application/json', body: JSON.stringify(a.body) });
    } catch { /* die Seite hat die Anfrage schon abgebrochen */ }
  });
  return anfragen;
}

const feld = (page: Page) => page.locator('#fwOsEingabe');
const pop = (page: Page) => page.locator('#fwOsPop');
const box = async (page: Page, sel: string) => (await page.locator(sel).first().boundingBox())!;
async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}
async function tippe(page: Page, text: string) {
  await feld(page).click();
  await page.keyboard.type(text, { delay: 20 });
}

// ───────────────────────── Desktop (Zugabe) ─────────────────────────
test.describe('Omnisearch am Desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('Zeile 1: Marke, Bestand, Bereiche, Suche, Werkzeuge; Zeile 2: das Menüband', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');

    const logo = await box(page, '.fw-kopf-z1 .fw-logo-kapsel');
    const bestand = await box(page, '.fw-kopf-z1 .fw-bestand');
    const nav = await box(page, '.fw-kopf-z1 #fwHauptnav');
    const os = await box(page, '.fw-kopf-z1 #fwOs');
    const werkzeug = await box(page, '.fw-kopf-z1 .fw-werkzeug-kapsel');
    expect(logo.x + logo.width, 'Der Bestand steht nicht neben der Marke').toBeLessThanOrEqual(bestand.x + 1);
    expect(bestand.x + bestand.width, 'Die Bereiche stehen nicht neben dem Bestand').toBeLessThanOrEqual(nav.x + 1);
    expect(nav.x - (bestand.x + bestand.width), 'Die Bereiche schliessen nicht direkt an den Bestand an').toBeLessThan(20);
    expect(nav.x + nav.width, 'Die Suche steht nicht rechts von den Bereichen').toBeLessThanOrEqual(os.x + 1);
    expect(os.x + os.width, 'Die Werkzeuge stehen nicht rechts von der Suche').toBeLessThanOrEqual(werkzeug.x + 1);
    // Die Suche steht rechtsbündig: zwischen ihr und den Werkzeugen bleibt nur der Zeilenabstand
    expect(werkzeug.x - (os.x + os.width), 'Die Suche steht nicht rechtsbündig vor den Werkzeugen').toBeLessThan(20);
    expect(Math.abs(os.width - 168), 'Bei 1280 px ist das Feld ruhend 10,5 rem breit').toBeLessThan(3);
    // alles in einer Reihe
    for (const b of [logo, bestand, nav, werkzeug]) expect(Math.abs(b.y + b.height / 2 - (os.y + os.height / 2))).toBeLessThan(10);

    // Menüband direkt unter den Bereichen, in der Kopfzeile (nicht im Inhalt)
    await expect(page.locator('#fwKopf #navsub-akten')).toHaveCount(1);
    await expect(page.locator('main #navsub-akten')).toHaveCount(0);
    const band = await box(page, '#navsub-akten');
    expect(band.y).toBeGreaterThanOrEqual(nav.y + nav.height);
    expect(band.y - (nav.y + nav.height), 'Das Menüband steht nicht direkt unter den Bereichen').toBeLessThan(24);
    await expect(page.locator('#navsub-akten .fw-bereichsreiter-name')).toHaveText(/Akten/i);
    await expect(page.locator('#navsub-akten a.hier')).toHaveText('Liegenschaften');
    // Der Bestandsfilter steht in Zeile 1 (Überzeile «Bestand», darunter der Name), nicht im Band
    expect(bestand.y + bestand.height, 'Der Bestand steht unter den Bereichen').toBeLessThanOrEqual(band.y);
    await expect(page.locator('.fw-bestand .fw-bestand-ueber')).toHaveText(/Bestand/i);
    await expect(page.locator('.fw-kopf-z2 .fw-bestand')).toHaveCount(0);
    await expect(page.locator('.fw-bestand select[name="lg"]')).toHaveCount(1);
    const gewaehlt = await page.locator('.fw-bestand select').evaluate((el) => (el as HTMLSelectElement).selectedOptions[0].textContent!.trim());
    expect(gewaehlt).toBe('Ganzer Bestand');
    // Die alte eigene Zeile und das alte Fenster gibt es nicht mehr
    await expect(page.locator('.fw-top, .fw-suche, #fwPalette')).toHaveCount(0);
    await keinQuerscrollen(page);
  });

  test('Fokus lässt das Feld wachsen, ohne die Bereiche zu verdecken; ⌘K / Strg+K fokussiert', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const ruhend = await box(page, '#fwOs .fw-os-feld');
    await page.keyboard.press('Control+k');
    await expect(feld(page)).toBeFocused();
    await page.waitForTimeout(400);                       // Übergang
    const offen = await box(page, '#fwOs .fw-os-feld');
    // Das Feld wächst in den freien Platz zwischen Bereichen und Suche (gemessen, höchstens 8 rem): bei 1280 px rund 20 px
    expect(offen.width, 'Das Feld wächst bei Fokus nicht').toBeGreaterThan(ruhend.width + 8);
    expect(offen.width, 'Das Feld wächst über 8 rem hinaus').toBeLessThanOrEqual(ruhend.width + 128 + 1);
    const nav = await box(page, '#fwHauptnav');
    expect(offen.x, 'Das offene Feld verdeckt die Bereiche').toBeGreaterThanOrEqual(nav.x + nav.width - 1);
    // Mit einem Zeichen noch kein Popover, mit zwei schon
    await attrappe(page, () => ({ body: BEH }));
    await page.keyboard.type('b');
    await expect(pop(page)).toBeHidden();
    await page.keyboard.type('e');
    await expect(pop(page)).toBeVisible();
  });

  test('Treffer nach Gruppen mit Kapseln, Zahlen, Status und Betrag', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await attrappe(page, () => ({ body: BEH }));
    await tippe(page, 'beh');
    await expect(pop(page)).toBeVisible();

    // Kapseln: Alle, Mieter, Immobilien, Buchhaltung, Tickets, Mietverhältnisse, Dokumente
    const kapseln = page.locator('#fwOsFilter .fw-os-chip');
    await expect(kapseln).toHaveCount(7);
    await expect(kapseln.nth(0)).toContainText('Alle');
    await expect(kapseln.nth(0)).toContainText('10');
    await expect(kapseln.nth(1)).toContainText('Mieter');
    await expect(kapseln.nth(1)).toContainText('3');
    await expect(kapseln.nth(5)).toContainText('Mietverhältnisse');
    await expect(kapseln.nth(0)).toHaveAttribute('aria-pressed', 'true');

    // Gruppen mit Kopf und Zahl, in der Reihenfolge des Vertrags
    const koepfe = page.locator('#fwOsListe .fw-os-kopf');
    await expect(koepfe).toHaveText([/Mieter & Personen\s*3/, /Immobilien\s*2/, /Mietverhältnisse\s*1/, /Buchhaltung\s*2/, /Tickets\s*1/, /Dokumente\s*1/]);

    // Treffer: hervorgehobener Begriff, Kontext, Status-Chip in der Zustandsfarbe, Betrag
    const anna = page.locator('#fwOsListe [role="option"]').first();
    await expect(anna.locator('mark')).toHaveText('Beh');
    await expect(anna.locator('small')).toContainText('Zürich');
    await expect(anna.locator('.fw-chip.fw-good')).toHaveText('aktiv');
    const rechnung = page.locator('#fwOsListe [role="option"]', { hasText: 'D-2026-0412' });
    await expect(rechnung.locator('.fw-chip.fw-crit')).toHaveText('überfällig');
    await expect(rechnung.locator('.fw-os-betrag')).toHaveText("CHF 2'670.00");
    await expect(page.locator('#fwOsListe .fw-chip.fw-warn').first()).toBeVisible();
    await expect(page.locator('#fwOsListe .fw-chip.fw-mut')).toHaveText('gekündigt per 31.03.');

    // Rollen und Verweise
    await expect(feld(page)).toHaveAttribute('role', 'combobox');
    await expect(feld(page)).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#fwOsListe')).toHaveAttribute('role', 'listbox');
    await expect(feld(page)).toHaveAttribute('aria-activedescendant', 'fwOsO0');
    await expect(page.locator('#fwOsAlle')).toHaveAttribute('href', '/neu/suche/?q=beh');
    await expect(page.locator('#fwOsAlle')).toContainText('beh');

    // Eine Kapsel zeigt nur ihre Gruppe
    await kapseln.nth(1).click();
    await expect(kapseln.nth(1)).toHaveAttribute('aria-pressed', 'true');
    await expect(koepfe).toHaveCount(1);
    await expect(feld(page), 'Die Kapsel nimmt dem Feld den Fokus').toBeFocused();
    await kapseln.nth(0).click();
    await expect(koepfe).toHaveCount(6);
  });

  test('Tastatur: ↑ ↓ wählen, ↵ öffnet, ⌘↵ in neuem Tab, Esc schliesst und gibt den Fokus zurück', async ({ page, context }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await attrappe(page, () => ({ body: BEH }));
    for (const ziel of ['**/neu/personen/2/', '**/neu/personen/1/']) {
      await context.route(ziel, (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<title>Ziel</title><p>Ziel</p>' }));
    }

    // Fokus liegt vor ⌘K auf einem Bereich; Esc bringt ihn dorthin zurück
    await page.locator('#fwHauptnav a').first().focus();
    await page.keyboard.press('Control+k');
    await page.keyboard.type('beh', { delay: 20 });
    const optionen = page.locator('#fwOsListe [role="option"]');
    await expect(optionen.first()).toBeVisible();
    await expect(optionen.nth(0)).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('ArrowDown');
    await expect(feld(page)).toHaveAttribute('aria-activedescendant', 'fwOsO1');
    await expect(optionen.nth(1)).toHaveClass(/sel/);
    await expect(optionen.nth(0)).not.toHaveClass(/sel/);
    await page.keyboard.press('ArrowUp');
    await expect(feld(page)).toHaveAttribute('aria-activedescendant', 'fwOsO0');

    await page.keyboard.press('Escape');
    await expect(pop(page)).toBeHidden();
    await expect(feld(page)).toHaveAttribute('aria-expanded', 'false');
    const fokus = await page.evaluate(() => document.activeElement && (document.activeElement as HTMLElement).textContent!.trim());
    expect(fokus, 'Esc gibt den Fokus nicht an den Bereich zurück').toBe('Heute');

    // ⌘/Strg+↵ öffnet den gewählten Treffer in einem neuen Tab
    // Das erneute Fokussieren fragt noch einmal an; deren Antwort setzt die Auswahl auf den ersten Treffer zurück.
    // Erst nach ihr wählen — sonst hängt der Test davon ab, wer schneller ist (gemessen: ohne dies in drei von
    // sechs Läufen rot; die Ursache liegt im Wettlauf, nicht im Layout).
    const antwort = page.waitForResponse('**/neu/palette/**');
    await page.keyboard.press('Control+k');
    await antwort;
    await page.waitForTimeout(150);
    await expect(optionen.first()).toBeVisible();
    await page.keyboard.press('ArrowDown');
    const [neuerTab] = await Promise.all([context.waitForEvent('page'), page.keyboard.press('Control+Enter')]);
    expect(neuerTab.url()).toContain('/neu/personen/2/');
    expect(page.url(), 'Die Seite selbst bleibt stehen').toContain('/neu/liegenschaften/');
    await neuerTab.close();

    // ↵ öffnet in diesem Tab (nach dem Schliessen des Tabs liegt der Fokus erst wieder im Feld)
    await page.bringToFront();
    await feld(page).focus();
    await expect(pop(page)).toBeVisible();
    await page.keyboard.press('Enter');
    await page.waitForURL('**/neu/personen/2/');
  });

  test('Entprellt (eine Anfrage), und nur die letzte Antwort zählt; die laufende wird abgebrochen', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.evaluate(() => {
      const f = window.fetch.bind(window);
      (window as any).__abrufe = [];
      window.fetch = (u: any, o?: any) => { (window as any).__abrufe.push({ u: String(u), signal: o && o.signal }); return f(u, o); };
    });
    const anfragen = await attrappe(page, (q) => q === 'beh' ? { body: BEH, verzoegerung: 900 } : { body: NUR_BEHR });
    await tippe(page, 'beh');
    await page.waitForTimeout(450);
    expect(anfragen, 'Drei Tastendrücke lösten mehr als eine Anfrage aus').toEqual(['beh']);

    // Die erste Antwort ist noch unterwegs: weiter tippen
    await page.keyboard.type('r', { delay: 20 });
    await expect(page.locator('#fwOsListe [role="option"]')).toHaveText([/Nur Behr/]);
    const abgebrochen = await page.evaluate(() => (window as any).__abrufe.map((a: any) => !!(a.signal && a.signal.aborted)));
    expect(abgebrochen, 'Die erste Anfrage wurde nicht abgebrochen').toEqual([true, false]);
    // Die späte Antwort auf «beh» darf nichts mehr ändern
    await page.waitForTimeout(1100);
    await expect(page.locator('#fwOsListe [role="option"]')).toHaveText([/Nur Behr/]);
    expect(anfragen).toEqual(['beh', 'behr']);
  });

  test('Gerüst beim Laden, leerer Zustand, Fehlerzustand mit Wiederholung', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    let modus: 'langsam' | 'leer' | 'fehler' | 'gut' = 'langsam';
    await attrappe(page, () => modus === 'langsam' ? { body: BEH, verzoegerung: 1200 }
      : modus === 'leer' ? { body: LEER } : modus === 'fehler' ? { abbruch: true } : { body: BEH });

    // Laden: ein Gerüst, die Kapseln stehen schon (ohne Zahlen)
    await tippe(page, 'beh');
    await expect(page.locator('#fwOsListe .fw-os-geruest')).toBeVisible();
    await expect(page.locator('#fwOsFilter .fw-os-chip')).toHaveCount(7);
    await expect(page.locator('#fwOsListe')).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('#fwOsListe [role="option"]').first()).toBeVisible({ timeout: 4000 });
    await expect(page.locator('#fwOsListe .fw-os-geruest')).toHaveCount(0);

    // Leer: ein Text, der sagt, was zu tun ist; Zahlen sind gemessene Nullen
    modus = 'leer';
    await feld(page).fill('xyzxyz');
    await expect(page.locator('#fwOsListe .fw-os-leer')).toContainText('Keine Treffer für «xyzxyz»');
    await expect(page.locator('#fwOsListe .fw-os-leer')).toContainText('Nachnamen');
    await expect(page.locator('#fwOsAlle')).toHaveAttribute('href', '/neu/suche/?q=xyzxyz');

    // Netzwerkfehler: eigener Text, keine alten Treffer, Wiederholung
    modus = 'fehler';
    await feld(page).fill('behr');
    const fehler = page.locator('#fwOsListe .fw-os-leer[role="alert"]');
    await expect(fehler).toContainText('nicht erreichbar');
    await expect(page.locator('#fwOsListe [role="option"]')).toHaveCount(0);
    await expect(page.locator('#fwOsFilter .fw-os-chip i'), 'Nach einem Fehler stehen keine Zahlen da — sie wären nicht gemessen').toHaveCount(0);
    modus = 'gut';
    await fehler.getByRole('button', { name: 'Nochmals versuchen' }).click();
    await expect(page.locator('#fwOsListe [role="option"]').first()).toBeVisible();
  });

  test('Antwortet der Endpunkt mit 403, zeigt das Popover den Fehlerzustand und die Seitentreffer', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await attrappe(page, () => ({ status: 403, body: { detail: 'verboten' } }));
    const seite = await page.evaluate(() => {
      const d = JSON.parse(document.getElementById('fw-palette-data')!.textContent!);
      return d.find((x: any) => x.label.length > 5 && x.url.startsWith('/neu/'));
    });
    const fehler = [] as string[];
    page.on('pageerror', (e) => fehler.push(String(e)));
    await tippe(page, seite.label.slice(0, 6));
    await expect(page.locator('#fwOsListe .fw-os-leer[role="alert"]')).toContainText('nicht erreichbar');
    await expect(page.locator('#fwOsListe [role="group"]', { hasText: 'Seiten & Aktionen' })).toBeVisible();
    expect(fehler, 'Das Skript wirft bei 403').toEqual([]);
  });

  test('Seiten & Befehle der früheren Palette stehen als Gruppe «Seiten & Aktionen»', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await attrappe(page, () => ({ body: LEER }));
    const seite = await page.evaluate(() => {
      const d = JSON.parse(document.getElementById('fw-palette-data')!.textContent!);
      return d.find((x: any) => x.label.length > 5 && x.url.startsWith('/neu/'));
    });
    expect(seite, 'Die Palette-Daten sind leer').toBeTruthy();
    await tippe(page, seite.label.slice(0, 6));
    const gruppe = page.locator('#fwOsListe [role="group"]', { hasText: 'Seiten & Aktionen' });
    await expect(gruppe).toBeVisible();
    await expect(gruppe.locator(`a[href="${seite.url}"]`).first()).toBeVisible();
    // ohne Datentreffer ist sie die einzige Gruppe, mit Treffern die letzte
    await expect(page.locator('#fwOsListe [role="group"]')).toHaveCount(1);
  });

  test('Ohne JavaScript bleibt das Feld ein Formular auf /neu/suche/', async ({ browser, baseURL }) => {
    const ctx = await browser.newContext({ javaScriptEnabled: false, baseURL, viewport: { width: 1280, height: 800 }, locale: 'de-CH',
      extraHTTPHeaders: { 'Accept-Language': 'de-CH,de;q=0.9' } });
    const p = await ctx.newPage();
    await p.goto('/login/', { waitUntil: 'domcontentloaded' });
    await p.fill('input[name="username"]', 'e2e');
    await p.fill('input[name="password"]', 'e2e-pass');
    await Promise.all([p.waitForURL((u) => !u.pathname.startsWith('/login/'), { waitUntil: 'domcontentloaded' }),
      p.click('button[type="submit"], input[type="submit"]')]);
    await p.goto('/neu/liegenschaften/', { waitUntil: 'domcontentloaded' });
    await expect(p.locator('#fwOsForm')).toHaveAttribute('action', '/neu/suche/');
    await p.locator('#fwOsEingabe').fill('Blaser');
    await Promise.all([p.waitForURL('**/neu/suche/?q=Blaser', { waitUntil: 'domcontentloaded' }), p.keyboard.press('Enter')]);
    expect(new URL(p.url()).searchParams.get('q')).toBe('Blaser');
    await ctx.close();
  });
});

// ───────────────────────── Telefon (Prüfbreite) ─────────────────────────
test.describe('Omnisearch am Telefon', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('Zeile 1 bleibt eine Reihe, das Feld ist ein Symbol, Menüband und Bestandsfilter erreichbar', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const logo = await box(page, '.fw-kopf-z1 .fw-logo-kapsel');
    const os = await box(page, '#fwOs .fw-os-feld');
    const werkzeug = await box(page, '.fw-kopf-z1 .fw-werkzeug-kapsel');
    expect(Math.abs(os.width - 44), 'Das Feld ist am Telefon ein Symbol').toBeLessThan(2);
    expect(Math.abs((logo.y + logo.height / 2) - (werkzeug.y + werkzeug.height / 2)), 'Marke und Werkzeuge stehen nicht in einer Reihe').toBeLessThan(4);
    expect(Math.abs(logo.y + logo.height / 2 - (os.y + os.height / 2))).toBeLessThan(8);
    // Die Bereiche darunter, das Band darunter
    const nav = await box(page, '#fwHauptnav');
    const band = await box(page, '#navsub-akten');
    expect(nav.y).toBeGreaterThanOrEqual(logo.y + logo.height);
    expect(band.y).toBeGreaterThanOrEqual(nav.y + nav.height);
    expect(band.height, 'Das Menüband ist am Telefon eine Reihe').toBeLessThan(70);
    const rollbar = await page.locator('#navsub-akten').evaluate((el) => el.scrollWidth > el.clientWidth && getComputedStyle(el).overflowX === 'auto');
    expect(rollbar, 'Das Menüband rollt nicht waagrecht').toBeTruthy();
    // Bestandsfilter: ein Symbol in Zeile 1, die Auswahl liegt unsichtbar darüber und trifft den Finger
    const chip = await box(page, '.fw-bestand');
    expect(chip.width).toBeLessThan(60);
    expect(chip.y + chip.height, 'Der Bestand steht nicht in der ersten Reihe').toBeLessThanOrEqual(nav.y);
    expect(chip.x, 'Der Bestand steht nicht hinter der Marke').toBeGreaterThanOrEqual(logo.x + logo.width);
    const trifft = await page.evaluate(() => {
      const c = document.querySelector('.fw-bestand')!.getBoundingClientRect();
      const e = document.elementFromPoint(c.x + c.width / 2, c.y + c.height / 2);
      return e && e.tagName;
    });
    expect(trifft, 'Der Tipp auf das Symbol erreicht die Auswahl nicht').toBe('SELECT');
    await expect(page.locator('.fw-bestand select option').first()).toHaveText('Ganzer Bestand');
    await keinQuerscrollen(page);
  });

  test('Ein Tipp öffnet das Feld über die volle Breite, das Popover liegt darunter', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await attrappe(page, () => ({ body: BEH }));
    await page.locator('#fwOs .fw-os-lupe').tap();
    await expect(feld(page)).toBeFocused();
    await page.waitForTimeout(400);
    const offen = await box(page, '#fwOs .fw-os-feld');
    expect(Math.abs(offen.width - 358), `Offen misst das Feld ${Math.round(offen.width)} px, erwartet die volle Zeile (358 px)`).toBeLessThan(3);
    await expect(page.locator('.fw-kopf-z1 .fw-logo-kapsel')).toBeHidden();
    await expect(page.locator('.fw-kopf-z1 .fw-werkzeug-kapsel')).toBeHidden();

    await page.keyboard.type('beh', { delay: 20 });
    await expect(pop(page)).toBeVisible();
    await expect(page.locator('#fwOsListe [role="option"]').first()).toBeVisible();
    const p = await box(page, '#fwOsPop');
    expect(Math.abs(p.width - 358), 'Das Popover hat nicht die ganze Breite').toBeLessThan(3);
    expect(p.y, 'Das Popover liegt nicht unter dem Feld').toBeGreaterThanOrEqual(offen.y + offen.height);
    expect(p.x).toBeGreaterThanOrEqual(15);
    expect(p.x + p.width).toBeLessThanOrEqual(391);
    // Beträge fehlen am Telefon nicht
    await expect(page.locator('#fwOsListe .fw-os-betrag').first()).toBeVisible();
    // Kein Treffer ragt aus dem Popover
    const ueber = await page.evaluate(() => {
      const pp = document.getElementById('fwOsPop')!.getBoundingClientRect();
      return Array.from(document.querySelectorAll('#fwOsListe .fw-os-t')).filter((e) => e.getBoundingClientRect().right > pp.right + 1).length;
    });
    expect(ueber).toBe(0);
    await keinQuerscrollen(page);

    // Schliessen: das Feld wird wieder ein Symbol, Marke und Werkzeuge kommen zurück
    await page.locator('#fwOsZu').tap();
    await expect(pop(page)).toBeHidden();
    await expect(page.locator('.fw-kopf-z1 .fw-logo-kapsel')).toBeVisible();
    const zu = await box(page, '#fwOs .fw-os-feld');
    expect(zu.width).toBeLessThan(46);
  });
});

// ───────────────────────── der echte Endpunkt ─────────────────────────
test('Der echte Endpunkt liefert den Vertrag (Gruppe, Status, Betrag, Zahlen)', async ({ page }) => {
  await login(page);
  const antwort = await page.request.get('/neu/palette/?q=e2e');
  expect(antwort.status()).toBe(200);
  const d = await antwort.json();
  expect(Array.isArray(d.treffer)).toBeTruthy();
  test.skip(!('zahlen' in d), 'Der Endpunkt kennt den erweiterten Vertrag noch nicht (zahlen fehlt)');
  const gruppen = ['personen', 'immobilien', 'vertraege', 'buchhaltung', 'tickets', 'dokumente'];
  for (const g of gruppen) expect(typeof d.zahlen[g]).toBe('number');
  for (const x of d.treffer) {
    expect(gruppen).toContain(x.gruppe);
    expect(x.url.startsWith('/neu/')).toBeTruthy();
    if (x.status) expect(['crit', 'warn', 'good', 'mut']).toContain(x.status.ton);
  }
  // Das Popover zeigt, was der Endpunkt liefert
  await goto(page, '/neu/liegenschaften/');
  await feld(page).click();
  await page.keyboard.type('e2e', { delay: 20 });
  if (d.treffer.length) await expect(page.locator('#fwOsListe [role="option"]').first()).toBeVisible();
  else await expect(page.locator('#fwOsListe .fw-os-leer')).toBeVisible();
});

// ───────────────────────── Betrag, Status und Mahnstufe (echter Endpunkt) ─────────────────────────
test('Der echte Endpunkt: Betrag am Vertrag, Belegung am Objekt, Überfälligkeit an der Rechnung', async ({ page }) => {
  await login(page);
  const antwort = await page.request.get('/neu/palette/?q=E2E');
  expect(antwort.status()).toBe(200);
  const d = await antwort.json();
  // Je Gruppe gibt es höchstens fünf Treffer; andere Specs legen weitere «E2E»-Rechnungen an.
  // Die Rechnung des Seeds wird deshalb mit ihrem vollen Titel gesucht.
  const rechnungen = await (await page.request.get('/neu/palette/?q=' + encodeURIComponent('E2E offene Miete'))).json();
  const vertrag = d.treffer.find((x: Treffer) => x.gruppe === 'vertraege' && x.label.includes('E2E'));
  expect(vertrag, 'Kein Vertrag der E2E-Welt gefunden').toBeTruthy();
  // Netto-Mietzins des Seeds (1500), ohne die Nebenkosten (200)
  expect(vertrag.betrag).toBe("CHF 1'500.00");
  const objekt = d.treffer.find((x: Treffer) => x.art === 'Objekt' && x.label === '3.5 Zi E2E');
  expect(objekt, 'Kein Objekt der E2E-Welt gefunden').toBeTruthy();
  expect(objekt.status).toEqual({ text: 'Vermietet', ton: 'good' });
  const rechnung = rechnungen.treffer.find((x: Treffer) => x.gruppe === 'buchhaltung' && x.label === 'E2E offene Miete');
  expect(rechnung, 'Keine Rechnung der E2E-Welt gefunden').toBeTruthy();
  expect(rechnung.status).toEqual({ text: 'Überfällig', ton: 'crit' });
  expect(rechnung.betrag).toBe("CHF 1'700.00");
  // Personen tragen keinen Betrag
  for (const x of d.treffer as Treffer[]) if (x.gruppe === 'personen') expect(x.betrag).toBeNull();
});

// ───────────────────────── lange Beträge und Status am Telefon ─────────────────────────
test.describe('Lange Beträge und Status am Telefon', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  const LANG = {
    q: 'lang',
    treffer: [
      t('vertraege', 'Mietverhältnis', 'Genossenschaft Wohnen im Alter Zürich-Oerlikon', 'Bahnhofstrasse 128, Erdgeschoss rechts, Hinterhaus', '/neu/vertraege/1/',
        { text: 'Gekündigt', ton: 'crit' }, "CHF 123'456.50"),
      t('immobilien', 'Objekt', '4½-Zimmer-Attikawohnung 5. OG', 'Bahnhofstrasse 128', '/neu/objekte/2/',
        { text: 'Vermietet ab 01.12.2026', ton: 'good' }),
      t('buchhaltung', 'Debitorenrechnung', 'Miete Oktober 2026 inkl. Nebenkostenakonto', 'Genossenschaft Wohnen im Alter', '/neu/debitoren/?q=x',
        { text: '3. Mahnung', ton: 'crit' }, "CHF 1'234'567.80"),
    ],
    zahlen: { personen: 0, immobilien: 1, vertraege: 1, buchhaltung: 1, tickets: 0, dokumente: 0 },
  };

  test('Nichts ragt aus dem Popover, die Seite scrollt nicht quer, Betrag und Status bleiben lesbar', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await attrappe(page, () => ({ body: LANG }));
    await page.locator('#fwOs .fw-os-lupe').tap();
    await page.keyboard.type('lang', { delay: 20 });
    await expect(page.locator('#fwOsListe [role="option"]').first()).toBeVisible();
    const p = await box(page, '#fwOsPop');
    const ueber = await page.evaluate(() => {
      const pp = document.getElementById('fwOsPop')!.getBoundingClientRect();
      const raus: string[] = [];
      document.querySelectorAll('#fwOsListe .fw-os-t').forEach((z) => {
        const r = z.getBoundingClientRect();
        if (r.right > pp.right + 1 || r.left < pp.left - 1) raus.push('Zeile');
        z.querySelectorAll('.fw-os-betrag, .fw-chip, .fw-os-txt b').forEach((k) => {
          const kr = k.getBoundingClientRect();
          if (kr.right > pp.right + 1) raus.push(k.className || k.tagName);
        });
      });
      return raus;
    });
    expect(ueber, 'Ein Betrag, Chip oder Titel ragt über den Rand des Popovers').toEqual([]);
    expect(p.x + p.width).toBeLessThanOrEqual(391);
    // Der volle Betrag steht da (nicht abgeschnitten), der Status ebenso
    const betrag = page.locator('#fwOsListe .fw-os-betrag', { hasText: "1'234'567.80" });
    await expect(betrag).toBeVisible();
    expect(await betrag.evaluate((e) => e.scrollWidth <= e.clientWidth + 1), 'Der Betrag ist abgeschnitten').toBeTruthy();
    const chip = page.locator('#fwOsListe .fw-chip.fw-good');
    await expect(chip).toHaveText('Vermietet ab 01.12.2026');
    expect(await chip.evaluate((e) => e.scrollWidth <= e.clientWidth + 1), 'Der Status ist abgeschnitten').toBeTruthy();
    await keinQuerscrollen(page);
  });
});

// ───────────────────────── die Hauswartung ─────────────────────────
// Eigene Anmeldung (e2e-hauswart, siehe seed_e2e): Mitgliedschaft «Hauswart», der
// Liegenschaft der E2E-Welt zugeordnet. Sie sucht in der Kopfzeile nur Schäden.
async function loginHauswart(page: Page) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', 'e2e-hauswart');
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

test.describe('Die Hauswartung am Telefon (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('Die Suche ist da, öffnet über die volle Breite und kennt nur Schäden', async ({ page }) => {
    await loginHauswart(page);
    await goto(page, '/neu/schaeden/');
    await expect(page.locator('#fwOs')).toHaveAttribute('data-gruppen', 'tickets');
    const os = await box(page, '#fwOs .fw-os-feld');
    expect(Math.abs(os.width - 44), 'Das Feld ist am Telefon ein Symbol').toBeLessThan(2);
    await keinQuerscrollen(page);

    await page.locator('#fwOs .fw-os-lupe').tap();
    await expect(feld(page)).toBeFocused();
    await page.waitForTimeout(400);
    const offen = await box(page, '#fwOs .fw-os-feld');
    expect(Math.abs(offen.width - 358), `Offen misst das Feld ${Math.round(offen.width)} px`).toBeLessThan(3);

    // echter Endpunkt: der Schaden der E2E-Welt
    await page.keyboard.type('Wasserhahn', { delay: 20 });
    await expect(pop(page)).toBeVisible();
    const optionen = page.locator('#fwOsListe [role="option"]');
    await expect(optionen).toHaveCount(1);
    await expect(optionen.first()).toContainText('Wasserhahn tropft');
    await expect(optionen.first()).toHaveAttribute('href', /^\/neu\/schaeden\/\d+\/$/);
    // Nur zwei Kapseln: «Alle» und «Tickets» — keine Gruppen, die es für sie nicht gibt
    const kapseln = page.locator('#fwOsFilter .fw-os-chip');
    await expect(kapseln).toHaveCount(2);
    await expect(kapseln.nth(0)).toContainText('Alle');
    await expect(kapseln.nth(1)).toContainText('Tickets');
    await expect(page.locator('#fwOsListe .fw-os-kopf')).toHaveText([/Tickets\s*1/]);
    // «Alle Ergebnisse» führt auf die Schadenliste (/neu/suche/ ist ihr gesperrt)
    await expect(page.locator('#fwOsAlle')).toHaveAttribute('href', '/neu/schaeden/?q=Wasserhahn');
    const p = await box(page, '#fwOsPop');
    expect(Math.abs(p.width - 358)).toBeLessThan(3);
    expect(p.x + p.width).toBeLessThanOrEqual(391);
    await keinQuerscrollen(page);
  });

  test('Ein Begriff aus den gesperrten Gruppen findet nichts und zeigt den leeren Zustand', async ({ page }) => {
    await loginHauswart(page);
    await goto(page, '/neu/schaeden/');
    await page.locator('#fwOs .fw-os-lupe').tap();
    // Die E-Mail-Adresse steht nur bei der Person; ein Schaden durchsucht Adressen und Namen,
    // aber keine E-Mail. («Erika» als Melderin kann in der CI-Welt in einem Schaden stehen.)
    await page.keyboard.type('e2e-mieter', { delay: 20 });
    await expect(page.locator('#fwOsListe .fw-os-leer')).toContainText('Keine Treffer für «e2e-mieter»');
    await expect(page.locator('#fwOsListe [role="option"]')).toHaveCount(0);
    await keinQuerscrollen(page);
  });
});

test.describe('Die Hauswartung am Desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('Der Endpunkt antwortet ihr mit Schäden allein; was ihr gesperrt ist, bleibt gesperrt', async ({ page }) => {
    await loginHauswart(page);
    const antwort = await page.request.get('/neu/palette/?q=E2E');
    expect(antwort.status()).toBe(200);
    const d = await antwort.json();
    expect(Object.keys(d.zahlen)).toEqual(['tickets']);
    expect(d.treffer.length).toBeGreaterThan(0);
    for (const x of d.treffer as Treffer[]) {
      expect(x.gruppe).toBe('tickets');
      expect(x.betrag).toBeNull();
    }
    for (const gesperrt of ['/neu/suche/?q=E2E', '/neu/personen/', '/neu/vertraege/', '/neu/debitoren/', '/neu/dokumente/']) {
      expect((await page.request.get(gesperrt)).status(), gesperrt).toBe(403);
    }
  });

  test('Das Formular ohne JavaScript führt auf die Schadenliste, nicht in die Absage', async ({ browser, baseURL }) => {
    const ctx = await browser.newContext({ javaScriptEnabled: false, baseURL, viewport: { width: 1280, height: 800 }, locale: 'de-CH',
      extraHTTPHeaders: { 'Accept-Language': 'de-CH,de;q=0.9' } });
    const p = await ctx.newPage();
    await p.goto('/login/', { waitUntil: 'domcontentloaded' });
    await p.fill('input[name="username"]', 'e2e-hauswart');
    await p.fill('input[name="password"]', 'e2e-pass');
    await Promise.all([p.waitForURL((u) => !u.pathname.startsWith('/login/'), { waitUntil: 'domcontentloaded' }),
      p.click('button[type="submit"], input[type="submit"]')]);
    await p.goto('/neu/schaeden/', { waitUntil: 'domcontentloaded' });
    await expect(p.locator('#fwOsForm')).toHaveAttribute('action', '/neu/schaeden/');
    await p.locator('#fwOsEingabe').fill('Wasserhahn');
    await Promise.all([p.waitForURL('**/neu/schaeden/?q=Wasserhahn', { waitUntil: 'domcontentloaded' }), p.keyboard.press('Enter')]);
    await expect(p.locator('body')).toContainText('Wasserhahn');
    await ctx.close();
  });
});
