"""Mahnstufen — je Organisation in der Datenbank (`crm.MahnStufe`), nie im Code.

EINE Quelle der Wahrheit. Ab wie vielen Tagen Verzug welche Mahnung fällig wird,
welche Spesen sie auslöst und ob sie die Kündigung nach Art. 257d OR androht,
bestimmt jede Verwaltung selbst (`/neu/mahnstufen/`). Im Programmcode steht
keine Frist: Der Mahnlauf, die Mahnübersicht, die Pendenzen und die
Mahnschreiben fragen alle hier.

Die einzige Stelle, an der Zahlen stehen, ist `STANDARD_MAHNSTUFEN` — der
Startwert, den `standard_mahnstufen_anlegen` einer NEUEN Organisation
mitgibt (und die Datenmigration den bestehenden). Danach gehören die Stufen der
Organisation; der Code liest sie nie wieder aus dieser Konstante.

Übersteuerung je Eigentümer: Hat ein Eigentümer (`crm.Eigentuemer.mahn_konfig`,
JSON) eine eigene Einstellung, legt sie sich über die Stufen seiner
Organisation — aktiv / ab_tage / gebuehr / kuendigung je Stufennummer. Ohne
Eintrag gelten die Stufen der Organisation unverändert.
"""
from decimal import Decimal

#: Startwert für neue Organisationen: (Stufe, Bezeichnung, ab Tagen, Spesen, Art. 257d).
#: NUR zum Anlegen — keine Laufzeitlogik liest diese Liste.
STANDARD_MAHNSTUFEN = (
    (1, '1. Mahnung - Erste Zahlungserinnerung', 14, Decimal('0.00'), False),
    (2, '2. Mahnung - Zweite schriftliche Erinnerung', 30, Decimal('20.00'), False),
    (3, '3. Mahnung - Letzte Mahnung (Fristansetzung nach Art. 257d OR)', 60,
     Decimal('40.00'), True),
)

# Farben der Oberfläche: die erste Stufe ist die milde, alle weiteren die strengen.
_CLS_MILD = 'fw-warn-flaeche fw-warnton'
_CLS_STRENG = 'fw-krit-flaeche fw-kritisch'


def standard_mahnstufen_anlegen(organisation):
    """Legt die Standardstufen für eine Organisation an — nur wo noch keine existiert.

    Idempotent: Ein zweiter Aufruf ändert nichts, und eine Organisation, die ihre
    Stufe 1 bearbeitet hat, bekommt sie nicht zurückgesetzt.
    """
    from crm.models import MahnStufe

    # alle_organisationen: Das Anlegen läuft beim Speichern der Organisation und
    # in der Datenmigration — beide ohne Mandantenkontext. Die Grenze steht im
    # Ausdruck (organisation=…).
    vorhanden = set(MahnStufe.alle_organisationen
                    .filter(organisation=organisation).values_list('stufe', flat=True))
    for stufe, bezeichnung, ab_tage, gebuehr, art_257d in STANDARD_MAHNSTUFEN:
        if stufe not in vorhanden:
            MahnStufe.objects.create(organisation=organisation, stufe=stufe,
                                     bezeichnung=bezeichnung, ab_tage=ab_tage,
                                     gebuehr=gebuehr, art_257d=art_257d)


def _organisation_bestimmen(eigentuemer, organisation):
    if organisation is not None:
        return organisation
    org = getattr(eigentuemer, 'organisation', None)
    if org is not None:
        return org
    from core.organisation_kette import organisation_bestimmen
    return organisation_bestimmen()


def _als_dict(zeile, erste):
    return {
        'stufe': zeile.stufe, 'id': zeile.pk, 'name': zeile.bezeichnung,
        'ab_tage': zeile.ab_tage, 'gebuehr': Decimal(zeile.gebuehr),
        'kuendigung': zeile.art_257d, 'aktiv': True,
        # `label` ist, was die Oberfläche anzeigt; die Bezeichnung gehört der Verwaltung.
        'label': zeile.bezeichnung, 'unter': '',
        'cls': _CLS_MILD if erste else _CLS_STRENG,
        'dot': 'fw-warn-voll' if erste else 'fw-krit-voll',
    }


def stufen_der_organisation(organisation):
    """Alle Stufen der Organisation, aufsteigend nach Stufennummer (Dicts)."""
    from crm.models import MahnStufe

    # Der Filter organisation=… ist ausdrücklich: Der Aufrufer kennt die
    # Organisation (Rechnung, Eigentümer oder Kontext), nicht der Manager.
    zeilen = list(MahnStufe.alle_organisationen
                  .filter(organisation=organisation).order_by('stufe'))
    return [_als_dict(z, i == 0) for i, z in enumerate(zeilen)]


def _uebersteuert(stufen, eigentuemer):
    """Legt die JSON-Einstellung eines Eigentümers über die Stufen der Organisation."""
    roh = getattr(eigentuemer, 'mahn_konfig', None) if eigentuemer is not None else None
    if not roh:
        return stufen
    nach_stufe = {}
    for c in roh:
        try:
            nach_stufe[int(c['stufe'])] = c
        except (KeyError, TypeError, ValueError):
            continue
    ergebnis = []
    for s in stufen:
        c = nach_stufe.get(s['stufe'])
        if c is None:
            ergebnis.append(s)
            continue
        s = dict(s)
        s['aktiv'] = bool(c.get('aktiv', True))
        try:
            s['ab_tage'] = max(0, int(c.get('ab_tage', s['ab_tage'])))
        except (TypeError, ValueError):
            pass
        try:
            s['gebuehr'] = Decimal(str(c.get('gebuehr', s['gebuehr'])))
        except Exception:
            pass
        s['kuendigung'] = bool(c.get('kuendigung', s['kuendigung']))
        ergebnis.append(s)
    return ergebnis


def mahnstufen_config(eigentuemer=None, organisation=None):
    """Effektive, AKTIVE Mahnstufen — absteigend nach `ab_tage` (strengste zuerst).

    `organisation` bestimmt, wessen Stufen gelten; ohne Angabe die des
    Eigentümers, sonst die des Mandantenkontexts (fehlt beides: Fehler).
    """
    org = _organisation_bestimmen(eigentuemer, organisation)
    stufen = [s for s in _uebersteuert(stufen_der_organisation(org), eigentuemer)
              if s['aktiv']]
    stufen.sort(key=lambda x: x['ab_tage'], reverse=True)
    return stufen


def stufe_fuer_tage(tage, eigentuemer=None, organisation=None):
    """Höchste erreichte Stufe (dict) bei `tage` Verzug — oder None."""
    for s in mahnstufen_config(eigentuemer, organisation):
        if tage >= s['ab_tage']:
            return s
    return None


class Mahnstufen:
    """Dieselben Auskünfte wie die Modulfunktionen, aber mit einmal geladenen Stufen.

    Für Schleifen über viele Rechnungen (Mahnlauf, Mahnübersicht, Liste): Die
    Stufen einer Organisation werden einmal gelesen statt je Rechnung. Der
    Speicher lebt nur so lang wie das Objekt — kein Cache über Anfragen hinweg,
    eine geänderte Einstellung gilt also sofort beim nächsten Aufruf.
    """

    def __init__(self):
        self._je_organisation = {}

    def config(self, eigentuemer=None, organisation=None):
        org = _organisation_bestimmen(eigentuemer, organisation)
        if org.pk not in self._je_organisation:
            self._je_organisation[org.pk] = stufen_der_organisation(org)
        stufen = [s for s in _uebersteuert(self._je_organisation[org.pk], eigentuemer)
                  if s['aktiv']]
        return sorted(stufen, key=lambda x: x['ab_tage'], reverse=True)

    def stufe_fuer_tage(self, tage, eigentuemer=None, organisation=None):
        for s in self.config(eigentuemer, organisation):
            if tage >= s['ab_tage']:
                return s
        return None

    def tage_im_verzug(self, faellig, heute, eigentuemer=None, organisation=None):
        """Tage seit Fälligkeit — oder None, solange der Verzug nach der Einstellung
        der Organisation (`mahn_verzug_ab_tag`) noch nicht begonnen hat.

        Der Fälligkeitstag ist Tag 0. Mit `mahn_verzug_ab_tag = 0` ist eine am 1.
        fällige Miete am 1. im Mahnlauf sichtbar, mit 1 erst am 2.
        """
        org = _organisation_bestimmen(eigentuemer, organisation)
        tage = (heute - faellig).days
        return tage if tage >= org.mahn_verzug_ab_tag else None


def roh_konfig(eigentuemer, organisation=None):
    """Alle Stufen der Organisation (auch inaktive) zum BEARBEITEN der
    Eigentümer-Übersteuerung — aufsteigend nach Stufennummer."""
    org = _organisation_bestimmen(eigentuemer, organisation)
    return [dict(s, gebuehr=str(s['gebuehr']))
            for s in _uebersteuert(stufen_der_organisation(org), eigentuemer)]


def gebuehr_fuer_stufe(stufe, eigentuemer=None, organisation=None):
    """Konfigurierte Mahngebühr (Decimal) einer Stufe — auch wenn sie inaktiv ist.
    Unbekannte Stufe: 0.00."""
    org = _organisation_bestimmen(eigentuemer, organisation)
    for s in _uebersteuert(stufen_der_organisation(org), eigentuemer):
        if s['stufe'] == stufe:
            return Decimal(s['gebuehr'])
    return Decimal('0.00')


def eigentuemer_von_rechnung(r):
    """Eigentuemer (Eigentuemer) einer DebitorenRechnung ueber ihre Liegenschaft."""
    lg = getattr(r, 'liegenschaft', None)
    if lg is None and getattr(r, 'vertrag_id', None) and getattr(r.vertrag, 'einheit_id', None):
        lg = r.vertrag.einheit.liegenschaft
    return getattr(lg, 'eigentuemer', None) if lg is not None else None


def pruefe_reihenfolge(zeilen):
    """Prüft eine geplante Stufenliste `[(stufe, ab_tage), …]`.

    Eine höhere Stufe muss später greifen als die niedrigere — sonst wäre
    «3. Mahnung» vor der «2. Mahnung» erreicht. Gibt das erste fehlerhafte Paar
    `(stufe_niedrig, tage_niedrig, stufe_hoch, tage_hoch)` zurück, sonst None.
    """
    zeilen = sorted(zeilen)
    for (s1, t1), (s2, t2) in zip(zeilen, zeilen[1:]):
        if t2 <= t1:
            return s1, t1, s2, t2
    return None


def mahnlauf_tag_im_monat(organisation):
    """Tag im Monat, ab dem der Mahnlauf etwas mahnen kann — aus den Mahnstufen, nicht fest.

    Die Miete ist am 1. des Monats fällig. Gemahnt werden kann frühestens, wenn
    die erste aktive Stufe erreicht UND der Verzug nach der Einstellung der
    Organisation (`mahn_verzug_ab_tag`) begonnen hat:

        Tag = 1 + max(ab_tage der ersten Stufe, Verzugsbeginn)

    Stufe 1 ab 14 Tagen → 15. · Stufe 1 ab 0 Tagen → 1. · ab 10 Tagen → 11.
    Ohne aktive Stufe gibt es keinen Termin: `None` (der Aufrufer behält dann
    seinen bisherigen Tag).
    """
    stufen = [s for s in stufen_der_organisation(organisation) if s['aktiv']]
    if not stufen:
        return None
    erste = min(s['ab_tage'] for s in stufen)
    return 1 + max(erste, organisation.mahn_verzug_ab_tag)
