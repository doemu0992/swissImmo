# core/views/fw/vertragserstellung.py
#
# Der 7-Schritte-Assistent fuer neue Mietvertraege, Live-Vorschau,
# Bearbeiten und der Versand zur Signatur.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Braucht anfangsmietzins_auto_ablegen aus mietzins.py -- bis zu diesem
# Umzug lief das ueber _rest.py, jetzt direkt.

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext, gettext_lazy
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from core.services import mietzinsmodell as regeln
from crm.models import Mieter, Organisation
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

from .mietzins import anfangsmietzins_auto_ablegen

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num
from core.tenancy import aktuelle_organisation


# ============================================================
# ETAPPE D: VERTRAGSERSTELLUNG (7-Schritte-Assistent + Live-Vorschau)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_neu(request):
    return render(request, 'fw/vertrag_neu.html',
                  _assistent_kontext(request, request.GET.get('edit')))


def _mzm_config(aktueller_lik):
    """Konfiguration und Texte für static/js/fw-mietzinsmodell.js (Block «Mietzinsmodell»).

    Alle Texte laufen hier durch `gettext`; das Skript setzt nur ein (`{name}`) und kennt keine Regel.
    Die Mindestjahre stammen aus der Regelquelle, damit sie nirgends ein zweites Mal stehen.
    """
    return {
        'url': reverse('fw_mietzinsmodell_pruefen'),
        'jahre': regeln.MINDESTJAHRE,
        'stufen_max': STUFEN_MAX,
        'aktueller_lik': str(aktueller_lik),
        'texte': {
            'stufe': gettext('Stufe {n}'),
            'stufe_weg': gettext('Stufe {n} entfernen'),
            'ab': gettext('ab'),
            'plus_chf': gettext('+ CHF'),
            'neu_vor': gettext('→ neu CHF'),
            'ampel_ok': gettext('Mindestdauer erfüllt'),
            'ampel_nok': gettext('Mindestdauer nicht erfüllt'),
            'ampel_offen': gettext('Dauer offen'),
            'ampel_laedt': gettext('Prüfung läuft …'),
            'ampel_unbekannt': gettext('Nicht geprüft'),
            'ampel_ok_text': gettext('Fest bis {bis}. Verlangt ist die Dauer bis {soll} ({jahre} Jahre ab Mietbeginn).'),
            'beginn_fehlt': gettext('Der Mietbeginn fehlt (Schritt «Konditionen»): Ohne ihn lässt sich die feste Dauer nicht beurteilen.'),
            'nicht_erreichbar': gettext('Die Prüfung ist gerade nicht erreichbar. Der Server prüft beim Speichern trotzdem.'),
            'rueck_staffel': gettext('Staffelstufen entfernt'),
            'rueck_index': gettext('Index-Angaben entfernt'),
            'gen_beginn': gettext('Zuerst den Mietbeginn im Schritt «Konditionen» eintragen.'),
            'gen_betrag': gettext('Einen Betrag über 0 eintragen.'),
            'gen_anzahl': gettext('Die Anzahl muss zwischen 1 und {max} liegen.'),
            'vorschlag': gettext('Vorschlag: {punkte} Punkte, Stand {stand} (Vormonat des Mietbeginns).'),
            'vorschlag_keiner': gettext('Für diesen Mietbeginn ist noch kein Indexstand veröffentlicht.'),
            'beispiel': gettext('Beispiel: Bei LIK {lik} würde der Mietzins CHF {neu} betragen (heute CHF {alt}).'),
            'beispiel_gleich': gettext('Beispiel: Bei LIK {lik} bliebe der Mietzins bei CHF {alt}.'),
            'fuss_gesperrt': gettext('Gesperrt: {grund}'),
            'fuss_weitere': gettext('(und {n} weitere)'),
            'zus_modell': gettext('Mietzinsmodell'),
            'zus_fest_bis': gettext('Feste Dauer bis'),
            'zus_basis': gettext('Basis Landesindex'),
            'zus_weitergabe': gettext('Weitergabe'),
            'modelle': {'fest': gettext('Fester Mietzins'), 'staffel': gettext('Staffelmiete'),
                        'index': gettext('Indexmiete')},
        },
    }


def _assistent_kontext(request, edit_id=None, immer_zeigen=None):
    """Alles, was der Vertragsassistent zum Anzeigen braucht.

    `immer_zeigen`: eine Einheit, die in der Auswahl stehen muss, auch wenn
    sie noch belegt ist — beim erneuten Anzeigen nach einem Fehler das Objekt,
    das schon gewählt war (etwa der Nachmieter-Vertrag, dessen Vorgänger noch
    aktiv ist).
    """
    from crm.models import Mieter
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = aktuelle_organisation()
    verwaltung = {
        'firma': vw.firma if vw else '', 'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

    # Bearbeiten-Modus: der Assistent editiert einen bestehenden ENTWURF (voll).
    from core.utils.parameter import id_param
    edit_id = id_param(edit_id)           # `?edit=abc` ist kein Entwurf, nicht 500 (ROUTE-05)
    edit_vertrag = (Mietvertrag.objects
                    .filter(id=edit_id, status='entwurf')
                    .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first()
                    if edit_id else None)

    # Vorwahl einer bestimmten Einheit (z.B. aus dem Mieterwechsel-Cockpit):
    # dann nur diese Liegenschaft + dieses Objekt anzeigen, keine Auswahl nötig.
    try:
        vorwahl_einheit = id_param(request.GET.get('einheit'))
    except ValueError:
        vorwahl_einheit = None
    vorwahl_e = Einheit.objects.select_related('liegenschaft').filter(id=vorwahl_einheit).first() if vorwahl_einheit else None
    # Die aufgelöste Einheit ist massgeblich, nicht die Zahl aus der URL:
    # `Einheit.objects` filtert auf den Mandanten, `vorwahl_e` ist bei einer
    # fremden ID also None — die rohe Zahl blieb aber im Kontext stehen und
    # damit eine fremde Objekt-ID im Formularzustand.
    vorwahl_einheit = vorwahl_e.pk if vorwahl_e else None

    # Belegte Einheiten (aktiver Vertrag inkl. Nebenobjekte) ausschliessen
    belegte = set(Mietvertrag.objects.filter(status='aktiv').values_list('einheit_id', flat=True))
    for nid in Mietvertrag.objects.filter(status='aktiv').values_list('nebenobjekte', flat=True):
        if nid:
            belegte.add(nid)
    # Die vorgewählte Einheit immer zeigen (Nachmieter-Vertrag beginnt nach Auszug,
    # der alte Vertrag kann noch aktiv/gekündigt sein).
    belegte.discard(vorwahl_einheit)
    belegte.discard(immer_zeigen)
    # Im Bearbeiten-Modus das Objekt des Entwurfs immer einschliessen (sonst kann
    # der Assistent es nicht vorbelegen).
    if edit_vertrag:
        belegte.discard(edit_vertrag.einheit_id)

    lg_qs = Liegenschaft.objects.select_related('eigentuemer').prefetch_related('einheiten').order_by('strasse')
    if vorwahl_e:
        lg_qs = lg_qs.filter(id=vorwahl_e.liegenschaft_id)
    elif aktive_lg and not edit_vertrag:
        lg_qs = lg_qs.filter(id=aktive_lg.id)

    liegenschaften = []
    for lg in lg_qs:
        objekte = []
        for e in lg.einheiten.all().order_by('bezeichnung'):
            if e.id in belegte:
                continue
            if vorwahl_e and e.id != vorwahl_einheit:
                continue   # bei Vorwahl nur genau dieses Objekt
            # Datierte Sollmietzins-Historie (gültig ab) — neue Verträge
            # übernehmen die zum Mietbeginn gültige Zeile automatisch.
            sollplan = [{'ab': s.gueltig_ab.isoformat(),
                         'netto': float(s.netto_mietzins or 0),
                         'nk': float(s.nebenkosten or 0),
                         'ref': float(s.basis_referenzzinssatz) if s.basis_referenzzinssatz is not None else None,
                         'lik': float(s.basis_lik_punkte) if s.basis_lik_punkte is not None else None}
                        for s in e.sollmietzinse.all()]  # bereits -gueltig_ab sortiert
            # Objekt-Staffelmiete-Vorlage (aufsteigend nach gueltig_ab) → belegt
            # einen neuen Gewerbe-Vertrag als Staffelmiete vor.
            staffelvorlage = [{'ab': s.gueltig_ab.isoformat(), 'netto': float(s.netto_mietzins or 0)}
                              for s in e.staffelvorlagen.all()]
            objekte.append({
                'id': e.id, 'bezeichnung': e.bezeichnung,
                'typ': e.get_typ_display(), 'typ_code': e.typ, 'etage': e.etage or '',
                'ewid': e.ewid or '', 'zimmer': float(e.zimmer) if e.zimmer else None,
                'flaeche': float(e.flaeche_m2) if e.flaeche_m2 else None,
                'netto': float(e.nettomiete_aktuell or 0), 'nk': float(e.nebenkosten_aktuell or 0),
                'sollplan': sollplan,
                'staffelvorlage': staffelvorlage,
                'nk_abrechnungsart': e.nk_abrechnungsart or 'akonto',
                'kaution_monate': e.standard_kautionsmonate or 3,
                'vertrag_titel': e.vertrag_titel, 'kategorie': e.mietrecht_kategorie,
                'ist_einstellplatz': e.ist_einstellplatz,
            })
        if not objekte:
            continue
        # Vermieter = Eigentümer sonst Verwaltung
        if lg.eigentuemer_id:
            vermieter = {'name': lg.eigentuemer.firma_oder_name,
                         'strasse': lg.eigentuemer.strasse or lg.strasse,
                         'plz': lg.eigentuemer.plz or lg.plz, 'ort': lg.eigentuemer.ort or lg.ort}
        else:
            vermieter = {'name': verwaltung['firma'], 'strasse': verwaltung['strasse'],
                         'plz': verwaltung['plz'], 'ort': verwaltung['ort']}
        liegenschaften.append({
            'id': lg.id, 'strasse': lg.strasse, 'plz': lg.plz, 'ort': lg.ort,
            'egid': lg.egid or '', 'vermieter': vermieter, 'objekte': objekte,
        })

    # Bestehende Mieter für Auswahl
    mieter = [{'id': m.id, 'name': m.display_name, 'anrede': m.anrede or '',
               'vorname': m.vorname or '', 'nachname': m.nachname or '',
               'strasse': m.strasse or '', 'plz': m.plz or '', 'ort': m.ort or '', 'email': m.email or ''}
              for m in Mieter.objects.all().order_by('nachname', 'firmen_name')]

    # Prefill-Daten für den Bearbeiten-Modus (Entwurf).
    edit_json = None
    if edit_vertrag:
        ev = edit_vertrag
        edit_json = {
            'id': ev.id, 'lg_id': ev.einheit.liegenschaft_id, 'einheit_id': ev.einheit_id,
            'mieter_id': ev.mieter_id, 'mit_mieter_id': ev.mitmieter_id or '',
            'mitmieter_name': ev.mitmieter_name or '', 'familienwohnung': bool(ev.familienwohnung),
            'anzahl_personen': ev.anzahl_personen or 1,
            'beginn': ev.beginn.isoformat() if ev.beginn else '',
            'ende': ev.ende.isoformat() if ev.ende else '', 'unbefristet': not ev.ist_befristet,
            'erstmals_kuendbar': ev.erstmals_kuendbar_auf.isoformat() if ev.erstmals_kuendbar_auf else '',
            'kuendigungsfrist': ev.kuendigungsfrist_monate, 'kuendigungstermine': ev.kuendigungstermine or '',
            'mitbenutzung': ev.mitbenutzung or '', 'nebenraeume': ev.nebenraeume or '',
            'besondere_vereinbarungen': ev.besondere_vereinbarungen or '',
            'weitere_vorbehalte': ev.weitere_vorbehalte or '', 'zweckbestimmung': ev.zweckbestimmung or '',
            'zahlungsrhythmus': ev.zahlungsrhythmus or 'monatlich',
            'netto_mietzins': float(ev.netto_mietzins or 0), 'nebenkosten': float(ev.nebenkosten or 0),
            'nk_abrechnungsart': ev.nk_abrechnungsart or 'akonto',
            'verteilschluessel': ev.verteilschluessel or 'm2',
            'mwst_pflichtig': bool(ev.mwst_pflichtig), 'mwst_satz': float(ev.mwst_satz or 8.1),
            'mietzins_modell': ev.mietzins_modell or 'fest',
            'verzicht_bis': ev.vermieter_kuendigungsverzicht_bis.isoformat() if ev.vermieter_kuendigungsverzicht_bis else '',
            'stufen': _stufen_fuer_assistent(ev),
            'basis_lik_stand': ev.basis_lik_stand.strftime('%Y-%m') if ev.basis_lik_stand else '',
            'index_weitergabe_prozent': str(ev.index_weitergabe_prozent) if ev.index_weitergabe_prozent is not None else '',
            'index_intervall_monate': ev.index_intervall_monate,
            'basis_referenzzinssatz': float(ev.basis_referenzzinssatz) if ev.basis_referenzzinssatz is not None else None,
            'basis_lik_punkte': float(ev.basis_lik_punkte) if ev.basis_lik_punkte is not None else None,
            'kautions_betrag': float(ev.kautions_betrag) if ev.kautions_betrag else '',
            'kautions_konto': ev.kautions_konto or '',
        }

    from core.services.docuseal_service import docuseal_konfiguriert
    lik_vorgaben = _lik_assistent_defaults(vw)
    return {
        **basis, 'nav': 'vertraege',
        'mzm_config': _mzm_config(lik_vorgaben['aktueller_lik']),
        'liegenschaften': liegenschaften, 'mieter': mieter,
        'verwaltung': verwaltung,
        'aktueller_ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.25,
        **lik_vorgaben,
        'heute_iso': timezone.localdate().isoformat(),
        'vorwahl_einheit': vorwahl_einheit or '',
        'edit_vertrag': edit_vertrag, 'edit_json': edit_json,
        'docuseal_konfiguriert': docuseal_konfiguriert(),
    }


def _assistent_mit_fehlern(request, P, feld_fehler, einheit):
    """Den Assistenten mit den Eingaben und den Meldungen am Feld erneut zeigen.

    Status 400. `rueckgabe` sind die abgeschickten Werte (Name → Liste); das
    Skript der Vorlage setzt sie wieder ein, wie beim Bearbeiten eines
    Entwurfs. Es sind die eigenen Eingaben dieser Anfrage, und `json_script`
    maskiert sie.
    """
    kontext = _assistent_kontext(request, P.get('edit_id'),
                                 immer_zeigen=einheit.pk if einheit else None)
    kontext.update({
        'rueckgabe': {k: P.getlist(k) for k in P if k != 'csrfmiddlewaretoken'},
        'feld_fehler': feld_fehler,
        'anzahl_fehler': len(feld_fehler),
    })
    return render(request, 'fw/vertrag_neu.html', kontext, status=400)


def _lik_assistent_defaults(vw):
    """Auto-Vorbelegung LIK für den Vertragsassistenten: Basis + neuester
    Stand-Monat + Punkte aus der offiziellen BFS-Tabelle (mit Fallback auf die
    Account-Einstellungen, falls die Tabelle mal leer ist)."""
    from core.services.lik import aktueller_lik_wert
    stand, pkt, basis = aktueller_lik_wert()
    lik = float(pkt) if pkt is not None else (float(vw.aktueller_lik_punkte) if vw else 107.1)
    stand_iso = (stand.strftime('%Y-%m') if stand
                 else (vw.aktueller_lik_stand.strftime('%Y-%m') if vw and vw.aktueller_lik_stand else ''))
    return {'aktueller_lik': lik, 'lik_basis': basis, 'aktueller_lik_stand_iso': stand_iso}


#: Felder des Assistenten, die gelesen werden müssen, wenn sie ausgefüllt sind.
#: (Name, Art, Beschriftung für die Meldung)
ASSISTENT_ZAHLEN = (
    ('netto_mietzins', 'betrag', gettext_lazy('Nettomietzins')),
    ('nebenkosten', 'betrag', gettext_lazy('Nebenkosten')),
    ('kautions_betrag', 'betrag', gettext_lazy('Kaution')),
    ('mwst_satz', 'betrag', gettext_lazy('MWST-Satz')),
    ('basis_referenzzinssatz', 'betrag', gettext_lazy('Referenzzinssatz')),
    ('basis_lik_punkte', 'betrag', gettext_lazy('LIK-Stand (Punkte)')),
    ('index_weitergabe_prozent', 'betrag', gettext_lazy('Index-Weitergabe (%)')),
    ('anzahl_personen', 'ganzzahl', gettext_lazy('Anzahl Personen')),
    ('kuendigungsfrist', 'ganzzahl', gettext_lazy('Kündigungsfrist (Monate)')),
    ('index_intervall_monate', 'ganzzahl', gettext_lazy('Index-Mindestintervall (Monate)')),
    ('beginn', 'datum', gettext_lazy('Mietbeginn')),
    ('ende', 'datum', gettext_lazy('Mietende')),
    ('erstmals_kuendbar', 'datum', gettext_lazy('Erstmals kündbar auf')),
    ('vermieter_kuendigungsverzicht_bis', 'datum', gettext_lazy('Vermieter verzichtet auf Kündigung bis')),
    ('kostensteigerung_datum', 'datum', gettext_lazy('Kostensteigerung per')),
)


#: Mehr Stufen sind ein Fehler in der Eingabe, keine Staffel (wie der Live-Endpunkt).
STUFEN_MAX = 60


def _stufen_fuer_assistent(vertrag):
    """Die gespeicherten Stufen eines Entwurfs als Zeilen des Assistenten: Datum und Erhöhung in CHF.
    Altstufen ohne Erhöhung (nur ein Betrag): die Erhöhung folgt aus dem Stand davor."""
    zeilen = []
    laufend = vertrag.netto_mietzins or Decimal('0')
    for s in vertrag.staffelstufen.all().order_by('ab_datum', 'id'):
        erh = s.erhoehung_chf if s.erhoehung_chf is not None else (s.netto_mietzins - laufend)
        zeilen.append({'ab': s.ab_datum.isoformat(), 'erhoehung': format(erh, 'f')})
        laufend = laufend + erh
    return zeilen


def _zahl(roh):
    """Decimal aus einer Eingabe (Schweizer Schreibweise), sonst None. Unlesbares wird nicht erraten."""
    t = _num((roh or '').strip())
    if not t:
        return None
    try:
        d = Decimal(t)
    except Exception:
        return None
    return d if d.is_finite() and abs(d) < Decimal('1e9') else None


def _tag(roh):
    try:
        return date.fromisoformat((roh or '').strip())
    except ValueError:
        return None


def _monat(roh):
    """JJJJ-MM (Feld type=month) → erster des Monats."""
    teile = (roh or '').strip().split('-')
    try:
        return date(int(teile[0]), int(teile[1]), 1)
    except (ValueError, IndexError):
        return None


def _nachkommastellen(d):
    return max(0, -d.as_tuple().exponent)


@dataclass
class ModellEingabe:
    """Das Mietzinsmodell, wie es der Assistent abgeschickt hat, samt Ergebnis der Prüfung.

    `sperren` verhindern das Speichern; `fehler` (Feld → Meldung) sind dieselben Befunde in der Form,
    in der der Assistent sie bei den Feldern zeigt. `altlast`: Die Sperren gehören zu einem
    bestehenden Entwurf, dessen Mietzinsmodell nicht geändert wurde, und blockieren nicht.
    """
    modell: str = 'fest'
    ist_befristet: bool = False          # befristet UND ein Ende gesetzt
    ende: date | None = None             # nur bei Befristung
    verzicht_bis: date | None = None     # nur bei einem unbefristeten Vertrag
    stufen: list = field(default_factory=list)   # regeln.Stufe in der Reihenfolge der Eingabe
    stufen_behalten: bool = False        # keine Staffelzeilen geschickt: die gespeicherten bleiben
    basis_punkte: Decimal | None = None
    basis_stand: date | None = None
    weitergabe: Decimal = Decimal('100')
    intervall: int = 12
    sperren: list = field(default_factory=list)
    fehler: dict = field(default_factory=dict)
    altlast: bool = False

    @property
    def stufen_fuer_vorschau(self):
        return [{'ab': s.ab, 'erhoehung': s.erhoehung_chf} for s in self.stufen]

    @property
    def meldungen(self):
        """Alle Meldungen, ohne Doppelte, in der Reihenfolge der Entdeckung."""
        return list(dict.fromkeys(self.fehler.values()))


def _befund_schluessel(b):
    feld = b.feld or 'mietzins_modell'
    return f'{feld}[{b.zeile}]' if b.zeile is not None else feld


def _signatur(modell, beginn, ende, ist_befristet, verzicht, stufen, punkte, stand, weitergabe, intervall):
    """Was am Mietzinsmodell hängt — zum Vergleich mit dem gespeicherten Entwurf."""
    sig = [modell, beginn, ende if ist_befristet else None, bool(ist_befristet), verzicht]
    if modell == 'staffel':
        sig.append(tuple(sorted(((s.ab, s.erhoehung_chf) for s in stufen),
                                key=lambda z: (z[0] or date.min, z[1] if z[1] is not None else Decimal('-1e9')))))
    if modell == 'index':
        sig += [punkte, (stand.year, stand.month) if stand else None, weitergabe, intervall]
    return tuple(sig)


def _stufen_aus_vertrag(vertrag):
    return [regeln.Stufe(ab=date.fromisoformat(z['ab']), erhoehung_chf=Decimal(z['erhoehung']))
            for z in _stufen_fuer_assistent(vertrag)]


def _modell_aus_eingabe(P, *, beginn, netto, vorhandener=None):
    """Liest das Mietzinsmodell aus den Eingaben und hält es gegen `core/services/mietzinsmodell.pruefe`.

    EINE Regelquelle: Der Live-Endpunkt des Assistenten und diese Stelle rufen dieselbe Prüfung. Der
    Browser lässt sich umgehen, diese Stelle nicht. `beginn` ist der abgeschickte Mietbeginn oder
    None; ohne ihn lässt sich die Dauer nicht beurteilen, und Index und Staffel werden abgelehnt.
    `vorhandener`: der Entwurf, der bearbeitet wird. Ändert die Eingabe nichts am Mietzinsmodell, wird
    er nicht wegen eines früheren Verstosses blockiert (Altlast).
    """
    e = ModellEingabe()
    modell = (P.get('mietzins_modell') or 'fest').strip()
    if modell not in regeln.MODELLE:
        e.fehler['mietzins_modell'] = gettext('Unbekanntes Mietzinsmodell.')
        modell = 'fest'
    e.modell = modell
    roh_befristet = P.get('ist_befristet') == '1'
    ende = _tag(P.get('ende'))
    e.ist_befristet = roh_befristet and ende is not None
    e.ende = ende if roh_befristet else None
    # Ein Verzicht des Vermieters ersetzt die Befristung; bei einem befristeten Vertrag zählt das Ende.
    e.verzicht_bis = None if roh_befristet else _tag(P.get('vermieter_kuendigungsverzicht_bis'))

    # Staffelzeilen: parallele Listen, wie im Assistenten
    ab_l, erh_l, proz_l = (P.getlist(n) for n in ('staffel_ab', 'staffel_erhoehung', 'staffel_prozent'))
    n = max(len(ab_l), len(erh_l), len(proz_l))
    if n > STUFEN_MAX:
        e.fehler['staffelstufen'] = gettext('Mehr als %(max)s Staffelstufen sind nicht möglich.') % {'max': STUFEN_MAX}
        n = STUFEN_MAX
    for i in range(n):
        ab = _tag(ab_l[i]) if i < len(ab_l) else None
        erh = _zahl(erh_l[i]) if i < len(erh_l) else None
        proz_roh = (proz_l[i] if i < len(proz_l) else '').strip()
        # Eine Prozentangabe gilt immer als Verstoss (Art. 269c lit. c OR), auch wenn sie unlesbar ist.
        prozent = (_zahl(proz_roh) or Decimal('1')) if proz_roh else None
        if erh is not None:
            if abs(erh) >= Decimal('1e6'):
                e.fehler[f'staffel_erhoehung[{i}]'] = gettext('Stufe %(nr)s: Die Erhöhung ist zu hoch.') % {'nr': i + 1}
            elif _nachkommastellen(erh) > 2:
                e.fehler[f'staffel_erhoehung[{i}]'] = gettext(
                    'Stufe %(nr)s: Die Erhöhung ist auf den Rappen genau anzugeben.') % {'nr': i + 1}
        e.stufen.append(regeln.Stufe(ab=ab, erhoehung_chf=erh, prozent=prozent))
    leer = not any(s.ab or s.erhoehung_chf is not None or s.prozent for s in e.stufen)
    if (leer and modell == 'staffel' and vorhandener is not None and vorhandener.mietzins_modell == 'staffel'
            and vorhandener.staffelstufen.exists()):
        # Das Formular brachte keine Staffeldaten mit (ältere Bearbeitungsmasken): die gespeicherten bleiben.
        e.stufen = _stufen_aus_vertrag(vorhandener)
        e.stufen_behalten = True

    # Indexangaben: nur bei der Indexmiete gültig
    w = _zahl(P.get('index_weitergabe_prozent'))
    iv = _zahl(P.get('index_intervall_monate'))
    punkte = _zahl(P.get('basis_lik_punkte'))
    stand = _monat(P.get('basis_lik_stand'))
    if modell == 'index':
        if w is not None and _nachkommastellen(w) > 1:
            e.fehler['index_weitergabe_prozent'] = gettext('Die Weitergabe hat höchstens eine Nachkommastelle.')
        if punkte is not None and _nachkommastellen(punkte) > 1:
            e.fehler['basis_lik_punkte'] = gettext('Die Basis des Landesindexes hat höchstens eine Nachkommastelle.')
    elif modell == 'fest' and ((w is not None and w != regeln.VORGABE_WEITERGABE)
                               or (iv is not None and iv != regeln.VORGABE_INTERVALL)):
        e.fehler['index_weitergabe_prozent'] = gettext(
            'Bei festem Mietzins darf keine Indexklausel stehen bleiben (Weitergabe, Mindestintervall).')

    befunde = regeln.pruefe(
        modell=modell, beginn=beginn, ende=e.ende, ist_befristet=roh_befristet, verzicht_bis=e.verzicht_bis,
        netto=netto, stufen=e.stufen, basis_lik_punkte=punkte, basis_lik_stand=stand,
        weitergabe_prozent=w, intervall_monate=iv)
    e.sperren = regeln.sperren(befunde)
    if modell in regeln.MINDESTJAHRE and beginn is None:
        e.fehler['beginn'] = gettext('Der Mietbeginn fehlt: Ohne ihn lässt sich die feste Dauer nicht beurteilen.')

    e.basis_punkte, e.basis_stand = punkte, stand
    if modell == 'index':
        e.weitergabe = w if w is not None else regeln.VORGABE_WEITERGABE
        e.intervall = int(iv) if iv is not None and iv >= 1 else regeln.VORGABE_INTERVALL

    if vorhandener is not None and e.sperren:
        alt = _signatur(vorhandener.mietzins_modell, vorhandener.beginn, vorhandener.ende, vorhandener.ist_befristet,
                        vorhandener.vermieter_kuendigungsverzicht_bis, _stufen_aus_vertrag(vorhandener),
                        vorhandener.basis_lik_punkte, vorhandener.basis_lik_stand,
                        vorhandener.index_weitergabe_prozent, vorhandener.index_intervall_monate)
        neu = _signatur(modell, beginn, e.ende, e.ist_befristet, e.verzicht_bis, e.stufen, punkte, stand,
                        e.weitergabe, e.intervall)
        e.altlast = alt == neu
    if not e.altlast:
        for b in e.sperren:
            e.fehler.setdefault(_befund_schluessel(b), b.volltext)
    return e


def _unlesbare_eingaben(P):
    """(Feld, Meldung) für ausgefüllte, aber unlesbare Felder des Assistenten."""
    fehler = []
    for name, art, beschriftung in ASSISTENT_ZAHLEN:
        roh = (P.get(name) or '').strip()
        if not roh:
            continue
        try:
            if art == 'betrag':
                Decimal(_num(roh))
            elif art == 'ganzzahl':
                int(roh)
            else:
                date.fromisoformat(roh)
        except Exception:
            fehler.append((name, gettext('«%(eingabe)s» ist für «%(feld)s» nicht lesbar — nichts wurde gespeichert.')
                           % {'eingabe': roh[:40], 'feld': beschriftung}))
    # LIK-Stand-Monat (Feld type=month, JJJJ-MM): früher still durch den Vorgabewert ersetzt.
    roh = (P.get('basis_lik_stand') or '').strip()
    if roh and _monat(roh) is None:
        fehler.append(('basis_lik_stand', gettext('«%(eingabe)s» ist für «%(feld)s» nicht lesbar — nichts wurde gespeichert.')
                       % {'eingabe': roh[:40], 'feld': gettext('LIK Stand-Monat')}))
    # Staffelzeilen: Datum und Erhöhung je Zeile. Der Betrag der Stufe («staffel_netto») gibt es nicht mehr:
    # Art. 269c lit. c OR verlangt den Frankenbetrag der ERHÖHUNG.
    for i, roh in enumerate(P.getlist('staffel_ab')):
        roh = (roh or '').strip()
        if roh and _tag(roh) is None:
            fehler.append((f'staffel_ab[{i}]', gettext('Stufe %(nr)s: «%(eingabe)s» ist als Datum nicht lesbar — nichts wurde gespeichert.')
                           % {'nr': i + 1, 'eingabe': roh[:40]}))
    for i, roh in enumerate(P.getlist('staffel_erhoehung')):
        roh = (roh or '').strip()
        if roh and _zahl(roh) is None:
            fehler.append((f'staffel_erhoehung[{i}]', gettext('Stufe %(nr)s: «%(eingabe)s» ist als Erhöhung nicht lesbar — nichts wurde gespeichert.')
                           % {'nr': i + 1, 'eingabe': roh[:40]}))
    if any((roh or '').strip() for roh in P.getlist('staffel_netto')):
        fehler.append(('staffelstufen', gettext(
            'Eine Staffelstufe wird als Erhöhung in Franken erfasst, nicht als neuer Mietzins — nichts wurde gespeichert.')))
    return fehler


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_neu_speichern(request):
    """Erstellt den Mietvertrag (+ optional neuen Mieter) aus dem Assistenten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mieter
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_vertrag_neu')

    P = request.POST
    try:
        einheit = Einheit.objects.filter(id=int(P.get('einheit_id') or 0)).first()
    except ValueError:
        einheit = None

    # --- Serverseitige Validierung VOR jeder DB-Änderung (Live-Test F) ---
    # Clientseitige Prüfungen lassen sich umgehen; ein ungültiger Vertrag
    # (negative Miete, Ende vor Beginn, Mieter ohne Namen) darf nie gespeichert
    # werden. Bewusst vor der Mieter-Anlage — sonst bliebe bei einem Fehler ein
    # Waisen-Mieter zurück.
    def _dec_val(key):
        try:
            return Decimal((_num(P.get(key)) or '0'))
        except Exception:
            return Decimal('0')

    def _datum_val(key):
        try:
            return date.fromisoformat(P.get(key)) if P.get(key) else None
        except ValueError:
            return None

    _v_beginn = _datum_val('beginn') or timezone.localdate()
    _v_ende = _datum_val('ende')
    # Bearbeiten-Modus: bestehenden ENTWURF aktualisieren statt neu anlegen.
    edit_id = P.get('edit_id')
    editing = (Mietvertrag.objects.filter(id=edit_id, status='entwurf').first()
               if edit_id else None)
    # Feld → Meldung. Die Meldung steht beim Feld; der Assistent öffnet den
    # Schritt des ersten Fehlers, und alle Eingaben bleiben stehen.
    feld_fehler = {}

    def _fehler(feld, meldung):
        feld_fehler.setdefault(feld, meldung)

    if not einheit:
        _fehler('einheit_id', gettext('Bitte wähle ein Objekt aus, bevor du den Vertrag erstellst.'))
    if _dec_val('netto_mietzins') < 0:
        _fehler('netto_mietzins', gettext('Der Netto-Mietzins darf nicht negativ sein.'))
    if not (einheit and einheit.ist_einstellplatz) and _dec_val('nebenkosten') < 0:
        _fehler('nebenkosten', gettext('Die Nebenkosten dürfen nicht negativ sein.'))
    # Nur prüfen, wenn der Vertrag WIRKLICH befristet gespeichert wird — sonst wird
    # `ende` beim Speichern ohnehin verworfen (siehe _ist_befristet weiter unten),
    # und ein stehengebliebener Alt-Wert im Feld dürfte die Anlage nicht blockieren.
    if P.get('ist_befristet') == '1' and _v_ende and _v_ende < _v_beginn:
        _fehler('ende', gettext('Das Vertragsende darf nicht vor dem Vertragsbeginn liegen.'))
    if not (P.get('mieter_id') or '').strip():
        _typ_neu = P.get('mieter_typ', 'person')
        if _typ_neu in ('firma', 'verein') and not P.get('firmen_name', '').strip():
            _fehler('firmen_name', gettext('Bitte den Firmen-/Vereinsnamen erfassen.'))
        elif _typ_neu == 'person' and not P.get('nachname', '').strip():
            _fehler('nachname', gettext('Bitte den Nachnamen des Mieters erfassen.'))
    # UNLESBARES WIRD ABGELEHNT, NICHT ERSETZT (Audit Etappe 2).
    #
    # Weiter unten deutet der Assistent eine unlesbare Eingabe still um: der
    # Nettomietzins wird CHF 0, der Mietbeginn heute, der Referenzzinssatz
    # 1.25 %, der LIK-Stand 107.1 Punkte. Die letzten beiden sind die Basis
    # jeder späteren Mietzinsanpassung — ein still eingesetzter Wert rechnet
    # dort falsch, ohne dass es jemand bemerkt. Eine unlesbare Personenzahl
    # war ein Serverfehler. Leer bleibt erlaubt (dann gilt die Vorgabe wie
    # bisher); nur, was eingetippt und nicht lesbar ist, hält hier an.
    for feld, meldung in _unlesbare_eingaben(P):
        _fehler(feld, meldung)
    # Kündigungsfrist unter der gesetzlichen Mindestfrist (Art. 266c/266d OR) wird abgelehnt (Audit MIET-08).
    from rentals.services import kuendigungsfrist_fehler
    _kf_fehler = kuendigungsfrist_fehler(P.get('kuendigungsfrist'), einheit)
    if _kf_fehler:
        _fehler('kuendigungsfrist', _kf_fehler)
    # MIETZINSMODELL (Art. 269b/269c OR): hart, nicht als Warnung. Dieselbe Regelquelle wie die
    # Live-Prüfung im Assistenten; der Browser lässt sich umgehen, diese Stelle nicht.
    modell = _modell_aus_eingabe(P, beginn=_datum_val('beginn'), netto=_dec_val('netto_mietzins'),
                                 vorhandener=editing)
    for feld, meldung in modell.fehler.items():
        _fehler(feld, meldung)
    if feld_fehler:
        # Vorher: Meldungen oben, Weiterleitung auf einen LEEREN Assistenten —
        # sieben Schritte Eingaben waren weg (Audit Etappe 2, Nachtrag).
        return _assistent_mit_fehlern(request, P, feld_fehler, einheit)

    # Mieter: bestehend oder neu
    mieter_id = P.get('mieter_id') or ''
    if mieter_id:
        mieter = get_object_or_404(Mieter, id=mieter_id)
    else:
        neu_typ = P.get('mieter_typ', 'person')
        if neu_typ not in ('person', 'firma', 'verein'):
            neu_typ = 'person'
        mieter = Mieter.objects.create(
            typ=neu_typ,
            anrede=P.get('anrede', 'Herr') if neu_typ == 'person' else '',
            vorname=P.get('vorname', '').strip(),
            nachname=P.get('nachname', '').strip(),
            firmen_name=P.get('firmen_name', '').strip(),
            kontaktperson=P.get('kontaktperson', '').strip(),
            uid_nummer=P.get('uid_nummer', '').strip(),
            strasse=P.get('m_strasse', '').strip(), plz=P.get('m_plz', '').strip(),
            ort=P.get('m_ort', '').strip(), email=P.get('m_email', '').strip(),
        )

    def dec(key, default='0'):
        try:
            return Decimal((_num(P.get(key)) or str(default)))
        except Exception:
            return Decimal(default)

    def datum(key):
        v = P.get(key)
        if not v:
            return None
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None

    # Zweiter Mieter (Ehepartner) — gleiche Erfassung wie 1. Person:
    # bestehend (mit_mieter_id) ODER neu (mit_* Felder). Name -> mitmieter_name.
    mitmieter = ''
    zweiter_obj = None
    mit_id = P.get('mit_mieter_id') or ''
    if mit_id:
        zweiter_obj = Mieter.objects.filter(id=mit_id).first()
        if zweiter_obj:
            mitmieter = zweiter_obj.display_name
    if not mitmieter:
        mit_vorname = P.get('mit_vorname', '').strip()
        mit_nachname = P.get('mit_nachname', '').strip()
        # Nur einen Mitmieter bilden, wenn wirklich ein Name erfasst wurde —
        # die Anrede allein (Default 'Frau') darf keinen Phantom-Mieter erzeugen.
        if mit_vorname or mit_nachname:
            mit_teile = [P.get('mit_anrede', '').strip(), mit_vorname, mit_nachname]
            mitmieter = ' '.join(t for t in mit_teile if t).strip()
        else:
            mitmieter = P.get('mitmieter_name', '').strip()
        # Neue zweite Person mit Namen -> als Mieter-Datensatz anlegen (erscheint in Personen)
        if not zweiter_obj and (P.get('mit_vorname', '').strip() or P.get('mit_nachname', '').strip()):
            zweiter_obj = Mieter.objects.create(
                typ='person', anrede=P.get('mit_anrede', 'Frau'),
                vorname=P.get('mit_vorname', '').strip(), nachname=P.get('mit_nachname', '').strip(),
                strasse=P.get('mit_strasse', '').strip(), plz=P.get('mit_plz', '').strip(),
                ort=P.get('mit_ort', '').strip(), email=P.get('mit_email', '').strip(),
            )
    familienwohnung = P.get('familienwohnung') == 'on'

    beginn = datum('beginn') or timezone.localdate()

    # Kein Rueckfall mehr: `Liegenschaft.organisation` ist seit Etappe 5
    # `null=False`, der `or`-Zweig war damit tot — und haette, waere er je
    # erreichbar geworden, die erste Verwaltung der Installation geliefert.
    _vw = einheit.liegenschaft.organisation

    # Kündigungsfrist: bei Geschäftsräumen gesetzlich min. 6 Monate (Art. 266d);
    # wird der Wert nicht gesetzt, greift der art-abhängige Default.
    _kfrist_default = 6 if einheit.mietrecht_kategorie == 'gewerbe' else 3
    try:
        _kfrist = int(P.get('kuendigungsfrist') or _kfrist_default)
    except ValueError:
        _kfrist = _kfrist_default
    # Indexparameter (E2.52): Weitergabe und Mindestintervall gelten nur bei der Indexmiete. Bis
    # 27.10.2026 kappte der Server eine Weitergabe über 100 % still auf 100 und ersetzte 0 oder weniger
    # durch die Vorgabe; jetzt lehnt `_modell_aus_eingabe` das ab. Bei den anderen Modellen gelten die
    # Vorgaben des Modells (100 %, 12 Monate).
    _idx_weiter = modell.weitergabe
    _idx_intervall = modell.intervall
    _mietzins_modell = modell.modell

    # Basis des Landesindexes: bei der Indexmiete die abgeschickte (geprüft), sonst der Stand des Monats
    # VOR dem Mietbeginn; erst wenn die Tabelle dafür nichts hat, der Stand der Verwaltung von heute.
    # Der aktuelle Stand wäre als Basis eines Vertrags, der früher begann, falsch.
    _vor_stand, _vor_punkte = regeln.basis_lik_vorschlag(beginn)
    if _mietzins_modell == 'index':
        basis_lik_stand = modell.basis_stand
    else:
        from core.services.lik import aktueller_lik_wert
        _auto_stand, _auto_pkt, _ = aktueller_lik_wert()
        basis_lik_stand = modell.basis_stand or _vor_stand or _auto_stand or (_vw.aktueller_lik_stand if _vw else None)
    _basis_punkte = modell.basis_punkte or (None if _mietzins_modell == 'index' else _vor_punkte)

    # Einstellplätze (Parkplatz/Garage, Art. 266e) haben keine separaten
    # Nebenkosten — serverseitig hart auf 0 setzen, egal was übermittelt wurde.
    _nk = Decimal('0.00') if einheit.ist_einstellplatz else dec('nebenkosten')

    # Befristet = explizit angehakt (Checkbox «unbefristet» aus) UND ein Enddatum
    # gesetzt. So bleibt `ende` bei einem unbefristeten Vertrag leer, und ein
    # später via Kündigung gesetztes `ende` macht den Vertrag nicht «befristet».
    _ende = modell.ende
    _ist_befristet = modell.ist_befristet

    felder = dict(
        mieter=mieter, einheit=einheit,
        status='aktiv' if P.get('aktiv_setzen') == 'on' else 'entwurf',
        # `ende` NUR bei einem befristeten Vertrag speichern — sonst wird ein im
        # Formular stehengebliebener Alt-Wert fälschlich als Enddatum eines
        # unbefristeten Vertrags abgelegt (der Kommentar unten versprach das schon,
        # der Code setzte es aber unbedingt; Review-Befund).
        beginn=beginn, ende=(_ende if _ist_befristet else None), ist_befristet=_ist_befristet,
        vermieter_kuendigungsverzicht_bis=modell.verzicht_bis,
        erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
        kuendigungsfrist_monate=_kfrist,
        index_weitergabe_prozent=_idx_weiter,
        index_intervall_monate=_idx_intervall,
        kuendigungstermine=P.get('kuendigungstermine', '').strip() or 'Ende jedes Monats ausser Dezember',
        mitmieter_name=mitmieter, mitmieter=zweiter_obj, familienwohnung=familienwohnung,
        anzahl_personen=int(P.get('anzahl_personen') or 1),
        besondere_vereinbarungen=P.get('besondere_vereinbarungen', '').strip(),
        mitbenutzung=P.get('mitbenutzung', '').strip(),
        nebenraeume=P.get('nebenraeume', '').strip(),
        netto_mietzins=dec('netto_mietzins'), nebenkosten=_nk,
        nk_abrechnungsart=P.get('nk_abrechnungsart', 'akonto'),
        verteilschluessel=P.get('verteilschluessel', 'm2'),
        zahlungsrhythmus=P.get('zahlungsrhythmus', 'monatlich'),
        mwst_pflichtig=P.get('mwst_pflichtig') == 'on',
        mwst_satz=dec('mwst_satz') or Decimal('8.1'),
        mietzins_modell=_mietzins_modell,
        zweckbestimmung=P.get('zweckbestimmung', '').strip(),
        weitere_vorbehalte=P.get('weitere_vorbehalte', '').strip(),
        basis_referenzzinssatz=dec('basis_referenzzinssatz') or _stand_zins(einheit),
        basis_lik_punkte=_basis_punkte or _stand_lik(einheit),
        basis_lik_stand=basis_lik_stand,
        kostensteigerung_datum=datum('kostensteigerung_datum'),
        kautions_betrag=dec('kautions_betrag') or None,
        kautions_konto=P.get('kautions_konto', '').strip(),
        solidarhaftung=P.get('solidarhaftung', 'on') != 'off',
    )

    # Weitere WG-Mieter (bestehende Personen, mehrfach) — als M2M nach dem Save.
    _wg_ids = [i for i in P.getlist('weitere_mieter') if str(i).strip().isdigit()]

    with transaction.atomic():
        if editing:
            for _k, _v in felder.items():
                setattr(editing, _k, _v)
            editing.save()
            vertrag = editing
            # Brachte das Formular keine Staffeldaten mit (ältere Bearbeitungsmasken), bleiben die
            # gespeicherten Stufen; sonst stünde das Modell auf «Staffel» ohne eine einzige Stufe.
            # Sie sind dann Teil der geprüften Eingabe (`stufen_behalten`).
            if not modell.stufen_behalten:
                vertrag.staffelstufen.all().delete()   # neu aus dem Formular aufbauen
        else:
            vertrag = Mietvertrag.objects.create(**felder)
        # Staffelstufen: Datum und ERHÖHUNG in CHF (Art. 269c lit. c OR). `Staffelstufe.save()` leitet den
        # Nettomietzins der Stufe aus Vorstufe und Erhöhung ab.
        if _mietzins_modell == 'staffel' and not modell.stufen_behalten:
            from rentals.models import Staffelstufe
            for ab_d, erh, neu_netto in regeln.stufen_berechnen(vertrag.netto_mietzins, modell.stufen):
                # Eine Altlast (unverändert übernommener Entwurf) kann eine Stufe ohne positive Erhöhung
                # tragen; die Datenbank lässt sie nur ohne Erhöhung zu.
                Staffelstufe.objects.create(vertrag=vertrag, ab_datum=ab_d, netto_mietzins=neu_netto,
                                            erhoehung_chf=erh if erh > 0 else None)
        elif modell.stufen_behalten:
            from rentals.models import Staffelstufe
            Staffelstufe.kette_neu_rechnen(vertrag)   # der Netto-Mietzins kann sich geändert haben
        # WG: weitere Mieter setzen (Haupt- und 2. Mieter ausgenommen, keine Dubletten).
        if _wg_ids:
            aus = {mieter.id}
            if zweiter_obj:
                aus.add(zweiter_obj.id)
            ids = [int(i) for i in _wg_ids if int(i) not in aus]
            vertrag.weitere_mieter.set(Mieter.objects.filter(id__in=ids))
        elif editing and 'wg_sektion' in P:
            # Nur leeren, wenn die WG-Sektion im Formular tatsächlich vorhanden
            # war (verstecktes Feld). Sonst würde das Bearbeiten eines Entwurfs,
            # dessen Formular die WG-Sektion nicht rendert, die solidarisch
            # haftenden Mitmieter stillschweigend entfernen.
            vertrag.weitere_mieter.clear()
    # Wohnadresse = Objektadresse ab Mietbeginn — als datierte Adress-Zeile
    # (gültig ab = Vertragsbeginn). Der tägliche Lauf (run_adress_umzuege) bzw.
    # sync_effektive_adresse führt die effektiven Flat-Felder am Stichtag nach.
    from crm.models import MieterAdresse
    lg = einheit.liegenschaft
    obj_strasse = f"{lg.strasse}{(', ' + einheit.etage) if einheit.etage else ''}"

    def setze_zukunftsadresse(person):
        if not person:
            return
        MieterAdresse.objects.get_or_create(
            mieter=person, art='wohn', gueltig_ab=beginn,
            defaults=dict(strasse=obj_strasse, plz=lg.plz, ort=lg.ort,
                          quelle=f'vertrag:{vertrag.id}',
                          notiz='Einzug gemäss Mietvertrag'))
        # Wenn der Einzug bereits erreicht ist, effektive Adresse sofort nachführen.
        person.sync_effektive_adresse()

    setze_zukunftsadresse(mieter)
    setze_zukunftsadresse(zweiter_obj)
    for _wg in vertrag.weitere_mieter.all():
        setze_zukunftsadresse(_wg)

    # Vertragsdokumente NUR erzeugen, wenn der Vertrag als AKTIV gesetzt wird
    # (→ erscheinen in der Akte + im Mieterportal). Ein Entwurf bleibt dokumentlos,
    # bis er aktiviert wird — dann werden die PDFs einmalig erzeugt (auch beim
    # Aktivieren eines bearbeiteten Entwurfs). Fehler dürfen nicht blockieren.
    anzahl_dok = 0
    if P.get('aktiv_setzen') == 'on':
        # Aktives Mietverhältnis → Objekt aus der Vermarktung/Feed/Exposé nehmen
        # (auch beim direkten Vertragsweg, nicht nur über Bewerbung→Vertrag).
        if vertrag.einheit_id and vertrag.einheit.zur_ausschreibung:
            vertrag.einheit.zur_ausschreibung = False
            vertrag.einheit.save(update_fields=['zur_ausschreibung'])
        try:
            from core.views.pdf import erzeuge_und_ablege_vertragspaket
            anzahl_dok = len(erzeuge_und_ablege_vertragspaket(vertrag))
        except Exception:
            anzahl_dok = 0
        # Modul 5: Regel «Vertrag erstellt» — ein Begleitdokument zusätzlich zum
        # Paket. Fehler protokolliert die Regel selbst; der Vertrag ist gespeichert.
        from core.services.dokument_regeln import dokument_fuer_ereignis
        dokument_fuer_ereignis('vertrag_erstellt', organisation=vertrag.organisation, vertrag=vertrag)
        # Amtliches Anfangsmietzins-Formular (Art. 270 Abs. 2 OR) automatisch
        # mitgenerieren, sofern Formularpflicht besteht — steht so zur
        # Schlüsselübergabe bereit (30-Tage-Anfechtungsfrist ab Erhalt).
        try:
            erzeugt, _grund = anfangsmietzins_auto_ablegen(vertrag, verwaltung=_vw)
            if erzeugt:
                messages.info(request, '📄 ' + gettext('Amtliches Anfangsmietzins-Formular wurde automatisch erstellt (Formularpflicht) — bei Schlüsselübergabe aushändigen.'))
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # Nettomietzins 0 ist fast immer ein vergessenes Feld — warnen (nicht blockieren),
    # da ohne Mietzins die Sollstellung 0 verrechnet.
    if (vertrag.netto_mietzins or Decimal('0')) <= 0:
        messages.warning(request, '⚠️ ' + gettext('Nettomietzins ist CHF 0 — bitte prüfen. Ohne Mietzins erzeugt der Mietenlauf keine Forderung.'))

    # Mietzinsmodell (Art. 269b/269c OR): Verstösse hat `_modell_aus_eingabe` schon vor dem Speichern
    # abgelehnt. Gemeldet wird hier nur noch eine Altlast, ein bestehender Entwurf mit unverändertem
    # Modell, der nach den heutigen Regeln nicht mehr zulässig wäre.
    if modell.altlast:
        for b in modell.sperren:
            messages.warning(request, '⚠️ ' + gettext('Mietzinsmodell dieses Entwurfs (unverändert, daher nicht gesperrt): %(text)s')
                             % {'text': b.volltext})

    log_aktion(request, "Mietvertrag bearbeitet (Assistent)" if editing else "Mietvertrag erstellt (Assistent)",
               str(mieter), f"{einheit.bezeichnung}, ab {beginn}", ziel=vertrag)
    if anzahl_dok:
        messages.success(
            request,
            '✅ ' + (gettext('Mietvertrag für %(display_name)s aktualisiert & aktiv gesetzt — %(anzahl_dok)s Dokumente automatisch abgelegt (im Portal sichtbar).') if editing else gettext('Mietvertrag für %(display_name)s erstellt & aktiv gesetzt — %(anzahl_dok)s Dokumente automatisch abgelegt (im Portal sichtbar).')) % {'display_name': mieter.display_name, 'anzahl_dok': anzahl_dok})
    elif editing:
        messages.success(request, '✅ ' + gettext('Vertrag (Entwurf) für %(display_name)s aktualisiert.') % {'display_name': mieter.display_name})
    else:
        messages.success(request, '✅ ' + gettext('Mietvertrag (Entwurf) für %(display_name)s erstellt — PDFs werden erst beim Aktivieren erzeugt.') % {'display_name': mieter.display_name})

    # Optionaler Abschluss: direkt zur digitalen Unterschrift senden (DocuSeal).
    if P.get('abschluss') == 'senden':
        from core.services.docuseal_service import docuseal_senden
        ok, msg = docuseal_senden(vertrag)
        if ok:
            log_aktion(request, "Vertrag zur Unterschrift gesendet", str(mieter), msg, ziel=vertrag)
            messages.success(request, f"✍️ {msg}")
        else:
            messages.warning(request, gettext('Vertrag erstellt, aber Signaturversand nicht möglich: %(msg)s') % {'msg': msg})
    return redirect(f'/neu/vertraege/{vertrag.id}/')


def _stand_zins(einheit):
    """Basis-Referenzzinssatz, wenn das Formular keinen liefert: der Stand der
    Verwaltung HEUTE (nicht ein geratenes 1.25 %). Siehe `mietprozess._aktuelle_basis`."""
    from .mietprozess import _aktuelle_basis
    return _aktuelle_basis(einheit)[0]


def _stand_lik(einheit):
    from .mietprozess import _aktuelle_basis
    return _aktuelle_basis(einheit)[1]


def _vorschau_sperre_html(meldungen):
    """Der Rahmen der Vorschau (srcdoc) kennt die Stilschicht nicht: schlichtes HTML mit eigenen Angaben."""
    from django.utils.html import format_html, format_html_join
    return format_html(
        '<div style="font-family:Helvetica,sans-serif;padding:24px;font-size:13px;line-height:1.5;color:#334155;">'
        '<p style="margin:0 0 8px;font-weight:700;">{}</p><ul style="margin:0;padding-left:18px;">{}</ul></div>',
        gettext('Vorschau nicht möglich: Das Mietzinsmodell ist noch nicht zulässig.'),
        format_html_join('', '<li style="margin-bottom:4px;">{}</li>', ((m,) for m in meldungen)))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_vorschau(request):
    """Live-Vorschau des Vertragsassistenten: rendert das ECHTE Vertrags-PDF-
    Template als HTML aus den aktuellen Formularwerten (ohne zu speichern). So
    entspricht die Vorschau immer 1:1 dem generierten PDF — eine Quelle statt
    zwei divergierender Implementierungen."""
    from django.http import HttpResponse
    from crm.models import Mieter
    from core.services.pdf_service import render_vertrag_html
    if request.method != 'POST':
        return HttpResponse('', content_type='text/html')
    P = request.POST
    einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).select_related('liegenschaft').first()
    if not einheit:
        return HttpResponse(
            '<div style="font-family:Helvetica,sans-serif;color:#64748b;padding:40px;'
            'text-align:center;font-size:14px;">Bitte zuerst ein Objekt auswählen — '
            'dann erscheint hier die 1:1-Vorschau des Vertrags.</div>',
            content_type='text/html')

    def dec(key, default='0'):
        try:
            return Decimal((_num(P.get(key)) or str(default)))
        except Exception:
            return Decimal(default)

    def datum(key):
        try:
            return date.fromisoformat(P.get(key)) if P.get(key) else None
        except ValueError:
            return None

    # Mieter: bestehend oder transient aus den Feldern.
    mieter = None
    if P.get('mieter_id'):
        mieter = Mieter.objects.filter(id=P.get('mieter_id')).first()
    if mieter is None:
        mieter = Mieter(
            typ=P.get('mieter_typ', 'person'),
            anrede=P.get('anrede', '') if P.get('mieter_typ', 'person') == 'person' else '',
            vorname=P.get('vorname', '').strip(), nachname=P.get('nachname', '').strip(),
            firmen_name=P.get('firmen_name', '').strip(),
            strasse=P.get('m_strasse', '').strip(), plz=P.get('m_plz', '').strip(),
            ort=P.get('m_ort', '').strip(), email=P.get('m_email', '').strip())

    mitmieter = P.get('mitmieter_name', '').strip()
    if not mitmieter and (P.get('mit_vorname') or P.get('mit_nachname')):
        mitmieter = ' '.join(t for t in [P.get('mit_anrede', '').strip(),
                                          P.get('mit_vorname', '').strip(),
                                          P.get('mit_nachname', '').strip()] if t)

    _nk = Decimal('0.00') if einheit.ist_einstellplatz else dec('nebenkosten')
    # Mietzinsmodell (Art. 269b/269c OR): Die Vorschau zeigt den Vertrag, wie er gedruckt wird. Ein Vertrag,
    # den der Server nicht speichern würde, wird nicht als fertiger Vertrag gezeigt: statt seiner stehen
    # die Befunde da. Dieselbe Prüfung wie beim Speichern.
    modell = _modell_aus_eingabe(P, beginn=datum('beginn'), netto=dec('netto_mietzins'))
    if modell.fehler:
        return HttpResponse(_vorschau_sperre_html(modell.meldungen), content_type='text/html')
    _modell = modell.modell
    _vor_stand, _vor_punkte = regeln.basis_lik_vorschlag(datum('beginn') or timezone.localdate())
    # Transienter (nicht gespeicherter) Vertrag — nur zum Rendern.
    vertrag = Mietvertrag(
        mieter=mieter, einheit=einheit,
        beginn=datum('beginn') or timezone.localdate(), ende=modell.ende, ist_befristet=modell.ist_befristet,
        vermieter_kuendigungsverzicht_bis=modell.verzicht_bis,
        erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
        kuendigungsfrist_monate=int(P.get('kuendigungsfrist') or (6 if einheit.mietrecht_kategorie == 'gewerbe' else 3)),
        kuendigungstermine=P.get('kuendigungstermine', '').strip() or 'Ende jedes Monats ausser Dezember',
        mitmieter_name=mitmieter, familienwohnung=P.get('familienwohnung') == 'on',
        anzahl_personen=int(P.get('anzahl_personen') or 1),
        besondere_vereinbarungen=P.get('besondere_vereinbarungen', '').strip(),
        mitbenutzung=P.get('mitbenutzung', '').strip(),
        nebenraeume=P.get('nebenraeume', '').strip(),
        netto_mietzins=dec('netto_mietzins'), nebenkosten=_nk,
        nk_abrechnungsart=P.get('nk_abrechnungsart', 'akonto'),
        verteilschluessel=P.get('verteilschluessel', 'm2'),
        zahlungsrhythmus=P.get('zahlungsrhythmus', 'monatlich'),
        mwst_pflichtig=P.get('mwst_pflichtig') == 'on',
        mwst_satz=dec('mwst_satz') or Decimal('8.1'),
        mietzins_modell=_modell,
        zweckbestimmung=P.get('zweckbestimmung', '').strip(),
        weitere_vorbehalte=P.get('weitere_vorbehalte', '').strip(),
        basis_referenzzinssatz=dec('basis_referenzzinssatz') or _stand_zins(einheit),
        basis_lik_punkte=modell.basis_punkte or _vor_punkte or _stand_lik(einheit),
        basis_lik_stand=modell.basis_stand or _vor_stand,
        index_weitergabe_prozent=modell.weitergabe, index_intervall_monate=modell.intervall,
        kautions_betrag=dec('kautions_betrag') or None,
        kautions_konto=P.get('kautions_konto', '').strip())
    # Die Stufen sind noch nicht gespeichert: Die Klausel liest sie von hier (`klausel_kontext`).
    vertrag.vorschau_stufen = modell.stufen_fuer_vorschau
    try:
        html = render_vertrag_html(vertrag, mit_unterschrift=False)
    except Exception as exc:
        html = ('<div style="font-family:Helvetica,sans-serif;color:#b91c1c;padding:24px;'
                f'font-size:13px;">Vorschau konnte nicht erstellt werden: {exc}</div>')
    return HttpResponse(html, content_type='text/html')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_bearbeiten(request, pk):
    """Bearbeitet einen bestehenden Mietvertrag.

    - Entwurf: alle Felder frei editierbar.
    - Aktiv/gekündigt/archiviert: nur UNKRITISCHE Felder (Fristen-Detail, Nebenräume,
      Vereinbarungen, Mitmieter …). Miete, Objekt, Mieter, Beginn, MWST und
      Abrechnungsart sind GESPERRT — serverseitig erzwungen, nicht nur im UI
      (Mietzinsänderungen laufen über das amtliche Formular Art. 269d). So bleibt
      die Buchhaltung konsistent."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mieter, Organisation
    from core.auth import log_aktion, snapshot_model, diff_model
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=pk)
    gesperrt = v.status != 'entwurf'   # nur Entwurf voll editierbar

    # Entwurf → voller Assistent (mit Live-Vorschau). Aktive/gekündigte Verträge
    # → reduziertes Formular (Miete/Objekt gesperrt).
    if not gesperrt and request.method == 'GET':
        from django.shortcuts import redirect
        return redirect(f'/neu/vertraege/neu/?edit={v.id}')

    if request.method == 'POST':
        P = request.POST
        alt = snapshot_model(v)

        from rentals.forms import VertragBearbeitenForm
        # `vertrag=v`: Das Formular hält Ende, Beginn, Kündigungsverzicht und Indexangaben gegen die Regeln
        # des Mietzinsmodells (Art. 269b/269c OR) und lehnt Verstösse ab; ein unverändertes Modell nicht.
        form = VertragBearbeitenForm(P, entwurf=not gesperrt, beginn=v.beginn, vertrag=v)
        if not form.is_valid():
            # Nichts wird gespeichert; das Formular kommt mit den Eingaben und
            # den Hinweisen am Feld zurück (Audit Etappe 2).
            return _vertrag_bearbeiten_rendern(request, v, gesperrt, form, status=400)
        cd = form.cleaned_data

        # --- Immer editierbar (unkritisch) ---
        v.ende = cd.get('ende')
        # Befristung folgt bei einem AKTIVEN Vertrag dem Enddatum (leer = unbefristet).
        # Bei gekündigten/archivierten Verträgen stammt `ende` aus der Kündigung —
        # die Befristungs-Kennung nicht anrühren.
        if v.status == 'aktiv':
            v.ist_befristet = bool(v.ende)
        v.erstmals_kuendbar_auf = cd.get('erstmals_kuendbar')
        # Kündigungsverzicht des Vermieters (Art. 17 Abs. 4 VMWG): nur überschreiben, wenn das Feld
        # mitgeschickt wurde, sonst löscht ein Formular ohne das Feld den Wert still.
        if 'vermieter_kuendigungsverzicht_bis' in P:
            v.vermieter_kuendigungsverzicht_bis = cd.get('vermieter_kuendigungsverzicht_bis')
        if cd.get('kuendigungsfrist'):
            v.kuendigungsfrist_monate = cd['kuendigungsfrist']
        # DIE INDEXPARAMETER SIND EDITIERBAR — MIT PROTOKOLLEINTRAG (E2.53)
        #
        # Die Gegenprüfung zu E2.52 hat sie hier entfernt, mit einem guten
        # Grund: Die Weitergabe ändert künftige Mietzinse, und in dieser
        # Ansicht sind mietzinswirksame Felder gesperrt.
        #
        # DOMINIKS ENTSCHEIDUNG WIEGT DEN ANDEREN FALL SCHWERER: Wer eine
        # Weitergabe unter 100 % vereinbart hat (Art. 269b OR lässt das
        # ausdrücklich zu), konnte sie bei einem AKTIVEN Vertrag nirgends
        # nachtragen. Dann rechnet jede Indexanpassung zu hoch — und eine zu
        # hohe Erhöhung ist anfechtbar.
        #
        # WARUM DAS TROTZDEM ETWAS ANDERES IST als eine Mietzinsänderung:
        # Diese Felder ändern KEINEN Mietzins. Sie halten fest, was im Vertrag
        # vereinbart wurde — die Erhöhung selbst läuft weiterhin über das
        # amtliche Formular nach Art. 269d.
        #
        # DESHALB MIT PROTOKOLL: Jede Änderung landet im Logbuch, mit altem
        # und neuem Wert. Wer später fragt, warum eine Anpassung anders
        # gerechnet hat, findet die Antwort.
        #
        # Auch hier: nur überschreiben, wenn das Feld MITGESCHICKT wurde.
        # Sonst löscht ein Formular ohne diese Felder die Werte still.
        # (`messages` und `log_aktion` sind oben in dieser Funktion bereits
        # eingebunden — ein zweiter Import an dieser Stelle war überflüssig.)

        # `ziel=v` IST DER GANZE PUNKT (Gegenprüfung E2.53).
        #
        # Die erste Fassung übergab nur `objekt=f'Vertrag {v.id}'`. Im Logbuch
        # nachgemessen stand der Eintrag dann mit `ziel_typ=''` und
        # `ziel_id=None` da — er erscheint NICHT im Verlauf des Vertrags und
        # ist nicht anklickbar. Genau dort schaut aber nach, wer fragt, warum
        # eine Anpassung anders gerechnet hat. Der Ausgleich für die
        # Editierbarkeit hätte dort gefehlt, wo man ihn sucht.
        #
        # ZWEITER EINTRAG MIT ABSICHT: Das allgemeine «Vertrag bearbeitet» am
        # Ende dieser Funktion protokolliert die Änderung über `diff_model`
        # ohnehin mit («Index-Weitergabe (%): 100.0 → 80», ebenfalls `ziel=v`).
        # Eine eigene, benannte Zeile ist trotzdem sinnvoll: Sie lässt sich
        # suchen, eine Zeile im Sammel-Diff nicht.
        if 'index_weitergabe_prozent' in P:
            neu_w = cd.get('index_weitergabe_prozent')
            if neu_w is not None and neu_w != v.index_weitergabe_prozent:
                log_aktion(request, 'Index-Weitergabe geändert', str(v.mieter),
                           f'{v.index_weitergabe_prozent} % → {neu_w} %', ziel=v)
                v.index_weitergabe_prozent = neu_w
        if 'index_intervall_monate' in P:
            neu_i = cd.get('index_intervall_monate')
            if neu_i is not None and neu_i != v.index_intervall_monate:
                log_aktion(request, 'Index-Intervall geändert', str(v.mieter),
                           f'{v.index_intervall_monate} → {int(neu_i)} Monate', ziel=v)
                v.index_intervall_monate = int(neu_i)

        v.kuendigungstermine = P.get('kuendigungstermine', '').strip() or v.kuendigungstermine
        v.familienwohnung = P.get('familienwohnung') == 'on'
        v.mitmieter_name = P.get('mitmieter_name', '').strip()
        v.anzahl_personen = cd.get('anzahl_personen') or v.anzahl_personen or 1
        v.mitbenutzung = P.get('mitbenutzung', '').strip()
        v.nebenraeume = P.get('nebenraeume', '').strip()
        v.zweckbestimmung = P.get('zweckbestimmung', '').strip()
        v.besondere_vereinbarungen = P.get('besondere_vereinbarungen', '').strip()
        v.weitere_vorbehalte = P.get('weitere_vorbehalte', '').strip()

        # --- Nur bei Entwurf editierbar (kritisch) ---
        if not gesperrt:
            if cd.get('beginn'):
                v.beginn = cd['beginn']
            neue_einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).first()
            if neue_einheit:
                v.einheit = neue_einheit
            neuer_mieter = Mieter.objects.filter(id=P.get('mieter_id') or 0).first()
            if neuer_mieter:
                v.mieter = neuer_mieter
            v.netto_mietzins = cd.get('netto_mietzins') or Decimal('0')
            v.nebenkosten = (Decimal('0.00') if v.einheit.ist_einstellplatz
                             else cd.get('nebenkosten') or Decimal('0'))
            v.nk_abrechnungsart = P.get('nk_abrechnungsart', v.nk_abrechnungsart)
            v.verteilschluessel = P.get('verteilschluessel', v.verteilschluessel)
            v.zahlungsrhythmus = P.get('zahlungsrhythmus', v.zahlungsrhythmus)
            v.mwst_pflichtig = P.get('mwst_pflichtig') == 'on'
            if cd.get('mwst_satz') is not None:
                v.mwst_satz = cd['mwst_satz']
            v.kautions_betrag = cd.get('kautions_betrag') or None
            v.kautions_konto = P.get('kautions_konto', '').strip()
        v.save()
        _diff = diff_model(alt, snapshot_model(v), v)
        log_aktion(request, "Vertrag bearbeitet", str(v.mieter),
                   f"{v.einheit.bezeichnung} · {'Entwurf' if not gesperrt else 'nur Detailfelder'}"
                   + (f" · {_diff}" if _diff else ''), ziel=v)
        messages.success(request, '✅ ' + (gettext('Vertrag aktualisiert.') if not gesperrt
                                          else gettext('Vertrag aktualisiert (aktiver Vertrag — nur Detailfelder geändert).')))
        return redirect(f'/neu/vertraege/{v.id}/')

    return _vertrag_bearbeiten_rendern(request, v, gesperrt, None)


#: Felder, deren Wert die Vorlage aus `wert` liest statt aus dem Vertrag: Nach
#: einem Fehler steht dort die Eingabe. Ein unlesbares Datum oder ein Betrag
#: wie «ca. 1800» hätte am Vertrag gar keinen Platz.
VERTRAG_ROHWERTE = ('ende', 'vermieter_kuendigungsverzicht_bis', 'erstmals_kuendbar', 'kuendigungsfrist', 'anzahl_personen',
                    'index_weitergabe_prozent', 'index_intervall_monate', 'beginn',
                    'netto_mietzins', 'nebenkosten', 'kautions_betrag', 'mwst_satz')


def _vertrag_bearbeiten_rendern(request, v, gesperrt, form, status=200):
    from crm.models import Mieter
    if form is None:
        gespeichert = {
            'ende': v.ende, 'vermieter_kuendigungsverzicht_bis': v.vermieter_kuendigungsverzicht_bis,
            'erstmals_kuendbar': v.erstmals_kuendbar_auf,
            'kuendigungsfrist': v.kuendigungsfrist_monate, 'anzahl_personen': v.anzahl_personen or 1,
            'index_weitergabe_prozent': v.index_weitergabe_prozent,
            'index_intervall_monate': v.index_intervall_monate, 'beginn': v.beginn,
            'netto_mietzins': v.netto_mietzins or Decimal('0'), 'nebenkosten': v.nebenkosten or Decimal('0'),
            'kautions_betrag': v.kautions_betrag, 'mwst_satz': v.mwst_satz or Decimal('8.1'),
        }
        wert = {k: ('' if x is None else x.isoformat() if isinstance(x, date) else str(x))
                for k, x in gespeichert.items()}
        feld_fehler = {}
        formular_fehler = []
    else:
        wert = {k: form.data.get(k, '') for k in VERTRAG_ROHWERTE}
        feld_fehler = {name: fehler[0] for name, fehler in form.errors.items() if name != '__all__'}
        formular_fehler = list(form.non_field_errors())
        # Die Freitexte zeigt die Vorlage aus dem Vertrag — bei einem Fehler
        # also die Eingabe, nicht den gespeicherten Stand.
        for name in ('mitmieter_name', 'kuendigungstermine', 'mitbenutzung', 'nebenraeume',
                     'zweckbestimmung', 'besondere_vereinbarungen', 'weitere_vorbehalte',
                     'kautions_konto'):
            if name in form.data:
                setattr(v, name, form.data.get(name, ''))
        v.familienwohnung = form.data.get('familienwohnung') == 'on'
    return render(request, 'fw/vertrag_bearbeiten.html', {
        **_global_filter(request), 'nav': 'vertraege', 'v': v, 'gesperrt': gesperrt,
        'objekte': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
        'mieter_liste': Mieter.objects.order_by('nachname', 'firmen_name'),
        'nk_arten': Mietvertrag.NK_TYP_CHOICES,
        'verteil_choices': Mietvertrag.VERTEIL_CHOICES,
        'rhythmus_choices': Mietvertrag.ZAHLUNGSRHYTHMUS_CHOICES,
        'wert': wert, 'feld_fehler': feld_fehler, 'formular_fehler': formular_fehler,
        'anzahl_fehler': len(feld_fehler) + len(formular_fehler),
    }, status=status)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_signieren(request, pk):
    """Sendet einen bestehenden Vertrag zur digitalen Unterschrift (DocuSeal)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.docuseal_service import docuseal_senden
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit'), id=pk)
    if request.method == 'POST':
        ok, msg = docuseal_senden(v)
        if ok:
            log_aktion(request, "Vertrag zur Unterschrift gesendet", str(v.mieter), msg, ziel=v)
            messages.success(request, f"✍️ {msg}")
        else:
            messages.error(request, f"❌ {msg}")
    return redirect(f'/neu/vertraege/{v.id}/')
