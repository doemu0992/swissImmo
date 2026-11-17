import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// DIE SCHIENE (17.11.2026) — ab 1024 px stehen die sechs Bereiche links; ein Klick klappt ihre Seiten auf.
// Hier steht, was nur der Browser zeigt: Öffnen und Schliessen, Fokus, Tastatur, die Hervorhebung.
// Der Aufbau ohne Skript steht in `kopfzeile.spec.ts`, die Telefon-Ansicht in `omnisearch.spec.ts` und `telefon.spec.ts`.

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('Schiene am PC', () => {
  test('Ein Klick öffnet das Feld mit den Seiten, die Wahl einer Seite führt dorthin und schliesst es', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const fach = page.locator('#fwFach');
    await expect(fach).toBeHidden();
    await page.locator('#fwSchiene a[data-fach="finanzen"]').click();
    await expect(fach).toBeVisible();
    await expect(page.locator('#fwSchiene a[data-fach="finanzen"]')).toHaveAttribute('aria-expanded', 'true');
    await expect(fach.locator('section:visible h2')).toHaveText('Finanzen');
    // Selten gebrauchte Seiten stehen unter eigener Überschrift am Ende
    await expect(fach.locator('section:visible .fw-fach-selten')).toBeVisible();
    await fach.locator('a[href^="/neu/debitoren/"]').click();
    await page.waitForURL('**/neu/debitoren/**');
    await expect(page.locator('#fwFach')).toBeHidden();
    // Auf der Seite leuchtet der Bereich in der Schiene
    await expect(page.locator('#fwSchiene a[data-fach="finanzen"]')).toHaveAttribute('aria-current', 'page');
  });

  test('Esc und ein Klick daneben schliessen das Feld; Esc gibt den Fokus an den Bereich zurück', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const knopf = page.locator('#fwSchiene a[data-fach="betrieb"]');
    await knopf.click();
    await expect(page.locator('#fwFach')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#fwFach')).toBeHidden();
    await expect(knopf, 'Esc gibt den Fokus nicht an den Bereich zurück').toBeFocused();
    await knopf.click();
    await expect(page.locator('#fwFach')).toBeVisible();
    await page.mouse.click(900, 600);
    await expect(page.locator('#fwFach')).toBeHidden();
    // Ein zweiter Klick auf denselben Bereich schliesst ebenfalls
    await knopf.click();
    await knopf.click();
    await expect(page.locator('#fwFach')).toBeHidden();
  });

  test('Tastatur: G dann B öffnet «Betrieb», die Ziffer 3 wählt die dritte Seite', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.locator('body').click({ position: { x: 700, y: 400 } });
    await page.keyboard.press('g');
    await page.keyboard.press('b');
    await expect(page.locator('#fwFach section:visible h2')).toHaveText('Betrieb');
    const ziele = await page.locator('#fwFach section:visible ul:not(.fw-fach-selten-liste) a').evaluateAll((l) => l.map((a) => (a as HTMLAnchorElement).getAttribute('href')));
    await page.keyboard.press('3');
    await page.waitForURL(`**${ziele[2]!.split('?')[0]}**`);
  });

  test('«Vermietung» ist ein Punkt: Mieterwechsel, Leerstand, Vermarktung und Bewerbungen leuchten ihn', async ({ page }) => {
    await login(page);
    for (const seite of ['/neu/mieterwechsel/', '/neu/leerstand/', '/neu/vermarktung/', '/neu/bewerbungen/']) {
      await goto(page, seite);
      await page.locator('#fwSchiene a[data-fach="betrieb"]').click();
      await expect(page.locator('#fwFach section:visible a[aria-current="page"]'), seite).toHaveText(/Vermietung/);
      await page.keyboard.press('Escape');
    }
  });

  test('Jede Seite der Schiene ist erreichbar: kein Link führt auf eine Fehlerseite', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/');
    const ziele = await page.locator('#fwFach a').evaluateAll((l) => Array.from(new Set(l.map((a) => (a as HTMLAnchorElement).getAttribute('href')!.split('?')[0]))));
    expect(ziele.length, 'Die Schiene führt auffällig wenige Seiten').toBeGreaterThan(40);
    for (const z of ziele) {
      const r = await page.request.get(z);
      expect(r.status(), z).toBeLessThan(400);
    }
  });

  test('Einstellungen: das Feld führt die Gruppen, die Seiten tragen einen Pfad zurück zum Hub', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.locator('#fwSchiene a[data-fach="einst"]').click();
    const fach = page.locator('#fwFach section:visible');
    await expect(fach.locator('h2')).toHaveText('Einstellungen');
    await expect(fach.locator('h3')).toHaveText(['Verwaltung', 'Team & Zugriff', 'Vorlagen & Regeln', 'Schnittstellen', 'Daten & Protokoll']);
    await fach.locator('a[href^="/neu/benutzer/"]').click();
    await page.waitForURL('**/neu/benutzer/**');
    // Pfad «Einstellungen / Team & Zugriff»; der erste Teil führt zurück
    const krume = page.locator('.fw-einst-krumen');
    await expect(krume).toContainText('Team & Zugriff');
    await krume.locator('a').click();
    await page.waitForURL('**/neu/einstellungen/**');
    await expect(page.locator('.fw-einst-krumen')).toHaveCount(0);
    await expect(page.locator('.fw-gruppe-titel')).toHaveCount(5);
  });

  test('Tastatur: G dann E öffnet die Einstellungen', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    await page.locator('body').click({ position: { x: 700, y: 400 } });
    await page.keyboard.press('g');
    await page.keyboard.press('e');
    await expect(page.locator('#fwFach section:visible h2')).toHaveText('Einstellungen');
  });
});
