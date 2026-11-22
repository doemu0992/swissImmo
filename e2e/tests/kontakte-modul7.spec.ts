import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Kontakte (Mockup Modul 7): Personen und Dienstleister haben denselben Aufbau.

const SEITEN = ['/neu/personen/', '/neu/dienstleister/'];

test.describe('Kontakte Modul 7', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('Beide Listen haben denselben Aufbau: Zahlenzeile, Kartenkopf mit Filter und Suche, dieselben Spalten', async ({ page }) => {
    await login(page);
    const aufbau: string[][] = [];
    for (const url of SEITEN) {
      await goto(page, url);
      await expect(page.locator('.fw-statuszeile .fw-sz').first(), url).toBeVisible();
      await expect(page.locator('.fw-lg-spalten > .fw-card > .fw-kopf .fw-filters'), url).toBeVisible();
      await expect(page.locator('.fw-lg-spalten > .fw-card > .fw-kopf input[type="search"]'), url).toBeVisible();
      const koepfe = await page.locator('.fw-lg-spalten table.fw-table thead th').evaluateAll((th) => th.map((t) => (t.textContent || '').trim()));
      aufbau.push([koepfe[0], koepfe[1], koepfe[3], koepfe[4]]);
      expect(koepfe.length, url).toBe(5);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), url).toBe(true);
    }
    // Name, Kontakt, Stand und Aktion heissen in beiden Listen gleich; nur die dritte Spalte unterscheidet sich.
    expect(aufbau[0]).toEqual(aufbau[1]);
  });

  test('Vorschau öffnet neben der Liste, ist in beiden Listen gleich breit, und die Zeile öffnet weiter die Akte', async ({ page }) => {
    await login(page);
    const breiten: number[] = [];
    for (const url of SEITEN) {
      await goto(page, url);
      const vorschau = page.locator('#fwVorschau');
      await expect(vorschau).toBeHidden();
      const knopf = page.locator('[data-vorschau]').first();
      await knopf.click();
      await expect(page).toHaveURL(new RegExp(url.replace(/\//g, '\\/') + '$'));
      await expect(vorschau).toBeVisible();
      await expect(vorschau.locator('a.fw-primary')).toHaveAttribute('href', /\/neu\/(personen|dienstleister)\/\d+\/$/);
      breiten.push(Math.round((await vorschau.boundingBox())!.width));
      // Die Tabelle scrollt mit offener Vorschau nicht quer.
      expect(await page.locator('.fw-lg-spalten .fw-tablewrap').first().evaluate((e) => e.scrollWidth - e.clientWidth), url).toBeLessThanOrEqual(1);
      await page.keyboard.press('Escape');
      await expect(vorschau).toBeHidden();
    }
    expect(breiten[0]).toBe(breiten[1]);
    await page.locator('.fw-lg-spalten table.fw-table tbody tr').first().locator('td').nth(3).click();
    await expect(page).toHaveURL(/\/neu\/dienstleister\/\d+\/$/);
  });

  test('Dienstleister: Bearbeiten klappt unter der Zeile auf, Löschen bleibt an der Zeile, Erfassen ist eine Schublade', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/dienstleister/');
    const zeile = page.locator('.fw-lg-spalten table.fw-table tbody tr.fw-klickzeile').first();
    await expect(zeile.locator('form[action$="/loeschen/"] button')).toBeVisible();
    const edit = page.locator('tr.fw-kontakt-edit').first();
    await expect(edit).toBeHidden();
    await zeile.locator('[data-umschalten^="dledit-"]').click();
    await expect(edit).toBeVisible();
    await expect(edit.locator('input[name="firma"]')).not.toHaveValue('');
    await expect(edit.locator('input[name="email"]')).not.toHaveValue('None');
    await edit.locator('[data-verstecken^="dledit-"]').click();
    await expect(edit).toBeHidden();
    await page.locator('.fw-phead [data-umschalten="dlform"]').click();
    const form = page.locator('#dlform');
    await expect(form).toBeVisible();
    const k = (await form.boundingBox())!;
    expect(Math.round(k.x + k.width)).toBe(1440);            // Schublade am rechten Rand
    await form.locator('[data-umschalten="dlform"]').click();
    await expect(form).toBeHidden();
  });
});

test('Kontakte am Telefon: keine Vorschau, nichts quer', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  for (const url of SEITEN) {
    await goto(page, url);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), url).toBe(true);
    await expect(page.locator('[data-vorschau]').first()).toBeHidden();
  }
});
