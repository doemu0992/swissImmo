"""Befunde je Objekt — was an der einzelnen Einheit klemmt.

WARUM

Die Objektliste zeigte bis hierher, was **da ist**: Bezeichnung, Typ, Zimmer,
Fläche, Soll-Miete, Status — sortiert nach `liegenschaft__strasse` und
`bezeichnung`, also nach Alphabet. Ein vermieteter Parkplatz stand damit
gleichberechtigt neben zwei leeren Wohnungen.

Am 21.08.2026 am Bestand gesehen: Beide leeren Wohnungen an der
Selzacherstrasse zeigten «Soll-Miete —». Das ist die eigentliche Nachricht der
Seite — zwei Wohnungen stehen leer und haben keinen Preis hinterlegt, man kann
sie also nicht ausschreiben — und sie stand dort als Gedankenstrich.

Grundentscheidung G9: **«Was fehlt ist wichtiger als was da ist.»**

DIE LEERSTANDSREGEL IST DIESELBE WIE IN `liegenschaften.py` — UND DAS WIRD
GEPRÜFT, NICHT BEHAUPTET

Ab Ende der Mietdauer gemäss Kündigung gilt eine Einheit als leer, ein
Nachmieter hebt den Befund auf, Nebenobjekte gelten mit dem Hauptvertrag als
belegt. Zwei Fassungen derselben Regel laufen mit Sicherheit irgendwann
auseinander, und dann sagen Liegenschaftsliste und Objektliste Verschiedenes
über dieselbe Wohnung.

Vollständig teilen lässt sich der Code trotzdem nicht: `liegenschaften.
_leerstand` rechnet je Liegenschaft und holt in derselben Schleife die
Ist-Miete; hier braucht es den Zustand je EINZELNER Einheit samt «leer seit».
Zwei Dinge halten die Regeln deshalb zusammen, und beide sind belastbarer als
ein Kommentar:

1. Die Statuslisten sind **importiert**, nicht abgeschrieben
   (`BELEGENDE_STATUS`, `NACHMIETER_STATUS`).
2. `faelle/test_objektliste.py::KonsistenzTests` stellt beide Module
   nebeneinander und lässt sie über dieselben Fälle urteilen. Weicht eines ab,
   wird der Test rot.

DIE GRUPPIERUNG NACH LIEGENSCHAFT BLEIBT (Entscheid 21.08.2026)

Die Alternative wäre eine flache Liste, streng nach Befund sortiert. Der
Entscheid fiel für die Gruppierung — mit dem Zusatz, dass die Filter die Arbeit
machen sollen. Beides zusammen heisst: Die Gruppen bleiben, aber sie sind nach
Befund GEORDNET und die auffälligen stehen offen. Wer nur die Problemfälle
will, nimmt «Mit Befund»; dann bleiben von zwölf Liegenschaften drei übrig,
jede mit genau den Zeilen, um die es geht.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from faelle.liegenschaften import BELEGENDE_STATUS, NACHMIETER_STATUS

log = logging.getLogger(__name__)

#: Wie weit nach vorn geschaut wird. Dieselbe Spanne wie in der
#: Liegenschaftsliste — ein halbes Jahr ist die Frist, innerhalb derer eine
#: Wohnung neu vermietet werden muss, wenn kein Ausfall entstehen soll.
VORSCHAU_TAGE = 180

#: Ab wann ein Leerstand nicht mehr «frisch» ist, sondern erklärungsbedürftig.
#: Drei Monate ohne Mieter sind keine Fluktuation mehr.
LANGE_LEER_TAGE = 90

#: Die drei Gruppen der Filterleiste. `whg` und `stwe` sind beide Wohnraum;
#: `pp`, `gar` und `bas` sind Nebenobjekte, die man nicht einzeln ausschreibt.
#: Der Bastelraum stand bis hierher in KEINER Gruppe und war über den Filter
#: nicht erreichbar.
TYP_GRUPPEN = {
    'wohnen': ('whg', 'stwe'),
    'parkplatz': ('pp', 'gar', 'bas'),
    'gewerbe': ('gew',),
}

STUFEN_RANG = {'crit': 0, 'warn': 1, 'good': 2}


def _belegung(einheiten, stichtag):
    """Belegungszustand je Einheit — nach derselben Regel wie die Liste.

    Liefert je Einheit-Id: `belegt_bis`, `nachmieter_ab`, `unbefristet`,
    `leer_seit`, `mieter`, `vertrag_id`.

    `leer_seit` ist der einzige Wert, den die Liegenschaftsliste nicht kennt.
    Er stammt aus dem ZULETZT abgelaufenen Vertrag und zieht dafür bewusst
    auch archivierte heran: Ein Vertrag, der vor 300 Tagen endete, ist genau
    die Quelle der Aussage «steht seit zehn Monaten leer». Für die Frage, ob
    die Einheit HEUTE belegt ist, zählt er nicht mit — dafür gelten die
    importierten Statuslisten.
    """
    from rentals.models import Mietvertrag

    zustand = {e.id: {'belegt_bis': None, 'nachmieter_ab': None,
                      'unbefristet': False, 'leer_seit': None,
                      'mieter': None, 'vertrag_id': None}
               for e in einheiten}
    if not zustand:
        return zustand
    ids = list(zustand)
    letztes_ende = defaultdict(lambda: None)

    def _einordnen(e_id, v):
        z = zustand.get(e_id)
        if z is None:
            return
        if v.beginn and v.beginn > stichtag:
            if v.status in NACHMIETER_STATUS and (
                    z['nachmieter_ab'] is None or v.beginn < z['nachmieter_ab']):
                z['nachmieter_ab'] = v.beginn
            return
        if v.status in BELEGENDE_STATUS and (v.ende is None or v.ende >= stichtag):
            if v.ende is None:
                z['unbefristet'] = True
            elif z['belegt_bis'] is None or v.ende > z['belegt_bis']:
                z['belegt_bis'] = v.ende
            if v.status == 'aktiv' and z['mieter'] is None and v.mieter_id:
                z['mieter'] = v.mieter.display_name
                z['vertrag_id'] = v.id
            return
        # Abgelaufen — Kandidat fuer «leer seit». Entwuerfe zaehlen nicht:
        # Ein nie in Kraft getretener Vertrag hat die Wohnung nie belegt.
        if v.ende and v.ende < stichtag and v.status != 'entwurf':
            alt = letztes_ende[e_id]
            if alt is None or v.ende > alt:
                letztes_ende[e_id] = v.ende

    for v in Mietvertrag.objects.filter(
            einheit_id__in=ids).select_related('mieter'):
        _einordnen(v.einheit_id, v)

    # Nebenobjekte gelten mit dem Hauptvertrag als belegt. Ein Kellerabteil
    # ohne eigenen Vertrag als Leerstand zu melden waere falsch — man vermietet
    # es nicht einzeln.
    for v in (Mietvertrag.objects.filter(nebenobjekte__id__in=ids)
              .select_related('mieter').prefetch_related('nebenobjekte')):
        for neben in v.nebenobjekte.all():
            if neben.id in zustand:
                _einordnen(neben.id, v)

    for e_id, z in zustand.items():
        if not z['unbefristet'] and z['belegt_bis'] is None:
            z['leer_seit'] = letztes_ende[e_id]
    return zustand


def _befunde(einheit, z, stichtag):
    """Was an dieser einen Einheit klemmt.

    Die Reihenfolge ist Absicht: Der Leerstand steht vorn, weil er die Ursache
    ist; «kein Mietzins» und «nicht ausgeschrieben» erklären, WARUM er
    andauert.

    Bei einer BELEGTEN Wohnung schweigen die letzten beiden. Ein fehlender
    Sollmietzins ist dort ohne Wirkung — der Zins ergibt sich aus dem laufenden
    Vertrag —, und ausschreiben will man sie ohnehin nicht. Ein Befund, der
    niemanden hindert, ist eine Beschwerde.
    """
    befunde = []
    bis = stichtag + timedelta(days=VORSCHAU_TAGE)

    # EIN NACHMIETER HEBT DEN BEFUND AUF — auch den heutigen, nicht nur den
    # angekuendigten. Der erste Anlauf pruefte `nachmieter_ab` nur beim
    # kuenftigen Leerstand; eine heute leere Wohnung mit Vertrag ab naechstem
    # Monat trug deshalb weiter «Steht leer» und «Nicht ausgeschrieben» —
    # zwei Rueffel fuer eine Wohnung, um die sich jemand laengst gekuemmert
    # hat. `KonsistenzTests` hat es gefunden: Die Liegenschaftsliste zaehlte
    # sie nicht als Leerstand, die Objektliste schon.
    versorgt = z['nachmieter_ab'] is not None
    leer_jetzt = (not z['unbefristet'] and z['belegt_bis'] is None
                  and not versorgt)
    leer_bald = (not leer_jetzt and z['belegt_bis'] is not None
                 and z['belegt_bis'] <= bis and not versorgt)

    if leer_jetzt:
        seit = z['leer_seit']
        if seit and (stichtag - seit).days > LANGE_LEER_TAGE:
            monate = max(1, (stichtag - seit).days // 30)
            befunde.append({'stufe': 'crit', 'text': 'Steht leer',
                            'titel': f'seit {seit.strftime("%d.%m.%Y")} — '
                                     f'{monate} Monate'})
        elif seit:
            befunde.append({'stufe': 'warn', 'text': 'Steht leer',
                            'titel': f'seit {seit.strftime("%d.%m.%Y")}'})
        else:
            befunde.append({'stufe': 'warn', 'text': 'Steht leer',
                            'titel': 'noch nie vermietet'})
    elif leer_bald:
        ab = z['belegt_bis'] + timedelta(days=1)
        befunde.append({'stufe': 'warn', 'text': 'Wird frei',
                        'titel': f'ab {ab.strftime("%d.%m.%Y")}, kein Nachmieter'})

    if leer_jetzt or leer_bald:
        # DER BEFUND AUS DEM BILDSCHIRMFOTO vom 21.08.2026: zwei leere
        # Wohnungen, beide mit «Soll-Miete —». Was keinen Preis hat, laesst
        # sich nicht ausschreiben — und die Seite sagte dazu einen Strich.
        if not einheit.nettomiete_aktuell:
            befunde.append({'stufe': 'crit', 'text': 'Kein Mietzins',
                            'titel': 'ohne Preis keine Ausschreibung'})
        elif not einheit.zur_ausschreibung:
            befunde.append({'stufe': 'warn', 'text': 'Nicht ausgeschrieben',
                            'titel': 'steht in keinem Inserat'})

    return befunde


def zeilen(einheiten, stichtag=None):
    """Eine Zeile je Einheit, mit Befunden und Belegung."""
    stichtag = stichtag or timezone.localdate()
    einheiten = list(einheiten)
    zustand = _belegung(einheiten, stichtag)

    ergebnis = []
    for e in einheiten:
        z = zustand[e.id]
        try:
            befunde = _befunde(e, z, stichtag)
        except Exception:
            # Ein stiller `except` wuerde hier eine dauerhaft ruhige Liste
            # erzeugen, die aussieht wie ein Portfolio ohne Probleme (Befund
            # P6: stumme except-Bloecke).
            log.exception('Objektbefunde fehlgeschlagen (Einheit %s)', e.id)
            befunde = []
        stufe = min((b['stufe'] for b in befunde),
                    key=lambda s: STUFEN_RANG.get(s, 9), default='good')
        ergebnis.append({
            'e': e, 'befunde': befunde, 'stufe': stufe,
            'mieter': z['mieter'], 'vertrag_id': z['vertrag_id'],
            'belegt': z['unbefristet'] or z['belegt_bis'] is not None,
            'nachmieter_ab': z['nachmieter_ab'],
            # `belegt` ist die PHYSISCHE Belegung und steuert die Zeile.
            # `versorgt` ist die BEWIRTSCHAFTLICHE: eine gekuendigte Wohnung
            # mit Nachmieter ist heute leer, aber niemand muss etwas tun. Die
            # Liegenschaftsliste zaehlt genau so — beide Seiten muessen
            # dieselbe Leerstandszahl zeigen, sonst traut man keiner.
            'versorgt': (z['unbefristet'] or z['belegt_bis'] is not None
                         or z['nachmieter_ab'] is not None),
        })
    return ergebnis


def gruppen(zeilenliste):
    """Zeilen nach Liegenschaft gruppieren — Gruppen nach Befund geordnet.

    Die Gruppierung bleibt (Entscheid 21.08.2026), aber sie folgt nicht mehr
    dem Alphabet: Die Liegenschaft mit der leerstehenden Wohnung steht oben,
    und sie steht offen. Ruhige Gruppen sind zu — was nichts zu sagen hat,
    soll keinen Bildschirm beanspruchen.
    """
    je_lg = defaultdict(list)
    for zeile in zeilenliste:
        je_lg[zeile['e'].liegenschaft_id].append(zeile)

    ergebnis = []
    for zeilen_der_lg in je_lg.values():
        # Innerhalb der Gruppe ebenfalls nach Befund — sonst steht der
        # vermietete Parkplatz vor der leeren Wohnung, nur weil er «P» heisst.
        zeilen_der_lg.sort(
            key=lambda z: (STUFEN_RANG.get(z['stufe'], 9),
                           -len(z['befunde']), z['e'].bezeichnung or ''))
        stufe = zeilen_der_lg[0]['stufe']
        ergebnis.append({
            'lg': zeilen_der_lg[0]['e'].liegenschaft,
            'zeilen': zeilen_der_lg,
            'anzahl': len(zeilen_der_lg),
            'belegt': sum(1 for z in zeilen_der_lg if z['belegt']),
            'leer': sum(1 for z in zeilen_der_lg if not z['versorgt']),
            'mit_befund': sum(1 for z in zeilen_der_lg if z['befunde']),
            'stufe': stufe,
            'offen': stufe != 'good',
        })
    ergebnis.sort(key=lambda g: (STUFEN_RANG.get(g['stufe'], 9),
                                 -g['mit_befund'], g['lg'].strasse or ''))
    return ergebnis


def streifen(zeilenliste):
    """Vier Zahlen für den Kopf — schmal, nicht als Kachelwand.

    Ersetzt die Fliesstextzeile «3 Mietobjekt(e) · 1 vermietet · 2 im
    Leerstand». Dieselbe Information, aber die vierte Zahl ist neu und die
    eigentlich handlungsleitende: wie viele Objekte einen Befund tragen.
    """
    gesamt = len(zeilenliste)
    belegt = sum(1 for z in zeilenliste if z['belegt'])
    # Leer heisst hier «ohne Nachfolge» — dieselbe Zaehlung wie in der
    # Liegenschaftsliste. Eine gekuendigte Wohnung mit Nachmieter ist zwar
    # bald leer, aber sie ist bewirtschaftet; sie mitzuzaehlen hiesse, den
    # beiden Seiten unterschiedliche Zahlen fuer denselben Bestand zu geben.
    leer = sum(1 for z in zeilenliste if not z['versorgt'])
    mit_befund = sum(1 for z in zeilenliste if z['befunde'])
    return {
        'gesamt': gesamt,
        'belegt': belegt,
        'leer': leer,
        'leer_stufe': 'warn' if leer else '',
        'mit_befund': mit_befund,
        'befund_stufe': ('crit' if any(z['stufe'] == 'crit' for z in zeilenliste)
                         else ('warn' if mit_befund else '')),
    }
