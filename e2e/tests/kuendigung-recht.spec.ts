import { test, expect } from '@playwright/test';
import { login, goto, warteAufURL } from './helpers';

// Etappe 1 Recht (G): Zahlungsverzug und Kündigung.
//  · Art. 257d OR: Fristansetzung — Zugang nach Abholung / letzter Tag der Abholfrist (BGE 119 II 147),
//    nur Mietzins und Nebenkosten im Rückstand, Hinweis «eigenhändig unterschreiben».
//  · Art. 271a OR: ein erfasstes Verfahren sperrt die Vermieterkündigung bis zur ausdrücklichen Ausnahme.
// Seed: Vertrag 1 mit der offenen Miete «E2E offene Miete» (seed_e2e).

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('Fristansetzung nennt Abholfrist, Rückstand und die eigenhändige Unterschrift', async ({ page }) => {
  const resp = await page.goto('/neu/vertraege/1/verzug/', { waitUntil: 'domcontentloaded' });
  expect(resp?.status()).toBeLessThan(400);
  await expect(page.locator('body')).toContainText('Offene, fällige Mietzinse und Nebenkosten');
  await expect(page.locator('body')).toContainText('nicht ab der Abholeinladung');
  await expect(page.locator('#unterschrift-hinweis')).toContainText('Eigenhändig unterschreiben');
  await expect(page.locator('#unterschrift-hinweis')).toContainText('kein Unterschriftsbild');
  await expect(page.locator('body')).not.toContainText(/Traceback|TemplateSyntaxError|OperationalError/);
});

test('Verfahren erfassen sperrt die Vermieterkündigung, Abschluss gibt sie wieder frei', async ({ page }) => {
  await goto(page, '/neu/vertraege/1/verfahren/');
  await expect(page.locator('h1')).toContainText('Art. 271a');

  await page.selectOption('#vf_art', 'schlichtung');
  await page.selectOption('#vf_gegenstand', 'mietzins');
  await page.fill('#vf_az', 'SB 1/26');
  // Eingeleitet in der Vergangenheit, damit der Abschluss unten die Sperre vollständig aufhebt (am Abschlusstag
  // selbst gilt das Verfahren noch als hängig gewesen).
  await page.fill('#vf_beginn', '2020-01-01');
  await Promise.all([
    warteAufURL(page, '**/verfahren/'),
    page.getByRole('button', { name: 'Erfassen' }).click(),
  ]);
  await expect(page.locator('body')).toContainText('SB 1/26');
  await expect(page.locator('body')).toContainText('Heute gesperrt');

  // Die Kündigungsmaske zeigt die Sperre und das Kästchen für die Ausnahme (nur beim Vermieter).
  await goto(page, '/neu/vertraege/1/kuendigen/');
  await expect(page.locator('#sperrfrist-box')).toBeHidden();
  await page.selectOption('#s_absender', 'vermieter');
  await expect(page.locator('#sperrfrist-box')).toBeVisible();
  await expect(page.locator('#sperrfrist-box')).toContainText('Art. 271a');
  await expect(page.locator('input[name="sperrfrist_ausnahme"]')).toBeVisible();

  // Aufräumen: Verfahren abschliessen (Mieter unterlegen: keine Nachfrist), damit andere Specs unberührt bleiben.
  await goto(page, '/neu/vertraege/1/verfahren/');
  await page.locator('select[name="ausgang"]').first().selectOption('mieter_unterlegen');
  await page.locator('input[name="abgeschlossen_am"]').first().fill('2020-02-01');
  await Promise.all([
    warteAufURL(page, '**/verfahren/'),
    page.getByRole('button', { name: 'Verfahren abschliessen' }).first().click(),
  ]);
  await expect(page.locator('body')).not.toContainText('Heute gesperrt');
});
