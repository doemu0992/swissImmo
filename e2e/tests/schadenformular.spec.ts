import { test, expect } from '@playwright/test';

// Das öffentliche Schadenformular — die Seite vom Aushang im Treppenhaus.
//
// WARUM DAS IM BROWSER GEPRÜFT WIRD UND NICHT IM QUELLTEXT
//
// Die Raumkacheln zeichnen ihr Symbol über `<use :href="'#z-' + r.z">`. Das
// setzt ALPINE zur Laufzeit — ein Django-Test sieht davon nichts, und der
// erste Entwurf von E2.51 schrieb dort `{% zeichen_wert r.z %}`, was nie
// funktionieren konnte: Django rendert auf dem Server, `r` entsteht erst im
// Browser. Der Baustein bekam eine leere Zeichenkette und fiel auf `hinweis`
// zurück — zwölfmal dasselbe Symbol, also genau der Zustand, den die Etappe
// beheben sollte. Auffallen konnte das nur beim Hinsehen.
//
// Dasselbe gilt für die Auswahl je Raum: Sie entsteht in `getCurrentObjects()`
// aus zwei Listen. Ob dabei etwas Sinnvolles herauskommt, steht in keiner
// Vorlage — es muss ausgerechnet werden.
//
// DER FEHLER, DEN DAS HIER FESTHÄLT
//
// Bis E2.51 hing `standardItems` an JEDEM Raum: Ein Briefkasten bot «Licht,
// Steckdose, Fenster, Storen/Markise, Boden, Wand, Decke». Wer «Decke» am
// Briefkasten meldet, schickt einen Handwerker zu etwas, das es nicht gibt.
// Sieben von zwölf Räumen hatten ausserdem gar keine eigene Liste.

/** Wartet den Ladevorhang ab (Notausgang nach 3 s) und gibt die Alpine-Daten. */
async function formular(page: import('@playwright/test').Page) {
  await page.goto('/report/1/', { waitUntil: 'load' });
  await page.waitForTimeout(3500);
  return page.evaluate(() => {
    // @ts-expect-error Alpine ist global, aber nicht typisiert.
    const w = Alpine.$data(document.querySelector('[x-data]'));
    const je: Record<string, string[]> = {};
    for (const r of w.rooms) {
      w.room = r.name;
      je[r.name] = w.getCurrentObjects().map((o: { name: string }) => o.name);
    }
    return {
      raeume: w.rooms.map((r: { name: string; z: string }) => ({ name: r.name, z: r.z })),
      eigene: Object.keys(w.objectMap),
      auswahl: je,
    };
  });
}

test('Jeder Raum trägt ein eigenes, auflösbares Zeichen', async ({ page }) => {
  await page.goto('/report/1/', { waitUntil: 'load' });
  await page.waitForTimeout(3500);
  await page.locator('text=Schadensmeldung').first().click();
  await page.waitForTimeout(400);

  const kacheln = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.icon-card'))
      .filter((k) => (k as HTMLElement).offsetParent)
      .map((k) => {
        const u = k.querySelector('use');
        const verweis = u?.getAttribute('href') || '';
        return {
          name: (k as HTMLElement).innerText.trim(),
          verweis,
          aufgeloest: !!(verweis && document.querySelector(verweis)),
        };
      }),
  );

  expect(kacheln.length, 'Keine Raumkacheln gefunden').toBeGreaterThan(5);

  const tot = kacheln.filter((k) => !k.aufgeloest);
  expect(
    tot.map((k) => `${k.name} → «${k.verweis}»`),
    'Diese Kacheln verweisen auf ein Symbol, das es im Sprite nicht gibt. Sie ' +
      'zeichnen NICHTS und melden das auch nicht — ein Tippfehler in `r.z` ' +
      'bleibt sonst unsichtbar.',
  ).toEqual([]);

  // Zwölf gleiche Zeichen wären so gut wie keine — das war der Zustand vor
  // E2.51, und der Sinn der Übung ist, dass das Auge sie unterscheidet.
  const verschieden = new Set(kacheln.map((k) => k.verweis));
  expect(
    verschieden.size,
    `Nur ${verschieden.size} verschiedene Zeichen auf ${kacheln.length} Kacheln.`,
  ).toBe(kacheln.length);
});

test('Kein Raum bietet an, was es dort nicht gibt', async ({ page }) => {
  const { raeume, eigene, auswahl } = await formular(page);

  // 1. Jeder Raum hat eine EIGENE Liste. Fehlt sie, fällt der Raum auf die
  //    allgemeinen Posten zurück — genau der Briefkasten-Fall.
  const ohne = raeume.map((r) => r.name).filter((n) => !eigene.includes(n));
  expect(
    ohne,
    'Diese Räume haben keinen Eintrag in `objectMap` und fallen auf die ' +
      'allgemeinen Posten zurück. Vor E2.51 waren das sieben von zwölf.',
  ).toEqual([]);

  // 2. Nichts doppelt. `Sonnenstore` neben `Storen/Markise` war so ein Fall.
  for (const [raum, posten] of Object.entries(auswahl)) {
    const doppelt = posten.filter((p, i) => posten.indexOf(p) !== i);
    expect(doppelt, `${raum} bietet doppelt an: ${doppelt.join(', ')}`).toEqual([]);
  }

  // 3. Der Briefkasten ist die Probe aufs Exempel: Er hat weder Decke noch
  //    Boden noch Fenster. Bleibt er sauber, greift die Trennung.
  const briefkasten = auswahl['Briefkasten'] || [];
  expect(briefkasten.length, 'Briefkasten ohne jede Auswahl').toBeGreaterThan(0);
  for (const unmoeglich of ['Decke', 'Boden', 'Fenster', 'Storen/Markise', 'Wand']) {
    expect(
      briefkasten,
      `Briefkasten bietet «${unmoeglich}» an — das gibt es dort nicht.`,
    ).not.toContain(unmoeglich);
  }

  // 4. Aussenbereiche haben keine Decke.
  for (const raum of ['Balkon/Terrasse']) {
    expect(auswahl[raum], `${raum} hat keine Decke`).not.toContain('Decke');
  }

  // 5. Und jeder Raum bietet überhaupt etwas an.
  for (const [raum, posten] of Object.entries(auswahl)) {
    expect(posten.length, `${raum} bietet gar nichts an`).toBeGreaterThan(1);
  }
});
