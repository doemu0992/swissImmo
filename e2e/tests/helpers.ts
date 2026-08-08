import { Page, expect } from '@playwright/test';

/** Loggt den deterministischen E2E-Verwaltungs-Nutzer ein (siehe seed_e2e). */
export async function login(page: Page) {
  await page.goto('/login/');
  await page.fill('input[name="username"]', 'e2e');
  await page.fill('input[name="password"]', 'e2e-pass');
  await page.click('button[type="submit"], input[type="submit"]');
  // Nach dem Login landet man auf /nach-login/ bzw. dem Dashboard — auf keinen
  // Fall mehr auf der Login-Seite.
  await expect(page).not.toHaveURL(/\/login\//);
}
