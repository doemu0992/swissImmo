import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// AKTIONSMENÜS «MEHR» — MIT ECHTEN ANIMATIONEN (UI-Audit 26.10.2026)
//
// Der Fehler, den Nutzer sahen und kein Test fand: Die Einblend-Animation lief mit
// `animation-fill-mode: both` und machte jeden Inhaltsblock dauerhaft zum eigenen
// Stapelkontext. Das «Mehr»-Menü im Seitenkopf lag dann UNTER den Kennzahlen —
// auf allen Breiten, kein Eintrag war klickbar. Automatisierte Browser schalten die
// Animation ab (`html.fw-ruhig` bei navigator.webdriver), deshalb blieb es unsichtbar.
// Dieser Test verbirgt `webdriver`, lässt die Animation auslaufen und prüft dann,
// dass jeder Eintrag OBEN liegt (elementFromPoint) und im Bild steht. Dazu: Tastatur
// (Escape schliesst, aria-expanded folgt) und Klick daneben.
//
// Zweiter Fehler derselben Menüs: Acht Akten-Menüs waren rechtsbündig verankert und
// ragten am Tablet und Telefon links aus dem Bild (x = -149). Jetzt passt
// `fwMenuEinpassen` sie ein.

const SEITEN = ['/neu/vertraege/1/', '/neu/liegenschaften/1/', '/neu/liegenschaften/', '/neu/kreditoren/', '/neu/berichte/'];
const BREITEN: [number, number][] = [[1440, 900], [820, 1180], [390, 844]];

for (const [w, h] of BREITEN) {
  test(`Mehr-Menüs liegen oben und im Bild (${w} px, mit Animation)`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.addInitScript(() => Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false }));
    await login(page);
    for (const url of SEITEN) {
      await goto(page, url);
      expect(await page.evaluate(() => document.documentElement.classList.contains('fw-ruhig')),
        'Die Animation ist aus — dann prüft dieser Test nicht, wofür er da ist.').toBe(false);
      await page.waitForTimeout(1300);   // Einblenden auslaufen lassen
      const knopf = page.locator('main .fw-phead [data-menu-btn]').first();
      await expect(knopf, `${url}: kein «Mehr»-Menü im Seitenkopf`).toBeVisible();
      await knopf.click();
      await expect(knopf).toHaveAttribute('aria-expanded', 'true');
      const liste = page.locator('main .fw-phead [data-menu-list]:not(.hidden)').first();
      await expect(liste).toBeVisible();
      const m = await liste.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const eintraege = [...el.querySelectorAll('a,button')].filter((e) => e.getBoundingClientRect().height > 0);
        const verdeckt = eintraege.filter((e) => {
          const q = e.getBoundingClientRect(); const y = q.top + q.height / 2;
          if (y < 0 || y > innerHeight) return false;
          const t = document.elementFromPoint(q.left + Math.min(20, q.width / 2), y);
          return !(t && (e.contains(t) || t.contains(e)));
        }).map((e) => (e.textContent || '').trim().slice(0, 30));
        return { l: r.left, r: r.right, n: eintraege.length, verdeckt };
      });
      expect(m.n, `${url}: Menü ohne Einträge`).toBeGreaterThan(0);
      expect(m.l, `${url}: Menü ragt links aus dem Bild (x = ${Math.round(m.l)})`).toBeGreaterThanOrEqual(0);
      expect(m.r, `${url}: Menü ragt rechts aus dem Bild`).toBeLessThanOrEqual(w);
      expect(m.verdeckt, `${url}: Einträge liegen unter einem anderen Block`).toEqual([]);
      // Escape schliesst und gibt den Fokus an den Knopf zurück
      await page.keyboard.press('Escape');
      await expect(liste).toBeHidden();
      await expect(knopf).toHaveAttribute('aria-expanded', 'false');
      // Klick daneben schliesst ebenfalls
      await knopf.click();
      await expect(page.locator('main .fw-phead [data-menu-list]:not(.hidden)').first()).toBeVisible();
      await page.mouse.click(5, h - 5);
      await expect(page.locator('main .fw-phead [data-menu-list]:not(.hidden)')).toHaveCount(0);
    }
  });
}
