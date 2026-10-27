import { test, expect, Page } from '@playwright/test';
import { goto, login } from './helpers';

// STAFFEL-MITTEILUNG (Auftrag C, 27.10.2026): Art. 269d Abs. 5 OR, Art. 19a VMWG.
//
// Auf der Vertragsakte (Reiter «Mietzins») steht je Staffelstufe der Stand der schriftlichen
// Mitteilung: noch nicht im Fenster / Mitteilung fällig / Schreiben erstellt / versandt, mit den
// Aktionen «Schreiben erstellen» und «Als versandt markieren». Die Mitteilung darf frühestens vier
// Monate vor der Erhöhung erfolgen — vorher gibt es keine Aktion.
//
// Testdaten: `seed_e2e_mietzins` (Sven Staffel: erste Stufe in 3 Monaten = im Fenster, zweite in 15 Monaten
// = noch nicht). Der Ablauf verändert die Daten; deshalb zuerst die Messung am Telefon, danach der Ablauf.

const SHOTS = process.env.E2E_SHOTS;

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

async function staffelAkte(page: Page) {
  await login(page);
  await goto(page, '/neu/vertraege/');
  const link = page.locator('a[href*="/neu/vertraege/"]').filter({ hasText: 'Staffel' }).first();
  await expect(link, 'Seed fehlt: kein Staffelvertrag').toBeVisible();
  const id = ((await link.getAttribute('href')) || '').match(/\/neu\/vertraege\/(\d+)\//)![1];
  await goto(page, `/neu/vertraege/${id}/?tab=mietzins`);
  const karte = page.locator('#vt-staffel-mitteilungen');
  await expect(karte).toBeVisible();
  return karte;
}

test.describe('Staffel-Mitteilung Telefon', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('zwei Stufen, nur die im Fenster hat Aktionen, nichts quer', async ({ page }) => {
    const karte = await staffelAkte(page);
    const zeilen = karte.locator('[data-staffel-stufe]');
    await expect(zeilen).toHaveCount(2);
    await expect(zeilen.nth(0)).toHaveAttribute('data-status', 'faellig');
    await expect(zeilen.nth(0)).toContainText('Mitteilung fällig');
    await expect(zeilen.nth(0).getByRole('button', { name: 'Schreiben erstellen' })).toBeVisible();
    await expect(zeilen.nth(0).getByRole('button', { name: 'Als versandt markieren' })).toBeVisible();
    await expect(zeilen.nth(1)).toHaveAttribute('data-status', 'noch_nicht');
    await expect(zeilen.nth(1)).toContainText('noch nicht im Fenster');
    await expect(zeilen.nth(1).locator('button.fw-btn')).toHaveCount(0);       // vor dem Fenster keine Aktion
    await expect(zeilen.nth(0)).toContainText('+ CHF 50.00');
    await expect(zeilen.nth(0)).toContainText('Mitteilung frühestens ab');
    await keinQuerscrollen(page, 'Vertragsakte, Reiter Mietzins');
    // Jede Zeile bleibt innerhalb des Bildschirms (390 px).
    for (let i = 0; i < 2; i++) {
      const box = (await zeilen.nth(i).boundingBox())!;
      expect(box.x + box.width, `Zeile ${i} ragt über den Rand`).toBeLessThanOrEqual(390.5);
    }
    if (SHOTS) await karte.screenshot({ path: `${SHOTS}/staffel-Telefon.png` });
  });
});

test.describe('Staffel-Mitteilung Desktop', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('Schreiben erstellen, dann als versandt markieren', async ({ page }) => {
    const karte = await staffelAkte(page);
    const erste = karte.locator('[data-staffel-stufe]').nth(0);
    await erste.getByRole('button', { name: 'Schreiben erstellen' }).click();
    await expect(page.locator('body')).toContainText('erstellt und in der Akte abgelegt');
    const danach = page.locator('#vt-staffel-mitteilungen [data-staffel-stufe]').nth(0);
    await expect(danach).toHaveAttribute('data-status', 'erstellt');
    await expect(danach).toContainText('Schreiben erstellt');
    await expect(danach.getByRole('link', { name: 'Schreiben öffnen' })).toBeVisible();

    await danach.getByRole('button', { name: 'Als versandt markieren' }).click();
    await expect(page.locator('body')).toContainText('als versandt markiert');
    const fertig = page.locator('#vt-staffel-mitteilungen [data-staffel-stufe]').nth(0);
    await expect(fertig).toHaveAttribute('data-status', 'versandt');
    await expect(fertig.locator('button.fw-btn')).toHaveCount(0);              // erledigt: keine Aktion mehr
    await keinQuerscrollen(page, 'nach dem Versand');
    if (SHOTS) await page.locator('#vt-staffel-mitteilungen').screenshot({ path: `${SHOTS}/staffel-Desktop.png` });
  });
});
