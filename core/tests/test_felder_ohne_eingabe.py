"""Ein Feld im Modell braucht einen Weg, es zu füllen.

DER ANLASS

E2.46 hat `Organisation.stundensatz` ins Modell gelegt und in der Fallakte
angezeigt. **Erfassen konnte man ihn nirgends** — E2.47 musste das nachholen.
Zwei Etappen zuvor dasselbe: `faelle.Zeiteintrag` stand seit der ersten
Migration im Code und wurde von niemandem benutzt, weil es kein Formular gab.

Zweimal derselbe Fehler, beim zweiten Mal von Dominik bemerkt statt von einem
Test. Dieser Wächter schliesst die Lücke.

WAS ER PRÜFT

Für jedes Feld, das ein **Mensch** setzen müsste, muss es einen Weg geben:
ein `name="…"` in einer Vorlage oder ein `v-model="form.…"` (Vue). Fehlt
beides, zählt hilfsweise eine blosse Erwähnung des Namens — mit den Grenzen,
die weiter unten stehen.

WARUM ÜBERHAUPT GEFILTERT WIRD

Ohne den `STILL`-Filter meldet die Suche **62** Felder. Die allermeisten davon
zu Recht ohne Formular: Hashes, Token, IP-Adressen, Zeitstempel,
Django-Systemfelder. Ein Wächter mit dieser Liste wäre nutzlos — er würde beim
ersten Blick weggeklickt, und dann meldet er auch den echten Fall vergeblich.

Gefiltert wird deshalb auf das, was ein Mensch eingibt. Die Ausnahmen stehen
in `STILL` und sind einzeln begründet.

(Der erste Entwurf nannte hier 72. Nachgezählt sind es 62 — dieselbe Aussage,
aber eine Zahl, die stimmt.)

DIE GRENZE DIESER MESSUNG — NACHGEZÄHLT

Sie sucht Zeichenketten. Der erste Entwurf nannte als Blindstelle nur
`ModelForm` mit `fields = '__all__'`. Nachgezählt ist die Lücke viel grösser,
und das muss dastehen, damit niemand dem Wächter mehr zutraut als er kann.

Von den geprüften Feldern bestehen:

  542  über einen ECHTEN Eingabeweg — `name="…"` in einer Vorlage oder
       `form.…` in einem Vue-Formular. Das ist der harte Teil.

  239  NUR, weil ihr Name irgendwo in Anführungszeichen vorkommt. Das kann
       ein Formular sein — oder ein Wörterbuchschlüssel, ein `order_by`, eine
       Protokollzeile. Für diese Felder sagt der Wächter nichts aus.

Ein engerer Abgleich (Name als POST-Schlüssel oder in einer `fields`-Liste)
wurde durchgerechnet: Er liesse **81** Felder rot. Die meisten davon zu Recht
still — `MietzinsAnpassung.alter_lik_index` etwa entsteht in der Berechnung.
Sie alle einzeln einzuordnen ist eigene Arbeit; solange das nicht geschehen
ist, bleibt der weite Abgleich UND die Zahl 239 steht als Sperrklinke
(`test_der_lose_abgleich_wird_nicht_grosszuegiger`), damit die Blindstelle
nicht unbemerkt wächst.

WAS ER DAFÜR SICHER KANN: Der Fall, für den er gebaut wurde, wird gefunden.
Nachgestellt, indem der Eingabeweg aus E2.47 wieder entfernt wurde —
`crm.Organisation.stundensatz` wird gemeldet.

DREI LISTEN, DREI VERSCHIEDENE SACHVERHALTE

Der erste Entwurf hatte zwei und gab allen sechzehn Einträgen der zweiten
denselben Satz mit: «wird angezeigt, aber nirgends erfasst». Nachgesehen
stimmte das für neun. Die übrigen sieben waren zweierlei anderes — und ein
falscher Grund in einer gepflegten Liste ist schlimmer als kein Grund: Er
sieht aus wie eine Feststellung.

  AUSNAHMEN       Der Code füllt das Feld. Erledigt.
  OFFENE_LUECKEN  Angezeigt, nicht erfassbar. Eine halbe Funktion.
  TOTE_SPALTEN    Steht nur in der eigenen Modelldefinition — nirgends
                  gelesen, nirgends geschrieben, nirgends gezeigt.
"""
import functools
import pathlib

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Die eigenen Anwendungen. Fremde Modelle (Django, Bibliotheken) gehen uns
#: nichts an.
EIGEN = ('core', 'crm', 'faelle', 'finance', 'portfolio', 'rentals',
         'tickets', 'mietprozess', 'benutzer')

#: Namensteile von Feldern, die KEIN Mensch eingibt.
#:
#: `hash`, `geheim`, `token`     Geheimnisse — nie in ein Formular
#: `ip_`, `_am`, `erstellt`      Protokoll: setzt das System
#: `is_`, `permissions`, …       Django-Systemfelder
#: `anonymisiert`                setzt der Löschlauf, nicht die Sachbearbeiterin
STILL = ('hash', 'geheim', 'token', 'ip_', '_am', 'anonymisiert', 'is_',
         'date_joined', 'permissions', 'password', 'last_login', 'erstellt',
         'geaendert', 'angelegt')

#: Felder, die der CODE fuellt — nicht ein Mensch. Mit Begruendung.
#:
#: Wer hier etwas eintraegt, sagt: «Das setzt ein Lauf, ein Import oder eine
#: Vorlage.» Wer es weglaesst und trotzdem kein Formular baut, wird rot.
AUSNAHMEN = {
    'faelle.Eingang.absender_email': 'kommt aus dem Postfach',
    'faelle.Eingang.absender_norm': 'aus `absender_email` normalisiert',
    'faelle.Fallschritt.etappe': 'von der Vorlage uebernommen',
    'faelle.Fallschritt.etappe_nr': 'von der Vorlage uebernommen',
    'faelle.Fallschritt.vorlage': 'beim Anlegen aus der Vorlage gesetzt',
    'faelle.Regel.verbindlichkeit': 'setzt `regelwerk_grundsatz`',
    'faelle.Regelanwendung.geprueft_war': 'Protokoll der Anwendung',
    'faelle.SchrittVorlage.etappe': 'aus der Fallart-Vorlage berechnet',
    'faelle.SchrittVorlage.etappe_nr': 'aus der Fallart-Vorlage berechnet',
    'faelle.SchrittVorlage.frist_regel': 'Regelwerk, nicht Formular',
    'finance.Bankbewegung.bank_referenz': 'entsteht im Lauf oder Import, nicht von Hand',
    # Nachgesehen in E2.49: Diese zwei standen als «offene Lücke» da, obwohl
    # der Code sie setzt. Sie gehören hierher.
    'finance.Buchung.storno_von':
        'setzt `finance/booking.py` beim Anlegen der Gegenbuchung '
        '(verkettet Original mit Storno)',
    'finance.LieferantProfil.standard_konto':
        'setzt `finance/lieferanten.py` aus der gelernten Zuordnung',
    'finance.DebitorenRechnung.pdf_dokument': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.DebitorenRechnung.qr_referenz': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.DebitorenRechnung.quell_kreditor': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.DebitorenRechnung.stammrechnung': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.Kontoauszug.dateiname': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.Kontoauszug.eroeffnungssaldo': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.Kontoauszug.importiert_von': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.Kontoauszug.schlusssaldo': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.KreditorenZahlung.bank_referenz': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.Mahnung.betrag_offen': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.NebenkostenLernRegel.kategorie_zuweisung': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.NebenkostenLernRegel.treffer_quote': 'entsteht im Lauf oder Import, nicht von Hand',
    'finance.Zahlungseingang.bank_referenz': 'entsteht im Lauf oder Import, nicht von Hand',
    'portfolio.EinheitFoto.bild': 'entsteht im Lauf oder Import, nicht von Hand',
    'portfolio.LiegenschaftVerteilschluessel.gueltig_bis': 'entsteht im Lauf oder Import, nicht von Hand',
    'portfolio.Verteilschluessel.gueltig_bis': 'entsteht im Lauf oder Import, nicht von Hand',
    'rentals.Kuendigung.ende_vorher': 'entsteht im Lauf oder Import, nicht von Hand',
    'rentals.Mietvertrag.index_letzte_anpassung': 'entsteht im Lauf oder Import, nicht von Hand',
    'tickets.SchadenFoto.bild': 'entsteht im Lauf oder Import, nicht von Hand',
    'tickets.SchadenFoto.hochgeladen_von': 'entsteht im Lauf oder Import, nicht von Hand',
    'tickets.TicketNachricht.empfaenger_handwerker': 'entsteht im Lauf oder Import, nicht von Hand',
}

#: OFFENE LUECKEN — angezeigt, aber nirgends erfassbar.
#:
#: Diese Felder stehen auf einer Seite und lassen sich nicht eingeben. Das ist
#: KEINE Entscheidung, sondern eine halbe Funktion, die ganz aussieht — genau
#: das, was der Auftrag verbietet («Halbfertige Funktionen werden
#: fertiggestellt oder entfernt»).
#:
#: Sie stehen getrennt von `AUSNAHMEN`, damit der Unterschied sichtbar bleibt:
#: Eine Ausnahme ist erledigt, eine Luecke wartet. Die Liste soll SCHRUMPFEN.
#:
#: `Mietvertrag.kuendigungsfrist_monate` ist der eindruecklichste Fall: E2.37
#: hat damit die Zustellfrist einer Mietzinsaenderung gerechnet — auf einem
#: Wert, den niemand eingeben kann.
#: Jede Zeile nennt die Vorlage, in der das Feld ERSCHEINT — nachgesehen, statt
#: behauptet. Ohne diesen Beleg wäre «wird angezeigt» eine Vermutung.
OFFENE_LUECKEN = {
    'finance.Buchung.ist_storno': 'steht in fw/kontoblatt.html',
    'finance.Buchung.zahlungseingang': 'steht in fw/buchhaltung.html',
    'portfolio.Einheit.gehoert_zu': 'steht in fw/objekt_form.html',
    'rentals.AbnahmeMangel.kostenschaetzung': 'steht in fw/abnahme_detail.html',
    'rentals.AbnahmeMangel.mieteranteil': 'steht in fw/abnahme_detail.html',
    'rentals.AbnahmeMangel.verursacher': 'steht in fw/abnahme_detail.html',
    'rentals.Mietvertrag.index_intervall_monate': 'steht in core/mietvertrag_pdf.html',
    'rentals.Mietvertrag.index_weitergabe_prozent': 'steht in core/mietvertrag_pdf.html',
    'rentals.Mietvertrag.kuendigungsfrist_monate': 'steht in fw/kuendigung_form.html',
}

#: TOTE SPALTEN — nirgends gezeigt, nirgends gelesen, nirgends geschrieben.
#:
#: Diese fünf Felder kommen im ganzen Bestand NUR in ihrer eigenen
#: Modellzeile vor. Das ist etwas anderes als eine offene Lücke: Dort wartet
#: eine halbe Funktion, hier steht eine Spalte, die niemand benutzt.
#:
#: SIE WERDEN HIER NICHT ENTFERNT. Ein Modellfeld zu streichen heisst eine
#: Migration über den Produktivbestand — das ist eine fachliche Entscheidung
#: («Soll die Reserve je erfasst werden?»), keine technische. Der Wächter
#: benennt sie und hält die Zahl fest; entschieden wird sie anderswo.
#:
#: (E2.49 führte `mietzinsreserve_betrag` als Beispiel für ein ANGEZEIGTES
#: Feld an. Nachgesehen steht es in keiner Vorlage.)
TOTE_SPALTEN = {
    'portfolio.Einheit.heizkosten_verteilschluessel':
        'nur portfolio/models.py:173 — Auswahlliste ohne Abnehmer',
    'portfolio.Liegenschaft.kaufdatum':
        'nur portfolio/models.py:43',
    'rentals.Mietvertrag.mietzinsreserve_betrag':
        'nur rentals/models.py:138',
    'rentals.Mietvertrag.mietzinsreserve_prozent':
        'nur rentals/models.py:139',
    'tickets.TicketNachricht.cc_email':
        'nur tickets/models.py:137 — die Nachricht kennt kein CC-Feld',
}


def _quellen():
    """Vorlagen und View-Code als ein Text.

    Vue-Formulare schreiben `v-model="form.geschlecht"` statt
    `name="geschlecht"` — beides zählt. Ein erster Entwurf kannte nur `name=`
    und meldete zehn Bewerbungsfelder als eingabelos; sie stehen alle im
    Vue-Formular.
    """
    teile = []
    for ordner in ('core/templates', 'templates'):
        p = WURZEL / ordner
        if p.exists():
            teile += [q.read_text(encoding='utf-8') for q in p.rglob('*.html')]
    for q in WURZEL.rglob('*.py'):
        t = q.as_posix()
        if any(x in t for x in ('node_modules', '/test', 'migrations')):
            continue
        teile.append(q.read_text(encoding='utf-8'))
    return '\n'.join(teile)


#: Ein echter Eingabeweg: ein Formularfeld oder eine Vue-Bindung.
def _echter_weg(name, text):
    return any(x in text for x in (f'name="{name}"', f"name='{name}'",
                                   f'form.{name}'))


#: Der Name irgendwo in Anführungszeichen. Das KANN ein Formular sein — oder
#: ein Wörterbuchschlüssel, ein `order_by`, eine Protokollzeile. Siehe den
#: Kopf: Für diese Felder sagt der Wächter nichts aus.
def _nur_erwaehnt(name, text):
    return any(x in text for x in (f"'{name}'", f'"{name}"'))


@functools.lru_cache(maxsize=1)
def _einordnung():
    """Jedes geprüfte Feld einmal einsortieren.

    `_quellen()` liest den halben Bestand; das dauert ein paar Sekunden und
    soll nicht viermal laufen.
    """
    text = _quellen()
    gelistet, echt, lose, offen = [], [], [], []
    for modell in apps.get_models():
        if modell._meta.app_label not in EIGEN:
            continue
        for feld in modell._meta.get_fields():
            if not getattr(feld, 'editable', False) or feld.auto_created:
                continue
            name = feld.name
            if name in ('id', 'organisation'):
                continue
            if any(s in name for s in STILL):
                continue
            if getattr(feld, 'auto_now', False) or getattr(feld, 'auto_now_add', False):
                continue
            voll = f'{modell._meta.label}.{name}'
            if voll in AUSNAHMEN or voll in OFFENE_LUECKEN or voll in TOTE_SPALTEN:
                gelistet.append(voll)
            elif _echter_weg(name, text):
                echt.append(voll)
            elif _nur_erwaehnt(name, text):
                lose.append(voll)
            else:
                offen.append(voll)
    return {'gelistet': gelistet, 'echt': echt, 'lose': lose, 'offen': offen}


class FelderOhneEingabewegTest(SimpleTestCase):

    def test_jedes_menschenfeld_hat_einen_weg(self):
        fehlend = sorted(_einordnung()['offen'])
        self.assertEqual(
            fehlend, [],
            'Diese Felder lassen sich nirgends eingeben:\n  '
            + '\n  '.join(fehlend)
            + '\n\nEntweder fehlt das Formular — dann ist die Funktion nur '
              'halb da und sieht ganz aus — oder das Feld füllt der Code; '
              'dann gehört es mit Begründung in AUSNAHMEN.')

    def test_der_lose_abgleich_wird_nicht_grosszuegiger(self):
        """Die Blindstelle darf schrumpfen, nicht wachsen.

        239 Felder bestehen nur, weil ihr Name irgendwo in Anführungszeichen
        steht — ohne belegten Eingabeweg (siehe Kopf). Das ist die Grenze
        dieses Wächters, und sie muss sichtbar bleiben: Ohne diese Zahl könnte
        die stille Menge wachsen, während der Wächter grün bleibt und immer
        weniger prüft.

        Nur eine Obergrenze, keine Untergrenze — anders als bei
        `OFFENE_LUECKEN`. Die Liste dort ist gepflegt und soll beim
        Schrumpfen nachgeführt werden; diese Zahl ist eine Messung und darf
        von selbst sinken.
        """
        lose = _einordnung()['lose']
        self.assertLessEqual(
            len(lose), 239,
            f'Es sind {len(lose)} Felder ohne belegten Eingabeweg geworden '
            f'(vorher 239). Für ein neues Feld bitte einen echten Weg bauen '
            f'(`name="…"` oder `form.…`), statt sich auf eine beliebige '
            f'Erwähnung zu verlassen.')

    def test_ein_echter_weg_wird_von_einer_blossen_erwaehnung_unterschieden(self):
        """Sonst wäre die Zahl oben ohne Bedeutung."""
        self.assertTrue(_echter_weg('stundensatz', 'x name="stundensatz" y'))
        self.assertTrue(_echter_weg('geschlecht', 'v-model="form.geschlecht"'))
        self.assertFalse(_echter_weg('kaufdatum', "sortieren nach 'kaufdatum'"))
        self.assertTrue(_nur_erwaehnt('kaufdatum', "sortieren nach 'kaufdatum'"))

    def test_die_suche_findet_ueberhaupt_felder(self):
        """Sonst wäre der Test oben trivial grün."""
        anzahl = sum(1 for m in apps.get_models()
                     if m._meta.app_label in EIGEN
                     for f in m._meta.get_fields()
                     if getattr(f, 'editable', False) and not f.auto_created)
        self.assertGreater(anzahl, 200, f'Nur {anzahl} Felder gefunden.')

    def test_die_gelisteten_felder_gibt_es_noch(self):
        """Ein Eintrag für ein gelöschtes Feld ist toter Ballast.

        Er sieht aus wie eine Entscheidung und ist keine mehr — und beim
        nächsten Lesen fragt sich jemand, warum das Feld nicht zu finden ist.
        """
        vorhanden = {f'{m._meta.label}.{f.name}'
                     for m in apps.get_models() if m._meta.app_label in EIGEN
                     for f in m._meta.get_fields()}
        for liste, was in ((AUSNAHMEN, 'AUSNAHMEN'),
                           (OFFENE_LUECKEN, 'OFFENE_LUECKEN'),
                           (TOTE_SPALTEN, 'TOTE_SPALTEN')):
            with self.subTest(liste=was):
                veraltet = sorted(set(liste) - vorhanden)
                self.assertEqual(
                    veraltet, [],
                    f'{was} nennt Felder, die es nicht mehr gibt: {veraltet}')

    def test_die_luecken_werden_nicht_mehr(self):
        """Die Listen sollen schrumpfen, nicht wachsen.

        Ohne diese Zahlen wären sie eine Ablage: Wer ein Feld anlegt und kein
        Formular baut, trägt es ein und ist fertig. Genau das soll der Wächter
        verhindern.

        Beide Richtungen sind zugesichert. Sinkt eine Zahl, ist der Test rot —
        das ist Absicht: Eine Obergrenze, die über dem Ist liegt, sperrt
        nichts, und ein geschlossener Fall soll hier vermerkt werden.
        """
        self.assertEqual(
            len(OFFENE_LUECKEN), 9,
            f'{len(OFFENE_LUECKEN)} statt 9 offene Lücken. Wer ein Feld '
            f'anlegt, baut auch den Weg dorthin — oder trägt es mit '
            f'Begründung in AUSNAHMEN ein. Wer eine schliesst, führt die '
            f'Zahl hier nach.')
        self.assertEqual(
            len(TOTE_SPALTEN), 5,
            f'{len(TOTE_SPALTEN)} statt 5 tote Spalten. Eine neue tote Spalte '
            f'gehört nicht angelegt; eine entfernte gehört hier gestrichen.')

    def test_jedes_feld_steht_in_hoechstens_einer_liste(self):
        """Ein Feld ist entschieden, offen oder tot — nicht zweierlei.

        Steht es in zweien, gilt die erste Prüfung, und die zweite Aussage ist
        unsichtbar falsch. Derselbe Fall wie beim Zeichensatz, wo `share`
        gleichzeitig entschieden und offen geführt wurde — und derselbe Fall
        wie hier in E2.49, wo `Buchung.storno_von` als offene Lücke geführt
        wurde, obwohl `finance/booking.py` es setzt.
        """
        for a, b, wie in ((AUSNAHMEN, OFFENE_LUECKEN, 'AUSNAHMEN/OFFENE_LUECKEN'),
                          (AUSNAHMEN, TOTE_SPALTEN, 'AUSNAHMEN/TOTE_SPALTEN'),
                          (OFFENE_LUECKEN, TOTE_SPALTEN, 'OFFENE_LUECKEN/TOTE_SPALTEN')):
            with self.subTest(paar=wie):
                doppelt = sorted(set(a) & set(b))
                self.assertEqual(doppelt, [], f'In beiden Listen ({wie}): {doppelt}')

    def test_die_toten_spalten_sind_wirklich_tot(self):
        """Sonst steht eine Behauptung im Code, die niemand nachgeprüft hat.

        «Kommt nur in der eigenen Modellzeile vor» ist eine Messung, keine
        Einschätzung — also wird sie gemessen. Fängt jemand an, das Feld zu
        benutzen, gehört es aus dieser Liste heraus.
        """
        text = _quellen()
        for voll in sorted(TOTE_SPALTEN):
            name = voll.split('.')[-1]
            with self.subTest(feld=voll):
                # In `_quellen()` sind die Modelldateien enthalten; genau ein
                # Vorkommen ist die Felddefinition selbst.
                self.assertLessEqual(
                    text.count(name), 1,
                    f'{voll} kommt {text.count(name)}-mal vor und ist damit '
                    f'nicht mehr tot — bitte in OFFENE_LUECKEN verschieben '
                    f'oder den Eingabeweg bauen.')
