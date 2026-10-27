import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// Bewerber-Board (Modul 4, 27.10.2026): /neu/bewerbungen/
//
// Testdaten aus `seed_e2e`: Lea (neu), Marco (geprueft), Nina (geprueft),
// Tom (neu) — je Ablauf eine eigene Karte, damit die Tests sich nicht den
// Zustand wegnehmen. Reihenfolge der Tests ist deshalb egal.
//
// Geprüft wird, was nur der Browser zeigt: Ziehen und Ablegen, der
// Rücksprung bei einem unzulässigen Wechsel, der Bestätigungsdialog vor der
// Absage (ein <dialog>, kein confirm()) und am Telefon die eingeklappten
// Spalten samt Auswahlfeld «Verschieben nach…».

const spalte = (page: Page, key: string) => page.locator(`.fw-spalte[data-spalte="${key}"]`);
const karteIn = (page: Page, key: string, name: string) =>
  spalte(page, key).locator('.fw-karte', { hasText: name });

async function neuGeladen(page: Page, tun: () => Promise<void>) {
  const geladen = page.waitForEvent('framenavigated', (f) => f === page.mainFrame());
  await tun();
  await geladen;
  await page.waitForLoadState('domcontentloaded');
}

test.describe('Bewerber-Board am Desktop', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await goto(page, '/neu/bewerbungen/');
  });

  test('vier Spalten, Umschalter Liste | Board', async ({ page }) => {
    await expect(page.locator('#fwBoard .fw-spalte')).toHaveCount(4);
    for (const key of ['eingegangen', 'geprueft', 'abgelehnt', 'vertrag']) {
      await expect(spalte(page, key)).toBeVisible();
    }
    await expect(page.locator('.fw-segment .fw-seg-link.an')).toContainText('Board');
  });

  test('Ziehen nach «Geprüft» setzt den Status', async ({ page }) => {
    const lea = karteIn(page, 'eingegangen', 'Lea');
    await expect(lea).toHaveCount(1);
    const antwort = page.waitForResponse((r) => r.url().includes('/verschieben/'));
    await lea.dragTo(spalte(page, 'geprueft'));
    expect((await antwort).status()).toBe(200);
    await expect(karteIn(page, 'geprueft', 'Lea')).toHaveCount(1);

    await goto(page, '/neu/bewerbungen/');                 // auch nach dem Neuladen
    await expect(karteIn(page, 'geprueft', 'Lea')).toHaveCount(1);
  });

  test('Unzulässiges springt zurück und nennt den Grund', async ({ page }) => {
    const marco = karteIn(page, 'geprueft', 'Marco');
    const antwort = page.waitForResponse((r) => r.url().includes('/verschieben/'));
    await marco.dragTo(spalte(page, 'eingegangen'));
    expect((await antwort).status()).toBe(400);
    await expect(karteIn(page, 'geprueft', 'Marco')).toHaveCount(1);
    await expect(karteIn(page, 'eingegangen', 'Marco')).toHaveCount(0);
    await expect(page.locator('#fwBoardMeldung')).toBeVisible();
    await expect(page.locator('#fwBoardMeldungText')).toContainText('kein Wechsel vorgesehen');
  });

  test('Ablegen auf «Abgelehnt» fragt im Dialog nach', async ({ page }) => {
    const dialog = page.locator('#fwBwAbsage');

    // Abbrechen: kein Aufruf, die Karte springt zurück.
    let aufrufe = 0;
    page.on('request', (r) => { if (r.url().includes('/verschieben/')) aufrufe += 1; });
    await karteIn(page, 'geprueft', 'Nina').dragTo(spalte(page, 'abgelehnt'));
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Nina E2E-Bewerber');
    await dialog.locator('#fwBwAbsageNein').click();
    await expect(dialog).toBeHidden();
    await expect(karteIn(page, 'geprueft', 'Nina')).toHaveCount(1);
    expect(aufrufe).toBe(0);

    // Bestätigen: Absage gesetzt (die Mail verschickt der Server).
    await karteIn(page, 'geprueft', 'Nina').dragTo(spalte(page, 'abgelehnt'));
    await expect(dialog).toBeVisible();
    const antwort = page.waitForResponse((r) => r.url().includes('/verschieben/'));
    await dialog.locator('#fwBwAbsageJa').click();
    expect((await antwort).status()).toBe(200);
    await expect(karteIn(page, 'abgelehnt', 'Nina')).toHaveCount(1);
    await expect(karteIn(page, 'abgelehnt', 'Nina')).toContainText('Absage gesetzt');
  });
});

test.describe('Bewerber-Board am Telefon', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('Spalten klappen, das Auswahlfeld verschiebt mit Rückfrage', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/bewerbungen/');

    // Kein horizontales Scrollen bei 390 px.
    const breite = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(breite).toBeLessThanOrEqual(390);

    // Offen stehen die Arbeitsspalten, Abgelehnt und Vertrag sind zu.
    const offen = (key: string) => spalte(page, key).locator('details').evaluate((d) => (d as HTMLDetailsElement).open);
    expect(await offen('eingegangen')).toBe(true);
    expect(await offen('geprueft')).toBe(true);
    expect(await offen('abgelehnt')).toBe(false);
    expect(await offen('vertrag')).toBe(false);
    await spalte(page, 'vertrag').locator('summary').click();
    expect(await offen('vertrag')).toBe(true);

    // «Verschieben nach…» → Abgelehnt: erst der Dialog, dann das Formular.
    const tom = karteIn(page, 'eingegangen', 'Tom');
    const wahl = tom.locator('select[data-wahl]');
    await expect(wahl).toBeVisible();
    const kasten = await wahl.boundingBox();
    expect(kasten && kasten.height).toBeGreaterThanOrEqual(36);     // mit dem Finger treffbar
    await wahl.selectOption('abgelehnt');
    const dialog = page.locator('#fwBwAbsage');
    await expect(dialog).toBeVisible();
    await neuGeladen(page, () => dialog.locator('#fwBwAbsageJa').click());

    await spalte(page, 'abgelehnt').locator('summary').click();
    await expect(karteIn(page, 'abgelehnt', 'Tom')).toHaveCount(1);
    await expect(karteIn(page, 'eingegangen', 'Tom')).toHaveCount(0);
  });
});
