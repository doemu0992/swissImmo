# core/views/fw/vertragserstellung.py
#
# Der 7-Schritte-Assistent fuer neue Mietvertraege, Live-Vorschau,
# Bearbeiten und der Versand zur Signatur.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Braucht anfangsmietzins_auto_ablegen aus mietzins.py -- bis zu diesem
# Umzug lief das ueber _rest.py, jetzt direkt.

import logging
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
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
    from crm.models import Organisation, Mieter
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = aktuelle_organisation()
    verwaltung = {
        'firma': vw.firma if vw else '', 'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

    # Bearbeiten-Modus: der Assistent editiert einen bestehenden ENTWURF (voll).
    edit_id = request.GET.get('edit')
    edit_vertrag = (Mietvertrag.objects
                    .filter(id=edit_id, status='entwurf')
                    .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first()
                    if edit_id else None)

    # Vorwahl einer bestimmten Einheit (z.B. aus dem Mieterwechsel-Cockpit):
    # dann nur diese Liegenschaft + dieses Objekt anzeigen, keine Auswahl nötig.
    try:
        vorwahl_einheit = int(request.GET.get('einheit') or 0) or None
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
            'basis_referenzzinssatz': float(ev.basis_referenzzinssatz) if ev.basis_referenzzinssatz is not None else None,
            'basis_lik_punkte': float(ev.basis_lik_punkte) if ev.basis_lik_punkte is not None else None,
            'kautions_betrag': float(ev.kautions_betrag) if ev.kautions_betrag else '',
            'kautions_konto': ev.kautions_konto or '',
        }

    from core.services.docuseal_service import docuseal_konfiguriert
    return render(request, 'fw/vertrag_neu.html', {
        **basis, 'nav': 'vertraege',
        'liegenschaften': liegenschaften, 'mieter': mieter,
        'verwaltung': verwaltung,
        'aktueller_ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.25,
        **_lik_assistent_defaults(vw),
        'heute_iso': timezone.localdate().isoformat(),
        'vorwahl_einheit': vorwahl_einheit or '',
        'edit_vertrag': edit_vertrag, 'edit_json': edit_json,
        'docuseal_konfiguriert': docuseal_konfiguriert(),
    })


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
    einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).first()
    if not einheit:
        messages.error(request, "Bitte wähle ein Objekt aus, bevor du den Vertrag erstellst.")
        return redirect('/neu/vertraege/neu/')

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
    _fehler = []
    if _dec_val('netto_mietzins') < 0:
        _fehler.append("Der Netto-Mietzins darf nicht negativ sein.")
    if not einheit.ist_einstellplatz and _dec_val('nebenkosten') < 0:
        _fehler.append("Die Nebenkosten dürfen nicht negativ sein.")
    # Nur prüfen, wenn der Vertrag WIRKLICH befristet gespeichert wird — sonst wird
    # `ende` beim Speichern ohnehin verworfen (siehe _ist_befristet weiter unten),
    # und ein stehengebliebener Alt-Wert im Feld dürfte die Anlage nicht blockieren.
    if P.get('ist_befristet') == '1' and _v_ende and _v_ende < _v_beginn:
        _fehler.append("Das Vertragsende darf nicht vor dem Vertragsbeginn liegen.")
    if not (P.get('mieter_id') or '').strip():
        _typ_neu = P.get('mieter_typ', 'person')
        if _typ_neu in ('firma', 'verein') and not P.get('firmen_name', '').strip():
            _fehler.append("Bitte den Firmen-/Vereinsnamen erfassen.")
        elif _typ_neu == 'person' and not P.get('nachname', '').strip():
            _fehler.append("Bitte den Nachnamen des Mieters erfassen.")
    if _fehler:
        for _f in _fehler:
            messages.error(request, _f)
        return redirect('/neu/vertraege/neu/')

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

    # LIK-Stand-Monat (aus dem die Basis-Punkte stammen): Formular-Override,
    # sonst automatisch der neueste veröffentlichte Monat (BFS-Tabelle,
    # Basis Dez. 2020), Fallback Account-Einstellung.
    from crm.models import Organisation as _Vw
    from core.services.lik import aktueller_lik_wert
    _vw = einheit.liegenschaft.organisation or _Vw.objects.first()
    _auto_stand, _auto_pkt, _ = aktueller_lik_wert()
    basis_lik_stand = _auto_stand or (_vw.aktueller_lik_stand if _vw else None)
    _stand_raw = (P.get('basis_lik_stand') or '').strip()  # 'YYYY-MM' aus <input type=month>
    if _stand_raw:
        try:
            _jahr, _monat = _stand_raw.split('-')[:2]
            basis_lik_stand = date(int(_jahr), int(_monat), 1)
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # Kündigungsfrist: bei Geschäftsräumen gesetzlich min. 6 Monate (Art. 266d);
    # wird der Wert nicht gesetzt, greift der art-abhängige Default.
    _kfrist_default = 6 if einheit.mietrecht_kategorie == 'gewerbe' else 3
    try:
        _kfrist = int(P.get('kuendigungsfrist') or _kfrist_default)
    except ValueError:
        _kfrist = _kfrist_default
    _mietzins_modell = P.get('mietzins_modell', 'fest')
    if _mietzins_modell not in ('fest', 'index', 'staffel'):
        _mietzins_modell = 'fest'

    # Einstellplätze (Parkplatz/Garage, Art. 266e) haben keine separaten
    # Nebenkosten — serverseitig hart auf 0 setzen, egal was übermittelt wurde.
    _nk = Decimal('0.00') if einheit.ist_einstellplatz else dec('nebenkosten')

    # Bearbeiten-Modus: bestehenden ENTWURF aktualisieren statt neu anlegen.
    edit_id = P.get('edit_id')
    editing = (Mietvertrag.objects.filter(id=edit_id, status='entwurf').first()
               if edit_id else None)

    # Befristet = explizit angehakt (Checkbox «unbefristet» aus) UND ein Enddatum
    # gesetzt. So bleibt `ende` bei einem unbefristeten Vertrag leer, und ein
    # später via Kündigung gesetztes `ende` macht den Vertrag nicht «befristet».
    _ende = datum('ende')
    _ist_befristet = (P.get('ist_befristet') == '1') and bool(_ende)

    felder = dict(
        mieter=mieter, einheit=einheit,
        status='aktiv' if P.get('aktiv_setzen') == 'on' else 'entwurf',
        # `ende` NUR bei einem befristeten Vertrag speichern — sonst wird ein im
        # Formular stehengebliebener Alt-Wert fälschlich als Enddatum eines
        # unbefristeten Vertrags abgelegt (der Kommentar unten versprach das schon,
        # der Code setzte es aber unbedingt; Review-Befund).
        beginn=beginn, ende=(_ende if _ist_befristet else None), ist_befristet=_ist_befristet,
        erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
        kuendigungsfrist_monate=_kfrist,
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
        basis_referenzzinssatz=dec('basis_referenzzinssatz') or Decimal('1.25'),
        basis_lik_punkte=dec('basis_lik_punkte') or Decimal('107.1'),
        basis_lik_stand=basis_lik_stand,
        kostensteigerung_datum=datum('kostensteigerung_datum'),
        kautions_betrag=dec('kautions_betrag') or None,
        kautions_konto=P.get('kautions_konto', '').strip(),
        solidarhaftung=P.get('solidarhaftung', 'on') != 'off',
    )

    # Weitere WG-Mieter (bestehende Personen, mehrfach) — als M2M nach dem Save.
    _wg_ids = [i for i in P.getlist('weitere_mieter') if str(i).strip().isdigit()]

    # Bringt das Formular überhaupt Staffeldaten mit? Das Bearbeiten-Formular
    # eines Entwurfs befüllt die Staffelsektion NICHT — würde man die
    # bestehenden Stufen trotzdem löschen und aus dem leeren Formular neu
    # aufbauen, wären sie weg (stiller Verlust, das Modell stünde weiter auf
    # «Staffel» ohne eine einzige Stufe → Miete stiege nie). Nur löschen, wenn
    # echte Ersatzdaten kommen oder das Modell von «Staffel» weggewechselt wird.
    _hat_staffel_input = any((ab or '').strip() for ab in P.getlist('staffel_ab'))

    with transaction.atomic():
        if editing:
            for _k, _v in felder.items():
                setattr(editing, _k, _v)
            editing.save()
            vertrag = editing
            if _hat_staffel_input or _mietzins_modell != 'staffel':
                vertrag.staffelstufen.all().delete()   # neu aus dem Formular aufbauen
        else:
            vertrag = Mietvertrag.objects.create(**felder)
        # Staffelstufen (parallele Listen ab_datum/netto) — nur bei Staffelmiete
        if _mietzins_modell == 'staffel':
            from rentals.models import Staffelstufe
            ab_list = P.getlist('staffel_ab')
            netto_list = P.getlist('staffel_netto')
            for i, ab in enumerate(ab_list):
                try:
                    ab_d = date.fromisoformat((ab or '').strip())
                except ValueError:
                    continue
                betrag = dec(f'__staffel_{i}') if False else None
                try:
                    betrag = Decimal(_num(netto_list[i])) if i < len(netto_list) and str(netto_list[i]).strip() else None
                except Exception:
                    betrag = None
                if ab_d and betrag and betrag > 0:
                    Staffelstufe.objects.create(vertrag=vertrag, ab_datum=ab_d, netto_mietzins=betrag)
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
        # Amtliches Anfangsmietzins-Formular (Art. 270 Abs. 2 OR) automatisch
        # mitgenerieren, sofern Formularpflicht besteht — steht so zur
        # Schlüsselübergabe bereit (30-Tage-Anfechtungsfrist ab Erhalt).
        try:
            erzeugt, _grund = anfangsmietzins_auto_ablegen(vertrag, verwaltung=_vw)
            if erzeugt:
                messages.info(request, "📄 Amtliches Anfangsmietzins-Formular wurde automatisch erstellt "
                                       "(Formularpflicht) — bei Schlüsselübergabe aushändigen.")
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # Nettomietzins 0 ist fast immer ein vergessenes Feld — warnen (nicht blockieren),
    # da ohne Mietzins die Sollstellung 0 verrechnet.
    if (vertrag.netto_mietzins or Decimal('0')) <= 0:
        messages.warning(request, "⚠️ Nettomietzins ist CHF 0 — bitte prüfen. Ohne Mietzins "
                                  "erzeugt der Mietenlauf keine Forderung.")

    # Mietrechtliche Plausibilitätsprüfung (Index ≥ 5 J / Staffel ≥ 3 J,
    # max. 1 Staffelerhöhung/Jahr) — als Warnung, nicht blockierend.
    try:
        from core.services.mietrecht import pruefe_mietzinsmodell, staffel_pruefung
        _warn = pruefe_mietzinsmodell(_mietzins_modell, vertrag.beginn, vertrag.ende)
        if _mietzins_modell == 'staffel':
            _warn += staffel_pruefung(list(vertrag.staffelstufen.all()))
        for _w in _warn:
            messages.warning(request, "⚠️ " + _w)
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)

    log_aktion(request, "Mietvertrag bearbeitet (Assistent)" if editing else "Mietvertrag erstellt (Assistent)",
               str(mieter), f"{einheit.bezeichnung}, ab {beginn}", ziel=vertrag)
    _verb = "aktualisiert" if editing else "erstellt"
    if anzahl_dok:
        messages.success(
            request,
            f"✅ Mietvertrag für {mieter.display_name} {_verb} & aktiv gesetzt — "
            f"{anzahl_dok} Dokumente automatisch abgelegt (im Portal sichtbar).")
    elif editing:
        messages.success(request, f"✅ Vertrag (Entwurf) für {mieter.display_name} aktualisiert.")
    else:
        messages.success(request, f"✅ Mietvertrag (Entwurf) für {mieter.display_name} erstellt — "
                         "PDFs werden erst beim Aktivieren erzeugt.")

    # Optionaler Abschluss: direkt zur digitalen Unterschrift senden (DocuSeal).
    if P.get('abschluss') == 'senden':
        from core.services.docuseal_service import docuseal_senden
        ok, msg = docuseal_senden(vertrag)
        if ok:
            log_aktion(request, "Vertrag zur Unterschrift gesendet", str(mieter), msg, ziel=vertrag)
            messages.success(request, f"✍️ {msg}")
        else:
            messages.warning(request, f"Vertrag erstellt, aber Signaturversand nicht möglich: {msg}")
    return redirect(f'/neu/vertraege/{vertrag.id}/')


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
    _modell = P.get('mietzins_modell', 'fest')
    if _modell not in ('fest', 'index', 'staffel'):
        _modell = 'fest'
    # Transienter (nicht gespeicherter) Vertrag — nur zum Rendern.
    vertrag = Mietvertrag(
        mieter=mieter, einheit=einheit,
        beginn=datum('beginn') or timezone.localdate(), ende=datum('ende'),
        erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
        kuendigungsfrist_monate=int(P.get('kuendigungsfrist') or 3),
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
        basis_referenzzinssatz=dec('basis_referenzzinssatz') or Decimal('1.25'),
        basis_lik_punkte=dec('basis_lik_punkte') or Decimal('107.1'),
        kautions_betrag=dec('kautions_betrag') or None,
        kautions_konto=P.get('kautions_konto', '').strip())
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

        def dec(key, default=None):
            raw = _num(P.get(key))
            try:
                return Decimal(raw) if raw else (Decimal(default) if default is not None else None)
            except Exception:
                return Decimal(default) if default is not None else None

        def datum(key):
            try:
                return date.fromisoformat(P.get(key)) if P.get(key) else None
            except ValueError:
                return None

        # --- Immer editierbar (unkritisch) ---
        v.ende = datum('ende')
        # Befristung folgt bei einem AKTIVEN Vertrag dem Enddatum (leer = unbefristet).
        # Bei gekündigten/archivierten Verträgen stammt `ende` aus der Kündigung —
        # die Befristungs-Kennung nicht anrühren.
        if v.status == 'aktiv':
            v.ist_befristet = bool(v.ende)
        v.erstmals_kuendbar_auf = datum('erstmals_kuendbar')
        try:
            v.kuendigungsfrist_monate = int(P.get('kuendigungsfrist') or v.kuendigungsfrist_monate)
        except ValueError:
            pass
        v.kuendigungstermine = P.get('kuendigungstermine', '').strip() or v.kuendigungstermine
        v.familienwohnung = P.get('familienwohnung') == 'on'
        v.mitmieter_name = P.get('mitmieter_name', '').strip()
        try:
            v.anzahl_personen = int(P.get('anzahl_personen') or v.anzahl_personen or 1)
        except ValueError:
            pass
        v.mitbenutzung = P.get('mitbenutzung', '').strip()
        v.nebenraeume = P.get('nebenraeume', '').strip()
        v.zweckbestimmung = P.get('zweckbestimmung', '').strip()
        v.besondere_vereinbarungen = P.get('besondere_vereinbarungen', '').strip()
        v.weitere_vorbehalte = P.get('weitere_vorbehalte', '').strip()

        # --- Nur bei Entwurf editierbar (kritisch) ---
        if not gesperrt:
            beginn = datum('beginn')
            if beginn:
                v.beginn = beginn
            neue_einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).first()
            if neue_einheit:
                v.einheit = neue_einheit
            neuer_mieter = Mieter.objects.filter(id=P.get('mieter_id') or 0).first()
            if neuer_mieter:
                v.mieter = neuer_mieter
            v.netto_mietzins = dec('netto_mietzins', '0')
            v.nebenkosten = Decimal('0.00') if v.einheit.ist_einstellplatz else dec('nebenkosten', '0')
            v.nk_abrechnungsart = P.get('nk_abrechnungsart', v.nk_abrechnungsart)
            v.verteilschluessel = P.get('verteilschluessel', v.verteilschluessel)
            v.zahlungsrhythmus = P.get('zahlungsrhythmus', v.zahlungsrhythmus)
            v.mwst_pflichtig = P.get('mwst_pflichtig') == 'on'
            _ms = dec('mwst_satz')
            if _ms is not None:
                v.mwst_satz = _ms
            v.kautions_betrag = dec('kautions_betrag') or None
            v.kautions_konto = P.get('kautions_konto', '').strip()
        v.save()
        _diff = diff_model(alt, snapshot_model(v), v)
        log_aktion(request, "Vertrag bearbeitet", str(v.mieter),
                   f"{v.einheit.bezeichnung} · {'Entwurf' if not gesperrt else 'nur Detailfelder'}"
                   + (f" · {_diff}" if _diff else ''), ziel=v)
        messages.success(request, "✅ Vertrag aktualisiert."
                         + ("" if not gesperrt else " (aktiver Vertrag — nur Detailfelder geändert)"))
        return redirect(f'/neu/vertraege/{v.id}/')

    verwaltung = v.einheit.liegenschaft.organisation
    return render(request, 'fw/vertrag_bearbeiten.html', {
        **_global_filter(request), 'nav': 'vertraege', 'v': v, 'gesperrt': gesperrt,
        'objekte': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
        'mieter_liste': Mieter.objects.order_by('nachname', 'firmen_name'),
        'nk_arten': Mietvertrag.NK_TYP_CHOICES,
        'verteil_choices': Mietvertrag.VERTEIL_CHOICES,
        'rhythmus_choices': Mietvertrag.ZAHLUNGSRHYTHMUS_CHOICES,
    })


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
