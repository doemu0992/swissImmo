import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// Listenform (Mockup «Immoswiss Listenform»): Zeilenlisten haben Spaltenkopf und Raster wie die Tabellen.

test('Objekte Desktop: eine Karte, Spaltenkopf, Zeilen im Raster, Gruppe klappt zu', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await login(page);
  await goto(page, '/neu/objekte/');
  await expect(page.locator('.fw-lf')).toHaveCount(1);
  const kopf = page.locator('.fw-lf-spalten');
  await expect(kopf).toBeVisible();
  await expect(kopf).toContainText('Mietzins');
  const zeile = page.locator('.fw-lf-zeile').first();
  await expect(zeile).toBeVisible();
  // Spalten der Zeile stehen unter denen des Kopfs (gleiches Raster)
  const kx = await kopf.locator('span').nth(1).evaluate((e) => Math.round(e.getBoundingClientRect().left));
  const zx = await zeile.locator('.fw-lf-zelle').evaluate((e) => Math.round(e.getBoundingClientRect().left));
  expect(Math.abs(kx - zx)).toBeLessThanOrEqual(1);
  // Der Statuspunkt ist rund, nicht ein Balken
  const punkt = await zeile.locator('.fw-marker').boundingBox();
  expect(Math.round(punkt!.height)).toBe(8);
  // Aktion erscheint beim Überfahren
  await page.mouse.move(5, 5); // der Zeiger steht vom Anmelden noch irgendwo über der Liste
  await expect(zeile.locator('.fw-lf-akt')).toHaveCSS('opacity', '0');
  await zeile.hover();
  await expect(zeile.locator('.fw-lf-akt')).toHaveCSS('opacity', '1');
  // Zuklappen bleibt
  const gruppe = page.locator('details.fw-lf-gruppe').first();
  const n = await gruppe.locator('.fw-lf-zeile').count();
  expect(n).toBeGreaterThan(0);
  await gruppe.locator('summary .fw-t').click();
  await expect(gruppe.locator('.fw-lf-zeile').first()).toBeHidden();
  await gruppe.locator('summary .fw-t').click();
  // Die Zeile führt in die Akte
  await gruppe.locator('.fw-lf-zeile').first().click();
  await expect(page).toHaveURL(/\/neu\/objekte\/\d+\//);
  await ctx.close();
});

test('Objekte Telefon: kein Spaltenkopf, nichts quer', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await login(page);
  await goto(page, '/neu/objekte/');
  await expect(page.locator('.fw-lf-spalten')).toBeHidden();
  await expect(page.locator('.fw-lf-zeile').first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await ctx.close();
});
