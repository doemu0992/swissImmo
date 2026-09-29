"""Die Mehrsprachigkeit — gemessen, nicht behauptet.

WAS E2 VERLANGT UND WO ES STAND

`docs/PLAN-V7.md` nennt fuer E2 zwei Haelften: den Vorlagendurchgang auf die
Komponentenschicht UND `{% trans %}` im selben Griff, mit dem Gate «.po fuer
DE vollstaendig, FR/IT/EN voruebersetzt». Die erste Haelfte war am 21.09.2026
praktisch fertig, die zweite hatte **nie begonnen**: Gemessen trugen genau
**1 von 177** Vorlagen ein `{% trans %}`, `locale/` enthielt nur `.gitkeep`,
und im Python-Code stand kein einziges `gettext`. Der Kommentar in
`settings.py` hielt denselben Stand schon zu Beginn von E2 fest — es hatte
sich seither nichts bewegt.

E2.85 macht den Anfang mit der Tranche «Heute» (`dashboard`, `zulauf`,
`termine`, `abwesenheiten`) — der Reihenfolge aus PLAN-V7 folgend, und
denselben vier Vorlagen, die schon bei der Komponentenschicht die ersten
waren.

WARUM DIESE DATEI DREI VERSCHIEDENE DINGE PRUEFT

Eine Uebersetzung kann an drei unabhaengigen Stellen kaputtgehen, und zwei
davon **lautlos**:

1. Die Vorlage traegt keine Auszeichnung  -> Text bleibt deutsch.
2. Der Katalog hat Luecken               -> Text faellt auf Deutsch zurueck.
3. Das `.mo` fehlt oder ist veraltet     -> ALLES bleibt deutsch, obwohl
   die `.po` vollstaendig aussieht.

Fall 3 ist der gefaehrlichste: `deploy.sh` ruft **kein** `compilemessages`
(nachgesehen am 21.09.2026 — es laeuft `migrate` und `collectstatic`).
Django liest aber `.mo`, nicht `.po`. Eine gepflegte `.po` ohne gebautes
`.mo` ist damit eine Uebersetzung, die es nur auf dem Papier gibt.

Deshalb liegen die `.mo` im Repo und werden hier gegen die `.po` geprueft —
dasselbe Muster wie `test_schicht_gebaut.py` fuer das erzeugte CSS.

WER EINE NEUE TRANCHE MACHT
    python manage.py makemessages -l de -l fr -l it -l en \\
        --ignore=node_modules --ignore=e2e --ignore=staticfiles
    # uebersetzen, dann:
    python manage.py compilemessages
    # und UEBERSETZT unten ergaenzen.

Dafuer braucht es `gettext` (msgfmt/xgettext) auf dem Rechner — in dieser
Umgebung war es nicht vorinstalliert.
"""
import gettext as gettext_modul
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

WURZEL = pathlib.Path(settings.BASE_DIR)
LOCALE = WURZEL / 'locale'
SPRACHEN = ('de', 'fr', 'it', 'en')

#: Vorlagen, die bereits ausgezeichnet sind. Diese Liste darf nur WACHSEN —
#: dieselbe Sperrklinke wie beim Farbklassen-Zaehler, nur andersherum.
UEBERSETZT = (
    'fw/abwesenheiten.html',
    'fw/dashboard.html',
    'fw/termine.html',
    'fw/zulauf.html',
    'fw/_arbeitsvorrat_abschnitte.html',
    'fw/base.html',
    # Tranche «Akten»: die sechs Register
    'fw/mandate.html',
    'fw/liegenschaften.html',
    'fw/eigentuemer_mahnstufen.html',
    'fw/objekte.html',
    'fw/vertraege.html',
    'fw/personen.html',
    'fw/dienstleister.html',
    # Tranche «Läufe»
    'fw/laeufe.html',
    'fw/sollstellung.html',
    'fw/bankabgleich.html',
    'fw/mahnwesen.html',
    'fw/zahllauf.html',
    # Tranche «Rest-Oberfläche» (29.09.2026)
    'fw/vertrag_neu.html',
    'fw/schlussabrechnung.html',
    'fw/kuendigung_form.html',
    'fw/untermiete.html',
    'fw/maengelruege.html',
    'fw/_modal_done.html',
    'fw/nebenkosten.html',
    'fw/mietzins.html',
    'fw/mwst.html',
    # Tranche «Finanzen»
    'fw/finanzen.html',
    'fw/mieterkonten.html',
    'fw/debitoren.html',
    'fw/kautionen.html',
    'fw/kreditoren.html',
    'fw/lieferantenkonten.html',
    'fw/bankkonten.html',
    'fw/buchhaltung.html',
    'fw/kontenplan.html',
    'fw/anlagen.html',
    'fw/hypotheken.html',
    'fw/_bezahlt_leer.html',
    # Tranche «Berichte»
    'fw/berichte.html',
    'fw/auswertung.html',
    'fw/mieterspiegel.html',
    'fw/mieterspiegel_auswahl.html',
    'fw/leerstand_verlauf.html',
    'fw/betriebskostenspiegel.html',
    'fw/debitoren_aging.html',
    # Tranche «Einstellungen» (Teil A)
    'fw/einstellungen.html',
    'fw/account.html',
    'fw/abonnement.html',
    'fw/benutzer.html',
    'fw/benutzer_form.html',
    'fw/integrationen.html',
    'fw/vorlagen.html',
    'fw/vorlage_form.html',
    'fw/logbuch.html',
    'fw/_unterschrift_feld.html',
    # Tranche «Einstellungen» (Teil B)
    'fw/regelwerk.html',
    'fw/regelsatz_form.html',
    'fw/regelwerk_protokoll.html',
    'core/postfach_liste.html',
    'core/postfach_form.html',
    'core/zweifaktor_uebersicht.html',
    'core/zweifaktor_einrichten.html',
    'core/zweifaktor_bestaetigen.html',
    'core/zweifaktor_codes.html',
    '403.html',
    '404.html',
    '500.html',
    # Tranche «Portale» (Teil A: Mieterportal)
    'core/portal_base.html',
    'core/_mieter_nav.html',
    'core/mieter_portal.html',
    'core/mieter_daten.html',
    'core/mieter_dokumente.html',
    'core/mieter_konto.html',
    'core/mieter_passwort.html',
    'core/mieter_rechnungen.html',
    'core/mieter_schaden.html',
    'core/mieter_ticket_detail.html',
    'core/mieter_tickets.html',
    'core/passwort_reset.html',
    'core/passwort_reset_complete.html',
    'core/passwort_reset_confirm.html',
    'core/passwort_reset_done.html',
    'core/_passwort_shell_top.html',
    'core/_passwort_shell_bottom.html',
    # Tranche «Portale» (Teil B: Eigentümerportal, Anmeldung)
    'core/portal.html',
    'core/portal_login.html',
    'core/login.html',
    # Tranche «Finanz-Details»
    'fw/kontoblatt.html',
    'fw/mieterkonto.html',
    'fw/lieferantenkonto.html',
    'fw/eigentuemer_kontokorrent.html',
    'fw/zahler_zuordnungen.html',
    'fw/mandat_abrechnung.html',
    'fw/nebenkosten_detail.html',
    'fw/weiterverrechnung.html',
    # Tranche «Akten-Details A»
    'fw/mandat_detail.html',
    'fw/mandat_form.html',
    'fw/dienstleister_detail.html',
    'fw/suche.html',
    'fw/dokumente.html',
    'fw/pendenzen.html',
    'fw/schaeden.html',
    'fw/schaden_kosten.html',
    # Tranche «Vermietung & Unterhalt»
    'fw/vermarktung.html',
    'fw/objekt_ausschreiben.html',
    'fw/bewerbungen.html',
    'fw/bewerbung_detail.html',
    'fw/bewerber_vergleich.html',
    'fw/lebensdauer.html',
    'fw/ersatzplanung.html',
    # Tranche «Kommunikation & Abläufe»
    'fw/kommunikation.html',
    'fw/fristen.html',
    'fw/mieterwechsel.html',
    'fw/abnahme_detail.html',
    'fw/fall_detail.html',
    'fw/_fwmodal.html',
    'fw/_bestaetigen.html',      # Audit Etappe 3: Bestätigungsdialog
    'fw/_seiten.html',           # Audit Etappe 4: Blätterleiste
    'fw/_listwerkzeug.html',     # Audit Etappe 4: Suche und Sortierung
    # Tranche «Formulare»
    'fw/objekt_form.html',
    'fw/liegenschaft_form.html',
    'fw/schaden_detail.html',
    # Tranche «Personen»
    'fw/person_detail.html',
    'fw/person_form.html',
    # Tranche «Liegenschaftsakte»
    'fw/liegenschaft_detail.html',
    # Tranche «Objektakte»
    'fw/objekt_detail.html',
    # Tranche «Vertragsakte»
    'fw/vertrag_detail.html',
    # Tranche «Wohnungsabnahme»
    'fw/abnahme_neu.html',
    # Tranche «Vertrag bearbeiten»
    'fw/vertrag_bearbeiten.html',
    # Tranche «Öffentliche Meldeformulare» (modern_base.html trägt nur die
    # Sprachwahl, keinen eigenen Text — deshalb nicht in dieser Liste)
    'core/public_ticket_form.html',
    'core/schaden_melden.html',
)

#: Eine Stichprobe je Vorlage, mit der erwarteten Fassung je Sprache.
#:
#: Absichtlich Text, den ein Mensch im Bildschirm sieht — kein Kunstwort.
#: Faellt eine Sprache auf Deutsch zurueck (fehlender Eintrag, fehlendes
#: `.mo`), schlaegt genau das hier fehl.
STICHPROBE = {
    'Abwesenheiten':      {'de': 'Abwesenheiten', 'fr': 'Absences',
                           'it': 'Assenze', 'en': 'Absences'},
    'Niemand abwesend.':  {'de': 'Niemand abwesend.', 'fr': "Personne n'est absent.",
                           'it': 'Nessuno assente.', 'en': 'Nobody is away.'},
    'Arbeitsvorrat':      {'de': 'Arbeitsvorrat', 'fr': 'Charge de travail',
                           'it': 'Carico di lavoro', 'en': 'Work queue'},
    'Kommende Termine':   {'de': 'Kommende Termine', 'fr': 'Rendez-vous à venir',
                           'it': 'Prossimi appuntamenti', 'en': 'Upcoming appointments'},
    'Zuletzt erledigt':   {'de': 'Zuletzt erledigt', 'fr': 'Traité récemment',
                           'it': 'Completati di recente', 'en': 'Recently done'},
    'Erledigt':           {'de': 'Erledigt', 'fr': 'Terminé',
                           'it': 'Completato', 'en': 'Done'},
    # Arbeitsvorrat
    'Läufe':              {'de': 'Läufe', 'fr': 'Processus', 'it': 'Processi', 'en': 'Processes'},
    'Termine':            {'de': 'Termine', 'fr': 'Rendez-vous', 'it': 'Appuntamenti', 'en': 'Appointments'},
    'Vertretung':         {'de': 'Vertretung', 'fr': 'Remplacement', 'it': 'Sostituzione', 'en': 'Replacement'},
    'Wartet auf Freigabe': {'de': 'Wartet auf Freigabe', 'fr': "En attente d'approbation", 'it': "In attesa di approvazione", 'en': 'Waiting for approval'},
    # Rahmen (fw/base.html, core/navigation.py) — Rechtsbegriffe nach OR
    'Abmelden':           {'de': 'Abmelden', 'fr': 'Se déconnecter', 'it': 'Esci', 'en': 'Sign out'},
    'Mietverhältnisse':   {'de': 'Mietverhältnisse', 'fr': 'Baux', 'it': 'Locazioni', 'en': 'Tenancies'},
    'Nebenkosten':        {'de': 'Nebenkosten', 'fr': 'Frais accessoires', 'it': 'Spese accessorie',
                           'en': 'Service charges'},
    'Mietzins':           {'de': 'Mietzins', 'fr': 'Loyer', 'it': 'Pigione', 'en': 'Rent'},
    # Akten
    'Eigentümer erfassen': {'de': 'Eigentümer erfassen', 'fr': 'Saisir un propriétaire',
                            'it': 'Registrare proprietario', 'en': 'Add owner'},
    'Ist-Miete':          {'de': 'Ist-Miete', 'fr': 'Loyer effectif', 'it': 'Pigione effettiva',
                           'en': 'Actual rent'},
    'Kündigen':           {'de': 'Kündigen', 'fr': 'Résilier', 'it': 'Disdire', 'en': 'Terminate'},
    'Gekündigt':          {'de': 'Gekündigt', 'fr': 'Résilié', 'it': 'Disdetto', 'en': 'Terminated'},
    'Mietet aktuell':     {'de': 'Mietet aktuell', 'fr': 'Loue actuellement',
                           'it': 'Affitta attualmente', 'en': 'Currently renting'},
    'Handwerker erfassen': {'de': 'Handwerker erfassen', 'fr': 'Saisir un artisan',
                            'it': 'Registrare artigiano', 'en': 'Add tradesperson'},
    # Läufe — Fachbegriffe aus OR und MWSTG
    'Offene Posten':      {'de': 'Offene Posten', 'fr': 'Postes ouverts', 'it': 'Partite aperte',
                           'en': 'Open items'},
    'Mahnlauf ausführen': {'de': 'Mahnlauf ausführen', 'fr': 'Lancer les rappels',
                           'it': 'Eseguire i solleciti', 'en': 'Run dunning'},
    '− Vorsteuer':        {'de': '− Vorsteuer', 'fr': '− Impôt préalable', 'it': '− Imposta precedente',
                           'en': '− Input tax'},
    'Zahllast an ESTV':   {'de': 'Zahllast an ESTV', 'fr': "Montant dû à l'AFC",
                           'it': "Debito fiscale verso l'AFC", 'en': 'Payable to the FTA'},
    'Senkungsanspruch':   {'de': 'Senkungsanspruch', 'fr': 'Droit à une baisse',
                           'it': 'Diritto a una riduzione', 'en': 'Entitled to reduction'},
    # Finanzen — Buchhaltungsbegriffe CH
    'Soll':               {'de': 'Soll', 'fr': 'Débit', 'it': 'Dare', 'en': 'Debit'},
    'Haben':              {'de': 'Haben', 'fr': 'Crédit', 'it': 'Avere', 'en': 'Credit'},
    'Buchwert':           {'de': 'Buchwert', 'fr': 'Valeur comptable', 'it': 'Valore contabile',
                           'en': 'Book value'},
    'Mietzinsdepots':     {'de': 'Mietzinsdepots', 'fr': 'Garanties de loyer',
                           'it': 'Depositi di garanzia', 'en': 'Rent deposits'},
    'Festhypothek':       {'de': 'Festhypothek', 'fr': 'Hypothèque à taux fixe',
                           'it': 'Ipoteca a tasso fisso', 'en': 'Fixed-rate mortgage'},
    # Berichte
    'Mieterspiegel':      {'de': 'Mieterspiegel', 'fr': 'État locatif',
                           'it': 'Specchietto delle pigioni', 'en': 'Rent roll'},
    'Leerstands-Verlauf': {'de': 'Leerstands-Verlauf', 'fr': 'Évolution de la vacance',
                           'it': 'Andamento dello sfitto', 'en': 'Vacancy trend'},
    # Einstellungen
    'Gefahrenzone':       {'de': 'Gefahrenzone', 'fr': 'Zone dangereuse', 'it': 'Zona di pericolo',
                           'en': 'Danger zone'},
    # PRUEFWORT — darf NICHT uebersetzt werden: `fw_datenreset` vergleicht die
    # Eingabe mit «LÖSCHEN». Eine Uebersetzung liesse den Reset in FR/IT/EN
    # still scheitern, weil niemand das deutsche Wort tippt.
    'LÖSCHEN':            {'de': 'LÖSCHEN', 'fr': 'LÖSCHEN', 'it': 'LÖSCHEN', 'en': 'LÖSCHEN'},
    'Seite nicht gefunden': {'de': 'Seite nicht gefunden', 'fr': 'Page introuvable',
                             'it': 'Pagina non trovata', 'en': 'Page not found'},
    'Notfallcodes':       {'de': 'Notfallcodes', 'fr': 'Codes de secours',
                           'it': 'Codici di emergenza', 'en': 'Backup codes'},
    # Mieterportal — Höflichkeitsform
    'Mietkaution':        {'de': 'Mietkaution', 'fr': 'Garantie de loyer',
                           'it': 'Deposito di garanzia', 'en': 'Rent deposit'},
    'Schaden melden':     {'de': 'Schaden melden', 'fr': 'Signaler un dégât',
                           'it': 'Segnalare un danno', 'en': 'Report damage'},
    'Reparaturen zur Freigabe': {'de': 'Reparaturen zur Freigabe', 'fr': 'Réparations à approuver',
                           'it': 'Riparazioni da approvare', 'en': 'Repairs awaiting approval'},
    'Willkommen zurück':  {'de': 'Willkommen zurück', 'fr': 'Bon retour',
                           'it': 'Bentornato/a', 'en': 'Welcome back'},
    'Kontoblatt':         {'de': 'Kontoblatt', 'fr': 'Extrait de compte',
                           'it': 'Scheda conto', 'en': 'Account ledger'},
    'Offener Saldo':      {'de': 'Offener Saldo', 'fr': 'Solde ouvert',
                           'it': 'Saldo aperto', 'en': 'Open balance'},
    'Kostenübersicht':    {'de': 'Kostenübersicht', 'fr': 'Aperçu des coûts',
                           'it': 'Panoramica dei costi', 'en': 'Cost overview'},
    'Neue Pendenz':       {'de': 'Neue Pendenz', 'fr': 'Nouvelle tâche en suspens',
                           'it': 'Nuova pendenza', 'en': 'New to-do'},
    'Bewerber-Vergleich': {'de': 'Bewerber-Vergleich', 'fr': 'Comparaison des candidats',
                           'it': 'Confronto candidati', 'en': 'Applicant comparison'},
    'Ersatzplanung':      {'de': 'Ersatzplanung', 'fr': 'Planification des remplacements',
                           'it': 'Pianificazione delle sostituzioni', 'en': 'Replacement planning'},
    'Mieterwechsel-Cockpit': {'de': 'Mieterwechsel-Cockpit', 'fr': 'Cockpit de changement de locataire',
                              'it': "Cockpit del cambio d'inquilino", 'en': 'Tenant-change cockpit'},
    'Mitteilungs-Assistent': {'de': 'Mitteilungs-Assistent', 'fr': 'Assistant de communication',
                              'it': 'Assistente comunicazioni', 'en': 'Notice assistant'},
    'Neue Liegenschaft erfassen': {'de': 'Neue Liegenschaft erfassen', 'fr': 'Saisir un nouvel immeuble',
                                   'it': 'Registrare un nuovo stabile', 'en': 'Record new property'},
    'Handwerker beauftragen': {'de': 'Handwerker beauftragen', 'fr': 'Mandater un artisan',
                               'it': 'Incaricare un artigiano', 'en': 'Order tradesperson'},
    'Kontaktjournal':     {'de': 'Kontaktjournal', 'fr': 'Journal des contacts',
                           'it': 'Giornale dei contatti', 'en': 'Contact journal'},
    'Neue Person erfassen': {'de': 'Neue Person erfassen', 'fr': 'Saisir une nouvelle personne',
                             'it': 'Registrare una nuova persona', 'en': 'Record new person'},
    'Wartungs- und Versicherungsfristen': {'de': 'Wartungs- und Versicherungsfristen',
                                           'fr': "Délais de maintenance et d'assurance",
                                           'it': 'Scadenze di manutenzione e assicurazione',
                                           'en': 'Maintenance and insurance deadlines'},
    'Raum aus Katalog anlegen': {'de': 'Raum aus Katalog anlegen', 'fr': 'Créer une pièce depuis le catalogue',
                                 'it': 'Creare un locale dal catalogo', 'en': 'Create room from catalogue'},
    'Mietzins und Anpassungen': {'de': 'Mietzins und Anpassungen', 'fr': 'Loyer et adaptations',
                                 'it': 'Pigione e adeguamenti', 'en': 'Rent and adjustments'},
}


def _po_eintraege(pfad):
    """msgid -> msgstr aus einer .po, Mehrzahl als msgid -> [form0, form1].

    Einträge mit Kontext (`msgctxt`, z.B. «Raumkatalog») erhalten den
    Schlüssel `kontext\x04msgid` — genau so legt msgfmt sie im .mo ab.

    Ein eigener Parser und keine Bibliothek: `polib` waere eine Abhaengigkeit
    fuer dreissig Zeilen. Er kann genau so viel, wie diese Kataloge brauchen —
    mehrzeilige Zeichenketten und Mehrzahlformen.
    """
    eintraege = {}
    schluessel = None
    ziel = None
    puffer = {}
    kontext = None       # Kontext des laufenden Eintrags
    kontext_neu = None   # gelesener msgctxt, gilt für das NÄCHSTE msgid

    def _ablegen():
        schl = f'{kontext}\x04{schluessel}' if kontext else schluessel
        eintraege[schl] = puffer
    for zeile in pfad.read_text(encoding='utf-8').split('\n'):
        zeile = zeile.strip()
        if zeile.startswith('#') or not zeile:
            continue
        m = re.match(r'^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d\])?) "(.*)"$', zeile)
        if m:
            marke, text = m.group(1), m.group(2)
            if marke == 'msgctxt':
                kontext_neu, ziel = text, 'msgctxt'
            elif marke == 'msgid':
                if schluessel is not None:
                    _ablegen()
                schluessel, puffer, ziel = text, {}, 'msgid'
                kontext, kontext_neu = kontext_neu, None
            else:
                ziel = marke
                puffer[marke] = text
            continue
        f = re.match(r'^"(.*)"$', zeile)
        if f and ziel:
            if ziel == 'msgctxt':
                kontext_neu += f.group(1)
            elif ziel == 'msgid':
                schluessel += f.group(1)
            else:
                puffer[ziel] = puffer.get(ziel, '') + f.group(1)
    if schluessel is not None:
        _ablegen()
    eintraege.pop('', None)          # Dateikopf
    # Escapes aufloesen (\" → ", \n → Zeilenumbruch), wie msgfmt es tut. Ohne
    # das passt ein Eintrag mit Anfuehrungszeichen — etwa ein <a class="…"> in
    # einem blocktrans — nie zu seinem Schluessel im .mo.
    return {_po_text(k): {m: _po_text(v) for m, v in w.items()}
            for k, w in eintraege.items()}


def _po_text(text):
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), text)


class KatalogTests(SimpleTestCase):

    def test_jede_sprache_hat_einen_katalog(self):
        fehlend = [s for s in SPRACHEN
                   if not (LOCALE / s / 'LC_MESSAGES' / 'django.po').exists()]
        self.assertEqual(
            fehlend, [],
            f'Ohne Katalog gibt es fuer diese Sprachen keine Uebersetzung: {fehlend}. '
            'Anlegen mit `manage.py makemessages -l <sprache>`.')

    def test_die_sprachen_stimmen_mit_den_einstellungen_ueberein(self):
        """Ein Katalog, den `LANGUAGES` nicht kennt, wird nie ausgeliefert."""
        eingestellt = {code for code, _ in settings.LANGUAGES}
        self.assertEqual(
            set(SPRACHEN), eingestellt,
            'settings.LANGUAGES und die Kataloge hier laufen auseinander.')

    def test_kein_eintrag_ist_unuebersetzt(self):
        """Das Gate aus PLAN-V7, mechanisch geprueft.

        DEUTSCH IST MITGEZAEHLT, obwohl es die Ausgangssprache ist und ein
        leerer `msgstr` dort auf die `msgid` zurueckfaellt — also gar nichts
        kaputtginge. Mit gefuelltem `de` sagt `msgfmt --statistics` fuer alle
        vier Sprachen dasselbe, und eine geaenderte deutsche Quelle markiert
        den Eintrag beim naechsten `makemessages` als `fuzzy`. Fuzzy ignoriert
        gettext — es faellt also weiterhin sauber auf die `msgid` zurueck,
        faellt aber jemandem auf.
        """
        for sprache in SPRACHEN:
            with self.subTest(sprache=sprache):
                pfad = LOCALE / sprache / 'LC_MESSAGES' / 'django.po'
                offen = [mid for mid, w in _po_eintraege(pfad).items()
                         if not any(v for k, v in w.items() if k.startswith('msgstr'))]
                self.assertEqual(
                    offen, [],
                    f'{len(offen)} Eintraege ohne Uebersetzung in {sprache}: '
                    f'{offen[:5]}')

    def test_kein_eintrag_ist_fuzzy(self):
        """`fuzzy` heisst: uebersetzt, aber wirkungslos.

        Aendert sich eine deutsche Quelle, markiert `makemessages` den alten
        Eintrag als `fuzzy` und raet die neue Zuordnung. gettext IGNORIERT
        solche Eintraege — die Seite faellt still auf Deutsch zurueck, waehrend
        die `.po` vollstaendig aussieht und `test_kein_eintrag_ist_unuebersetzt`
        gruen bleibt.

        Am 23.09.2026 real passiert: Nach einer Syntax-Reparatur standen fuenf
        Eintraege auf `fuzzy`, darunter einer, den msgmerge aus «Ø Liegezeit
        %(n)s Tage» auf «liegt seit %(n)s Tag» geraten hatte — zwei
        verschiedene Aussagen. Wer den Rateweg uebernimmt, ohne hinzusehen,
        liefert eine falsche Uebersetzung aus.

        Deshalb: Eintrag pruefen, dann die Marke entfernen. Nicht umgekehrt.
        """
        for sprache in SPRACHEN:
            with self.subTest(sprache=sprache):
                pfad = LOCALE / sprache / 'LC_MESSAGES' / 'django.po'
                text = pfad.read_text(encoding='utf-8')
                fuzzy = re.findall(r'^#,[^\n]*\bfuzzy\b[^\n]*\n(?:#[^\n]*\n)*'
                                   r'msgid "([^"]*)"', text, re.M)
                self.assertEqual(
                    fuzzy, [],
                    f'{len(fuzzy)} Eintraege in {sprache} sind `fuzzy` und wirken '
                    f'damit NICHT: {fuzzy[:4]}. Uebersetzung pruefen, dann die '
                    'Marke entfernen.')

    def test_jeder_ausgezeichnete_text_steht_im_katalog(self):
        """Die vierte stille Lücke: ausgezeichnet, aber nie extrahiert.

        `test_kein_eintrag_ist_unuebersetzt` prüft nur, was IN der `.po`
        steht. Wer ein neues `{% trans %}` oder `_('…')` schreibt und
        `makemessages` nicht laufen lässt, hat einen Text, den kein Katalog
        kennt — er bleibt in jeder Sprache deutsch, und alle Tests hier sind
        grün. So geschehen mit der Liegenschaftsliste (Audit Etappe 4, #52):
        Suche, Sortierung, Blätterleiste und CSV-Spalten, zwölf Texte.

        Geprüft werden die einfachen Formen mit einem Literal — `{% trans "…" %}`
        ohne `context` in den Vorlagen, `_('…')`/`gettext(_lazy)('…')` im Code.
        Nachgeschlagen wird im gebauten französischen `.mo`. Ein `%` in einer
        Vorlage legt makemessages als `%%` ab.

        Gegenprobe: in `core/templates/fw/liegenschaften.html` den Text
        `{% trans "Sortieren" %}` in `{% trans "Sortieren nach" %}` ändern —
        der Test wird rot.
        """
        with (LOCALE / 'fr' / 'LC_MESSAGES' / 'django.mo').open('rb') as f:
            katalog = gettext_modul.GNUTranslations(f)._catalog
        vorlage = re.compile(r"""{%\s*(?:trans|translate)\s+(?:"([^"]*)"|'([^']*)')(?![^%]*\bcontext\b)[^%]*%}""")
        code = re.compile(r"""\b(?:_|_t|gettext|gettext_lazy)\(\s*(?:'([^'\\\n]*)'|"([^"\\\n]*)")\s*\)""")
        fehlend = []
        for pfad in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            text = pfad.read_text(encoding='utf-8')
            for m in vorlage.finditer(text):
                s = m.group(1) if m.group(1) is not None else m.group(2)
                if s and s not in katalog and s.replace('%', '%%') not in katalog:
                    fehlend.append(f'{pfad.relative_to(WURZEL)}: {s}')
        for app in ('core', 'crm', 'portfolio', 'rentals', 'finance', 'tickets',
                    'faelle', 'mietprozess', 'benutzer'):
            for pfad in sorted((WURZEL / app).rglob('*.py')):
                if {'tests', 'migrations'} & set(pfad.parts):
                    continue
                for m in code.finditer(pfad.read_text(encoding='utf-8')):
                    s = m.group(1) if m.group(1) is not None else m.group(2)
                    if s and s not in katalog:
                        fehlend.append(f'{pfad.relative_to(WURZEL)}: {s}')
        self.assertEqual(
            fehlend, [],
            f'{len(fehlend)} ausgezeichnete Texte stehen in keinem Katalog: '
            f'{fehlend[:5]}. `makemessages` laufen lassen (siehe Kopf dieser '
            'Datei), übersetzen, `compilemessages`.')

    def test_das_mo_ist_gebaut_und_aktuell(self):
        """Der gefaehrlichste stille Fehler bekommt einen lauten Test.

        `deploy.sh` ruft kein `compilemessages`; Django liest `.mo`. Eine
        gepflegte `.po` ohne passendes `.mo` ist deshalb eine Uebersetzung,
        die nur im Quelltext existiert.

        Verglichen werden die EINTRAEGE, nicht die Bytes: Zwei msgfmt-Fassungen
        duerfen dieselbe Tabelle verschieden ablegen.
        """
        for sprache in SPRACHEN:
            with self.subTest(sprache=sprache):
                mo = LOCALE / sprache / 'LC_MESSAGES' / 'django.mo'
                self.assertTrue(
                    mo.exists(),
                    f'{mo.relative_to(WURZEL)} fehlt — `manage.py compilemessages` '
                    'laufen lassen und mitcommitten.')
                with mo.open('rb') as f:
                    gebaut = gettext_modul.GNUTranslations(f)._catalog
                quelle = _po_eintraege(LOCALE / sprache / 'LC_MESSAGES' / 'django.po')
                fehlend = [mid for mid, w in quelle.items()
                           if 'msgstr' in w and w['msgstr'] and mid not in gebaut]
                self.assertEqual(
                    fehlend, [],
                    f'Das .mo fuer {sprache} ist aelter als die .po — '
                    f'{len(fehlend)} Eintraege fehlen darin, z.B. {fehlend[:3]}. '
                    '`manage.py compilemessages` laeuft nicht im Deploy.')


class AusgezeichneteVorlagenTests(SimpleTestCase):

    def test_die_tranche_traegt_die_auszeichnung(self):
        """`{% load i18n %}` UND mindestens ein `{% trans %}`/`{% blocktrans %}`.

        Beides, weil das eine ohne das andere nichts tut: Ein `{% trans %}`
        ohne `{% load i18n %}` ist ein Vorlagenfehler, ein `{% load i18n %}`
        ohne Auszeichnung ist eine Zeile ohne Wirkung.

        ALLE VIER SCHREIBWEISEN: Django kennt `trans`/`blocktrans` und die
        neueren `translate`/`blocktranslate`. Der erste Entwurf dieses Tests
        suchte nur die kurzen — aufgefallen an `admin/base.html`, das
        `{% translate 'Home' %}` traegt und damit unbemerkt durchgefallen
        waere. Ein Waechter, der eine gueltige Schreibweise nicht kennt,
        laesst genau die durch.
        """
        for name in UEBERSETZT:
            with self.subTest(vorlage=name):
                text = (WURZEL / 'core' / 'templates' / name).read_text(encoding='utf-8')
                self.assertRegex(
                    text, r'{%\s*load[^%]*\bi18n\b',
                    f'{name} zeichnet Text aus, laedt aber `i18n` nicht.')
                self.assertRegex(
                    text, r'{%\s*(trans|translate|blocktrans|blocktranslate)\b',
                    f'{name} steht in UEBERSETZT, traegt aber keine Auszeichnung.')

    def test_jede_vorlage_der_liste_laesst_sich_kompilieren(self):
        """Jede ausgezeichnete Vorlage laesst sich laden — nicht nur lesen.

        Der Regex-Test oben sieht `{% load i18n %}` auch dann, wenn es VOR
        `{% extends %}` steht. Django verweigert das («extends must be the
        first tag»), die Seite antwortet mit 500. So geschehen mit
        `leerstand_verlauf.html` in der Tranche «Berichte»: Die Datei trug
        vorher gar kein `{% load %}`, das Hilfsskript setzte es an den
        Anfang. Kein anderer Test rendert diese Seite.

        `get_template` kompiliert — Syntaxfehler, unbekannte Tags und falsch
        geschachtelte blocktrans fallen hier auf, ohne dass es Daten braucht.

        Gegenprobe: `{% load i18n %}` in einer Vorlage der Liste vor
        `{% extends %}` setzen — der Test wird rot.
        """
        from django.template.loader import get_template
        for name in UEBERSETZT:
            with self.subTest(vorlage=name):
                get_template(name)

    def test_uebersetzte_auswahl_hat_einen_festen_wert(self):
        """Eine `<option>` mit übersetzter Beschriftung braucht ein `value`.

        Ohne `value` schickt der Browser die BESCHRIFTUNG — in der
        französischen Oberfläche also «Madame» statt «Frau». Gespeichert
        wird dann die Übersetzung, und alles, was den Wert liest (Anrede im
        Brief, Filter, Vergleiche wie `m.anrede == 'Frau'`), greift ins
        Leere. So stand es in `fw/person_form.html` bei Anrede, Zivilstand
        und Erwerbsstatus.

        Gegenprobe: in `fw/person_form.html` bei einer Anrede das
        `value="Frau"` entfernen — der Test wird rot.
        """
        ohne_wert = re.compile(r'<option(?![^>]*\bvalue=)[^>]*>\s*\{%\s*(?:trans|blocktrans)\b')
        for name in UEBERSETZT:
            with self.subTest(vorlage=name):
                text = (WURZEL / 'core' / 'templates' / name).read_text(encoding='utf-8')
                self.assertIsNone(
                    ohne_wert.search(text),
                    f'{name}: <option> mit übersetzter Beschriftung, aber ohne value=')

    def test_die_liste_schrumpft_nicht(self):
        """Sperrklinke: Eine einmal ausgezeichnete Vorlage bleibt es.

        Der umgekehrte Fall zum Farbklassen-Zaehler — dort darf eine Zahl nur
        kleiner werden, hier darf eine Liste nur laenger werden.
        """
        for name in UEBERSETZT:
            with self.subTest(vorlage=name):
                self.assertTrue(
                    (WURZEL / 'core' / 'templates' / name).exists(),
                    f'{name} ist verschwunden — dann gehoert sie auch hier raus.')

    def test_keine_vorlage_faellt_durch_die_liste(self):
        """Wer auszeichnet, traegt es hier ein — sonst prueft nichts es nach."""
        ausgezeichnet = set()
        for pfad in sorted((WURZEL / 'core' / 'templates' / 'fw').glob('*.html')):
            text = pfad.read_text(encoding='utf-8')
            if re.search(r'{%\s*(trans|translate|blocktrans|blocktranslate)\b', text):
                ausgezeichnet.add(f'fw/{pfad.name}')
        fehlend = sorted(ausgezeichnet - set(UEBERSETZT))
        self.assertEqual(
            fehlend, [],
            f'Diese Vorlagen sind ausgezeichnet, stehen aber nicht in '
            f'UEBERSETZT: {fehlend}. Eintragen, damit die Stichprobe sie deckt.')


class UebersetzungWirktTests(SimpleTestCase):

    def test_die_stichprobe_kommt_in_jeder_sprache_richtig_an(self):
        """Der Test, der wirklich zaehlt: gettext ueber den gebauten Katalog.

        Nicht die `.po` gelesen, sondern uebersetzt — damit haengt dieser Test
        an derselben Kette wie die Anwendung: Katalog, `.mo`, `LOCALE_PATHS`.
        """
        for quelle, erwartet in STICHPROBE.items():
            for sprache, soll in erwartet.items():
                with self.subTest(sprache=sprache, text=quelle):
                    with translation.override(sprache):
                        self.assertEqual(
                            translation.gettext(quelle), soll,
                            f'«{quelle}» kommt auf {sprache} als '
                            f'«{translation.gettext(quelle)}» an, erwartet «{soll}».')

    def test_eine_andere_sprache_ist_wirklich_eine_andere(self):
        """Gegenprobe gegen den haeufigsten stillen Fehler.

        Faellt eine Sprache auf Deutsch zurueck — fehlendes `.mo`, falscher
        `LOCALE_PATHS`, Tippfehler im Sprachcode —, sind die Tests oben
        trotzdem gruen, solange das deutsche Wort zufaellig passt. Deshalb
        hier ausdruecklich: Franzoesisch darf nicht Deutsch sein.
        """
        with translation.override('fr'):
            franzoesisch = translation.gettext('Abwesenheiten')
        self.assertNotEqual(
            franzoesisch, 'Abwesenheiten',
            'Franzoesisch liefert den deutschen Text — der Katalog greift nicht.')

class FehlendeWerteTests(SimpleTestCase):
    """`{% blocktrans count %}` bricht ab, wo `pluralize` nur haesslich war.

    WIE WEIT DAS BELEGT IST — damit niemand mehr hineinliest als drinsteht:
    Diese Klasse ist beim Nachgehen einer gemeldeten Fehlerseite entstanden.
    Dass sie DEREN Ursache war, ist NICHT belegt; die drei abgesicherten
    Werte (`vorrat.tage`, `faelle.tage_ohne_bewegung`, `lg_mandate.objekte`)
    koennen heute gar nicht fehlen — nachgesehen: alle drei kommen aus
    `(datum - heute).days`, `len()` bzw. `n_objekte or 0`.

    Die Absicherung ist damit VORSORGE, und zwar begruendete: `blocktrans
    count` bricht bei einem fehlenden Wert hart ab, wo der abgeloeste
    `pluralize`-Filter nur haesslich wurde. Der Unterschied trifft die
    meistbesuchte Seite der Anwendung. Dass die Gefahr real ist, zeigt die
    Parallelarbeit am selben Tag: Dort steht vor demselben Konstrukt ein
    `{% if f.tage %}` — fuer einen Wert, der tatsaechlich `None` sein kann
    (`arbeitsvorrat.py:671` setzt ihn fuer Vertragsentwuerfe).

    DER UNTERSCHIED, UM DEN ES GEHT

    E2.85 hat in `dashboard.html` vier `pluralize`-Filter durch
    `{% blocktrans count %}` ersetzt — fachlich richtig, weil `pluralize`
    eine deutsche Endung anhaengt und in keiner anderen Sprache etwas
    bedeutet. Uebersehen wurde der Unterschied im FEHLERFALL:

        {{ e.tage|pluralize:"en" }}     mit e.tage = None  ->  "in None Tag"
        {% blocktrans count n=e.tage %} mit e.tage = None  ->  TemplateSyntaxError

    Aus einer haesslichen Anzeige wurde damit eine Fehlerseite. Die
    Testsuite hat das nicht gesehen: Die E2E-Saat kennt weder Termine noch
    Mandate noch Abwesenheiten, also lief JEDE dieser Zeilen nur im
    Leerzustand — und im Leerzustand wird die Schleife gar nicht betreten.

    Gruen war die Suite trotzdem, und der Seitendurchlauf lieferte fuer alle
    19 Seiten 200. Was fehlt, ist nicht mehr Abdeckung in der Breite,
    sondern Daten in der Tiefe: dieselbe Seite mit gefuellten Listen.

    WER EINEN ZAEHLER EINBAUT prueft, ob der Wert fehlen kann. Kann er es,
    gehoert ein `{% if ... is not None %}` darum — nicht `|default:0`, denn
    «0 Tage» ist eine Aussage und «kein Datum» ist keine.
    """

    #: Die Felder, die ein `{% blocktrans count %}` in der Tranche speist.
    ZAEHLERFELDER = (
        ('fw/dashboard.html', 'vorrat', 'tage'),
        ('fw/dashboard.html', 'faelle', 'tage_ohne_bewegung'),
        ('fw/dashboard.html', 'lg_mandate', 'objekte'),
        ('fw/abwesenheiten.html', 'laufend', 'offene_faelle'),
    )

    def test_kein_zaehler_bricht_bei_fehlendem_wert_ab(self):
        """Jedes Zaehlerfeld einmal auf None — die Seite muss stehen bleiben."""
        from django.template.loader import get_template
        from django.test import RequestFactory
        from types import SimpleNamespace as N
        import datetime

        anfrage = RequestFactory().get('/neu/')
        anfrage.user = N(username='pruef', get_full_name=lambda: 'Pruef',
                         is_authenticated=True, is_superuser=False,
                         is_staff=False, id=1, pk=1, email='p@example.ch')
        heute = datetime.date(2026, 9, 23)
        jetzt = datetime.datetime(2026, 9, 23, 8, 0)
        wer = N(get_full_name=lambda: 'Lea', username='lea', id=1, pk=1)

        def grund(vorlage, liste, feld):
            eintrag = {
                'vorrat': lambda: N(dringlichkeit='warn', ikon='wartet', marke='',
                                    nummer='', titel='T', fortschritt='', schritt='',
                                    zeile='', wer='', wofuer='', datum=heute,
                                    tage=0, ziel='/', modal=False, knopf='Auf'),
                'faelle': lambda: N(id=1, betreff='B', fallart=N(bezeichnung='F'),
                                    nummer='F-1', get_status_display=lambda: 'Offen',
                                    zustaendig=wer, tage_ohne_bewegung=0),
                'lg_mandate': lambda: N(mandat='M', objekte=1, leer=0, offen=0,
                                        stufe='warn', belegung=90),
                'laufend': lambda: N(benutzer=wer, bis=heute, von=heute,
                                     get_grund_display=lambda: 'Ferien', notiz='',
                                     offene_faelle=1, vertreten_durch_id=None,
                                     vertreten_durch=None),
            }[liste]()
            setattr(eintrag, feld, None)          # DER FEHLENDE WERT
            k = {'request': anfrage, 'heute': heute, 'kw': 39,
                 'ansicht_titel': 'Heute',
                 'ansicht': 'liegen' if liste == 'faelle' else 'heute',
                 'vertretung_fuer': [], 'vorrat': [], 'faelle': [],
                 'lg_mandate': [], 'laufend': [], 'kommend': [], 'vergangen': [],
                 'ansichten': [], 'av_band': [], 'av_eingaenge': [], 'inbox': [],
                 'lg_streifen': [], 'lg_abweichungen': [],
                 'leute': [], 'gruende': [], 'arten': [],
                 'zeilen': [], 'erledigt': [], 'jetzt': jetzt}
            k[liste] = [eintrag]
            return k

        for vorlage, liste, feld in self.ZAEHLERFELDER:
            for sprache in SPRACHEN:
                with self.subTest(vorlage=vorlage, feld=feld, sprache=sprache):
                    with translation.override(sprache):
                        try:
                            get_template(vorlage).render(grund(vorlage, liste, feld))
                        except Exception as fehler:
                            self.fail(
                                f'{vorlage} bricht ab, wenn `{liste}.{feld}` fehlt: '
                                f'{type(fehler).__name__}: {fehler}. '
                                'Ein Zaehler braucht ein `{% if ... is not None %}`.')
