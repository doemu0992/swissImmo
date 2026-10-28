import { test, expect, Page } from '@playwright/test';
import { login, goto, warteAufURL } from './helpers';

// MANDANT UND «ZULETZT GEÖFFNET» IM PROFILMENÜ — GEMESSEN IM BROWSER (28.10.2026)
//
// Beide standen nur in der Schublade `#fwSidebar`. Die ist ab 1024 px aus; am PC kam man an den Mandantenwechsel
// nicht heran. Jetzt stehen sie im Profilmenü `#fwProfil`, bei jeder Breite.
//
// Gemessen wird, was der Quelltext nicht verrät: dass die Schublade am PC wirklich aus ist (sonst bewiese der Test
// nichts), dass der Wechsel wirkt, dass das Menü bei 390 px im Bild bleibt und nicht quer scrollt, dass lange Namen mit
// Ellipse gekürzt werden und dass es im Dunkelmodus lesbar bleibt.
//
// Daten: `seed_e2e_mandanten` (Benutzer `e2e-zwei` mit zwei Organisationen, die zweite mit sehr langem Namen und einer
// eigenen Liegenschaft «Mandantenweg 7»). Der Benutzer `e2e` hat eine Organisation und sieht keinen Wechsel.

const ZWEITE_STRASSE = 'Mandantenweg 7';

async function loginAls(page: Page, name: string) {
  await goto(page, '/login/');
  await page.fill('input[name="username"]', name);
  await page.fill('input[name="password"]', 'e2e-pass');
  await Promise.all([warteAufURL(page, '**'), page.click('button[type="submit"], input[type="submit"]')]);
  await expect(page).not.toHaveURL(/\/login\//);
}

const profilOeffnen = async (page: Page) => {
  await page.locator('.fw-avatar-knopf').click();
  await expect(page.locator('#fwProfil')).toBeVisible();
};

/** Die erste Akte der Liegenschaftsliste öffnen (so merkt sich die Seite «Zuletzt geöffnet»); gibt Pfad und Titel zurück. */
async function ersteAkteOeffnen(page: Page): Promise<{ pfad: string; titel: string }> {
  await goto(page, '/neu/liegenschaften/');
  const pfad = await page.evaluate(() => {
    const a = Array.from(document.querySelectorAll('main a')).map((x) => (x as HTMLAnchorElement).getAttribute('href') || '')
      .find((h) => /^\/neu\/liegenschaften\/\d+\/$/.test(h));
    return a || '';
  });
  expect(pfad, 'Die Liste hat keine Akte').not.toBe('');
  await goto(page, pfad);
  const titel = await page.evaluate(() => {
    const h = document.querySelector('.fw-aktenkopf h1, .fw-phead h1, main h1');
    return (h?.textContent || '').replace(/\s+/g, ' ').trim();
  });
  expect(titel).not.toBe('');
  return { pfad, titel };
}

function leuchtdichte(farbe: string): number {
  const m = farbe.match(/(\d+(?:\.\d+)?)/g)!.slice(0, 3).map(Number).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
}
const kontrast = (a: string, b: string) => {
  const [x, y] = [leuchtdichte(a), leuchtdichte(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

/** Das Menü liegt im Bild und scrollt nicht quer; gibt die Zahlen zurück. */
async function menueMessen(page: Page, breite: number, hoehe: number) {
  const m = await page.evaluate(() => {
    const p = document.getElementById('fwProfil')!;
    const r = p.getBoundingClientRect();
    const de = document.documentElement;
    return {
      x: r.x, rechts: r.right, oben: r.y, unten: r.bottom, breite: r.width,
      scrollB: p.scrollWidth, clientB: p.clientWidth, scrollH: p.scrollHeight, clientH: p.clientHeight,
      seiteQuer: de.scrollWidth - de.clientWidth,
    };
  });
  expect(m.x, `Menü ragt links hinaus (${JSON.stringify(m)})`).toBeGreaterThanOrEqual(0);
  expect(m.rechts, `Menü ragt rechts hinaus (${JSON.stringify(m)})`).toBeLessThanOrEqual(breite);
  expect(m.unten, `Menü ragt unten hinaus (${JSON.stringify(m)})`).toBeLessThanOrEqual(hoehe);
  expect(m.scrollB, 'Das Menü scrollt quer').toBeLessThanOrEqual(m.clientB);
  expect(m.seiteQuer, 'Die Seite scrollt quer').toBeLessThanOrEqual(0);
  return m;
}

for (const [name, breite, hoehe, touch] of [['PC', 1280, 800, false], ['Telefon', 390, 844, true]] as const) {
  test.describe(`${name} ${breite} px: Mandant und «Zuletzt geöffnet» im Profilmenü`, () => {
    test.use({ viewport: { width: breite, height: hoehe }, hasTouch: touch });

    test('Wer in zwei Organisationen ist, wechselt den Mandanten im Profilmenü — und der Wechsel wirkt', async ({ page }) => {
      await loginAls(page, 'e2e-zwei');
      await goto(page, '/neu/liegenschaften/');
      expect(await page.content(), 'Ohne Wechsel gilt die älteste Organisation').not.toContain(ZWEITE_STRASSE);

      if (breite >= 1024) {
        // Ohne diese Zeile bewiese der Test nichts: Die Schublade ist am PC wirklich nicht erreichbar.
        await expect(page.locator('#fwSidebar')).toBeHidden();
        await expect(page.locator('#fwMandantWahl')).toBeHidden();
      }
      await profilOeffnen(page);
      const wahl = page.locator('#fwProfil #fwMandantWahlProfil');
      await expect(wahl).toBeVisible();
      await expect(page.locator('#fwProfil label[for="fwMandantWahlProfil"]')).toBeVisible();
      const optionen = await wahl.locator('option').evaluateAll((l) =>
        l.map((o) => ({ wert: (o as HTMLOptionElement).value, text: o.textContent || '', gewaehlt: (o as HTMLOptionElement).selected })));
      expect(optionen.length).toBe(2);
      expect(optionen[0].text).toContain('E2E Verwaltung AG');
      expect(optionen[0].gewaehlt).toBe(true);
      expect(optionen[1].gewaehlt).toBe(false);

      // Das Menü bleibt im Bild, auch mit dem langen Namen der zweiten Organisation
      const m = await menueMessen(page, breite, hoehe);
      console.log(`[${name}] Menü mit Mandant: ${JSON.stringify(m)}`);
      const feld = (await wahl.boundingBox())!;
      expect(feld.x).toBeGreaterThanOrEqual(m.x);
      expect(feld.x + feld.width, 'Die Auswahl ragt aus dem Menü').toBeLessThanOrEqual(m.rechts);
      expect(await wahl.evaluate((el) => getComputedStyle(el).textOverflow)).toBe('ellipsis');

      await Promise.all([
        warteAufURL(page, '**/neu/'),
        wahl.selectOption(optionen[1].wert),
      ]);
      await goto(page, '/neu/liegenschaften/');
      expect(await page.content(), 'Nach dem Wechsel gilt noch die erste Organisation').toContain(ZWEITE_STRASSE);
      await profilOeffnen(page);
      expect(await page.locator('#fwProfil #fwMandantWahlProfil').inputValue()).toBe(optionen[1].wert);
    });

    test('Wer in einer Organisation ist, sieht keinen Wechsel — «Zuletzt geöffnet» zeigt die eben besuchte Akte', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/');
      await profilOeffnen(page);
      await expect(page.locator('#fwMandantWahlProfil'), 'Ein Wechsel ohne Wahl').toHaveCount(0);
      await expect(page.locator('#fwZuletztProfilAbschnitt'), 'Ohne Einträge keine leere Überschrift').toBeHidden();
      await page.keyboard.press('Escape');
      await expect(page.locator('#fwProfil')).toBeHidden();

      const akte = await ersteAkteOeffnen(page);
      await goto(page, '/neu/');
      await profilOeffnen(page);
      await expect(page.locator('#fwZuletztProfilAbschnitt')).toBeVisible();
      const eintraege = page.locator('#fwZuletztProfil a');
      await expect(eintraege.first()).toBeVisible();
      expect(await eintraege.first().getAttribute('href')).toBe(akte.pfad);
      expect((await eintraege.first().innerText()).replace(/\s+/g, ' ')).toContain(akte.titel);
      await menueMessen(page, breite, hoehe);

      // Der Eintrag führt dorthin
      await Promise.all([warteAufURL(page, `**${akte.pfad}`), eintraege.first().click()]);

      // Esc schliesst das Menü
      await profilOeffnen(page);
      await page.keyboard.press('Escape');
      await expect(page.locator('#fwProfil')).toBeHidden();
    });

    test('Die Liste hat höchstens drei Einträge, lange Titel werden gekürzt, nichts scrollt quer', async ({ page }) => {
      await login(page);
      await goto(page, '/neu/');
      const lang = 'Sehr lange Bezeichnung einer Liegenschaft an der Hauptstrasse mit Nebengebäude und Einstellhalle';
      await page.evaluate((l) => localStorage.setItem('fw-zuletzt', JSON.stringify([
        { h: '/neu/vertraege/9001/', l: `${l} 1` }, { h: '/neu/vertraege/9002/', l: `${l} 2` }, { h: '/neu/vertraege/9003/', l: `${l} 3` }])), lang);
      const akte = await ersteAkteOeffnen(page); // der vierte Eintrag verdrängt den ältesten
      await goto(page, '/neu/');
      await profilOeffnen(page);

      const eintraege = page.locator('#fwZuletztProfil a');
      await expect(eintraege).toHaveCount(3);
      expect(await eintraege.first().getAttribute('href')).toBe(akte.pfad);
      expect(await page.locator('#fwZuletzt a').count(), 'Schublade und Profilmenü zeigen dieselbe Liste').toBe(3);
      const m = await menueMessen(page, breite, hoehe);
      console.log(`[${name}] Menü ohne Mandant, mit drei Einträgen: ${JSON.stringify(m)}`);

      const gekuerzt = await page.locator('#fwZuletztProfil a .truncate').evaluateAll((l) =>
        l.map((el) => ({ ellipse: getComputedStyle(el).textOverflow, abgeschnitten: el.scrollWidth > el.clientWidth })));
      expect(gekuerzt[1], 'Ein langer Titel wird nicht gekürzt').toEqual({ ellipse: 'ellipsis', abgeschnitten: true });
      for (const a of await eintraege.all()) {
        const b = (await a.boundingBox())!;
        expect(b.x + b.width, 'Ein Eintrag ragt aus dem Menü').toBeLessThanOrEqual(m.rechts);
      }
    });

    test('Dunkelmodus: Auswahl und Liste bleiben lesbar', async ({ page }) => {
      await loginAls(page, 'e2e-zwei');
      await page.evaluate(() => localStorage.setItem('fw-zuletzt', JSON.stringify([{ h: '/neu/vertraege/9001/', l: 'Dunkeltest Vertrag' }])));
      await goto(page, '/neu/');
      await page.evaluate(() => (window as any).fwSetTheme('dark'));
      await profilOeffnen(page);
      const f = await page.evaluate(() => {
        const p = document.getElementById('fwProfil')!;
        const s = document.getElementById('fwMandantWahlProfil')!;
        const e = document.querySelector('#fwZuletztProfil a .truncate')!;
        const t = document.querySelector('#fwProfil .fw-profil-titel')!;
        const c = (el: Element) => getComputedStyle(el);
        return { grund: c(p).backgroundColor, selGrund: c(s).backgroundColor, selSchrift: c(s).color,
                 eintrag: c(e).color, titel: c(t).color };
      });
      expect(leuchtdichte(f.grund), `Das Menü ist im Dunkeln hell: ${f.grund}`).toBeLessThan(0.2);
      expect(leuchtdichte(f.selGrund), `Die Auswahl ist im Dunkeln hell: ${f.selGrund}`).toBeLessThan(0.2);
      expect(kontrast(f.selSchrift, f.selGrund), 'Auswahl: Schrift zu schwach').toBeGreaterThanOrEqual(4.5);
      expect(kontrast(f.eintrag, f.grund), 'Eintrag: Schrift zu schwach').toBeGreaterThanOrEqual(4.5);
      expect(kontrast(f.titel, f.grund), 'Überschrift: Schrift zu schwach').toBeGreaterThanOrEqual(3);
      await menueMessen(page, breite, hoehe);
    });
  });
}
