import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// DIE KOPFZEILE (seit 18.11.2026 OHNE Bereichskapsel und Menüband)
//
// Die Bereiche stehen bei jeder Breite in der Schiene am linken Rand (`schiene.spec.ts`). Die Kopfzeile trägt Bestand
// (Kontext-Chip), Suche und Werkzeuge. Die Überlauf-Tests des Menübands («Mehr») sind mit dem Band entfallen.

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
    const ohne = await page.locator('#fwSchiene a[data-fach], #fwFach a').evaluateAll((l) =>
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

    test('Ohne Filter nur das Symbol, bei aktivem Filter steht die Strasse im Knopf', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/liegenschaften/');
      const breite = async () => (await page.locator('.fw-bestand').boundingBox())!.width;
      expect(await breite(), 'Ohne Filter bleibt der Knopf ein Symbol').toBeLessThan(60);
      await expect(page.locator('.fw-bestand-name')).toHaveCount(0);
      await waehle(page, 1);
      await expect(page.locator('.fw-bestand-name'), 'Bei aktivem Filter fehlt der Name im Knopf').toBeVisible();
      expect(await breite()).toBeLessThanOrEqual(160);
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
