import { test, expect } from '@playwright/test';
import { login } from './helpers';

// Smoke: Nach dem Login müssen die zentralen /neu/-Seiten ohne Serverfehler
// rendern. Fängt Template-/Rendering-Regressionen, die die Django-Unit-Tests
// (Views/Context, kein DOM) strukturell nicht sehen.

test.beforeEach(async ({ page }) => {
  await login(page);
});

const SEITEN: Array<{ url: string; erwartet: RegExp }> = [
  { url: '/neu/',                 erwartet: /Dashboard|Übersicht|Portfolio/i },
  { url: '/neu/buchhaltung/',     erwartet: /Erfolgsrechnung|Bilanz|Buchhaltung|Journal/i },
  { url: '/neu/kreditoren/',      erwartet: /Kreditor|Rechnung/i },
  { url: '/neu/zahllauf/',        erwartet: /Zahllauf|Zahlung/i },
  { url: '/neu/mahnwesen/',       erwartet: /Mahn/i },
  { url: '/neu/mieterspiegel/',   erwartet: /Mieterspiegel|Soll|Ist|Leerstand/i },
  { url: '/neu/nebenkosten/',     erwartet: /Nebenkosten|Abrechnung/i },
];

for (const seite of SEITEN) {
  test(`Seite rendert: ${seite.url}`, async ({ page }) => {
    const resp = await page.goto(seite.url);
    expect(resp?.status(), `HTTP-Status für ${seite.url}`).toBeLessThan(400);
    await expect(page.locator('body')).toContainText(seite.erwartet);
    // Keine Django-Debug-Fehlerseite
    await expect(page.locator('body')).not.toContainText(/Traceback|TemplateSyntaxError|OperationalError/);
  });
}
