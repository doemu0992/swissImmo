import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// Serienbrief («Mitteilungs-Assistent») im Assistenten-Standard (27.10.2026, client-seitige Variante
// mit Vorschau): Empfänger → Mitteilung → Versand. Es wird nichts verschickt: Der PDF-Versand
// wird nur bis zur Anfrage verfolgt, der E-Mail-Versand an der Rückfrage abgebrochen.
// Gegen die Seed-Mieterin «Erika E2E». Am Telefon scrollt nur die Leiste, die Seite nie.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

async function imBild(page: Page, selektor: string) {
  const v = page.viewportSize()!;
  for (const el of await page.locator(selektor).all()) {
    if (!(await el.isVisible())) continue;
    const r = await el.boundingBox();
    expect(r!.x, `${selektor} ragt links hinaus`).toBeGreaterThanOrEqual(0);
    expect(r!.x + r!.width, `${selektor} ragt rechts hinaus`).toBeLessThanOrEqual(v.width);
  }
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Drei Schritte: Empfänger, Mitteilung, Versand — Weiter prüft, die Vorschau folgt', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/kommunikation/');
      const leiste = page.locator('.fw-assistent.an .fw-assistent-leiste');
      await expect(leiste.locator('li')).toHaveCount(3);
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Empfänger');
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 1 von 3/i);
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 1 von 3');
      await expect(leiste.locator('li.hier')).toBeInViewport();
      await expect(page.locator('#brief')).toContainText('[Kein Empfänger ausgewählt]');
      await keinQuerscrollen(page);

      // Ohne Empfänger geht es nicht weiter: «Weiter» bleibt in Schritt 1 und meldet es am Suchfeld.
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Empfänger');
      expect(await page.locator('#emp-search').evaluate((e: HTMLInputElement) => e.validationMessage)).not.toBe('');

      // Empfängerin ankreuzen: Zähler und Vorschau folgen, der Hinweis am Feld verschwindet.
      await page.locator('.emp-row', { hasText: 'Erika E2E' }).locator('.emp-check').check();
      await expect(page.locator('#emp-count')).toHaveText('1 ausgewählt');
      await expect(page.locator('#pv-empfaenger')).toContainText('Erika E2E');
      expect(await page.locator('#emp-search').evaluate((e: HTMLInputElement) => e.validationMessage)).toBe('');

      // Schritt 2: Betreff und Text; ohne Text kein «Weiter».
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Mitteilung');
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 2 von 3/i);
      await expect(leiste.locator('li.fertig .nr')).toHaveText('✓');
      await page.fill('#betreff', 'Heizungswartung im November');
      await expect(page.locator('#pv-betreff')).toHaveText('Heizungswartung im November');
      await page.fill('#nachricht', '');
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Mitteilung');
      await page.fill('#nachricht', 'Guten Tag {name}, am Montag wird die Heizung gewartet ({objekt}).');
      await expect(page.locator('#pv-text')).toContainText('Guten Tag Erika E2E');
      await page.getByRole('button', { name: '+ Anrede' }).click();
      await expect(page.locator('#nachricht')).toHaveValue(/\{anrede\}$/);
      await keinQuerscrollen(page);

      // Schritt 3: Versandart wählen; der Hauptknopf im Fuss folgt der Wahl.
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Versand');
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 3 von 3');
      await expect(page.locator('.fw-assistent-fuss [data-assistent-weiter]')).toBeHidden();
      await expect(page.locator('#mk-zusammen')).toHaveText(/1 Empfänger · Heizungswartung im November/);
      await expect(page.locator('input[name="mk-art"]')).toHaveCount(3);
      await expect(page.locator('#mk-los')).toContainText('Serienbrief-PDF erzeugen');
      await page.locator('input[name="mk-art"][value="mail"]').check();
      await expect(page.locator('#mk-los')).toContainText('Per E-Mail senden');
      await page.locator('input[name="mk-art"][value="druck"]').check();
      await expect(page.locator('#mk-los')).toContainText('Als Brief drucken');
      await keinQuerscrollen(page);
      await imBild(page, '.fw-assistent-fuss, .fw-assistent-fuss .fw-btn, .fw-mk-arten label');

      // E-Mail: die Rückfrage nennt die Zahl; abgebrochen wird nichts gesendet.
      await page.locator('input[name="mk-art"][value="mail"]').check();
      let frage = '';
      let gesendet = false;
      page.on('request', (r) => { if (r.url().includes('/neu/kommunikation/senden/')) gesendet = true; });
      page.once('dialog', (d) => { frage = d.message(); void d.dismiss(); });
      await page.locator('#mk-los').click();
      await expect.poll(() => frage).toContain('1 Empfänger per E-Mail');
      expect(gesendet, 'Nach «Abbrechen» darf nichts gesendet werden').toBe(false);

      // PDF: die Anfrage geht an den Serienbrief-Dienst, mit der gewählten Person und dem Text.
      // Sie wird abgefangen — der Server soll hier kein PDF erzeugen und nichts ablegen.
      await page.context().route('**/neu/kommunikation/serienbrief/', (r) => r.abort());
      await page.locator('input[name="mk-art"][value="pdf"]').check();
      const anfrage = page.context().waitForEvent('request', (r) => r.url().includes('/neu/kommunikation/serienbrief/') && r.method() === 'POST');
      await page.locator('#mk-los').click();
      const daten = (await anfrage).postData() || '';
      expect(daten).toContain('empfaenger_id=');
      expect(decodeURIComponent(daten.replace(/\+/g, ' '))).toContain('Heizungswartung im November');
    });

    test('Vorschau: ein- und ausklappbar am Telefon, Spalte rechts auf dem Desktop', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/kommunikation/');
      const knopf = page.locator('[data-vorschau-knopf]');
      const brief = page.locator('#brief');
      if (b.viewport.width >= 1200) {
        await expect(knopf).toBeHidden();
        await expect(brief).toBeVisible();
        const inhalt = await page.locator('.fw-assistent-inhalt').boundingBox();
        const vorschau = await page.locator('.fw-assistent-vorschau').boundingBox();
        expect(vorschau!.x).toBeGreaterThan(inhalt!.x + inhalt!.width - 1);
      } else {
        await expect(knopf).toBeVisible();
        await expect(brief).toBeVisible();
        await knopf.click();
        await expect(brief).toBeHidden();
        await knopf.click();
        await expect(brief).toBeVisible();
        await imBild(page, '#brief, #brief > div');
      }
      await keinQuerscrollen(page);
    });
  });
}
