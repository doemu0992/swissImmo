import { test, expect, Page } from '@playwright/test';
import { login } from './helpers';

// Das öffentliche Bewerbungsformular und die alten Dossier-Adressen (Etappe 3, 29.10.2026).
//
// Als `zz-`-Spec, weil sie ein Objekt kurz ausschreibt (der E2E-Bestand hat keines) und danach
// wieder zurücknimmt; die Specs laufen alphabetisch in einer Datenbank, und kein anderes soll das
// Objekt in der Zwischenzeit sehen. Höchstens eine Absendung: Die Drossel erlaubt fünf je IP und Stunde.

const OBJEKT = 2; // «Keller E2E»

async function csrf(page: Page) {
  const c = (await page.context().cookies()).find((k) => k.name === 'csrftoken');
  return c ? c.value : '';
}

async function ausschreiben(page: Page, ziel: 'an' | 'aus') {
  const r = await page.request.post(`/neu/objekte/${OBJEKT}/ausschreiben/`, {
    form: { ziel, weiter: '/neu/', csrfmiddlewaretoken: await csrf(page) },
    headers: { 'X-CSRFToken': await csrf(page) },
  });
  expect(r.status()).toBeLessThan(400);
}

// Der Assistent setzt 50 ms nach jedem Schrittwechsel den Fokus auf das erste Feld; wer in dieser
// Zeit schon tippt, landet im falschen Feld. Ein Mensch ist nicht so schnell, der Test schon.
const weiter = {
  click: async (page: Page) => { await page.locator('[data-assistent-weiter]').click(); await page.waitForTimeout(200); },
};

test.describe.serial('Bewerbung', () => {
  test.beforeAll(async ({ browser }) => {
    const seite = await (await browser.newContext()).newPage();
    await login(seite);
    await ausschreiben(seite, 'an');
    await seite.context().close();
  });
  test.afterAll(async ({ browser }) => {
    const seite = await (await browser.newContext()).newPage();
    await login(seite);
    await ausschreiben(seite, 'aus');
    await seite.context().close();
  });

  test('Telefon 390 px: Kopf heil, DM Sans, kein Querscroll (DESIGN-24)', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/bewerben/${OBJEKT}/`, { waitUntil: 'load' });
    // Vorher stand der Kopf in einer schwarzen Knopfkapsel, vom Titel blieb am Telefon ein «K».
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Keller E2E');
    await expect(page.locator('.fw-phead .fw-btn')).toHaveCount(0);
    const m = await page.evaluate(() => ({
      breit: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      schrift: getComputedStyle(document.body).fontFamily,
      plex: Array.from(document.querySelectorAll('body *')).some((e) => /IBM Plex Sans/.test(getComputedStyle(e).fontFamily.split(',')[0])),
    }));
    expect(m.breit).toBeLessThanOrEqual(0);
    expect(m.schrift).toContain('DM Sans');
    expect(m.plex).toBe(false);
  });

  test('Pflichtfelder halten im Schritt fest, Dunkelmodus lesbar', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto(`/bewerben/${OBJEKT}/`, { waitUntil: 'load' });
    await weiter.click(page);
    await expect(page.locator('.fw-assistent-stand')).toHaveText('Schritt 1 von 6');
    const grund = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(grund).not.toBe('rgb(255, 255, 255)');
  });

  test('Eine vollständige Bewerbung geht durch; «unbefristet» abgehakt wird als nein gesendet', async ({ page }) => {
    await page.goto(`/bewerben/${OBJEKT}/`, { waitUntil: 'load' });
    await page.fill('#b-vorname', 'Anna'); await page.fill('#b-nachname', 'Beispiel'); await page.fill('#b-geburtsdatum', '1990-05-17');
    await weiter.click(page);
    await page.fill('#b-mobil', '0791112233'); await page.fill('#b-email', 'anna@example.ch'); await page.fill('#b-adresse', 'Altweg 3');
    await page.fill('#b-plz', '8000'); await page.fill('#b-ort', 'Zürich');
    await page.fill('#b-vermieter', 'Alt AG'); await page.fill('#b-vermieter-tel', '0441112233');
    await weiter.click(page);
    await page.fill('#b-beruf', 'Ingenieurin'); await page.selectOption('#b-einkommen', '70’000 - 80’000');
    await page.fill('#b-arbeitgeber', 'Firma X'); await page.fill('#b-seit', '2018-01-01'); await page.fill('#b-ag-tel', '0445556677');
    await page.uncheck('input[name="ist_unbefristet"]');
    await weiter.click(page);
    await weiter.click(page);   // Wohnen (alles freiwillig)
    await page.fill('#b-bezug', '2026-12-01');
    // Ohne Auszug und ohne «nachreichen» geht es nicht weiter (Pflicht folgt der Sichtbarkeit).
    await weiter.click(page);
    await expect(page.locator('.fw-assistent-stand')).toHaveText('Schritt 5 von 6');
    await page.check('#b-nachreichen');
    await weiter.click(page);
    await expect(page.locator('.fw-assistent-pruefen')).toContainText('Anna');
    const gesendet = page.waitForRequest((r) => r.url().endsWith('/api/mietprozess/public/bewerben'));
    await page.getByRole('button', { name: /Verbindlich einreichen/ }).click();
    // Ein nicht angehaktes Feld fehlt im Formularversand; die Schnittstelle liest «fehlt» als Vorgabe
    // (bei `ist_unbefristet` «ja»). Deshalb sendet das Skript jedes Häkchen ausdrücklich.
    const koerper = (await gesendet).postData() || '';
    expect(koerper).toMatch(/name="ist_unbefristet"\r\n\r\nfalse/);
    expect(koerper).toMatch(/name="haustiere"\r\n\r\nfalse/);
    await expect(page.locator('#bewerbungErfolg')).toBeVisible();
    await expect(page.getByText('Bewerbung eingereicht!')).toBeVisible();
  });
});

test('Die Absageseite hat einen Weg zurück (ROUTE-17 d)', async ({ page }) => {
  // «Index E2E» (3) ist nicht ausgeschrieben.
  const r = await page.goto('/bewerben/3/', { waitUntil: 'load' });
  expect(r!.status()).toBe(410);
  await page.getByRole('link', { name: 'Zurück zur Startseite' }).click();
  await expect(page).toHaveURL(/\/$/);
});

test('Alte Dossier-Adressen führen in die Akte', async ({ page }) => {
  await login(page);
  await page.goto('/dossier/mieter/1/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/neu\/personen\/1\/$/);
  await page.goto('/dossier/vertrag/1/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/neu\/vertraege\/1\/$/);
});
