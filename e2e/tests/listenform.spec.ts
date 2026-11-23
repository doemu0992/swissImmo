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

test('Schäden Desktop: Spaltenkopf, Status und Befund stehen als Spalten neben dem Titel', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await login(page);
  await goto(page, '/neu/schaeden/');
  const kopf = page.locator('.fw-schaden-spalten');
  await expect(kopf).toBeVisible();
  const zeile = page.locator('.fw-schadenzeile').first();
  const titel = await zeile.locator('.fw-mitte > .fw-t').boundingBox();
  const status = await zeile.locator('.fw-schaden-tags').boundingBox();
  // Status steht rechts neben dem Titel, nicht darüber
  expect(status!.x).toBeGreaterThan(titel!.x + titel!.width - 1);
  // … und unter der Spalte «Status»
  const kx = await kopf.locator('span').nth(2).evaluate((e) => Math.round(e.getBoundingClientRect().left));
  expect(Math.abs(kx - Math.round(status!.x))).toBeLessThanOrEqual(1);
  // Die Nummer steht in der Unterzeile
  await expect(zeile.locator('.fw-mitte > .fw-s .fw-schaden-nr')).toContainText('#');
  // Nichts ragt aus der Zeile: kein Chip überdeckt die Spalte «Alter»
  const alter = await zeile.locator('.fw-seit').boundingBox();
  for (const c of await zeile.locator('.fw-chip').all()) {
    const b = await c.boundingBox();
    if (b) expect(b.x + b.width).toBeLessThanOrEqual(alter!.x);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await ctx.close();
});

test('Pendenzen: eine Karte mit Spaltenkopf, Fälligkeit in einer Spalte, Erledigen bleibt', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await login(page);
  const titel = `Listenform ${Date.now() % 100000}`;
  for (const [t, d] of [[titel + ' A', '2026-12-05'], [titel + ' B', '2026-12-20']]) {
    await goto(page, '/neu/pendenzen/');
    await page.fill('input[name="titel"]', t);
    await page.fill('input[name="faellig_am"]', d);
    await page.locator('form:has(input[name="titel"]) button.fw-btn').last().click();
    await page.waitForLoadState('domcontentloaded');
  }
  await goto(page, '/neu/pendenzen/');
  const karte = page.locator('.fw-lf-pendenzen').filter({ hasText: titel + ' A' });
  await expect(karte).toHaveCount(1);
  await expect(karte.locator('.fw-lf-spalten')).toBeVisible();
  const a = karte.locator('.fw-zeile').filter({ hasText: titel + ' A' });
  const b = karte.locator('.fw-zeile').filter({ hasText: titel + ' B' });
  // Die Fälligkeit beider Zeilen endet an derselben Kante (eine Spalte)
  const ra = await a.locator('.fw-zeit').evaluate((e) => Math.round(e.getBoundingClientRect().right));
  const rb = await b.locator('.fw-zeit').evaluate((e) => Math.round(e.getBoundingClientRect().right));
  expect(ra).toBe(rb);
  // Erledigen funktioniert weiter
  await a.locator('button[title="Als erledigt markieren"]').click();
  await page.waitForLoadState('domcontentloaded');
  await goto(page, '/neu/pendenzen/');
  await expect(page.locator('.fw-lf-pendenzen .fw-zeile .line-through', { hasText: titel + ' A' })).toBeVisible();
  // Telefon: kein Spaltenkopf, nichts quer
  await page.setViewportSize({ width: 390, height: 844 });
  await goto(page, '/neu/pendenzen/');
  await expect(page.locator('.fw-lf-pendenzen .fw-lf-spalten').first()).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await ctx.close();
});
