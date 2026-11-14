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
  '/neu/anfragen/', '/neu/ablesung/', '/neu/vertraege/neu/',
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
    // Auch ein per Skript gesetzter Stil (`el.style.x = …`) erscheint als style-Attribut. Chromium meldet ihn nicht,
    // Safari in Produktion schon (14.11.2026) — darum zählt hier jedes Element mit style-Attribut als Fund.
    const mitStil: string[] = await page.evaluate(() => Array.from(document.querySelectorAll('[style]'))
      .map((e) => `<${e.tagName.toLowerCase()} id="${e.id}" class="${String(e.getAttribute('class') || '').slice(0, 40)}"> ${e.getAttribute('style')}`));
    for (const eintrag of mitStil) funde.push(`${url}: style-Attribut ${eintrag}`);
  }
  expect(funde, funde.join('\n')).toEqual([]);
});

test('Bedienung setzt kein style-Attribut: Schublade am Telefon, Aktionsmenü, Suche', async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 800 });
  await goto(page, '/neu/');
  await page.evaluate(() => (window as any).fwOpenMobileNav());
  expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe('hidden');
  expect(await page.evaluate(() => document.querySelectorAll('[style]').length)).toBe(0);
  await page.evaluate(() => (window as any).fwCloseMobileNav());
  expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden');

  await page.setViewportSize({ width: 1280, height: 800 });
  await goto(page, '/neu/liegenschaften/');
  const menue = page.locator('.fw-menu > button, [data-fw-menu] > button').first();
  if (await menue.count()) { await menue.click(); }
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => Array.from(document.querySelectorAll('[style]')).map((e) => e.outerHTML.slice(0, 120)))).toEqual([]);
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

test('Gesperrter Inline-Stil: die eigene Meldung nennt Element und Stil', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/');
  const meldung = page.waitForRequest((r) => r.url().endsWith('/csp-bericht/') && (r.postData() || '').includes('"element"'));
  await page.evaluate(() => {
    const el = document.createElement('div');
    el.id = 'cspProbe';
    el.className = 'eins zwei';
    document.body.appendChild(el);
    el.setAttribute('style', 'color: red');
  });
  const koerper = JSON.parse((await meldung).postData() || '{}')['csp-report'];
  expect(koerper['element']).toBe('div#cspProbe.eins.zwei');
  expect(koerper['script-sample']).toContain('color: red');
  expect(String(koerper['violated-directive'])).toContain('style-src');
});

test('Ohne adoptedStyleSheets (Safari vor 16.4): Stile über <style nonce>, kein style-Attribut', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Document.prototype, 'adoptedStyleSheets', { get() { return undefined; }, set() {}, configurable: true });
  });
  await login(page);
  await page.setViewportSize({ width: 390, height: 800 });
  await goto(page, '/neu/');
  await page.evaluate(() => (window as any).fwOpenMobileNav());
  expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe('hidden');
  expect(await page.evaluate(() => document.querySelectorAll('[style]').length)).toBe(0);
});

test('Stil-Attribut des Browsers (iOS: text-overflow:inherit am select) ist erlaubt, jedes andere nicht', async ({ page }) => {
  await sammeln(page);
  await login(page);
  await goto(page, '/neu/');
  await page.evaluate(() => {
    const a = document.createElement('select');
    document.body.appendChild(a);
    a.setAttribute('style', 'text-overflow:inherit');
  });
  await page.waitForTimeout(200);
  expect(await page.evaluate(() => (window as any).__verstoesse)).toEqual([]);
  await page.evaluate(() => {
    const b = document.createElement('select');
    document.body.appendChild(b);
    b.setAttribute('style', 'text-overflow:ellipsis');
  });
  await page.waitForTimeout(200);
  expect((await page.evaluate(() => (window as any).__verstoesse)).length).toBe(1);
});
