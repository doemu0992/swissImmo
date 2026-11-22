import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Einstellungen (Mockup Modul 9): links die Liste aller Einstellungen, rechts die offene Seite.

test('Einstellungen Desktop: Seitenliste markiert die offene Seite, Suche filtert, Klick wechselt', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await login(page);
  await goto(page, '/neu/vorlagen/');
  const nav = page.locator('#fwEinstNav');
  await expect(nav).toBeVisible();
  await expect(nav.locator('a[aria-current="page"]')).toHaveCount(1);
  await expect(nav.locator('a[aria-current="page"]')).toHaveText(/Vorlagen/);
  // Liste und Seite stehen nebeneinander
  const n = await nav.boundingBox();
  const s = await page.locator('.fw-einst-seite').boundingBox();
  expect(n!.x + n!.width).toBeLessThanOrEqual(s!.x);
  await nav.locator('input[type="search"]').fill('frist');
  await expect(nav.locator('a:visible')).toHaveCount(1);
  await expect(nav.locator('a:visible')).toHaveText(/Regelwerk/);
  await nav.locator('a:visible').click();
  await expect(page).toHaveURL(/\/neu\/regelwerk\//);
  await expect(page.locator('#fwEinstNav a[aria-current="page"]')).toHaveText(/Regelwerk/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await ctx.close();
});

test('Einstellungen Telefon: keine Seitenliste, die Krume führt zur Übersicht', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await login(page);
  await goto(page, '/neu/account/');
  await expect(page.locator('#fwEinstNav')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await ctx.close();
});
