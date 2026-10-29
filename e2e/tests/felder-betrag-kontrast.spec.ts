import { test, expect, Page } from '@playwright/test';
import { goto, login, imAssistent } from './helpers';

// FELDNAMEN, BETRAGSFELD, KONTRAST (29.10.2026, DESIGN-10/11/27/28)
//
// Telefon (390 x 844), wo die Seite lebt. Geprüft wird im Browser:
//   * dass ein Feld seinen Namen von der Beschriftung bekommt (`getByLabel`) und ein Klick auf die
//     Beschriftung den Fokus ins Feld setzt,
//   * dass das Betragsfeld «1'450.50» schreibt, «1450,5» und «CHF 12'500» versteht und Unsinn meldet,
//   * dass weisser Text auf der orangen Hauptkarte AA erreicht (Pixelprobe hinter dem Text, hell und dunkel).
// Nichts davon speichert oder belegt ein Objekt des E2E-Bestands.

test.use({ viewport: { width: 390, height: 844 } });

async function keinQuerscrollen(page: Page, wo: string) {
  const quer = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(quer, `${wo}: die Seite scrollt ${quer} px quer`).toBeLessThanOrEqual(0);
}

test.describe('Feldnamen', () => {
  test('Ein Feld heisst wie seine Beschriftung, und ein Klick auf die Beschriftung fokussiert es', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/personen/');
    const id = await page.locator('a[href^="/neu/personen/"]').evaluateAll((a) =>
      (a as HTMLAnchorElement[]).map((x) => (x.getAttribute('href') || '').match(/personen\/(\d+)\//)).find(Boolean)?.[1]);
    expect(id, 'Seed: keine Person').toBeTruthy();
    await goto(page, `/neu/personen/${id}/bearbeiten/`);
    const anrede = page.getByRole('combobox', { name: 'Anrede' });
    await expect(anrede).toHaveCount(1);
    await page.locator('label', { hasText: /^Anrede$/ }).first().click();
    await expect(anrede).toBeFocused();
    await keinQuerscrollen(page, 'Person bearbeiten');
  });

  test('Auswahl des Jahres im Kontenplan hat einen Namen', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/kontenplan/');
    await expect(page.getByRole('combobox', { name: 'Jahr' })).toBeVisible();
  });

  test('Kein Feld einer Seite ist ohne Namen (Stichprobe über die Hauptseiten)', async ({ page }) => {
    await login(page);
    for (const url of ['/neu/liegenschaften/', '/neu/vertraege/', '/neu/debitoren/', '/neu/kreditoren/', '/neu/mahnwesen/',
      '/neu/personen/', '/neu/objekte/', '/neu/buchhaltung/', '/neu/mwst/', '/neu/schaeden/', '/neu/einstellungen/']) {
      await goto(page, url);
      const ohne = await page.evaluate(() => {
        const felder = Array.from(document.querySelectorAll('input, select, textarea')) as HTMLInputElement[];
        return felder.filter((f) => !['hidden', 'submit', 'button', 'reset', 'image'].includes(f.type) && !f.hidden
          && !f.closest('[hidden], template')
          && !((f.labels && f.labels.length) || f.getAttribute('aria-label') || f.getAttribute('aria-labelledby') || f.title))
          .map((f) => `${f.tagName.toLowerCase()}[${f.name}]`);
      });
      expect(ohne, `${url}: Felder ohne Namen`).toEqual([]);
    }
  });
});

test.describe('Betragsfeld', () => {
  test('Der Vertragsassistent schreibt «1\'450.50», versteht Komma und Währung und meldet Unsinn', async ({ page }) => {
    await login(page);
    await goto(page, '/neu/vertraege/neu/');
    const lg = await page.$$eval('#s_lg option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
    await page.selectOption('#s_lg', lg[0]);
    const ob = await page.evaluate(() => {
      const d = JSON.parse(document.getElementById('lg-data')!.textContent!);
      const l = d.find((x: any) => String(x.id) === (document.getElementById('s_lg') as HTMLSelectElement).value);
      return l.objekte.filter((o: any) => !o.ist_einstellplatz).map((o: any) => String(o.id));
    });
    await page.selectOption('#s_obj', ob[0]);
    await page.locator('#btn-next').click();
    const mieter = await page.$$eval('#s_mieter option', (o) => (o as HTMLOptionElement[]).map((x) => x.value).filter(Boolean));
    await page.selectOption('#s_mieter', mieter[0]);
    await page.locator('#btn-next').click();
    await page.fill('#s_beginn', '2026-12-01');
    await page.locator('#btn-next').click();

    const netto = await imAssistent(page, '#s_netto');
    await expect(netto).toHaveAttribute('type', 'text');
    await netto.fill('1450,5');
    await netto.blur();
    await expect(netto).toHaveValue("1'450.50");

    await netto.fill("CHF 12'500");
    await netto.blur();
    await expect(netto).toHaveValue("12'500.00");

    await netto.fill('abc');
    await netto.blur();
    await expect(netto).toHaveAttribute('aria-invalid', 'true');

    // Die Kaution rechnet mit dem Wert, den das Feld zeigt («1'500.00»), nicht mit «1».
    await netto.fill("1'500.00");
    await netto.blur();
    const kaution = await imAssistent(page, '#s_kaution');
    await page.locator('button[onclick="kautionSet(3)"]').click();
    await expect(kaution).toHaveValue("4'500.00");
    await keinQuerscrollen(page, 'Vertragsassistent');
  });
});

/** Kleinster Kontrast (weisse Schrift) über die Pixel hinter dem Text einer Karte. */
async function kontrastHinterText(page: Page, selektor: string) {
  const karte = page.locator(selektor).first();
  await karte.scrollIntoViewIfNeeded();
  await page.evaluate((s) => {
    const k = document.querySelector(s)!;
    (window as any).__alt = [];
    k.querySelectorAll('*').forEach((a) => {
      const e = a as HTMLElement;
      const cs = getComputedStyle(e);
      const eigenerGrund = cs.backgroundImage !== 'none' || !/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor);
      // Kinder mit eigenem Grund (der weisse Knopf «Erledigen») sind eine andere Farbpaarung: ausblenden,
      // damit der Grund DER KARTE darunter gemessen wird. Alles andere: nur die Schrift unsichtbar machen.
      (window as any).__alt.push([e, e.style.color, e.style.visibility]);
      if (eigenerGrund) e.style.setProperty('visibility', 'hidden', 'important');
      else e.style.setProperty('color', 'transparent', 'important');
    });
    (k as HTMLElement).style.setProperty('color', 'transparent', 'important');
    k.querySelectorAll('svg').forEach((v) => (v as SVGElement).style.setProperty('visibility', 'hidden'));
  }, selektor);
  const png = await karte.screenshot();
  const minK = await page.evaluate(async (b64) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + b64;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const g = c.getContext('2d')!;
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    const lum = (r: number, gg: number, b: number) => {
      const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(r) + 0.7152 * f(gg) + 0.0722 * f(b);
    };
    let min = 99;
    const lw = lum(255, 255, 255);
    // Ränder (abgerundete Ecken, Schatten) auslassen: nur das Innere der Karte zählt.
    const rand = Math.round(Math.min(c.width, c.height) * 0.12);
    for (let y = rand; y < c.height - rand; y += 3) {
      for (let x = rand; x < c.width - rand; x += 3) {
        const i = (y * c.width + x) * 4;
        const lb = lum(d[i], d[i + 1], d[i + 2]);
        min = Math.min(min, (lw + 0.05) / (lb + 0.05));
      }
    }
    return min;
  }, png.toString('base64'));
  await page.evaluate(() => {
    ((window as any).__alt || []).forEach(([e, c, v]: [HTMLElement, string, string]) => {
      e.style.removeProperty('color'); if (c) e.style.color = c;
      e.style.removeProperty('visibility'); if (v) e.style.visibility = v;
    });
  });
  return minK;
}

for (const theme of ['light', 'dark'] as const) {
  test.describe(`Kontrast der orangen Hauptkarte (${theme})`, () => {
    test.use({ colorScheme: theme });

    test('Weisse Schrift erreicht 4.5:1 auf jedem Pixel der Karte', async ({ page }) => {
      await page.addInitScript((t) => { try { localStorage.setItem('fw-theme', t); } catch (e) { /* ohne Speicher */ } }, theme);
      await login(page);
      await goto(page, '/neu/');
      const k = await kontrastHinterText(page, '.fw-kachel.akzent');
      expect(k, `kleinster Kontrast Weiss/Karte: ${k.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
      await goto(page, '/neu/debitoren/');
      const kpi = await kontrastHinterText(page, '.fw-kpis:not(.fw-stats) > .fw-kpi.fw-accent');
      expect(kpi, `kleinster Kontrast Weiss/Kennzahlkarte: ${kpi.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
    });
  });
}
