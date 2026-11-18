# core/views/fw/personen_liste.py
#
# Personenliste mit Telefonsuche und CSV-Export.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).


from django.utils.translation import gettext
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)
from crm.models import Mieter
from rentals.models import Mietvertrag
from core.views.fw.liegenschaft_crud import telefon_kern
from core.views.fw._liste import (Sortierung, blaettern, csv_antwort, query_mit,
                                  sortieren, sortierung_waehlen, verdeckte_felder)


from ._basis import (_global_filter)


def telefon_treffer_ids(kern, grundmenge):
    """Die Ids aller Personen, deren Nummer diesen Kern enthaelt.

    WARUM NICHT DIE ABFRAGE UM SCHREIBWEISEN ERWEITERT WIRD

    Naheliegend waere, aus dem Kern die moeglichen Speicherformen zu erzeugen
    (`079 123 45 67`, `+41 79 …`, `0791234567`) und danach zu suchen. Das
    wurde gebaut und gemessen — und es raet, in welcher Form die Nummer
    erfasst wurde. Realistische Formen ausserhalb der geratenen Liste fallen
    still durch: `079/123 45 67` und `079.123.45.67` wurden von KEINER der
    sieben Suchvarianten gefunden, `079 123 4567` von einer.

    Ueber acht Speicherformate x sieben Suchbegriffe gemessen:

        Schreibweisen raten   33 von 56
        Kern vergleichen      56 von 56

    Die zweite Zahl ist auch die der Kopfzeilensuche (E2.26) — dieselbe
    Methode, deshalb dasselbe Ergebnis. Zwei Suchen mit unterschiedlichem
    Verhalten waeren fuer den Benutzer nicht erklaerbar.

    WARUM DAS HIER TROTZDEM EINE ABFRAGE BLEIBT

    Der Vergleich braucht Python — die Datenbank kann `telefon_kern` nicht
    bilden, ohne die gespeicherten Werte zu normalisieren. Diese Funktion
    liefert deshalb nur die **Ids**; der Aufrufer haengt sie mit `id__in` an
    seine Bedingung. Die Abfrage bleibt eine Abfrage, Sortierung und
    Zaehlung bleiben unberuehrt.

    Gelesen werden vier Spalten ueber `values_list` — und nur, wenn die
    Eingabe ueberhaupt nach einer Nummer aussieht.
    """
    treffer = []
    for pk, mobil, privat, geschaeft in grundmenge.exclude(
            mobile='', telefon_privat='', telefon_geschaeft='').values_list(
            'id', 'mobile', 'telefon_privat', 'telefon_geschaeft'):
        # Jedes Feld einzeln: Zusammengeklebt entstuenden Treffer ueber
        # Feldgrenzen hinweg (siehe E2.26).
        for wert in (mobil, privat, geschaeft):
            kandidat = telefon_kern(wert)
            if kandidat and kern in kandidat:
                treffer.append(pk)
                break
    return treffer


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_personen(request):
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    from core.services.archiv import ausblenden
    qs = ausblenden(Mieter.objects.all()).order_by('nachname', 'firmen_name')
    if aktive_lg:
        # Haupt- ODER Mitmieter eines Vertrags in dieser Liegenschaft
        qs = qs.filter(Q(vertraege__einheit__liegenschaft=aktive_lg)
                       | Q(vertraege_als_mitmieter__einheit__liegenschaft=aktive_lg)).distinct()

    typ_filter = request.GET.get('typ', '')
    if typ_filter in ('person', 'firma', 'verein'):
        qs = qs.filter(typ=typ_filter)
    # «Anrede prüfen»: Privatpersonen mit «Herr», das nie bestätigt wurde (bis PR #161 war «Herr»
    # die Vorgabe). Zählung vor Suche/Typ, damit der Reiter immer die ganze Aufgabe nennt.
    anrede_offen = ausblenden(Mieter.objects.filter(typ='person', anrede='Herr', anrede_geprueft=False))
    if aktive_lg:
        anrede_offen = anrede_offen.filter(
            Q(vertraege__einheit__liegenschaft=aktive_lg)
            | Q(vertraege_als_mitmieter__einheit__liegenschaft=aktive_lg)).distinct()
    anrede_pruefen = request.GET.get('anrede') == 'pruefen'
    if anrede_pruefen:
        qs = qs.filter(id__in=anrede_offen.values('id'))
    q = (request.GET.get('q') or '').strip()
    if q:
        bedingung = (Q(vorname__icontains=q) | Q(nachname__icontains=q)
                     | Q(firmen_name__icontains=q) | Q(email__icontains=q)
                     | Q(ort__icontains=q)
                     | Q(mobile__icontains=q) | Q(telefon_privat__icontains=q)
                     | Q(telefon_geschaeft__icontains=q))

        # TELEFONNUMMERN UEBER SCHREIBWEISEN HINWEG
        #
        # `icontains` allein findet `079 123 45 67` nicht, wenn jemand
        # `0791234567` tippt — und schon gar nicht `+41 79 …`. Gemessen waren
        # es 5 von 18 Treffern; die Suche fand also weniger als ein Drittel.
        #
        # `telefon_kern()` (E2.26) macht aus jeder Schreibweise denselben
        # Kern; `telefon_treffer_ids` vergleicht ihn gegen den Bestand und
        # liefert Ids. Die kommen mit `id__in` in dieselbe Bedingung — die
        # Abfrage bleibt eine Abfrage, Sortierung und Zaehlung bleiben, wie
        # sie waren.
        kern = telefon_kern(q)
        if len(kern) >= 5:
            bedingung |= Q(id__in=telefon_treffer_ids(kern, qs))
        qs = qs.filter(bedingung).distinct()

    aktive_vertraege = (Mietvertrag.objects.filter(status='aktiv')
                        .select_related('einheit__liegenschaft'))
    vertrag_je_mieter = {}
    for v in aktive_vertraege:
        # Vertrag beim Hauptmieter UND beim Mitmieter (2. Person) anzeigen
        vertrag_je_mieter.setdefault(v.mieter_id, []).append(v)
        if v.mitmieter_id:
            vertrag_je_mieter.setdefault(v.mitmieter_id, []).append(v)

    def zeile(m):
        aktive = vertrag_je_mieter.get(m.id, [])
        return {
            'm': m,
            'telefon': m.mobile or m.telefon_privat or m.telefon_geschaeft,
            'aktive': aktive,
            'objekt': (f"{aktive[0].einheit.liegenschaft.strasse} · {aktive[0].einheit.bezeichnung}"
                       if aktive else None),
        }

    sort = sortierung_waehlen(request, PERSON_SORTEN, 'name')
    qs = sortieren(qs, PERSON_SORTEN, sort)

    if request.GET.get('export') == 'csv':
        if anrede_pruefen:
            return _anrede_csv(request, qs, zeile)
        return _personen_csv(request, qs, zeile)

    seite, query_ohne_seite = blaettern(request, qs)
    rows = [zeile(m) for m in seite.object_list]

    return render(request, 'fw/personen.html', {
        **basis, 'nav': 'personen', 'rows': rows,
        'seite': seite, 'query_ohne_seite': query_ohne_seite, 'treffer': seite.paginator.count,
        'typ_filter': typ_filter, 'q': q,
        'typ_chips': [(k, label, query_mit(request, typ=k, anrede=None)) for k, label in
                      [('', _('Alle')), ('person', _('Privatpersonen')), ('firma', _('Firmen')),
                       ('verein', _('Vereine'))]],
        'anrede_pruefen': anrede_pruefen, 'anrede_offen': anrede_offen.count(),
        'anrede_chip_url': query_mit(request, anrede='pruefen', typ=None),
        'zurueck': request.get_full_path(),
        # Über die Abfrage gezählt, nicht über die Seite.
        'mit_vertrag_count': qs.filter(id__in=list(vertrag_je_mieter)).count(),
        'sort': sort, 'sorten': [(k, x.label) for k, x in PERSON_SORTEN.items()],
        'verdeckt': verdeckte_felder(request, 'q', 'sort'),
        'csv_url': query_mit(request, export='csv'),
        'suche_aufheben_url': query_mit(request, q=None),
    })


#: Wählbare Sortierungen der Personenliste; `id` hält die Seiten stabil.
PERSON_SORTEN = {
    'name': Sortierung(gettext_lazy('Name'), None,
                       felder=('nachname', 'firmen_name', 'vorname', 'id')),
    'ort': Sortierung(gettext_lazy('Ort'), None,
                      felder=('ort', 'nachname', 'firmen_name', 'id')),
    'neueste': Sortierung(gettext_lazy('Zuletzt erfasst'), None, felder=('-id',)),
}


def _anrede_csv(request, qs, zeile):
    """Die Liste «Anrede prüfen» als CSV: Name, Objekt, Anrede, E-Mail (nur Kontaktdaten)."""
    from core.models import AktivitaetsLog

    AktivitaetsLog.objects.create(
        benutzer=request.user, kategorie='sonstiges',
        aktion=gettext('Liste «Anrede prüfen» exportiert (CSV)'),
        objekt=gettext('%(n)s Personen') % {'n': qs.count()},
        details=request.GET.urlencode()[:2000])
    return csv_antwort(
        f'Anrede_pruefen_{timezone.localdate():%Y-%m-%d}.csv',
        [_('Name'), _('Objekt'), _('Anrede'), _('E-Mail')],
        ([z['m'].display_name, z['objekt'] or '', z['m'].anrede, z['m'].email]
         for z in (zeile(m) for m in qs.iterator(chunk_size=500))))


def _personen_csv(request, qs, zeile):
    """Kontaktliste — bewusst NUR Kontaktdaten.

    Das Personenmodell trägt auch AHV-Nummer, Einkommen, Betreibungsauskunft
    und Bankverbindung. Nichts davon gehört in eine Datei, die per E-Mail
    weitergereicht wird (DSG Art. 6: Verhältnismässigkeit). Wer es braucht,
    sieht es in der Akte.

    Der Export wird protokolliert: Eine Liste aller Mieter mit Adressen, die
    das Haus verlässt, soll im Logbuch nachvollziehbar sein.
    """
    from core.models import AktivitaetsLog

    heute = timezone.localdate()
    anzahl = qs.count()
    AktivitaetsLog.objects.create(
        benutzer=request.user, kategorie='sonstiges',
        aktion=gettext('Personenliste exportiert (CSV)'),
        objekt=gettext('%(n)s Personen') % {'n': anzahl},
        details=request.GET.urlencode()[:2000])
    return csv_antwort(
        f'Personen_{heute:%Y-%m-%d}.csv',
        [_('Name'), _('Typ'), _('E-Mail'), _('Telefon'), _('Strasse'), _('PLZ'),
         _('Ort'), _('Sprache'), _('Aktives Mietverhältnis')],
        ([z['m'].display_name, z['m'].get_typ_display(), z['m'].email, z['telefon'],
          z['m'].strasse, z['m'].plz, z['m'].ort, z['m'].get_sprache_display(),
          z['objekt'] or '']
         for z in (zeile(m) for m in qs.iterator(chunk_size=500))))
