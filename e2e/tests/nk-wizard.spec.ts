import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// Nebenkosten-Wizard (Modul 1, 27.10.2026): durch die sechs Schritte klicken, ohne etwas
// auszuführen (kein Speichern, kein Verbuchen). Gegen die Seed-Periode «NK E2E 2024»
// (seed_e2e: eine Einheit ohne Fläche → Schritt 1 meldet sie).
// Am Telefon scrollt der Stepper waagrecht, die Seite selbst nie.
// Seit dem Assistenten-Standard (27.10.2026) im Rahmen des server-seitigen Assistenten
// (fw/_assistent_server.html): Klassen `fw-assistent-*` statt `fw-nkw-*`, aktueller Schritt
// `li.hier` statt `li.an`, im Fuss «Schritt i von 6» und «Abbrechen».

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

const SCHRITTE = [
  { titel: 'Periode & Objekte', text: /Für welchen Zeitraum wird abgerechnet/ },
  { titel: 'Kosten', text: /Welche Kosten gehören in diese Abrechnung/ },
  { titel: 'Verteilung', text: /Wie wird jede Kostenart verteilt/ },
  { titel: 'Heizung & Zähler', text: /Wie werden die Heizkosten geteilt/ },
  { titel: 'Prüfen', text: /Geht die Abrechnung auf/ },
  { titel: 'Verbuchen & Zustellen', text: /Verbuchen stellt Nachzahlungen und Guthaben/ },
];

// Die Farbe eines Tokens, wie der Browser sie auflöst (für den Vergleich mit der Leiste).
async function tokenFarbe(page: Page, token: string) {
  return page.evaluate((t) => {
    const e = document.createElement('i');
    e.style.background = `var(${t})`;
    document.body.appendChild(e);
    const f = getComputedStyle(e).backgroundColor;
    e.remove();
    return f;
  }, token);
}

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Durch die sechs Schritte, oben steht was fehlt', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByText('NK E2E 2024').first().click();
      await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
      const leiste = page.locator('.fw-assistent.an .fw-assistent-leiste');
      await expect(leiste.locator('li')).toHaveCount(6);

      // Schritt 1 direkt: die flächenlose Einheit steht unter «Was fehlt» und als Kachel.
      await leiste.getByRole('link', { name: /Periode & Objekte/ }).click();
      await page.waitForURL(/\/periode\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('.fw-nk-fehlt')).toContainText('Keller E2E');
      await expect(page.locator('form.fw-kachel').filter({ hasText: 'Keller E2E' })).toBeVisible();
      await keinQuerscrollen(page);

      // Mit «Weiter» durch alle Schritte.
      for (let i = 0; i < SCHRITTE.length; i++) {
        const s = SCHRITTE[i];
        await expect(page.locator('.fw-assistent-schritt-kopf h2')).toHaveText(s.titel);
        await expect(page.locator('.fw-assistent-schritt-kopf')).toContainText(s.text);
        await expect(page.locator('.fw-assistent-schritt-kopf .fw-ueber')).toHaveText(new RegExp(`Schritt ${i + 1} von 6`, 'i'));
        await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText(`Schritt ${i + 1} von 6`);
        await expect(page.locator('.fw-assistent-fuss').getByRole('link', { name: 'Abbrechen' })).toHaveAttribute('href', /\/neu\/nebenkosten\/$/);
        await expect(leiste.locator('li.hier')).toHaveCount(1);
        await expect(leiste.locator('li.hier')).toBeInViewport();
        await keinQuerscrollen(page);
        if (i < SCHRITTE.length - 1) {
          await page.locator('.fw-assistent-fuss a.fw-primary').click();
          await page.waitForLoadState('domcontentloaded');
        }
      }
      // Verbuchen bleibt ungeklickt; der Versand steht erst nach dem Verbuchen bereit.
      await expect(page.getByRole('button', { name: 'Verbuchen' })).toBeVisible();
      await expect(page.getByRole('button', { name: /PDF erstellen/ })).toHaveCount(0);
    });

    test('Neue Periode: Schritt 1 als Seite, höchstens 12 Monate', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByRole('link', { name: /Periode anlegen/ }).first().click();
      await page.waitForURL(/\/nebenkosten\/neu\//, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('input[name="start_datum"]')).toBeVisible();
      // Dieselbe Leiste wie in der Periode: Schritt 1 aktuell, fünf gesperrt, überall «1 von 6».
      const leiste = page.locator('.fw-assistent.an .fw-assistent-leiste');
      await expect(leiste.locator('li')).toHaveCount(6);
      await expect(leiste.locator('li.hier')).toHaveCount(1);
      await expect(leiste.locator('li.gesperrt')).toHaveCount(5);
      await expect(leiste.locator('li.gesperrt a')).toHaveCount(0);
      await expect(page.locator('.fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 1 von 6/i);
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 1 von 6');
      await expect(page.locator('main')).not.toContainText(/Schritt \d von [^6]/);
      await page.locator('[data-nk-schnell] [data-von="heiz"]').click();
      await expect(page.locator('input[name="bezeichnung"]')).toHaveValue(/Heizperiode/);
      await keinQuerscrollen(page);
    });

    test('Leiste in den Farben des Standards: fertig Akzent, Hinweis Warnfarbe, aktuell schwarz', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByText('NK E2E 2024').first().click();
      await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
      await page.locator('.fw-assistent-leiste').getByRole('link', { name: /Verteilung/ }).click();
      await page.waitForURL(/\/verteilung\/$/, { waitUntil: 'domcontentloaded' });
      const nr = (sel: string) => page.locator(`.fw-assistent-leiste ${sel} .nr`).first();
      const hg = (sel: string) => nr(sel).evaluate((e) => getComputedStyle(e).backgroundColor);
      // Seed: Kosten erfasst (fertig), Periode mit flächenloser Einheit (Hinweis), Verteilung hier.
      await expect(nr('li.fertig')).toHaveText('✓');
      expect(await hg('li.fertig')).toBe(await tokenFarbe(page, '--ds-akzent'));
      await expect(nr('li.warnung:not(.hier)')).toHaveText('!');
      expect(await hg('li.warnung:not(.hier)')).toBe(await tokenFarbe(page, '--ds-warn'));
      expect(await hg('li.hier')).toBe(await tokenFarbe(page, '--ds-ink'));
      // Kein grünes «erledigt» mehr wie in der eigenen NK-Leiste.
      expect(await hg('li.fertig')).not.toBe(await tokenFarbe(page, '--ds-good'));
      await keinQuerscrollen(page);
    });

    test('Heizung: Zählerstände und CSV-Import öffnen sich, ohne etwas zu speichern', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/nebenkosten/');
      await page.getByText('NK E2E 2024').first().click();
      await page.waitForURL(/\/nebenkosten\/\d+\//, { waitUntil: 'domcontentloaded' });
      await page.locator('.fw-assistent-leiste').getByRole('link', { name: /Heizung & Zähler/ }).click();
      await page.waitForURL(/\/heizung\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('input[name="hkvo_grundkosten_prozent"]')).toBeVisible();
      await expect(page.getByText(/Kantonale Vorgabe prüfen/)).toBeVisible();
      await page.getByRole('link', { name: /CSV einlesen/ }).click();
      await page.waitForURL(/\/import\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('input[type="file"][name="datei"]')).toBeVisible();
      await keinQuerscrollen(page);
    });
  });
}
