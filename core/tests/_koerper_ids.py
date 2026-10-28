"""Fremde IDs im BODY — der Fuzz hinter `test_isolation.FremdeIdImBodyTests`.

WARUM ES DAS GIBT (Audit 28.10.2026, SICH-01, SICH-27)

Der Registrylauf von `test_isolation.py` setzt fremde IDs in den URL-PFAD. Die
drei Löcher des Audits standen woanders: `fw_pendenz_neu` übernahm
`liegenschaft_id` aus dem FORMULAR, das QR-Aushangformular `einheit_id` aus dem
Body, und `fw_abwesenheit_neu` zwei Benutzer-IDs. Jede dieser Stellen hatte
einen Test, der grün war — er stellte die Frage nur an die falsche Stelle.

Dieser Fuzz schickt an JEDE POST-Route eine Anfrage, in der JEDES bekannte
Feld (`liegenschaft_id`, `einheit_id`, `benutzer`, `konto_id`, …) auf eine
Zeile von Mandant B zeigt, und prüft danach den Bestand:

* NEUE_ZEILE_IN_B        — in B ist eine Zeile entstanden (`OrganisationAusKette`
                           leitet die Organisation aus der fremden Liegenschaft ab)
* B_ZEILE_GEAENDERT/_GELOESCHT — eine Zeile von B wurde angefasst
* FK_UEBER_GRENZE        — eine neue/geänderte Zeile von A zeigt auf eine Zeile von B
* USER_OHNE_MITGLIEDSCHAFT — ein Benutzer-Verweis auf jemanden, der nicht zur
                           Organisation der Zeile gehört (`Benutzer` hat KEINEN
                           Mandantenfilter, `bekannte-fallen` Nr. 4)

Gemessen wird am Bestand, nicht an der Antwort: Ein 302 sagt nichts darüber, ob
geschrieben wurde. Jede Anfrage läuft in einem Sicherungspunkt und wird danach
zurückgerollt, damit die nächste vom selben Ausgangsbestand ausgeht.

Nur Tabellen, in die die Anfrage tatsächlich geschrieben hat, werden neu
gelesen (`connection.execute_wrapper`) — das hält den Lauf bei rund 500 Routen
kurz.
"""
import json
import re

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.urls import NoReverseMatch, get_resolver, reverse

from ._isolation import KEINE_OBJEKT_ID

EIGENE_APPS = ('benutzer', 'core', 'crm', 'portfolio', 'rentals', 'finance', 'tickets',
               'mietprozess', 'faelle', 'stweg')

#: Routen, die Anonymen absichtlich erlauben, in der Verwaltung einer GEWÄHLTEN
#: Liegenschaft/Einheit etwas anzulegen. Die gewählte ID IST dort die Zuordnung.
#: Was sie dabei dürfen (nur die eigene Liegenschaft für Einheit und Foto), prüfen
#: `test_oeffentliches_meldeformular.py` und `FremdeIdImBodyTests` an den
#: Pfad-Routen (`public_report`).
OEFFENTLICH_BY_DESIGN = {
    'schaden_melden': 'anonymes Formular: die Liegenschaft aus dem Body ist die Zuordnung',
    'public_bewerbung': 'anonymes Bewerbungsformular: das Objekt aus dem Pfad ist die Zuordnung',
}

#: Verweise auf einen Portal-Login: Mieter und Eigentümer haben ein Konto ohne Mitgliedschaft.
PORTAL_LOGINS = {('crm.Mieter', 'benutzer'), ('crm.Eigentuemer', 'benutzer')}

#: Parameter, die eine Route nicht mit einem Objekt des Fixtures beantworten kann.
_NICHT_BELEGBAR = {'uidb64', 'token', 'pfad', 'nummer', 'zweck', 'art', 'doc_type', 'nr',
                   'content_type_id', 'object_id'}


def tenant_modelle():
    """Modelle mit eigener Organisationsspalte und vorhandener Tabelle."""
    vorhanden = set(connection.introspection.table_names())
    modelle = []
    for m in apps.get_models():
        if m._meta.app_label not in EIGENE_APPS or m._meta.label == 'crm.Organisation':
            continue
        if m._meta.db_table not in vorhanden or m._meta.proxy:
            continue
        if any(f.name == 'organisation' for f in m._meta.concrete_fields):
            modelle.append(m)
    return modelle


def durchgangsmodelle():
    """Automatisch angelegte M2M-Tabellen zwischen Mandantenmodellen und Benutzern."""
    vorhanden = set(connection.introspection.table_names())
    ergebnis = []
    for m in apps.get_models(include_auto_created=True):
        if m._meta.auto_created and m._meta.app_label in EIGENE_APPS and m._meta.db_table in vorhanden:
            ergebnis.append(m)
    return ergebnis


def felder_fuer(b, benutzer_b, benutzer_b2=None):
    """Feldname → Wert, jeder zeigt auf Mandant B. Namen aus dem Bestand der Views.

    Aus den Fixture-Attributen werden zusätzlich `<attr>`, `<attr>_id` und
    `<modell>_id` abgeleitet: ein neues Fixture-Objekt ist damit automatisch im
    Fuzz, ohne dass jemand daran denken muss.
    """
    from django.db.models import Model

    f = {
        'liegenschaft_id': b.liegenschaft.pk, 'lg': b.liegenschaft.pk, 'liegenschaft': b.liegenschaft.pk,
        'gehoert_zu_id': b.einheit.pk, 'einheit_id': b.einheit.pk, 'einheit': b.einheit.pk,
        'objekt_id': b.einheit.pk, 'id': b.einheit.pk,
        'vertrag_id': b.vertrag.pk, 'vertrag': b.vertrag.pk, 'akte': b.vertrag.pk, 'edit_id': b.vertrag.pk,
        'mieter_id': b.mieter.pk, 'mieter': b.mieter.pk, 'person_id': b.mieter.pk, 'mit_mieter_id': b.mieter.pk,
        'rechnung_id': b.debitor.pk, 'rechnung': b.debitor.pk, 'debitor_id': b.debitor.pk,
        'kreditor_id': b.kreditor.pk, 'zahlung_id': b.zahlung.pk, 'zahlungseingang': b.zahlung.pk,
        'konto_id': b.konto_soll.pk, 'konto': b.konto_soll.pk, 'soll_konto': b.konto_soll.pk,
        'haben_konto': b.konto_haben.pk, 'konto_haben': b.konto_haben.pk,
        'gegenkonto': b.konto_haben.nummer, 'bank_konto': b.konto_soll.nummer,
        'handwerker_id': b.handwerker.pk, 'handwerker': b.handwerker.pk,
        'eigentuemer_id': b.eigentuemer.pk, 'eigentuemer': b.eigentuemer.pk,
        'mandat': b.eigentuemer.pk, 'mandat_id': b.eigentuemer.pk,
        'schaden': b.schaden.pk, 'schaden_id': b.schaden.pk, 'ticket': b.schaden.pk, 'ticket_id': b.schaden.pk,
        'auftrag_id': b.auftrag.pk, 'periode_id': b.periode.pk, 'periode': b.periode.pk,
        'bewerbung': b.bewerbung.pk, 'bewerbung_id': b.bewerbung.pk,
        'dokument_id': b.dokument_rentals.pk, 'ausstattung_id': b.ausstattung.pk,
        'geraet_id': b.geraet.pk, 'zaehler_id': b.zaehler.pk, 'zaehler': b.zaehler.pk,
        'anlage_id': b.schliessanlage.pk, 'schliesspunkt': b.schliesspunkt.pk, 'tuer': b.schliesspunkt.pk,
        'schluessel_id': b.schluessel.pk, 'schluessel': b.schluessel.pk,
        'fall_id': b.fall.pk, 'fall': b.fall.pk, 'fallart': b.fallart.pk,
        'empfaenger_id': b.mieter.pk, 'vorlage_id': b.vorlage.pk, 'vorlage': b.vorlage.pk,
        'budget_id': b.budget.pk, 'termin': b.termin.pk, 'termin_id': b.termin.pk,
        'ausgabe_id': b.schluessel_ausgabe.pk, 'betreibung_id': b.betreibung.pk,
        'wartungsfrist_id': b.wartungsfrist.pk, 'eingang_id': b.eingang.pk, 'lauf_id': b.lauf.pk,
        'pendenz': b.pendenz.pk, 'traktandum': b.stweg_traktandum.pk,
        'bewegung_id': b.debitor.pk, 'beleg_id': b.debitor.pk, 'anwendung_id': b.fall.pk,
        # Personen des Teams von B — `Benutzer` hat keinen Mandantenfilter.
        # Zwei verschiedene Personen: `Abwesenheit.clean()` verwirft «Vertretung = abwesende Person».
        'benutzer': benutzer_b.pk, 'benutzer_id': benutzer_b.pk,
        'vertreten_durch': (benutzer_b2 or benutzer_b).pk,
        'zustaendig': benutzer_b.pk, 'zugewiesen_an': benutzer_b.pk, 'betreut_von': benutzer_b.pk,
        # Die Organisation selbst darf nie aus dem Body kommen.
        'organisation': b.organisation.pk, 'organisation_id': b.organisation.pk,
        # Nutzdaten, damit Pflichtfelder nicht schon vor dem Schreiben abbrechen.
        'titel': 'XFUZZ', 'betreff': 'XFUZZ', 'name': 'XFUZZ', 'bezeichnung': 'XFUZZ', 'text': 'XFUZZ',
        'nachricht': 'XFUZZ', 'notiz': 'XFUZZ', 'beschreibung': 'XFUZZ', 'kategorie': 'x',
        'betrag': '10.00', 'datum': '2026-10-01', 'von': '2026-11-01', 'bis': '2026-11-05',
        'faellig_am': '2026-12-01', 'beginn': '2026-11-01', 'grund': 'ferien',
        'vorname': 'Fuzz', 'nachname': 'Fuzz', 'email': 'fuzz@example.ch', 'telefon': '0790000000',
    }
    for attr, wert in vars(b).items():
        if isinstance(wert, Model):
            f.setdefault(attr, wert.pk)
            f.setdefault(f'{attr}_id', wert.pk)
            f.setdefault(f'{wert._meta.model_name}_id', wert.pk)
    return f


def post_routen(a):
    """Alle POST-fähigen benannten Routen mit einem Pfad aus dem Bestand von A.

    Gibt `(name, pfad)` zurück. Alle Parameter einer Route (auch zwei) werden mit
    Objekten von A belegt, so dass die Route den Pfad als „eigen" erkennt und der
    Body die einzige fremde Quelle ist. Nicht belegbare Routen kommen in
    `uebersprungen` zurück, damit der Test sie benennen muss.
    """
    gefunden, uebersprungen = [], []
    for name, eintrag in sorted((n, e) for n, e in get_resolver().reverse_dict.items() if isinstance(n, str)):
        params = None
        for _pfad, p in eintrag[0]:
            params = list(p)
            break
        if params is None:
            continue
        try:
            args = []
            for p in params:
                if p in _NICHT_BELEGBAR or p in KEINE_OBJEKT_ID:
                    raise LookupError(p)
                args.append(a.objekt_fuer(p, name).pk)
            pfad = reverse(name, args=args)
        except (LookupError, NoReverseMatch):
            uebersprungen.append((name, params))
            continue
        if pfad.startswith('/admin/') or name in ('logout', 'login', 'portal_login'):
            continue
        gefunden.append((name, pfad))
    return gefunden, uebersprungen


class _Schreiber:
    """`execute_wrapper`: merkt sich die Tabellen, in die geschrieben wurde."""

    _MUSTER = re.compile(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"?(\w+)"?', re.I)

    def __init__(self):
        self.tabellen = set()

    def __call__(self, execute, sql, params, many, context):
        m = self._MUSTER.match(sql)
        if m:
            self.tabellen.add(m.group(1))
        return execute(sql, params, many, context)


class Bestand:
    """Der Zustand aller Mandantentabellen — gelesen, verglichen, zurückgesetzt."""

    def __init__(self, b_organisation):
        self.b = b_organisation.pk
        self.modelle = tenant_modelle()
        self.durchgang = durchgangsmodelle()
        self.nach_tabelle = {m._meta.db_table: m for m in self.modelle + self.durchgang}
        self.zeilen = {m: self._lese(m) for m in self.modelle + self.durchgang}
        self.org = {m: {pk: z[0] for pk, z in self.zeilen[m].items()} for m in self.modelle}
        from crm.models import Mitgliedschaft
        self.mitglieder = set(Mitgliedschaft.alle_organisationen.values_list('benutzer_id', 'organisation_id'))

    @staticmethod
    def _lese(modell):
        zeilen = {}
        for o in modell._base_manager.all():
            org = getattr(o, 'organisation_id', None)
            zeilen[o.pk] = (org, tuple(getattr(o, f.attname) for f in modell._meta.concrete_fields))
        return zeilen

    def befunde(self, tabellen):
        """Vergleicht die beschriebenen Tabellen mit dem Ausgangsbestand."""
        res = []
        aktuell = {}
        for t in tabellen:
            m = self.nach_tabelle.get(t)
            if m is None:
                continue
            aktuell[m] = self._lese(m)
        org_neu = {m: dict(self.org.get(m, {})) for m in aktuell}
        for m, jetzt in aktuell.items():
            if m in self.org:
                org_neu[m] = {pk: z[0] for pk, z in jetzt.items()}
        for m, jetzt in aktuell.items():
            vorher = self.zeilen[m]
            label = m._meta.label
            neu = [pk for pk in jetzt if pk not in vorher]
            geaendert = [pk for pk in jetzt if pk in vorher and jetzt[pk] != vorher[pk]]
            weg = [pk for pk in vorher if pk not in jetzt]
            for pk in neu:
                if jetzt[pk][0] == self.b:
                    res.append(('NEUE_ZEILE_IN_B', label, pk))
            for pk in geaendert:
                if jetzt[pk][0] == self.b or vorher[pk][0] == self.b:
                    res.append(('B_ZEILE_GEAENDERT', label, pk))
            for pk in weg:
                if vorher[pk][0] == self.b:
                    res.append(('B_ZEILE_GELOESCHT', label, pk))
            for pk in neu + geaendert:
                res.extend(self._fremdschluessel(m, pk, jetzt[pk], org_neu))
        return res

    def _fremdschluessel(self, modell, pk, zeile, org_neu):
        res = []
        eigene_org = zeile[0]
        werte = dict(zip((f.attname for f in modell._meta.concrete_fields), zeile[1]))
        for f in modell._meta.concrete_fields:
            if not (f.is_relation and (f.many_to_one or f.one_to_one)):
                continue
            ziel_pk = werte.get(f.attname)
            if ziel_pk is None or f.name == 'organisation':
                continue
            ziel = f.related_model
            if ziel._meta.label_lower == settings.AUTH_USER_MODEL.lower():
                # Wer das Konto angelegt hat (`erstellt_von`), ist der Angemeldete;
                # geprüft wird die Zugehörigkeit zur Organisation der Zeile.
                if (modell._meta.label, f.name) in PORTAL_LOGINS:
                    # Ein Portal-Login (Mieter/Eigentümer) ist KEIN Teammitglied. Er darf
                    # aber nirgends Teammitglied sein — sonst hängt ein Konto von B am Mieter von A.
                    if any(u == ziel_pk and o != eigene_org for u, o in self.mitglieder):
                        res.append(('PORTAL_LOGIN_EINES_TEAMS', modell._meta.label, pk, f.name))
                elif eigene_org is not None and (ziel_pk, eigene_org) not in self.mitglieder:
                    res.append(('USER_OHNE_MITGLIEDSCHAFT', modell._meta.label, pk, f.name))
                continue
            if ziel in org_neu:
                ziel_org = org_neu[ziel].get(ziel_pk)
            else:
                ziel_org = self.org.get(ziel, {}).get(ziel_pk)
            if eigene_org is None:
                # Durchgangstabelle (M2M): Vergleichswert ist die Organisation des anderen Endes.
                continue
            if ziel_org is not None and ziel_org != eigene_org:
                res.append(('FK_UEBER_GRENZE', modell._meta.label, pk, f.name, ziel._meta.label, ziel_org))
        if eigene_org is None and modell._meta.auto_created:
            res.extend(self._durchgang(modell, pk, werte, org_neu))
        return res

    def _durchgang(self, modell, pk, werte, org_neu):
        """M2M-Zeile (zum Beispiel `Liegenschaft.hauswarte`): beide Enden müssen zusammenpassen."""
        orgs, benutzer = set(), []
        for f in modell._meta.concrete_fields:
            if not (f.is_relation and f.many_to_one):
                continue
            ziel, ziel_pk = f.related_model, werte.get(f.attname)
            if ziel._meta.label_lower == settings.AUTH_USER_MODEL.lower():
                benutzer.append(ziel_pk)
            else:
                org = (org_neu.get(ziel) or self.org.get(ziel, {})).get(ziel_pk)
                if org is not None:
                    orgs.add(org)
        res = []
        if len(orgs) > 1:
            res.append(('FK_UEBER_GRENZE', modell._meta.label, pk, 'durchgang', '', sorted(orgs)))
        for u in benutzer:
            for o in orgs:
                if (u, o) not in self.mitglieder:
                    res.append(('USER_OHNE_MITGLIEDSCHAFT', modell._meta.label, pk, 'benutzer'))
        return res


def sende(client, bestand, pfad, daten, als_json=False, methode='post'):
    """Eine Anfrage in einem Sicherungspunkt: `(Status, Befunde)`; danach zurückgerollt."""
    status, befunde, _inhalt = sende_mit_inhalt(client, bestand, pfad, daten, als_json, methode)
    return status, befunde


def sende_mit_inhalt(client, bestand, pfad, daten, als_json=False, methode='post'):
    """Wie `sende`, dazu der Antworttext (für die Suche nach Daten von B)."""
    schreiber = _Schreiber()
    ergebnis = {}

    class _Zurueck(Exception):
        pass

    try:
        with transaction.atomic():
            with connection.execute_wrapper(schreiber):
                if methode == 'get':
                    antwort = client.get(pfad)
                elif als_json:
                    antwort = client.post(pfad, json.dumps(daten), content_type='application/json')
                else:
                    antwort = client.post(pfad, daten)
            ergebnis['status'] = antwort.status_code
            ergebnis['inhalt'] = antwort.content.decode('utf-8', 'ignore') if antwort.status_code == 200 else ''
            ergebnis['befunde'] = bestand.befunde(schreiber.tabellen)
            raise _Zurueck
    except _Zurueck:
        pass
    return ergebnis['status'], ergebnis['befunde'], ergebnis['inhalt']
