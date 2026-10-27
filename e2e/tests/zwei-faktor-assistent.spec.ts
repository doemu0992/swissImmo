import { test, expect, Page } from '@playwright/test';
import { createHmac } from 'crypto';
import { goto, login } from './helpers';

// 2FA-Einrichtung im Assistenten-Standard (27.10.2026, server-seitige Variante):
// Code scannen → Code bestätigen → Notfallcodes. Jeder Schritt hat eine Adresse, die Notfallcodes
// erscheinen nur als Antwort auf das richtige POST. Der Test richtet den zweiten Faktor wirklich
// ein (mit einem Code aus dem Geheimnis auf der Seite) und schaltet ihn am Ende wieder ab, damit
// der Lauf wiederholbar ist.
// Am Telefon scrollt nur die Leiste waagrecht, die Seite nie; der Fuss bleibt im Bild.

const BREITEN = [
  { name: 'Desktop', viewport: { width: 1280, height: 900 } },
  { name: 'Telefon', viewport: { width: 390, height: 844 } },
];

const EINRICHTEN = '/konto/zwei-faktor/einrichten/';

// TOTP nach RFC 6238 (SHA-1, 6 Stellen, 30 s) — dieselbe Rechnung wie core/services/totp.py.
function base32(s: string): Buffer {
  const A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const c of s.replace(/=+$/, '').toUpperCase()) bits += A.indexOf(c).toString(2).padStart(5, '0');
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}
function totp(geheimnis: string): string {
  const zaehler = Buffer.alloc(8);
  zaehler.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const h = createHmac('sha1', base32(geheimnis)).update(zaehler).digest();
  const o = h[h.length - 1] & 0x0f;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, '0');
}

async function keinQuerscrollen(page: Page) {
  const [breit, sicht] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(breit, 'Die Seite scrollt quer').toBeLessThanOrEqual(sicht);
}

// Der Fuss klebt unten im Bild und ragt weder links noch rechts hinaus.
async function fussImBild(page: Page) {
  const r = await page.locator('.fw-assistent-fuss').boundingBox();
  const v = page.viewportSize()!;
  expect(r, 'Fuss fehlt').not.toBeNull();
  expect(r!.x).toBeGreaterThanOrEqual(0);
  expect(r!.x + r!.width).toBeLessThanOrEqual(v.width);
}

async function tokenFarbe(page: Page, token: string) {
  return page.evaluate((t) => {
    const e = document.createElement('i');
    e.style.background = `var(${t})`;
    document.body.appendChild(e);
    const f = getComputedStyle(e).backgroundColor;
    e.remove();
    return f;
  }, token);
}

for (const b of BREITEN) {
  test.describe(b.name, () => {
    test.use({ viewport: b.viewport });

    test('Durch die drei Schritte: scannen, bestätigen, Notfallcodes', async ({ page }) => {
      await login(page);
      await goto(page, EINRICHTEN);

      // Schritt 1: Leiste mit drei Schritten, der dritte gesperrt, überall «1 von 3».
      const leiste = page.locator('.fw-assistent.an .fw-assistent-leiste');
      await expect(leiste.locator('li')).toHaveCount(3);
      await expect(leiste.locator('li.hier')).toContainText('Code scannen');
      await expect(leiste.locator('li.gesperrt')).toHaveCount(1);
      await expect(leiste.locator('li.gesperrt a')).toHaveCount(0);
      await expect(page.locator('.fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 1 von 3/i);
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 1 von 3');
      await expect(page.locator('.fw-assistent-fuss').getByRole('link', { name: 'Abbrechen' })).toHaveAttribute('href', /\/konto\/zwei-faktor\/$/);
      await expect(page.locator('.fw-zf-qr svg')).toBeVisible();
      const geheimnis = (await page.locator('.fw-zf-geheimnis').innerText()).trim();
      expect(geheimnis).toMatch(/^[A-Z2-7]{32}$/);
      // Das QR-Feld ist 200 px breit und bricht den Schlüssel am Telefon unter sich um.
      const qr = await page.locator('.fw-zf-qr').boundingBox();
      expect(Math.round(qr!.width)).toBe(200);
      const schluessel = await page.locator('.fw-zf-geheimnis').boundingBox();
      expect(schluessel!.x + schluessel!.width).toBeLessThanOrEqual(b.viewport.width);
      await keinQuerscrollen(page);
      await fussImBild(page);

      // Schritt 2: nur das Codefeld, Schlüssel und QR stehen nicht mehr auf der Seite.
      await page.locator('.fw-assistent-fuss a.fw-primary').click();
      await page.waitForURL(/schritt=2$/, { waitUntil: 'domcontentloaded' });
      await expect(leiste.locator('li.hier')).toContainText('Code bestätigen');
      await expect(leiste.locator('li.fertig .nr')).toHaveText('✓');
      await expect(page.locator('.fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 2 von 3/i);
      await expect(page.locator('.fw-zf-qr')).toHaveCount(0);
      await expect(page.locator('main')).not.toContainText(geheimnis);
      await expect(page.locator('#zf-code-feld')).toBeVisible();
      await keinQuerscrollen(page);
      await fussImBild(page);

      // Falscher Code: bleibt in Schritt 2, meldet es, nichts ist aktiv.
      await page.fill('#zf-code-feld', '000000');
      await page.locator('.fw-assistent-fuss button[form="zf-code"]').click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('[role="alert"]')).toContainText('Der Code stimmt nicht');
      await expect(leiste.locator('li.hier')).toContainText('Code bestätigen');
      await keinQuerscrollen(page);

      // Richtiger Code → Schritt 3: zehn Codes, keine Rückwege.
      await page.fill('#zf-code-feld', totp(geheimnis));
      await page.locator('.fw-assistent-fuss button[form="zf-code"]').click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('.fw-assistent-schritt-kopf h2')).toHaveText('Notfallcodes');
      await expect(page.locator('.fw-assistent-schritt-kopf .fw-ueber')).toHaveText(/Schritt 3 von 3/i);
      await expect(page.locator('.fw-assistent-fuss .stand')).toHaveText('Schritt 3 von 3');
      await expect(page.locator('.fw-zf-codes .fw-feld')).toHaveCount(10);
      await expect(leiste.locator('li.fertig')).toHaveCount(2);
      await expect(leiste.locator('a')).toHaveCount(0);
      await expect(page.locator('.fw-assistent-fuss').getByRole('link', { name: 'Abbrechen' })).toHaveCount(0);
      await expect(page.locator('.fw-assistent-fuss').getByRole('button', { name: /Zurück/ })).toBeDisabled();
      // Die Codes stehen im Bild, auch am Telefon (zwei Spalten, kein Überlauf).
      for (const feld of await page.locator('.fw-zf-codes .fw-feld').all()) {
        const r = await feld.boundingBox();
        expect(r!.x + r!.width).toBeLessThanOrEqual(b.viewport.width);
      }
      // Farben des Standards: erledigt im Akzent, aktuell schwarz.
      const hg = (sel: string) => page.locator(`.fw-assistent-leiste ${sel} .nr`).first().evaluate((e) => getComputedStyle(e).backgroundColor);
      expect(await hg('li.fertig')).toBe(await tokenFarbe(page, '--ds-akzent'));
      expect(await hg('li.hier')).toBe(await tokenFarbe(page, '--ds-ink'));
      await keinQuerscrollen(page);
      await fussImBild(page);

      // Fertig: die Übersicht zeigt «Aktiv»; die Einrichtung führt jetzt dorthin zurück.
      await page.getByRole('link', { name: 'Ich habe sie gesichert' }).click();
      await page.waitForURL(/\/konto\/zwei-faktor\/$/, { waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('heading', { name: 'Aktiv' })).toBeVisible();
      await goto(page, EINRICHTEN);
      await expect(page).toHaveURL(/\/konto\/zwei-faktor\/$/);

      // Aufräumen: abschalten (verlangt das Passwort), damit der Lauf wiederholbar bleibt.
      await page.fill('input[name="password"]', 'e2e-pass');
      await page.getByRole('button', { name: 'Abschalten' }).click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page.getByRole('link', { name: 'Jetzt einrichten' })).toBeVisible();
    });
  });
}
