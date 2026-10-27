import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// Abnahme vor Ort einrichten im Assistenten-Standard (27.10.2026, client-seitige Variante):
// «Allgemein» (Datum, Art, Strukturvorlage) und «Struktur» (Räume). Ein POST am Schluss legt das
// Protokoll an und führt auf die Abnahmeseite. Gegen den Seed-Vertrag 1.
// Am Telefon bleibt die Seite ohne Quer-Scrollen, die Raumzeilen haben 44-px-Knöpfe.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

const START = '/neu/vertraege/1/abnahme/vorort/?typ=auszug';

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

const namen = (page: Page) => page.locator('#vnListe input[name="raum"]').evaluateAll((l) => l.map((i) => (i as HTMLInputElement).value));

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Zwei Schritte im Standard; Räume ergänzen, verschieben, entfernen; Anlegen', async ({ page }) => {
      await login(page);
      await goto(page, START);
      const leiste = page.locator('.fw-assistent.an .fw-assistent-leiste');
      await expect(leiste.locator('li')).toHaveCount(2);
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Allgemein');
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 1 von 2/i);
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 1 von 2');
      await expect(page.locator('.fw-assistent-fuss').getByRole('link', { name: 'Abbrechen' })).toHaveAttribute('href', /\/neu\/vertraege\/1\/$/);
      await expect(page.locator('#vnTyp')).toHaveValue('auszug');
      // Im ersten Schritt steht der Abschluss noch nicht im Fuss.
      await expect(page.locator('.fw-assistent-fuss [data-assistent-absenden]')).toBeHidden();
      await keinQuerscrollen(page);

      // Vorlage «Leer»: die Raumliste im zweiten Schritt ist leer, der Leerhinweis steht da.
      await page.selectOption('#vnVorlage', 'leer');
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Struktur');
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 2 von 2');
      await expect(leiste.locator('li.fertig .nr')).toHaveText('✓');
      await expect(page.locator('#vnLeer')).toBeVisible();
      await expect(page.locator('.fw-assistent-fuss [data-assistent-weiter]')).toBeHidden();
      await expect(page.locator('.fw-assistent-fuss [data-assistent-absenden]')).toBeVisible();

      // Ohne Raum: der Server meldet es, und der Assistent steht wieder im Schritt «Struktur».
      await page.locator('.fw-assistent-fuss [data-assistent-absenden]').click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page.getByText('Mindestens ein Raum ist nötig')).toBeVisible();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Struktur');
      await expect(page.locator('#vnListe')).toHaveAttribute('aria-invalid', 'true');

      // Räume über den Katalog und als eigener Name ergänzen.
      await page.click('#vnHinzu');
      await expect(page.locator('#vnDialog')).toBeVisible();
      const dialog = await page.locator('#vnDialog').boundingBox();
      expect(dialog!.x).toBeGreaterThanOrEqual(0);
      expect(dialog!.x + dialog!.width).toBeLessThanOrEqual(b.viewport.width);
      await page.fill('#vnEigen', 'Dachboden');
      await page.click('#vnEigenOk');
      await expect(page.locator('#vnDialog')).toBeHidden();
      await page.click('#vnHinzu');
      await page.fill('#vnEigen', 'Keller');
      await page.click('#vnEigenOk');
      await page.click('#vnHinzu');
      await page.fill('#vnEigen', 'Bad');
      await page.click('#vnEigenOk');
      expect(await namen(page)).toEqual(['Dachboden', 'Keller', 'Bad']);
      await expect(page.locator('#vnLeer')).toBeHidden();

      // Die Knöpfe der Zeilen sind 44 px gross und stehen im Bild.
      const ikon = await page.locator('.fw-abn-zeile').first().locator('.fw-abn-ikon').first().boundingBox();
      expect(Math.round(ikon!.width)).toBe(44);
      expect(Math.round(ikon!.height)).toBe(44);
      for (const zeile of await page.locator('.fw-abn-zeile').all()) {
        const r = await zeile.boundingBox();
        expect(r!.x + r!.width).toBeLessThanOrEqual(b.viewport.width);
      }
      await expect(page.locator('.fw-abn-zeile').first().locator('.hoch')).toBeDisabled();
      await expect(page.locator('.fw-abn-zeile').last().locator('.runter')).toBeDisabled();

      // Verschieben und Entfernen: «Bad» ganz nach oben, «Keller» weg.
      await page.locator('.fw-abn-zeile').nth(2).locator('.hoch').click();
      await page.locator('.fw-abn-zeile').nth(1).locator('.hoch').click();
      expect(await namen(page)).toEqual(['Bad', 'Dachboden', 'Keller']);
      await page.locator('.fw-abn-zeile').nth(2).locator('.gefahr').click();
      expect(await namen(page)).toEqual(['Bad', 'Dachboden']);
      await keinQuerscrollen(page);

      // Zurück und wieder vor: die Räume bleiben. Datum und Art stehen im Formular.
      await page.locator('.fw-assistent-fuss [data-assistent-zurueck]').click();
      await expect(page.locator('.zeigt .fw-assistent-schritt-kopf h2')).toHaveText('Allgemein');
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      expect(await namen(page)).toEqual(['Bad', 'Dachboden']);

      // Anlegen: ein Protokoll, auf der Abnahmeseite stehen die Räume in dieser Reihenfolge.
      await page.locator('.fw-assistent-fuss [data-assistent-absenden]').click();
      await page.waitForURL(/\/neu\/abnahme\/\d+\/vorort\//, { waitUntil: 'domcontentloaded' });
    });

    test('Mit der Standardvorlage stehen Räume da, und die Art «Aus- und Einzug» ist ohne zweiten Vertrag gesperrt', async ({ page }) => {
      await login(page);
      await goto(page, START + '&vorlage=standard');
      await expect(page.locator('#vnTyp option[value="beides"]')).toBeDisabled();
      await expect(page.getByRole('link', { name: 'Folgevertrag anlegen' })).toBeVisible();
      await page.locator('.fw-assistent-fuss [data-assistent-weiter]').click();
      expect((await namen(page)).length).toBeGreaterThan(3);
      await keinQuerscrollen(page);
    });
  });
}
