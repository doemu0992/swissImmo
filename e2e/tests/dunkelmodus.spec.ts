import { test, expect, Page } from '@playwright/test';


// Der Dunkelmodus der Aussenseiten — im Browser gemessen, nicht im Quelltext gelesen.
//
// WARUM DAS HIER STEHT UND NICHT IN DER DJANGO-SAMMLUNG
//
// `core/tests/test_dunkelmodus_huellen.py` sucht feste Farbwerte in `body`-Regeln.
// Das findet den Fehler an seiner Quelle, aber es rechnet keine Stile aus: Ob eine
// Regel am Ende greift, entscheidet die Spezifität, und genau daran ist E2.48
// gescheitert. Die Etappe nahm an, `#f8fafc` überschreibe das `fw-flaeche2` des
// `<body>` und lasse die Seite im Dunkeln hell. Gemessen war das Gegenteil richtig:
// `.fw-flaeche2` ist eine Klasse (0,1,0), `body` ein Element (0,0,1) — der Grund
// folgte dem Modus die ganze Zeit. Eingefroren war die SCHRIFT, weil `fw-flaeche2`
// kein `color` setzt.
//
// Eine Aussage über Spezifität lässt sich nicht lesen, nur messen. Deshalb dieser Test.
//
// WAS ER PRÜFT
//
//   1. Grund UND Schrift wechseln zwischen hell und dunkel.
//   2. In beiden Modi ist der Kontrast lesbar (WCAG AA, 4.5:1).
//
// Punkt 2 ist nicht doppelt gemoppelt: `public_bewerbung_geschlossen.html` hatte
// einen eingefrorenen Grund `rgb(248,250,252)` und eine mitlaufende Schrift
// `rgb(228,237,238)` — Kontrast 1.14:1. `modern_base.html` lag im Dunkeln bei
// 1.06:1. Beide Male stand der Text da und war nicht zu sehen.

/** Die Seiten, die Mieter, Bewerber und Passanten ohne Anmeldung sehen. */
const AUSSENSEITEN: Array<[string, string]> = [
  ['/schaden/melden/', 'Schaden melden (modern_base.html)'],
  ['/report/1/', 'Ticket-Formular vom Aushang (public_ticket_form.html)'],
  ['/bewerben/1/', 'Bewerbung — Formular oder Absageseite'],
];

type Messung = { grund: [number, number, number]; schrift: [number, number, number] };

function zerlegen(farbe: string): [number, number, number] {
  const m = farbe.match(/(\d+(?:\.\d+)?)/g);
  if (!m || m.length < 3) throw new Error(`Unlesbarer Farbwert: ${farbe}`);
  // `rgba(0, 0, 0, 0)` ist kein Schwarz, sondern «gar keine Farbe» — so
  // liefert der Browser einen `var()`-Aufruf auf ein unbelegtes Token. Ohne
  // diesen Wurf käme es als Schwarz durch und der Kontrast wäre rechnerisch 1,
  // was wie ein Farbfehler aussieht statt wie ein fehlendes Stylesheet.
  if (m.length >= 4 && Number(m[3]) === 0) {
    throw new Error(`Durchsichtig statt gefärbt: ${farbe}`);
  }
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}

/** Relative Helligkeit nach WCAG 2.1. */
function helligkeit([r, g, b]: [number, number, number]) {
  const k = [r, g, b].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
}

function kontrast(a: [number, number, number], b: [number, number, number]) {
  const [h, d] = [helligkeit(a), helligkeit(b)].sort((x, y) => y - x);
  return (h + 0.05) / (d + 0.05);
}

async function messen(page: Page, pfad: string): Promise<Messung> {
  // NICHT der `goto`-Helfer aus helpers.ts, und das ist der Punkt.
  //
  // Der Helfer wartet auf `domcontentloaded`, weil die Aktenseiten auf
  // blockierte CDN-Quellen laufen würden. Diese drei Seiten haben KEINE
  // Fremdaufrufe mehr (E2.23, im Browser nachgemessen) — dafür hat
  // `domcontentloaded` hier einen Haken: Es wartet nicht zwingend auf die
  // Stylesheets. Die Absageseite bindet kein blockierendes Skript ein, also
  // kann gemessen werden, bevor `schicht.css` greift. Dann sind die Tokens
  // unbelegt, `var(--ds-surface-2)` ergibt nichts, der Grund ist durchsichtig
  // und der Kontrast rechnerisch 1.
  //
  // Genau so ist dieser Test beim ersten Lauf der ganzen Sammlung
  // fehlgeschlagen — einzeln lief er dreimal grün. Ein Test, der von der
  // Maschinenlast abhängt, ist keiner.
  //
  // Die Absageseite antwortet mit 410; sie rendert trotzdem, und `goto` wirft
  // darauf nicht.
  await page.goto(pfad, { waitUntil: 'load' });

  // Belegt, dass die Schicht wirklich da ist. Ohne diese Zusicherung sähe ein
  // kaputter `schicht.css`-Pfad aus wie ein Kontrastfehler.
  const token = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--ds-surface-2').trim());
  expect(token, `${pfad}: --ds-surface-2 ist unbelegt — schicht.css fehlt.`).not.toBe('');

  const roh = await page.evaluate(() => {
    const cs = getComputedStyle(document.body);
    return { grund: cs.backgroundColor, schrift: cs.color };
  });
  return { grund: zerlegen(roh.grund), schrift: zerlegen(roh.schrift) };
}

// Die Kontrastrechnung prüft sich selbst. Sonst wäre `toBeGreaterThanOrEqual(4.5)`
// eine Zusicherung, die immer erfüllt ist, weil die Funktion etwas Grosses liefert —
// und die Gegenprobe fällt in den Freeze-Test, bevor der Kontrast drankommt.
test('Kontrastrechnung ist geeicht', async () => {
  expect(kontrast([255, 255, 255], [0, 0, 0])).toBeCloseTo(21, 1);
  expect(kontrast([255, 255, 255], [255, 255, 255])).toBeCloseTo(1, 2);
  // Die zwei gemessenen Fälle aus dem Dunkelmodus VOR der Korrektur:
  //
  //   modern_base.html              Grund #173038, Schrift #1e293b → 1.06:1
  //   public_bewerbung_geschlossen  Grund #f8fafc, Schrift #e4edee → 1.14:1
  //
  // Einmal dunkel auf dunkel, einmal hell auf hell. Beide Male stand der Text da
  // und war nicht zu sehen.
  expect(kontrast([23, 48, 56], [30, 41, 59])).toBeCloseTo(1.06, 2);
  expect(kontrast([248, 250, 252], [228, 237, 238])).toBeCloseTo(1.14, 2);
  for (const paar of [[[23, 48, 56], [30, 41, 59]], [[248, 250, 252], [228, 237, 238]]] as const) {
    expect(kontrast(paar[0] as [number, number, number],
                    paar[1] as [number, number, number])).toBeLessThan(4.5);
  }
});

/**
 * Jede Textstelle der Seite gegen ihren tatsächlichen Hintergrund.
 *
 * WARUM `body` ALLEIN NICHT REICHT — DER FALL AUS E2.50
 *
 * Die Prüfungen weiter unten messen `document.body`. Damit fanden sie den
 * eingefrorenen Seitengrund (E2.48), aber nicht das hier: Im Kopfbalken von
 * `/report/<id>/` stand die Adresse der Liegenschaft in `fw-faint` — einem
 * gedämpften Grau für den SEITENgrund — auf der satten Markenfläche.
 *
 *     hell    rgb(92,117,124)  auf rgb(15,111,106)  → 1.23:1
 *     dunkel  rgb(139,164,170) auf rgb(79,179,170)  → 1.05:1
 *
 * Die Adresse war in beiden Modi praktisch unsichtbar, auf der Seite, die am
 * Treppenhaus hängt. Kein Test sah es: `body` war in Ordnung, der Balken nicht.
 *
 * Deshalb läuft dieser Durchgang über ALLE Elemente mit eigenem Text und
 * sucht den nächsten undurchsichtigen Hintergrund darüber — so, wie das Auge
 * es sieht.
 */
async function schwacheStellen(page: Page) {
  return page.evaluate(() => {
    const lum = ([r, g, b]: number[]) => {
      const k = [r, g, b].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
    };
    const kon = (a: number[], b: number[]) => {
      const [h, d] = [lum(a), lum(b)].sort((x, y) => y - x);
      return (h + 0.05) / (d + 0.05);
    };
    const zer = (s: string) => {
      const m = s.match(/\d+(\.\d+)?/g);
      return m ? m.slice(0, 3).map(Number) : null;
    };
    // `rgba(…, 0)` ist durchsichtig — dann zaehlt der Hintergrund darueber.
    const undurchsichtig = (c: string) => {
      const m = c.match(/rgba?\([^)]*\)/);
      return !!m && !/,\s*0\s*\)$/.test(m[0]);
    };
    const grundVon = (el: Element) => {
      let n: Element | null = el;
      while (n) {
        const c = getComputedStyle(n).backgroundColor;
        if (undurchsichtig(c)) return zer(c)!;
        n = n.parentElement;
      }
      return [255, 255, 255];
    };
    const funde: string[] = [];
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      // Nur EIGENER Text — sonst wird jeder Vorfahr mitgezaehlt.
      const txt = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => (n.textContent || '').trim())
        .join(' ')
        .trim();
      if (!txt) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
      const fg = zer(cs.color);
      if (!fg) continue;
      const k = kon(fg, grundVon(el));
      if (k < 4.5) {
        funde.push(
          `${k.toFixed(2)}:1 «${txt.slice(0, 40)}» ` +
            `[${(el.className || '').toString().slice(0, 50)}]`,
        );
      }
    }
    return funde;
  });
}

for (const [pfad, name] of AUSSENSEITEN) {
  test(`Lesbarer Text: ${name}`, async ({ browser }) => {
    for (const modus of ['light', 'dark'] as const) {
      const ctx = await browser.newContext({ colorScheme: modus });
      const page = await ctx.newPage();
      await page.goto(pfad, { waitUntil: 'load' });
      // Das Ticket-Formular legt einen Vorhang ueber die Seite, bis Alpine
      // startet — spaetestens nach 3 s raeumt ein Notausgang ihn weg. Vorher
      // gemessen misst man den Vorhang, nicht die Seite.
      await page.waitForTimeout(3500);
      const funde = await schwacheStellen(page);
      await ctx.close();
      expect(
        funde,
        `${pfad} (${modus}): Diese Stellen liegen unter 4.5:1 zu ihrem ` +
          `eigenen Hintergrund:\n  ${funde.join('\n  ')}`,
      ).toEqual([]);
    }
  });

  test(`Dunkelmodus: ${name}`, async ({ browser }) => {
    const messungen: Record<string, Messung> = {};
    for (const modus of ['light', 'dark'] as const) {
      const ctx = await browser.newContext({ colorScheme: modus });
      const page = await ctx.newPage();
      messungen[modus] = await messen(page, pfad);
      await ctx.close();
    }

    const { light, dark } = messungen;

    // 1. Beide Werte folgen dem Modus. Ein fester Hexwert tut das nicht.
    expect(
      light.grund.join(),
      `${pfad}: Der Grund ist in beiden Modi ${light.grund.join()} — eingefroren.`,
    ).not.toBe(dark.grund.join());
    expect(
      light.schrift.join(),
      `${pfad}: Die Schrift ist in beiden Modi ${light.schrift.join()} — eingefroren.`,
    ).not.toBe(dark.schrift.join());

    // 2. Lesbar in beiden Modi.
    for (const modus of ['light', 'dark'] as const) {
      const m = messungen[modus];
      const k = kontrast(m.grund, m.schrift);
      expect(
        k,
        `${pfad} (${modus}): Kontrast ${k.toFixed(2)}:1 zwischen Grund ` +
          `rgb(${m.grund.join(',')}) und Schrift rgb(${m.schrift.join(',')}).`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
}
