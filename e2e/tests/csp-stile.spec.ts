import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// STILE UNTER DER SCHARFEN RICHTLINIE (12.11.2026): `style-src` kennt kein 'unsafe-inline' mehr. Ein style-Attribut im
// Quelltext oder ein <style> ohne Nonce würde der Browser blockieren — die Seite sähe dann still anders aus, und kein
// Test, der nur nach Text sucht, merkte es. Dieser Durchlauf öffnet die Hauptseiten und sammelt jede Verletzung der
// Richtlinie, die der Browser meldet (Ereignis `securitypolicyviolation`).

const SEITEN = [
  '/neu/', '/neu/auswertung/', '/neu/berichte/', '/neu/berichte/leerstand-verlauf/', '/neu/portfolio/', '/neu/finanzen/',
  '/neu/zulauf/', '/neu/ersatzplanung/', '/neu/regelwerk/protokoll/', '/neu/kommunikation/', '/neu/stweg/',
  '/neu/liegenschaften/', '/neu/objekte/', '/neu/vertraege/', '/neu/personen/', '/neu/schaeden/', '/neu/debitoren/',
  '/neu/kreditoren/', '/neu/buchhaltung/', '/neu/mahnwesen/', '/neu/einstellungen/', '/neu/abonnement/',
  '/neu/vertraege/neu/',
];

async function sammeln(page) {
  await page.addInitScript(() => {
    (window as any).__verstoesse = [];
    document.addEventListener('securitypolicyviolation', (e: any) => {
      (window as any).__verstoesse.push(`${e.violatedDirective} ${e.blockedURI} ${(e.sample || '').slice(0, 80)}`);
    });
  });
}

test('Hauptseiten: keine Verletzung der Stil-Richtlinie', async ({ page }) => {
  await sammeln(page);
  await login(page);
  const funde: string[] = [];
  for (const url of SEITEN) {
    await goto(page, url);
    await page.waitForTimeout(300);
    const v: string[] = await page.evaluate(() => (window as any).__verstoesse || []);
    for (const eintrag of v) funde.push(`${url}: ${eintrag}`);
  }
  expect(funde, funde.join('\n')).toEqual([]);
});

test('Anmeldeseite und öffentliche Seiten: keine Verletzung', async ({ page }) => {
  await sammeln(page);
  for (const url of ['/login/', '/']) {
    await goto(page, url);
    const v: string[] = await page.evaluate(() => (window as any).__verstoesse || []);
    expect(v, `${url}: ${v.join(' | ')}`).toEqual([]);
  }
});

test('Vertragsvorschau lädt mit ihren Stilen im Rahmen', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/vertraege/neu/');
  const rahmen = page.frameLocator('#pvFrame');
  // Die Vorschau lädt nach dem ersten Eintrag; ohne Objekt zeigt sie den Hinweistext. Beides kommt von der Antwort der
  // Vorschau-Adresse (POST in den Rahmen), nicht aus `srcdoc`.
  await page.evaluate(() => (window as any).refreshServerPreview && (window as any).refreshServerPreview());
  await expect(rahmen.locator('body')).toContainText(/Objekt auswählen|Vertrag/i, { timeout: 15000 });
});
