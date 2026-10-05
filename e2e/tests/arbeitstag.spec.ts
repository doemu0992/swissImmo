import { test, expect, Page } from '@playwright/test';
import { bestaetigen, goto, login } from './helpers';

// «Day in the Life» (Phase 4 des Audits): ein Arbeitstag der Verwaltung, nur über die
// Oberfläche — wie ein Mensch, ohne direkte Datenbank- oder API-Aufrufe.
//
//   Login → neues Mandat (Eigentümer) → Liegenschaft → Objekt → Mieter einbuchen
//   → Mietvertrag (Assistent) → Ticket erfassen und zuweisen → Monatslauf (Sollstellung)
//   → die Miete steht in den Debitoren.
//
// Jeder Lauf benutzt eindeutige Namen (Zeitstempel), damit ein wiederverwendeter
// Server keine Dubletten-Sperre auslöst. Kein Schritt darf eine Fehlerseite, einen
// JS-Fehler oder einen dauerhaften Lade-Zustand zeigen — das prüft `kein500` laufend.

const id = Date.now().toString().slice(-7);
const MANDAT = `Tag ${id} Immobilien AG`;
const STRASSE = `Arbeitstagweg ${id.slice(-3)}`;
const OBJEKT = `4.5 Zi ${id.slice(-3)}`;
const VORNAME = 'Berta';
const NACHNAME = `Tagesmieter${id.slice(-4)}`;
const TICKET = `Wasserhahn tropft ${id.slice(-3)}`;

const heute = new Date();
const monatsanfang = new Date(heute.getFullYear(), heute.getMonth(), 1);
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** Letzte ID aus einer Adresse wie /neu/liegenschaften/12/ . */
function idAusUrl(url: string, bereich: string): string {
  const m = url.match(new RegExp(`/neu/${bereich}/(\\d+)/`));
  if (!m) throw new Error(`Keine ID für «${bereich}» in ${url}`);
  return m[1];
}

test.describe('Arbeitstag', () => {
  test.setTimeout(120_000);

  test('Vom Mandat bis zur Sollstellung', async ({ page }) => {
    const fehler: string[] = [];
    page.on('pageerror', (e) => fehler.push(`JS-Fehler: ${e.message}`));
    page.on('response', (r) => {
      if (r.status() >= 500 && r.url().includes('127.0.0.1')) fehler.push(`HTTP ${r.status()}: ${r.url()}`);
    });
    // Eine Fehlerseite (404/500/403) trägt keinen Seitenkopf der Anwendung.
    const kein500 = async (wo: string) => {
      await expect(page.locator('body'), `Fehlerseite bei «${wo}»`).not.toContainText(/Server Error|Seite nicht gefunden|Keine Berechtigung/i);
    };

    // 1 — Anmelden
    await login(page);

    // 2 — Neues Mandat (Eigentümer)
    await goto(page, '/neu/mandate/neu/');
    await page.fill('input[name="firma_oder_name"]', MANDAT);
    await page.fill('input[name="email"]', `mandat${id}@example.ch`);
    await page.fill('input[name="strasse"]', 'Bahnhofstrasse 1');
    await page.fill('input[name="plz"]', '8001');
    await page.fill('input[name="ort"]', 'Zürich');
    await page.locator('form:has(input[name="firma_oder_name"]) button[type="submit"]').click();
    // Das Mandat führt zurück in die Liste der Mandate (nicht in eine Detailseite).
    await page.waitForURL(/\/neu\/mandate\/$/, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(MANDAT).first()).toBeVisible();
    await kein500('Mandat');

    // 3 — Liegenschaft anlegen und dem Mandat zuordnen
    await goto(page, '/neu/liegenschaften/neu/');
    await page.fill('input[name="strasse"]', STRASSE);
    await page.fill('input[name="plz"]', '8004');
    await page.fill('input[name="ort"]', 'Zürich');
    await page.selectOption('select[name="status"]', 'aktiv');
    await page.selectOption('select[name="eigentuemer_id"]', { label: MANDAT });
    await page.locator('form:has(input[name="strasse"]) button[type="submit"]').click();
    await page.waitForURL(/\/neu\/liegenschaften\/\d+\/$/, { waitUntil: 'domcontentloaded' });
    const lgId = idAusUrl(page.url(), 'liegenschaften');
    await expect(page.getByText(STRASSE).first()).toBeVisible();
    await kein500('Liegenschaft');

    // 4 — Objekt (Wohnung) in der Liegenschaft
    await goto(page, '/neu/objekte/neu/');
    await page.selectOption('select[name="liegenschaft_id"]', lgId);
    await page.fill('input[name="bezeichnung"]', OBJEKT);
    await page.selectOption('select[name="typ"]', 'whg');
    await page.fill('input[name="nettomiete_aktuell"]', '1500');
    await page.fill('input[name="nebenkosten_aktuell"]', '200');
    await page.locator('form:has(input[name="bezeichnung"]) button[type="submit"]').click();
    await page.waitForURL(/\/neu\/objekte\/\d+\/$/, { waitUntil: 'domcontentloaded' });
    const objektId = idAusUrl(page.url(), 'objekte');
    await kein500('Objekt');

    // 5 — Mieter erfassen
    await goto(page, '/neu/personen/neu/');
    await page.selectOption('select[name="anrede"]', 'Frau');
    await page.fill('input[name="vorname"]', VORNAME);
    await page.fill('input[name="nachname"]', NACHNAME);
    await page.fill('input[name="email"]', `mieter${id}@example.ch`);
    await page.fill('input[name="strasse"]', 'Alte Adresse 5');
    await page.fill('input[name="plz"]', '8005');
    await page.fill('input[name="ort"]', 'Zürich');
    await page.locator('form:has(input[name="nachname"]) button[type="submit"]').click();
    await page.waitForURL(/\/neu\/personen\/\d+\/$/, { waitUntil: 'domcontentloaded' });
    const mieterId = idAusUrl(page.url(), 'personen');
    await expect(page.getByText(NACHNAME).first()).toBeVisible();
    await kein500('Person');

    // 6 — Mieter einbuchen: Mietvertrag über den Assistenten
    await goto(page, '/neu/vertraege/neu/');
    await page.selectOption('#s_lg', lgId);
    await page.selectOption('#s_obj', objektId);
    const weiter = page.locator('#btn-next');
    await weiter.click();                                   // → Personen
    await page.selectOption('#s_mieter', mieterId);
    await weiter.click();                                   // → Laufzeit
    await page.fill('#s_beginn', iso(monatsanfang));
    await weiter.click();                                   // → Mietzins
    await expect(page.locator('#s_netto')).toBeVisible();
    await page.fill('#s_netto', '1500');
    await page.fill('#s_nk', '200');
    await weiter.click();                                   // → Kaution
    await weiter.click();                                   // → Nebenkosten
    await weiter.click();                                   // → Abschluss
    const speichern = page.locator('#btn-save');
    await expect(speichern).toBeVisible();
    await speichern.click();
    await page.waitForURL(/\/neu\/vertraege\/\d+\/$/, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(NACHNAME).first()).toBeVisible();
    await kein500('Vertrag');

    // 7 — Ticket erfassen (Telefonanruf des Mieters)
    await goto(page, '/neu/schaeden/');
    await page.getByRole('button', { name: /Schaden erfassen/ }).click();   // klappt das Formular auf
    const formular = page.locator('form[action="/neu/schaeden/neu/"]');
    await expect(formular).toBeVisible();
    await formular.locator('input[name="titel"]').fill(TICKET);
    await formular.locator('select[name="liegenschaft_id"]').selectOption(lgId);
    await formular.locator('textarea[name="beschreibung"]').fill('Der Wasserhahn in der Küche tropft seit gestern.');
    await formular.locator('select[name="prioritaet"]').selectOption('hoch');
    await formular.getByRole('button', { name: /Ticket erstellen/ }).click();
    await page.waitForURL(/\/neu\/schaeden\/\d+\/$/, { waitUntil: 'domcontentloaded' });
    const ticketId = idAusUrl(page.url(), 'schaeden');
    await expect(page.getByText(TICKET).first()).toBeVisible();
    await kein500('Ticket erfassen');

    // 8 — Ticket intern zuweisen (Frist folgt der Priorität «hoch»: zwei Tage)
    await goto(page, `/neu/schaeden/${ticketId}/`);
    await page.getByRole('link', { name: 'Zuweisen' }).click();
    await page.waitForURL(/\/zuweisen\/$/, { waitUntil: 'domcontentloaded' });
    await page.selectOption('select[name="zugewiesen_an"]', { label: 'e2e' });
    await page.locator('form:has(select[name="zugewiesen_an"]) button.fw-primary').click();
    await page.waitForURL(new RegExp(`/neu/schaeden/${ticketId}/$`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Zuständigkeit').first()).toBeVisible();
    await expect(page.getByText('erledigen bis').first()).toBeVisible();
    await kein500('Ticket');

    // 9 — Monatslauf: Sollstellung für den laufenden Monat
    await goto(page, '/neu/sollstellung/');
    await expect(page.getByText(NACHNAME).first()).toBeVisible();     // der neue Vertrag ist dabei
    // Nachzügler: Ist der Lauf dieses Monats schon abgeschlossen (z. B. weil der Server schon
    // einen Lauf sah), bietet die Seite keinen Start-Knopf an, sondern den Weg über «Läufe».
    if (await page.locator('#soll-gesperrt').isVisible()) {
      await page.getByRole('link', { name: /Lauf zurücksetzen/ }).click();
      await page.waitForURL(/\/neu\/laeufe\/\d+\//, { waitUntil: 'domcontentloaded' });
      await page.locator('#lauf-zuruecksetzen summary').click();
      await page.fill('#lauf-zuruecksetzen input[name="grund"]', 'Nachzügler: Einzug nach dem Monatslauf');
      await page.locator('#lauf-zuruecksetzen button', { hasText: 'Zurücksetzen' }).click();
      await page.waitForLoadState('domcontentloaded');
      await goto(page, '/neu/sollstellung/');
    }
    await page.getByRole('button', { name: /Sollstellung starten/ }).click();
    await bestaetigen(page);
    await kein500('Sollstellung');

    // 10 — Ergebnis: die Miete steht in den Debitoren (offen, mit Betrag)
    await goto(page, '/neu/debitoren/');
    const debitor = page.locator('table[data-spaltenfilter] tbody tr', { hasText: NACHNAME }).first();
    await expect(debitor).toBeVisible();
    await expect(debitor).toContainText('1\'700.00');

    expect(fehler, 'Fehler während des Arbeitstags').toEqual([]);
  });
});
