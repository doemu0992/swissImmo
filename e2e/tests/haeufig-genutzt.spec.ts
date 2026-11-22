import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild: «Häufig genutzt» ist eine feste Liste mit drei Einträgen und verschwindet während der Suche.
for (const [seite, suche] of [['/neu/berichte/', '#berichtSuche'], ['/neu/einstellungen/', '#fwEinstSuche']]) {
  test(`Häufig genutzt (${seite}): drei Einträge, bei der Suche verborgen`, async ({ page }) => {
    await login(page);
    await goto(page, seite);
    const block = page.locator('[data-haeufig]');
    await expect(block).toBeVisible();
    await expect(block.getByText('Häufig genutzt')).toBeVisible();
    await expect(block.locator('a')).toHaveCount(3);
    await page.locator(suche).fill('a');
    await expect(block).toBeHidden();
    await page.locator(suche).fill('');
    await expect(block).toBeVisible();
  });
}
