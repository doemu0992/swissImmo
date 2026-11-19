import { test, expect } from '@playwright/test';
import { login, goto } from './helpers';

// UI-Zielbild Phase 0: Die Sortierung einer Liste wirkt sofort, «Anwenden» entfällt (nur ohne Skript bleibt der Knopf).
test.describe('Listenwerkzeug', () => {
  test('Mit Skript: kein «Anwenden», die Auswahl sortiert sofort, Enter sucht', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/liegenschaften/');
    const werkzeug = page.locator('#fw-inhalt form.fw-listwerkzeug').first();
    await expect(werkzeug.locator('button[type="submit"]')).toBeHidden();
    const sort = werkzeug.locator('select[name="sort"]');
    const optionen = await sort.locator('option').evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
    const aktuell = await sort.inputValue();
    const andere = optionen.find((v) => v !== aktuell)!;       // eine andere Sortierung als die gewählte
    await Promise.all([page.waitForURL(new RegExp('sort=' + andere)), sort.selectOption(andere)]);
    const suche = page.locator('#fw-inhalt form.fw-listwerkzeug input[type="search"]').first();
    await suche.fill('Zzzzunbekannt');
    await Promise.all([page.waitForURL(/suche=Zzzzunbekannt/), suche.press('Enter')]);
  });
});

test.describe('Listenwerkzeug ohne Skript', () => {
  test.use({ javaScriptEnabled: false });
  test('der Knopf «Anwenden» bleibt sichtbar', async ({ page }) => {
    await page.goto('/login/');
    await page.fill('input[name="username"]', 'e2e');
    await page.fill('input[name="password"]', 'e2e-pass');
    await Promise.all([page.waitForURL('**/neu/**'), page.click('button[type="submit"], input[type="submit"]')]);
    await page.goto('/neu/liegenschaften/');
    await expect(page.locator('#fw-inhalt form.fw-listwerkzeug button[type="submit"]').first()).toBeVisible();
  });
});
