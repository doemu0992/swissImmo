import { test, expect } from '@playwright/test';
import { goto, login } from './helpers';

// Die Vertragserfassung auf Französisch.
//
// Übersetzt ist die OBERFLÄCHE des Assistenten. Was in den Vertrag geht,
// bleibt deutsch: Der Vertrag ist ein deutscher Rechtstext, und seine Werte
// werden gespeichert. Zwei Stellen, an denen das nicht selbstverständlich ist:
//
// - Die Kündigungsmonate entstehen im Skript aus Häkchen und landen als Text
//   («März, Juni, September») im Feld `kuendigungstermine`. Angezeigt wird der
//   Monat in der Sprache der Seite, der WERT bleibt deutsch.
// - Die Anrede hatte `<option>Herr</option>` ohne `value` — der sichtbare Text
//   war der gespeicherte Wert. Übersetzt hätte das «Monsieur» gespeichert.
//
// Ein Django-Test sieht davon nichts: Die Häkchen baut erst das Skript.

test.describe('Vertragserfassung auf Französisch', () => {
  test('Oberfläche übersetzt, Vertragswerte deutsch', async ({ page, context }) => {
    const fehler: string[] = [];
    page.on('pageerror', (e) => fehler.push(String(e)));

    await context.addCookies([{ name: 'django_language', value: 'fr', url: 'http://127.0.0.1:8811' }]);
    await login(page);
    await goto(page, '/neu/vertraege/neu/');

    // Oberfläche: Auswahl-Platzhalter aus dem Skript und Schrittbeschreibung
    await expect(page.locator('#s_lg option').first()).toHaveText('Choisir un immeuble…');
    await expect(page.locator('#s_mieter option').first()).toHaveText('Choisir une personne…');

    // Kündigungsmonate: Anzeige französisch, Wert deutsch
    const maerz = page.locator('.monat-cb[value="März"]');
    await expect(maerz).toHaveCount(1);
    await expect(page.locator('#monate-grid')).toContainText('mars');
    // Die Schaltfläche «Standard» liegt in Schritt 3; dieselbe Funktion läuft beim Laden.
    await page.evaluate(() => (window as any).monateStandard());
    await expect(page.locator('#f_kuendigungstermine')).toHaveValue('März, Juni, September');

    // Anrede: angezeigt «Monsieur», gespeichert «Herr»
    const herr = page.locator('select[name="anrede"] option').first();
    await expect(herr).toHaveText('Monsieur');
    expect(await herr.evaluate((o: HTMLOptionElement) => o.value)).toBe('Herr');

    expect(fehler).toEqual([]);
  });
});
