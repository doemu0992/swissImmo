"""Der eine Platzhalter-Dienst (Modul 5, 27.10.2026).

Bis hierher gab es drei Ersetzer, jeder mit eigenen Namen:

- `{mieter_name}`, `{objekt}`, `{vermieter}` … in den Vorlagen
  (`core/services/ticket_workflow.py`, Hilfe in `fw_vorlage_form`),
- `{name}`, `{anrede}`, `{adresse}` … im Serienbrief
  (`core/services/serienbrief.py`),
- `{monat}`, `{betrag}`, `{gebuehr}`, `{mieter}` im Mahnschreiben
  (`crm.MahnStufe.brief_text`, `core/services/mahnbrief.py`).

Dieser Dienst führt eine Registry mit Gruppen (`{gruppe.feld}`), baut den
Kontext aus dem Bestand und ersetzt. Die alten Schreibweisen bleiben gültig:
Sie stehen in `ALIASE` und zeigen auf ihren neuen Schlüssel (oder auf keinen,
wenn ihr Wert nur aus ihrem eigenen Zusammenhang kommt — ein Ticket, eine
Mahnung). So bricht keine Vorlage in Kundendaten.

Regeln, die der Editor durchsetzt:

- Ein Platzhalter, den weder die Registry noch `ALIASE` kennt, wird beim
  Speichern abgelehnt (`unbekannte`).
- Ein Platzhalter, für den der Kontext keinen Wert hat, bleibt stehen. Ein
  sichtbares `{vertrag.ende}` im Probedruck ist ehrlicher als eine Lücke.

Werte rechnet dieser Dienst NICHT neu: Beträge und Vertragsdaten kommen aus
`build_vertrag_context` (`core/services/pdf_service.py`), Absender und
Zustelladresse aus `_kontext` (`core/services/mietprozess_briefe.py`).
"""
import re
from collections import OrderedDict
from dataclasses import dataclass

from django.utils import timezone
from django.utils.html import escape as _html_escape
from django.utils.translation import gettext, gettext_lazy as _


@dataclass(frozen=True)
class Platzhalter:
    schluessel: str        # 'mieter.name'
    beschriftung: str      # Anzeige im Editor
    beispiel: str          # Wert der Vorschau ohne echten Datensatz
    gruppe: str            # 'mieter'

    @property
    def code(self):
        return '{' + self.schluessel + '}'


GRUPPEN = OrderedDict([
    ('mieter', _('Mieter')),
    ('objekt', _('Objekt')),
    ('vertrag', _('Vertrag')),
    ('verwaltung', _('Verwaltung')),
    ('bewerbung', _('Bewerbung')),
    ('datum', _('Datum')),
])


def _p(schluessel, beschriftung, beispiel):
    return Platzhalter(schluessel, beschriftung, beispiel, schluessel.split('.', 1)[0])


#: Die Registry. Reihenfolge = Reihenfolge der Chips im Editor.
REGISTRY = OrderedDict((p.schluessel, p) for p in (
    _p('mieter.anrede', _('Briefanrede'), 'Sehr geehrte Frau Frei'),
    _p('mieter.anrede_kurz', _('Anrede (Frau/Herr)'), 'Frau'),
    _p('mieter.name', _('Vor- und Nachname'), 'Lea Frei'),
    _p('mieter.vorname', _('Vorname'), 'Lea'),
    _p('mieter.nachname', _('Nachname'), 'Frei'),
    _p('mieter.adresse', _('Zustelladresse'), 'Bergweg 3, 8400 Winterthur'),
    _p('mieter.strasse', _('Strasse'), 'Bergweg 3'),
    _p('mieter.plz', _('PLZ'), '8400'),
    _p('mieter.ort', _('Ort'), 'Winterthur'),
    _p('mieter.email', _('E-Mail'), 'lea.frei@example.ch'),
    _p('objekt.bezeichnung', _('Bezeichnung des Objekts'), '3.5-Zimmer-Wohnung, 2. OG'),
    _p('objekt.adresse', _('Adresse der Liegenschaft'), 'Seestrasse 12, 8000 Zürich'),
    _p('objekt.strasse', _('Strasse der Liegenschaft'), 'Seestrasse 12'),
    _p('objekt.plz', _('PLZ der Liegenschaft'), '8000'),
    _p('objekt.ort', _('Ort der Liegenschaft'), 'Zürich'),
    _p('objekt.zimmer', _('Zimmerzahl'), '3.5'),
    _p('vertrag.beginn', _('Mietbeginn'), '01.01.2027'),
    _p('vertrag.ende', _('Mietende'), '31.12.2029'),
    _p('vertrag.mietzins_netto', _('Nettomietzins (CHF)'), "2'450.00"),
    _p('vertrag.nebenkosten', _('Nebenkosten (CHF)'), "220.00"),
    _p('vertrag.mietzins_brutto', _('Bruttomietzins (CHF)'), "2'670.00"),
    _p('vertrag.kaution', _('Kaution (CHF)'), "7'350.00"),
    _p('verwaltung.name', _('Name der Verwaltung'), 'Muster Verwaltung AG'),
    _p('verwaltung.adresse', _('Adresse der Verwaltung'), 'Seestrasse 1, 8000 Zürich'),
    _p('verwaltung.telefon', _('Telefon der Verwaltung'), '044 000 00 00'),
    _p('verwaltung.email', _('E-Mail der Verwaltung'), 'info@muster-verwaltung.ch'),
    _p('verwaltung.sachbearbeiter', _('Betreut von (Liegenschaft)'), 'Anna Muster'),
    _p('verwaltung.vermieter', _('Vermieter (Eigentümer, sonst Verwaltung)'), 'Muster Verwaltung AG'),
    _p('bewerbung.name', _('Name der Bewerberin / des Bewerbers'), 'Lea Frei'),
    _p('bewerbung.email', _('E-Mail aus der Bewerbung'), 'lea.frei@example.ch'),
    _p('bewerbung.telefon', _('Telefon aus der Bewerbung'), '079 000 00 00'),
    _p('bewerbung.bezugstermin', _('Gewünschter Bezugstermin'), '01.01.2027'),
    _p('datum.heute', _('Heutiges Datum'), '27.10.2026'),
    _p('datum.jahr', _('Laufendes Jahr'), '2026'),
))

#: Die alten Schreibweisen → ihr neuer Schlüssel. `None` heisst: Der Name ist
#: gültig, sein Wert kommt aber nur aus dem eigenen Zusammenhang (Ticket,
#: Mahnung) und nie aus `kontext_fuer`.
#:
#: Die Bedeutung ist nachgesehen, nicht geraten:
#: `{anrede}` ist im Serienbrief «Frau»/«Herr» (`Mieter.anrede`) — darum
#: `mieter.anrede_kurz`, nicht die Briefanrede. `{liegenschaft}` nennt die
#: Hilfe «Strasse der Liegenschaft» (`fw_vorlage_form`).
ALIASE = {
    # Vorlagen (Hilfe in fw_vorlage_form, ticket_kontext)
    'mieter_name': 'mieter.name',
    'mieter_adresse': 'mieter.adresse',
    'objekt': 'objekt.bezeichnung',
    'liegenschaft': 'objekt.strasse',
    'vermieter': 'verwaltung.vermieter',
    'datum': 'datum.heute',
    'miete': 'vertrag.mietzins_brutto',
    'bewerber_name': 'bewerbung.name',
    # Serienbrief (core/services/serienbrief.py)
    'name': 'mieter.name',
    'anrede': 'mieter.anrede_kurz',
    'strasse': 'mieter.strasse',
    'plz': 'mieter.plz',
    'ort': 'mieter.ort',
    'adresse': 'mieter.adresse',
    # Schadensfall (ticket_kontext) — nur dort mit Wert
    'melder_name': None, 'melder_tel': None, 'schaden': None, 'ticket_id': None,
    'handwerker': None, 'status': None, 'termin': None,
    # Mahnschreiben (crm.MahnStufe.brief_text) — nur dort mit Wert
    'monat': None, 'betrag': None, 'gebuehr': None, 'mieter': 'mieter.name',
}

#: Neuer Schlüssel → alte Namen, damit ein alter Ersetzer mit flachem Kontext
#: auch `{mieter.name}` versteht.
_RUECKWAERTS = {}
for _alt, _neu in ALIASE.items():
    if _neu:
        _RUECKWAERTS.setdefault(_neu, []).append(_alt)

#: Ein Platzhalter: geschweifte Klammer, Name, optional `.feld`. Gross-
#: buchstaben zählen mit, damit ein `{Mieter.name}` als unbekannt auffällt
#: statt still stehen zu bleiben. Leerzeichen und Doppelpunkte nicht — so
#: bleiben CSS (`p { … }`) und Freitext wie `{Ihr Text}` unberührt.
MUSTER = re.compile(r'\{([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?)\}')


def bekannt(name):
    return name in REGISTRY or name in ALIASE


def unbekannte(text):
    """Die Platzhalter in `text`, die weder Registry noch Aliase kennen.

    In der Reihenfolge des ersten Auftretens, jeder einmal, mit Klammern —
    so, wie die Fehlermeldung sie nennen soll.
    """
    gesehen = []
    for name in MUSTER.findall(text or ''):
        code = '{' + name + '}'
        if not bekannt(name) and code not in gesehen:
            gesehen.append(code)
    return gesehen


def _wert(name, kontext):
    if name in kontext:
        return kontext[name]
    ziel = ALIASE.get(name)
    if ziel and ziel in kontext:
        return kontext[ziel]
    for alt in _RUECKWAERTS.get(name, ()):
        if alt in kontext:
            return kontext[alt]
    raise KeyError(name)


def ersetze(text, kontext, *, html=False):
    """Setzt die Werte aus `kontext` ein; alles Übrige bleibt stehen.

    `kontext` darf neue (`'mieter.name'`) und alte Schlüssel (`'mieter_name'`)
    tragen — beide Richtungen werden über `ALIASE` aufgelöst.
    `html=True` maskiert die eingesetzten Werte (die Vorlage selbst nicht:
    die bereinigt der Renderer, `core/services/vorlagen_pdf.py`).
    """
    def _ein(treffer):
        name = treffer.group(1)
        try:
            wert = _wert(name, kontext)
        except KeyError:
            return treffer.group(0)
        wert = '' if wert is None else str(wert)
        return _html_escape(wert) if html else wert
    return MUSTER.sub(_ein, text or '')


def gruppiert():
    """[(gruppe, beschriftung, [Platzhalter, …]), …] für die Chips im Editor."""
    return [(g, label, [p for p in REGISTRY.values() if p.gruppe == g])
            for g, label in GRUPPEN.items()]


def beispiel_kontext():
    """Die Beispielwerte der Registry — die Vorschau ohne echten Datensatz."""
    return {k: p.beispiel for k, p in REGISTRY.items()}


# ---------------------------------------------------------------------------
# Kontext aus dem Bestand
# ---------------------------------------------------------------------------

def _datum(d):
    return d.strftime('%d.%m.%Y') if d else ''


def _zimmer(z):
    if z is None:
        return ''
    text = f"{z}"
    return text.rstrip('0').rstrip('.') if '.' in text else text


def briefanrede(anrede_kurz, nachname, *, firma=False):
    """«Sehr geehrte Frau Frei» — in der Sprache des laufenden Blocks.

    Der Aufrufer setzt die Sprache des Empfängers (`in_sprache`); hier wird
    nur übersetzt, nicht geraten.
    """
    if firma or not nachname:
        return gettext('Sehr geehrte Damen und Herren')
    if anrede_kurz == 'Frau':
        return gettext('Sehr geehrte Frau %(name)s') % {'name': nachname}
    if anrede_kurz == 'Herr':
        return gettext('Sehr geehrter Herr %(name)s') % {'name': nachname}
    return gettext('Guten Tag %(name)s') % {'name': nachname}


def kontext_fuer(vertrag=None, bewerbung=None, mieter=None, organisation=None, sprache=None):
    """Alle Platzhalterwerte für einen Vertrag, eine Bewerbung oder eine Person.

    Baut auf `build_vertrag_context` (Beträge, Vertragsdaten) und `_kontext`
    (Absender, Zustelladresse) auf. `organisation` ist die Verwaltung, deren
    Briefkopf gilt; fehlt sie, gilt die des Datensatzes. Ein Datensatz einer
    ANDEREN Verwaltung ist ein Programmfehler und wirft — so kann eine
    Vorschau nie fremde Daten in den eigenen Briefkopf setzen.
    """
    from core.services.dokumentsprache import STANDARD, in_sprache

    org = (organisation or getattr(vertrag, 'organisation', None)
           or getattr(bewerbung, 'organisation', None) or getattr(mieter, 'organisation', None))
    for obj in (vertrag, bewerbung, mieter):
        if obj is not None and org is not None and getattr(obj, 'organisation_id', org.pk) != org.pk:
            raise ValueError('Datensatz einer anderen Verwaltung im Platzhalter-Kontext.')

    heute = timezone.localdate()
    k = {'datum.heute': _datum(heute), 'datum.jahr': str(heute.year)}
    einheit = lg = eigentuemer = None
    vermieter = ''

    if vertrag is not None:
        from core.services.mietprozess_briefe import _kontext
        from core.services.pdf_service import build_vertrag_context
        _vorlage, vk = build_vertrag_context(vertrag, mit_unterschrift=False)
        mieter = mieter or vk['mieter']
        einheit, lg, eigentuemer = vk['einheit'], vk['liegenschaft'], vk['eigentuemer']
        k.update({
            'vertrag.beginn': _datum(vertrag.beginn),
            'vertrag.ende': _datum(vertrag.ende),
            'vertrag.mietzins_netto': vk['miete_fmt'],
            'vertrag.nebenkosten': vk['nk_fmt'],
            'vertrag.mietzins_brutto': vk['brutto_fmt'],
            'vertrag.kaution': vk['kaution_fmt'],
        })
        _m, _e, _lg, _abs, _ort, empf, _obj, vermieter, _sig = _kontext(vertrag, org)
        k['mieter.adresse'] = ', '.join(z for z in empf[1:] if z)
    elif bewerbung is not None:
        from core.services.mietprozess_briefe import _absender_zeilen, _fr
        einheit = bewerbung.einheit
        lg = einheit.liegenschaft if einheit is not None else None
        eigentuemer = lg.eigentuemer if lg is not None else None
        # Das ANGEBOT: die Konditionen der Einheit, wie sie `fw_bewerbung_zu_vertrag`
        # in den Vertragsentwurf übernimmt. Eine Kaution wird hier nicht
        # ausgerechnet — sie steht erst im Vertrag fest.
        if einheit is not None:
            netto = einheit.nettomiete_aktuell or 0
            nk = einheit.nebenkosten_aktuell or 0
            k.update({
                'vertrag.mietzins_netto': _fr(netto),
                'vertrag.nebenkosten': _fr(nk),
                'vertrag.mietzins_brutto': _fr(netto + nk),
            })
        k['vertrag.beginn'] = _datum(bewerbung.gewuenschter_bezugstermin)
        vermieter = _absender_zeilen(org, eigentuemer)[0]
        name = f"{bewerbung.vorname or ''} {bewerbung.nachname or ''}".strip()
        k.update({
            'bewerbung.name': name,
            'bewerbung.email': bewerbung.email or '',
            'bewerbung.telefon': bewerbung.mobilnummer or '',
            'bewerbung.bezugstermin': _datum(bewerbung.gewuenschter_bezugstermin),
        })
        if mieter is None:
            kurz = {'weiblich': 'Frau', 'maennlich': 'Herr'}.get(bewerbung.geschlecht, '')
            ort_zeile = f"{bewerbung.plz or ''} {bewerbung.ort or ''}".strip()
            k.update({
                'mieter.name': name, 'mieter.vorname': bewerbung.vorname or '',
                'mieter.nachname': bewerbung.nachname or '', 'mieter.anrede_kurz': kurz,
                'mieter.strasse': bewerbung.adresse or '', 'mieter.plz': bewerbung.plz or '',
                'mieter.ort': bewerbung.ort or '', 'mieter.email': bewerbung.email or '',
                'mieter.adresse': ', '.join(z for z in (bewerbung.adresse or '', ort_zeile) if z),
            })
            with in_sprache(sprache or STANDARD):
                k['mieter.anrede'] = briefanrede(kurz, bewerbung.nachname)

    if mieter is not None:
        firma = getattr(mieter, 'typ', '') in ('firma', 'verein') and bool(getattr(mieter, 'firmen_name', ''))
        k.update({
            'mieter.name': mieter.display_name,
            'mieter.vorname': mieter.vorname or '',
            'mieter.nachname': mieter.nachname or '',
            'mieter.anrede_kurz': mieter.anrede or '',
            'mieter.email': mieter.email or '',
        })
        s, _zusatz, plz, ort = mieter.zustelladresse()
        k.update({'mieter.strasse': s or '', 'mieter.plz': plz or '', 'mieter.ort': ort or ''})
        if 'mieter.adresse' not in k:
            ort_zeile = f"{plz or ''} {ort or ''}".strip()
            k['mieter.adresse'] = ', '.join(z for z in (s or '', ort_zeile) if z)
        with in_sprache(sprache or STANDARD):
            k['mieter.anrede'] = briefanrede(mieter.anrede, mieter.nachname, firma=firma)

    if einheit is not None:
        k['objekt.bezeichnung'] = einheit.bezeichnung or ''
        k['objekt.zimmer'] = _zimmer(getattr(einheit, 'zimmer', None))
    if lg is not None:
        k.update({
            'objekt.strasse': lg.strasse or '', 'objekt.plz': lg.plz or '', 'objekt.ort': lg.ort or '',
            'objekt.adresse': f"{lg.strasse or ''}, {lg.plz or ''} {lg.ort or ''}".strip(' ,'),
        })
        betreuer = getattr(lg, 'betreut_von', None)
        if betreuer is not None:
            k['verwaltung.sachbearbeiter'] = (betreuer.get_full_name() or betreuer.get_username())

    if org is not None:
        k.update({
            'verwaltung.name': org.firma or '',
            'verwaltung.adresse': f"{org.strasse or ''}, {org.plz or ''} {org.ort or ''}".strip(' ,'),
            'verwaltung.telefon': org.telefon or '',
            'verwaltung.email': org.email or '',
        })
        k['verwaltung.vermieter'] = vermieter or org.firma or ''
    return k
