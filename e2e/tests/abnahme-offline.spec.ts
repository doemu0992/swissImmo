import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// ABNAHME VOR ORT OHNE EMPFANG — IM ECHTEN BROWSER
//
// Im Keller fehlt der Empfang. Die Zusage der Seite: Was angezeigt wurde, ist
// auf dem Gerät, und es geht beim nächsten Empfang der Reihe nach hinaus. Das
// hängt an drei Teilen, die nur zusammen im Browser stimmen (Service Worker,
// IndexedDB-Schlange, Überlagerung nach dem Neuladen) — ein Django-Test sieht
// davon nur die Zeichenkette.

test.setTimeout(90_000);
test.use({ viewport: { width: 390, height: 844 }, serviceWorkers: 'allow' });

test('Eingaben ohne Netz bleiben erhalten und gehen mit Netz hinaus', async ({ page, context }) => {
  await login(page);

  // Protokoll über den Assistenten anlegen (leere Vorlage, zwei Räume)
  await goto(page, '/neu/vertraege/1/abnahme/vorort/?typ=auszug&vorlage=standard');
  await page.selectOption('#vnVorlage', 'leer');
  await page.click('button[data-tab=struktur].fw-btn');
  for (const raum of ['Küche', 'Keller']) {
    await page.click('#vnHinzu');
    await page.fill('#vnEigen', raum);
    await page.click('#vnEigenOk');
  }
  await page.click('button[type=submit].fw-btn');
  await page.waitForURL(/\/neu\/abnahme\/\d+\/vorort\//, { waitUntil: 'domcontentloaded' });
  const seite = page.url().split('?')[0];

  // Service Worker anmelden lassen; die Räume werden vorgehalten
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true));
  await expect.poll(() => page.evaluate(async () => {
    const c = await caches.open('abnahme-vor-ort-v1');
    return (await c.keys()).length;
  })).toBeGreaterThanOrEqual(3);

  // Netz weg: Ampel, Kommentar
  await context.setOffline(true);
  const karte = page.locator('.vo-karte').first();
  await karte.locator('[data-zustand=normal]').click();
  await karte.locator('[data-kommentar]').click();
  await karte.locator('[data-feld=kommentar]').fill('Kratzer links');
  await karte.locator('[data-feld=kommentar]').blur();
  await expect.poll(() => page.evaluate(() => (window as any).voSync.wartende().then((w: unknown[]) => w.length))).toBe(2);

  // Neuladen ohne Netz: Seite kommt aus dem Cache, die Eingaben liegen darüber
  await page.goto(seite + '?r=0', { waitUntil: 'domcontentloaded' });
  const nach = page.locator('.vo-karte').first();
  await expect(nach).toHaveAttribute('data-zustand', 'normal');
  await expect(nach.locator('[data-feld=kommentar]')).toHaveValue('Kratzer links');

  // Abschliessen ist ohne Netz gesperrt
  await page.goto(seite + '?r=2', { waitUntil: 'domcontentloaded' });
  await page.click('#vo form button.fw-gutknopf[type=submit]');
  await expect(page.locator('#voSync')).toBeVisible();

  // Netz zurück: die Schlange leert sich, der Server hat den Stand
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect.poll(() => page.evaluate(() => (window as any).voSync.wartende().then((w: unknown[]) => w.length))).toBe(0);
  await goto(page, seite + '?r=0');
  const server = page.locator('.vo-karte').first();
  await expect(server).toHaveAttribute('data-zustand', 'normal');
  await expect(server.locator('[data-feld=kommentar]')).toHaveValue('Kratzer links');
});
