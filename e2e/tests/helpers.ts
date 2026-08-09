import { Page, expect } from '@playwright/test';

// Die Seiten referenzieren externe CDN-Assets (Tailwind/FontAwesome/Fonts), die
// der Egress-Proxy blockt. Mit `waitUntil: 'load'` würde jede Navigation ~26 s
// auf deren Timeout warten. `domcontentloaded` reicht für unsere DOM-Assertions
// und macht die Tests schnell + stabil.
export async function goto(page: Page, url: string) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
}

export async function warteAufURL(page: Page, glob: string) {
  await page.waitForURL(glob, { waitUntil: 'domcontentloaded' });
}

/** Loggt den deterministischen E2E-Verwaltungs-Nutzer ein (siehe seed_e2e). */
export async function login(page: Page) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', 'e2e');
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([
    warteAufURL(page, '**'),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  await expect(page).not.toHaveURL(/\/login\//);
}
