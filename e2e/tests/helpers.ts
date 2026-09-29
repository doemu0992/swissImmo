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

// Rückfrage bestätigen. Seit dem gestalteten Bestätigungsdialog
// (fw/_bestaetigen.html) erscheint statt `confirm()` ein <dialog> der App —
// `page.on('dialog', d => d.accept())` greift dort nicht mehr. Wie ein Mensch:
// im Dialog auf «Bestätigen» klicken.
//
// Das Absenden beginnt erst nach dem `close`-Ereignis des Dialogs, also einen
// Takt NACH dem Klick. Ohne zu warten liefe ein folgendes `warteAufURL` sofort
// durch (die Adresse passt schon) und ein `goto` bräche die laufende
// Absendung ab (net::ERR_ABORTED — so in der CI gesehen). Deshalb wartet die
// Hilfe, bis die ausgelöste Navigation geladen ist. `navigation: false` für
// Rückfragen, die keine Seite laden (z. B. PDF in neuem Tab).
export async function bestaetigen(page: Page, { navigation = true } = {}) {
  const dialog = page.locator('#fwBestaetigen');
  await dialog.waitFor({ state: 'visible' });
  const geladen = navigation
    ? page.waitForEvent('framenavigated', (f) => f === page.mainFrame())
    : Promise.resolve(null);
  await dialog.locator('#fwBestaetigenJa').click();
  await geladen;
  if (navigation) await page.waitForLoadState('domcontentloaded');
}
