import { test, expect } from '@playwright/test';
import { login } from './helpers';

// «Aus einem Guss» in den Fenstern über der Seite. Gemessen 23.11.2026: Das Bestätigungsfenster stand oben links in der
// Ecke (x 0, y 0) statt mittig; Titel 18 und 22 px; Auswahlfenster «Verwaltung und Bestand» mit 14 statt 24 px Radius.
const fenster = (sel: string) => {
  const d = document.querySelector(sel) as HTMLElement, b = d.getBoundingClientRect(), c = getComputedStyle(d);
  const t = d.querySelector('h2') as HTMLElement;
  return { mittig: Math.abs((b.left + b.right) / 2 - innerWidth / 2) < 2 && Math.abs((b.top + b.bottom) / 2 - innerHeight / 2) < 2,
    radius: c.borderTopLeftRadius, titel: getComputedStyle(t).fontSize + ' ' + getComputedStyle(t).fontWeight,
    knoepfe: [...new Set(([...d.querySelectorAll('.fw-btn')] as HTMLElement[]).filter(k => k.offsetWidth).map(k => getComputedStyle(k).minHeight + ' ' + getComputedStyle(k).borderTopLeftRadius))],
    hauptRechts: (() => { const k = ([...d.querySelectorAll('.fw-btn')] as HTMLElement[]).filter(x => x.offsetWidth); const p = k.filter(x => x.classList.contains('fw-primary')).pop(); return !p || k.every(x => x.getBoundingClientRect().right <= p.getBoundingClientRect().right + 1 || x.getBoundingClientRect().top > p.getBoundingClientRect().bottom); })() };
};
const SOLL = { mittig: true, radius: '28px', titel: '18px 600', knoepfe: ['36px 999px'], hauptRechts: true };

test('Bestätigungsfenster: mittig, Titel 18 px, Knöpfe als Pille, Hauptknopf rechts', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto('/neu/vertraege/1/schlussabrechnung/', { waitUntil: 'load' });
  await page.locator('[data-bestaetigen]:visible').first().click();
  await expect(page.locator('#fwBestaetigen')).toBeVisible();
  expect(await page.evaluate(fenster, '#fwBestaetigen')).toEqual(SOLL);
  // am Telefon ebenfalls mittig und nicht breiter als der Bildschirm
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('[data-bestaetigen]:visible').first().click();
  const m = await page.evaluate(() => { const b = document.getElementById('fwBestaetigen')!.getBoundingClientRect(); return [b.left >= 0 && b.right <= innerWidth, Math.abs((b.left + b.right) / 2 - innerWidth / 2) < 2]; });
  expect(m).toEqual([true, true]);
});

test('Zahlung zuordnen: dieselben Masse wie das Bestätigungsfenster', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto('/neu/bankabgleich/?spur=klaerung', { waitUntil: 'load' });
  await page.evaluate(() => (document.getElementById('fwZuordnen') as HTMLDialogElement).showModal());
  expect(await page.evaluate(fenster, '#fwZuordnen')).toEqual(SOLL);
});

test('Schublade und Auswahlfenster: Titel 18 px, Auswahlfenster mit dem Radius des Profilmenüs', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto('/neu/vertraege/1/', { waitUntil: 'load' });
  await page.locator('a[data-modal]:visible').first().click();
  await expect(page.locator('#fwModalBox')).toBeVisible();
  expect(await page.evaluate(() => { const t = getComputedStyle(document.querySelector('#fwModalTitle')!); return t.fontSize + ' ' + t.fontWeight; })).toBe('18px 600');
  await page.goto('/neu/', { waitUntil: 'load' });
  const r = await page.evaluate(() => { document.getElementById('fwProfil')!.classList.remove('hidden'); (document.getElementById('fwArbeitPop') as HTMLElement).hidden = false;
    return [getComputedStyle(document.getElementById('fwProfil')!).borderTopLeftRadius, getComputedStyle(document.getElementById('fwArbeitPop')!).borderTopLeftRadius]; });
  expect(r).toEqual(['24px', '24px']);
});
