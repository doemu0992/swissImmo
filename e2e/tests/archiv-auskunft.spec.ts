import { test, expect, Page } from '@playwright/test';
import { login, goto } from './helpers';

// Etappe 2: Archiv statt Löschen und Auskunftsrecht (DSG Art. 25).
// Die Spec ändert keinen Seed-Zustand: Das Archiv ist leer, die Archivierung einer
// Liegenschaft mit laufendem Vertrag wird abgewiesen, und die Auskunft schreibt nur
// einen Eintrag ins Audit-Log.

async function ersterLink(page: Page, liste: string, muster: RegExp): Promise<string> {
  await goto(page, liste);
  const hrefs: string[] = await page.locator('a[href]').evaluateAll(
    (as) => as.map((a) => (a as HTMLAnchorElement).getAttribute('href') || ''));
  const treffer = hrefs.find((h) => muster.test(h));
  expect(treffer, `Kein Eintrag in ${liste}`).toBeTruthy();
  return treffer as string;
}

test('Das Archiv ist leer und sagt es', async ({ page }) => {
  await login(page);
  await goto(page, '/neu/archiv/');
  await expect(page.getByRole('heading', { name: 'Archiv' })).toBeVisible();
  await expect(page.locator('body')).toContainText('Das Archiv ist leer');
});

test('Eine Liegenschaft mit laufendem Vertrag lässt sich nicht archivieren', async ({ page }) => {
  await login(page);
  const href = await ersterLink(page, '/neu/liegenschaften/', /^\/neu\/liegenschaften\/\d+\/$/);
  await goto(page, href);
  await page.locator('main button[data-menu-btn], #fwMain button[data-menu-btn], button[data-menu-btn]').filter({ hasText: 'Mehr' }).last().click();
  await page.getByRole('button', { name: 'Archivieren' }).first().click();
  await expect(page.locator('body')).toContainText('Es laufen noch');
});

test('Die Auskunft zu einer Person ist ein ZIP-Download', async ({ page }) => {
  await login(page);
  const href = await ersterLink(page, '/neu/personen/', /^\/neu\/personen\/\d+\/$/);
  await goto(page, href);
  await page.locator('main button[data-menu-btn], #fwMain button[data-menu-btn], button[data-menu-btn]').filter({ hasText: 'Mehr' }).last().click();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Auskunft (DSG Art. 25)' }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^auskunft-person-\d+\.zip$/);
});
