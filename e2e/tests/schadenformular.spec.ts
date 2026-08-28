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

// ES GIBT DAS FORMULAR ZWEIMAL — UND DAS WAR DER FEHLER
//
// `/report/<id>/` ist der Treppenhaus-Aushang, `/schaden/melden/` der Weg
// über die Website. Zwei Vorlagen, dieselbe Aufgabe.
//
// E2.50 und E2.51 haben nur die erste behoben. Ich habe eine Adresse gemessen
// und angenommen, damit sei die Sache erledigt — die zweite bot weiterhin im
// Bad einen Kühlschrank an und zeigte fünfmal dasselbe Symbol. Gemeldet hat es
// Dominik, mit einem Bildschirmfoto.
//
// Dieser Test läuft deshalb über BEIDE. Wer künftig eine der zwei ändert,
// merkt es an der anderen.
const FORMULARE = [
  { pfad: '/report/1/', name: 'Aushang' },
  { pfad: '/schaden/melden/', name: 'Website' },
];

/** Wartet den Ladevorhang ab (Notausgang nach 3 s) und gibt die Alpine-Daten. */
async function formular(page: import('@playwright/test').Page, pfad = '/report/1/') {
  await page.goto(pfad, { waitUntil: 'load' });
  await page.waitForTimeout(3500);
  return page.evaluate(() => {
    // @ts-expect-error Alpine ist global, aber nicht typisiert.
    const w = Alpine.$data(document.querySelector('[x-data]'));
    // Die zwei Vorlagen nennen ihre Daten verschieden: `rooms`/`objectMap`
    // im Aushang, `raeume`/`objekte` auf der Website. Der Test kennt beide,
    // statt eine Vereinheitlichung zu erzwingen, die niemand entschieden hat.
    const raeume = w.rooms ?? w.raeume;
    const eigene = Object.keys(w.objectMap ?? w.objekte);
    const je: Record<string, string[]> = {};
    for (const r of raeume) {
      if (w.rooms) {
        w.room = r.name;
        je[r.name] = w.getCurrentObjects().map((o: { name: string }) => o.name);
      } else {
        w.formData.raum = r.name;
        je[r.name] = w.objekteFuerRaum();
      }
    }
    return {
      raeume: raeume.map((r: { name: string; z: string }) => ({ name: r.name, z: r.z })),
      eigene,
      auswahl: je,
    };
  });
}

for (const f of FORMULARE) {
test(`${f.name}: Jeder Raum trägt ein eigenes, auflösbares Zeichen`, async ({ page }) => {
  // DIESER TEST STAND AUF `/report/1/`, AUCH IM DURCHLAUF «Website».
  //
  // Die Schleife über FORMULARE war da, der Pfad im Rumpf aber fest verdrahtet
  // — beide Durchläufe besuchten den Aushang, und der zweite trug nur einen
  // falschen Namen. Genau der Fehler, den die Etappe im NACHBARTEST gefunden
  // und behoben hat, hier unverändert stehen geblieben.
  //
  // Er konnte dort auch gar nicht greifen: Die Website-Vorlage kennt kein
  // `.icon-card`. Deshalb sucht der Test die Kacheln jetzt über die DATEN —
  // je Raumname die sichtbare Schaltfläche mit diesem Text. Das funktioniert
  // auf beiden Vorlagen, ohne dass eine von beiden für den Test umgebaut wird.
  const { raeume } = await formular(page, f.pfad);
  await page.evaluate(() => {
    // @ts-expect-error Alpine ist global.
    Alpine.$data(document.querySelector('[x-data]')).step = 2;
  });
  await page.waitForTimeout(400);

  const kacheln = await page.evaluate((namen: string[]) => {
    const treffer: { name: string; verweis: string; aufgeloest: boolean }[] = [];
    for (const name of namen) {
      const el = Array.from(document.querySelectorAll('button, .icon-card')).find(
        (k) => (k as HTMLElement).offsetParent && (k as HTMLElement).innerText.trim() === name,
      );
      if (!el) continue;
      const verweis = el.querySelector('use')?.getAttribute('href') || '';
      treffer.push({ name, verweis, aufgeloest: !!(verweis && document.querySelector(verweis)) });
    }
    return treffer;
  }, raeume.map((r) => r.name));

  expect(
    kacheln.map((k) => k.name),
    'Nicht jeder Raum aus den Daten hat eine sichtbare Kachel.',
  ).toEqual(raeume.map((r) => r.name));

  const tot = kacheln.filter((k) => !k.aufgeloest);
  expect(
    tot.map((k) => `${k.name} → «${k.verweis}»`),
    'Diese Kacheln verweisen auf ein Symbol, das es im Sprite nicht gibt. Sie ' +
      'zeichnen NICHTS und melden das auch nicht — ein Tippfehler in `r.z` ' +
      'bleibt sonst unsichtbar.',
  ).toEqual([]);

  // Zwölf gleiche Zeichen wären so gut wie keine — das war der Zustand vor
  // E2.51 (Aushang) und vor E2.55 (Website, fünfmal dasselbe `einheit`).
  // `Anderer Raum` teilt sich `einheit` mit nichts anderem, also bleibt die
  // Zahl der Zeichen gleich der Zahl der Kacheln.
  const verschieden = new Set(kacheln.map((k) => k.verweis));
  expect(
    verschieden.size,
    `Nur ${verschieden.size} verschiedene Zeichen auf ${kacheln.length} Kacheln.`,
  ).toBe(kacheln.length);
});

test(`${f.name}: Kein Raum bietet an, was es dort nicht gibt`, async ({ page }) => {
  const { raeume, eigene, auswahl } = await formular(page, f.pfad);

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
  // DER KERN: Ein Briefkasten hat keine Decke, keine Steckdose, kein Fenster.
  // Bis E2.51/E2.55 bot er genau das an — wer «Decke» meldet, schickt einen
  // Handwerker zu etwas, das es nicht gibt.
  //
  // Die vorige Fassung fragte nur, ob überhaupt etwas da ist. Das blieb grün,
  // als ich den Fehler zur Gegenprobe wieder einbaute.
  for (const unmoeglich of ['Decke', 'Boden', 'Wand', 'Steckdose', 'Fenster',
                            'Storen/Markise']) {
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
}

// DER WÄCHTER GEGEN DIE URSACHE, NICHT GEGEN DAS SYMPTOM
//
// Die Prüfungen oben laufen über beide Formulare und hätten den gemeldeten
// Fehler gefunden. Sie hätten aber nicht verhindert, dass die zwei Listen
// LANGSAM auseinanderlaufen: Wer künftig auf einer Seite einen Raum ergänzt,
// bleibt auf beiden grün — jede Seite ist für sich stimmig, nur eben anders.
//
// Genau so ist es passiert. E2.51 hat die Räume des Aushangs überarbeitet;
// die Website behielt ihre eigene, fest verdrahtete Liste, und niemand sah es,
// weil beide Seiten einzeln in Ordnung aussahen.
test('Beide Formulare bieten dieselben Räume an', async ({ page }) => {
  const je: Record<string, { name: string; z: string }[]> = {};
  for (const f of FORMULARE) {
    je[f.name] = (await formular(page, f.pfad)).raeume;
  }
  const [a, b] = FORMULARE.map((f) => f.name);
  expect(
    je[b].map((r) => `${r.name} (${r.z})`),
    `«${a}» und «${b}» bieten verschiedene Räume an. Wer einen Raum ergänzt, ` +
      'ergänzt ihn auf beiden — sonst meldet ein Mieter je nach Weg etwas ' +
      'anderes, und beide Seiten sehen für sich richtig aus.',
  ).toEqual(je[a].map((r) => `${r.name} (${r.z})`));
});
