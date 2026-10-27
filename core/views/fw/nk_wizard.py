# core/views/fw/nk_wizard.py
#
# Nebenkosten-Wizard (Modul 1, 27.10.2026): sechs Schritte unter /neu/nebenkosten/<pk>/.
#
#   1 periode/     Periode & Objekte (Masse und Personen direkt in der Kachel)
#   2 kosten/      HNK-Kreditoren, manuelle Belege, Heizöl-Bestand
#   3 verteilung/  Schlüssel je Kostenart, ausgeschlossene Kosten (E2), Leerstand/Personen (E3)
#   4 heizung/     Grundkostenanteil (E4), Zählerstände, CSV-Import (import/, E5)
#   5 pruefen/     Kennzahlen und eine Karte je Mieter
#   6 abschluss/   Verbuchen, PDF, E-Mail, Zustellung (bestehende Aktionen)
#
# Gerechnet wird nur in `core.utils.billing` (hole_abrechnung). Jede Seite zeigt zuerst, was
# fehlt — Warnungen der Engine und der Stand aus `core.services.nk_prozess` —, dann die Aufgabe.
#
# Rechte: Ansehen alle Team-Rollen; Schreiben nur SCHREIB_ROLLEN (innere Schranke, siehe
# `core/tests/test_sicherheit.py`). Eine verbuchte Periode ist gesperrt: Die Schritte leiten
# auf die Leseansicht, Schreibversuche werden abgewiesen.

from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich

from ._basis import _global_filter

__all__ = ['fw_nebenkosten_periode', 'fw_nebenkosten_kosten', 'fw_nebenkosten_verteilung',
           'fw_nebenkosten_heizung', 'fw_nebenkosten_import', 'fw_nebenkosten_pruefen',
           'fw_nebenkosten_abschluss']


def _periode(pk):
    from finance.models import AbrechnungsPeriode
    return get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), pk=pk)


def _url(p, teil=''):
    return f'/neu/nebenkosten/{p.id}/' + (f'{teil}/' if teil else '')


def _gesperrt(request, p):
    """Verbuchte Periode: Schreiben abgewiesen. Gibt die Weiterleitung zurück oder None."""
    if p.abgeschlossen:
        messages.error(request, gettext('Die Periode ist verbucht — ändern lässt sich nichts mehr.'))
        return redirect(_url(p))
    return None


def _akonto_vorschlaege(p, result):
    """Akonto-Anpassungs-Vorschlag je Mieter (Rechnung in `akonto_empfehlung`).

    E1: Der Vorschlag überschreibt nichts mehr. Er verweist auf den Ablauf «Mietzinsanpassung»
    (Formular und Termin nach Art. 269d OR), vorbelegt mit dem neuen Akonto.
    """
    from rentals.models import Mietvertrag
    from .nebenkosten import akonto_empfehlung
    zeilen = [a for a in result.get('abrechnungen', []) if a.get('vertrag_id') and a.get('typ') == 'mieter_akonto']
    # Nur Verträge, die über das Periodenende hinaus laufen: Wer ausgezogen ist, bekommt kein
    # neues Akonto. Bezugsgrösse ist die Mietdauer IN der Periode, nicht die ganze Periode —
    # sonst teilte ein Mieter mit vier Monaten seine Kosten durch zwölf.
    laufend = set(Mietvertrag.objects.filter(id__in=[a['vertrag_id'] for a in zeilen])
                  .filter(Q(ende__isnull=True) | Q(ende__gt=p.ende_datum)).values_list('id', flat=True))
    vorschlaege = {}
    for a in zeilen:
        vid = a['vertrag_id']
        if vid not in laufend:
            continue
        tage = a.get('tage') or ((p.ende_datum - p.start_datum).days + 1)
        monate = max(Decimal('1'), Decimal(tage) / Decimal('30.44'))
        kosten_monat = Decimal(str(a.get('kosten_anteil', 0))) / monate
        akonto_monat = Decimal(str(a.get('akonto', 0))) / monate
        empfohlen, diff, _schwelle, empfehlen = akonto_empfehlung(kosten_monat, akonto_monat)
        if empfehlen:
            vorschlaege[vid] = {
                'aktuell': akonto_monat.quantize(Decimal('1')), 'empfohlen': empfohlen,
                'richtung': 'erhoehen' if diff > 0 else 'senken', 'diff': abs(diff).quantize(Decimal('1')),
                'url': f'/neu/mietzins/{vid}/anpassung/?nk={empfohlen}&nk_periode={p.id}',
            }
    return vorschlaege


def _kontext(request, p, nr, result=None):
    """Was jede Seite des Wizards braucht: Engine-Ergebnis, Stepper, Warnungen dieses Schritts."""
    from core.services import nk_wizard as nkw
    from core.services.nk_prozess import schritte, warnungen_fuer, wizard_schritte
    from core.utils.billing import hole_abrechnung
    lg = p.liegenschaft
    if result is None:
        result = hole_abrechnung(p)
    vorschlaege = _akonto_vorschlaege(p, result) if not result.get('error') else {}
    prozess = schritte(p, total_kosten=Decimal(str(result.get('total_kosten', 0) or 0)),
                       warnungen=result.get('warnungen', []), akonto_vorschlaege=list(vorschlaege),
                       hkvo_aktiv=getattr(lg, 'hkvo_aktiv', False),
                       hkvo_angewendet=result.get('hkvo_angewendet', False))
    kacheln = nkw.einheiten_kacheln(p, result)
    zu_lang = nkw.periode_zu_lang(p)
    je_schritt = {i: warnungen_fuer(result, i) for i in range(1, 7)}
    leiste = wizard_schritte(
        p, prozess, objekt_luecken=nkw.objekt_luecken(kacheln), periode_zu_lang=zu_lang,
        warnungen_je_schritt=je_schritt, hinweise=result.get('hinweise', []),
        differenz=Decimal(str(result.get('differenz', 0) or 0)),
        anzahl_kosten=len(result.get('belege_details', [])),
        total_kosten=Decimal(str(result.get('total_kosten', 0) or 0)))
    schritt = leiste[nr - 1]
    fehlt = []
    if nr == 1:
        if zu_lang:
            fehlt.append(gettext('Die Periode ist länger als %(n)s Monate.') % {'n': nkw.MAX_MONATE})
        for k in nkw.objekt_luecken(kacheln):
            fehlt.append(gettext('%(e)s: %(was)s fehlt') % {'e': k['e'].bezeichnung, 'was': ', '.join(k['fehlt'])})
    elif nr == 2 and not Decimal(str(result.get('total_kosten', 0) or 0)) > 0:
        fehlt.append(gettext('Noch keine Kosten. Kreditoren mit «In Nebenkostenabrechnung einbeziehen» '
                             'erscheinen automatisch; weitere Kosten erfassen Sie als Beleg.'))
    elif nr == 4:
        fehlt += list(result.get('hinweise') or [])
    elif nr == 5 and Decimal(str(result.get('differenz', 0) or 0)):
        fehlt.append(gettext('Verteilt ist nicht genau das Total: Differenz CHF %(d)s.') % {'d': result.get('differenz')})
    basis = _global_filter(request)
    return {
        **basis, 'nav': 'nebenkosten', 'p': p, 'lg': lg, 'result': result,
        'leiste': leiste, 'schritt': schritt, 'nr': nr,
        'assistent': _assistent(leiste, nr, basis.get('lg_query', ''), abgeschlossen=p.abgeschlossen),
        'warnungen': je_schritt.get(nr, []), 'fehlt': fehlt, 'kacheln': kacheln, 'periode_zu_lang': zu_lang,
        'akonto_vorschlaege': vorschlaege,
        'kann_schreiben': hat_rolle(request.user, SCHREIB_ROLLEN),
    }


#: Zustand aus `nk_prozess` (Prozessleiste, auch auf anderen Seiten) → Zustand des Assistenten.
_ZUSTAND = {'erledigt': 'fertig'}


def _assistent(leiste, nr, lg_query='', *, abgeschlossen=False):
    """Leiste, Kopf und Fuss im Assistenten-Standard (fw/_assistent_server.html).
    «Abbrechen» führt zur Nebenkosten-Liste; nach dem Verbuchen heisst der Knopf «Schliessen»."""
    from core.services.assistent import server_assistent
    schritte = [{**s, 'zustand': _ZUSTAND.get(s['zustand'], s['zustand'])} for s in leiste]
    return server_assistent(schritte, nr, abbrechen_url='/neu/nebenkosten/' + (lg_query or ''),
                            abbrechen_text=gettext('Schliessen') if abgeschlossen else None)


def einstieg_assistent(lg_query=''):
    """Die Leiste der Seite «Neue Periode» (/neu/nebenkosten/neu/): dieselben sechs Schritte,
    Schritt 1 aktuell, die übrigen gesperrt — es gibt noch keine Periode, zu der sie führten."""
    from core.services.assistent import server_assistent
    from core.services.nk_prozess import WIZARD
    schritte = [{'nr': nr, 'titel': titel, 'zustand': 'offen' if nr == 1 else 'gesperrt',
                 'url': '/neu/nebenkosten/neu/' + (lg_query or '') if nr == 1 else ''}
                for nr, _teil, titel in WIZARD]
    return server_assistent(schritte, 1, abbrechen_url='/neu/nebenkosten/' + (lg_query or ''))


def _zeigen(request, p, nr, vorlage, status=200, **extra):
    ctx = _kontext(request, p, nr)
    ctx.update(extra)
    return render(request, f'fw/nk/{vorlage}.html', ctx, status=status)


def wizard_aktueller_schritt(request, p):
    """Für /neu/nebenkosten/<pk>/ einer offenen Periode: der erste Schritt, der nicht erledigt ist."""
    ctx = _kontext(request, p, 1)
    hier = next((s for s in ctx['leiste'] if s['hier']), ctx['leiste'][-1])
    return SCHRITT_VIEWS[hier['teil']](request, p.id)


# --------------------------------------------------------------------------- Schritt 1

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_periode(request, pk):
    """Schritt 1 — Periode (höchstens 12 Monate) und Objekte als Kacheln."""
    from core.services import nk_wizard as nkw
    from portfolio.models import Einheit
    p = _periode(pk)
    if request.method != 'POST':
        if p.abgeschlossen:
            return redirect(_url(p))
        return _zeigen(request, p, 1, 'schritt_periode')
    if not hat_rolle(request.user, SCHREIB_ROLLEN):
        raise PermissionDenied
    if (weg := _gesperrt(request, p)) is not None:
        return weg
    aktion = request.POST.get('aktion')

    if aktion == 'periode':
        start, ende, fehler = nkw.periode_pruefen(request.POST.get('start_datum'), request.POST.get('ende_datum'))
        bez = (request.POST.get('bezeichnung') or '').strip()[:100]
        if not bez:
            fehler['bezeichnung'] = gettext('Bitte eine Bezeichnung angeben.')
        if fehler:
            return _zeigen(request, p, 1, 'schritt_periode', status=400, periode_fehler=fehler,
                           periode_eingabe=request.POST.dict())
        p.start_datum, p.ende_datum, p.bezeichnung = start, ende, bez
        p.save(update_fields=['start_datum', 'ende_datum', 'bezeichnung'])
        log_aktion(request, 'Abrechnungsperiode geändert', bez, f'{start:%d.%m.%Y}–{ende:%d.%m.%Y}')
        messages.success(request, gettext('Periode gespeichert.'))
        return redirect(_url(p, 'periode'))

    if aktion == 'einheit':
        e = get_object_or_404(Einheit.objects.filter(liegenschaft=p.liegenschaft), pk=request.POST.get('einheit_id') or 0)
        vertraege = nkw.vertraege_der_periode(e, p)
        fehler = nkw.einheit_speichern(e, vertraege, request.POST)
        if fehler:
            return _zeigen(request, p, 1, 'schritt_periode', status=400, kachel_fehler={e.id: fehler},
                           kachel_eingabe={e.id: request.POST.dict()})
        log_aktion(request, 'NK-Wizard: Objektdaten ergänzt', str(e), p.bezeichnung)
        messages.success(request, gettext('%(e)s gespeichert.') % {'e': e.bezeichnung})
        return redirect(_url(p, 'periode') + f'#einheit-{e.id}')

    messages.error(request, gettext('Unbekannte Aktion.'))
    return redirect(_url(p, 'periode'))


# --------------------------------------------------------------------------- Schritt 2

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_kosten(request, pk):
    """Schritt 2 — HNK-Kreditoren mit Positionen, manuelle Belege, Heizöl-Bestand."""
    from core.services import nk_wizard as nkw
    from finance.models import NebenkostenBeleg
    p = _periode(pk)
    extra = {}
    if request.method == 'POST':
        if not hat_rolle(request.user, SCHREIB_ROLLEN):
            raise PermissionDenied
        if (weg := _gesperrt(request, p)) is not None:
            return weg
        aktion = request.POST.get('aktion')
        if aktion == 'beleg':
            werte, fehler = nkw.beleg_pruefen(request.POST, p)
            if not fehler:
                b = NebenkostenBeleg.objects.create(periode=p, **werte)
                log_aktion(request, 'NK-Beleg erfasst', p.bezeichnung, f'{b.text}: CHF {b.betrag}')
                messages.success(request, gettext('Beleg erfasst.'))
                return redirect(_url(p, 'kosten'))
            extra = {'beleg_fehler': fehler, 'beleg_eingabe': request.POST.dict()}
        elif aktion == 'beleg_loeschen':
            b = get_object_or_404(NebenkostenBeleg.objects.filter(periode=p), pk=request.POST.get('beleg_id') or 0)
            text = f'{b.text}: CHF {b.betrag}'
            b.delete()
            log_aktion(request, 'NK-Beleg gelöscht', p.bezeichnung, text)
            messages.success(request, gettext('Beleg gelöscht.'))
            return redirect(_url(p, 'kosten'))
        elif aktion == 'oel':
            werte, fehler = nkw.oel_pruefen(request.POST)
            if not fehler:
                for feld, wert in werte.items():
                    setattr(p, feld, wert)
                p.save(update_fields=list(werte))
                log_aktion(request, 'NK: Heizöl-Bestand erfasst', p.bezeichnung,
                           f"Anfang {werte['anfangsbestand_liter']} L, Ende {werte['endbestand_liter']} L")
                messages.success(request, gettext('Heizöl-Bestand gespeichert.'))
                return redirect(_url(p, 'kosten'))
            extra = {'oel_fehler': fehler, 'oel_eingabe': request.POST.dict()}
        else:
            messages.error(request, gettext('Unbekannte Aktion.'))
            return redirect(_url(p, 'kosten'))
    elif p.abgeschlossen:
        return redirect(_url(p))
    ctx = _kontext(request, p, 2)
    nicht_einbezogen = nkw.nicht_einbezogene_kreditoren(p)
    if nicht_einbezogen:
        ctx['fehlt'].append(gettext('%(n)s HNK-Rechnung(en) im Status «neu», «in Zahlung» oder «teilbezahlt» — '
                                    'die Abrechnung liest nur freigegebene und bezahlte Rechnungen.')
                            % {'n': len(nicht_einbezogen)})
    ctx.update(extra)
    ctx.update(dict(kreditoren=nkw.kreditoren_liste(p), nicht_einbezogen=nicht_einbezogen,
                    belege=p.belege.order_by('-datum', '-id'),
                    kategorien=NebenkostenBeleg.NK_KATEGORIE_CHOICES, schluessel=NebenkostenBeleg.VERTEIL_CHOICES))
    return render(request, 'fw/nk/schritt_kosten.html', ctx, status=400 if extra else 200)


# --------------------------------------------------------------------------- Schritt 3

def _kostenart_kacheln(p, result, raster=None):
    """Je Kostenart der Periode: Betrag, Verteilung, Ausschlüsse und (bei «Eigene %») das Raster."""
    from core.services import nk_wizard as nkw
    from portfolio.models import Verteilschluessel
    namen = dict(Verteilschluessel.KOSTENART_CHOICES)
    vertraege = nkw.vertraege_liegenschaft(p)
    einheiten = list(p.liegenschaft.einheiten.order_by('bezeichnung'))
    kacheln = []
    for k in result.get('kostenarten', []):
        ka = k['kostenart']
        s = nkw.schluessel_der_periode(p.liegenschaft, ka, p.ende_datum) if ka != 'heizung' else None
        aktiv = (k.get('tabelle') or (s.typ if s and p.liegenschaft.verteilschluessel_aktiv else None))
        kachel = {'ka': ka, 'name': namen.get(ka, ka), 'betrag': k['betrag'], 'arten': k.get('arten', []),
                  'tabelle': aktiv, 'schluessel': s,
                  'ausschluesse': [v for v in vertraege if ka in (v.ausgeschlossene_kostenarten or [])],
                  'vertraege': vertraege}
        if aktiv == 'prozent' and s is not None:
            vorhanden = {z.einheit_id: z.wert for z in Verteilschluessel.objects.filter(
                einheit__liegenschaft=p.liegenschaft, kostenart=ka, typ='prozent', gueltig_ab=s.gueltig_ab)}
            eigene = (raster or {}).get(ka)
            kachel['raster'] = [{'e': e, 'wert': (eigene['werte'].get(e.id, '') if eigene
                                                  else _ohne_nullen(vorhanden.get(e.id))),
                                 'fehler': (eigene or {}).get('fehler', {}).get(e.id)} for e in einheiten]
            kachel['summenfehler'] = (eigene or {}).get('summe')
        kacheln.append(kachel)
    return kacheln


def _ohne_nullen(wert):
    if wert is None:
        return ''
    from .verteilschluessel import _ohne_nullen as basis
    return basis(wert)


def _verteilung_zeigen(request, p, raster=None, status=200):
    from core.services import nk_wizard as nkw
    from finance.models import AbrechnungsPeriode
    ctx = _kontext(request, p, 3)
    ctx.update({'kostenarten': _kostenart_kacheln(p, ctx['result'], raster), 'segment': nkw.SEGMENT,
                'leerstand_wahl': AbrechnungsPeriode.LEERSTAND_PERSONEN_CHOICES})
    return render(request, 'fw/nk/schritt_verteilung.html', ctx, status=status)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_verteilung(request, pk):
    """Schritt 3 — je Kostenart der Schlüssel (Segment), Ausschlüsse je Vertrag (E2), Leerstand (E3)."""
    from core.services import nk_wizard as nkw
    from finance.models import AbrechnungsPeriode
    from portfolio.models import Liegenschaft, Verteilschluessel
    from rentals.models import Mietvertrag
    p = _periode(pk)
    lg = p.liegenschaft
    if request.method != 'POST':
        if p.abgeschlossen:
            return redirect(_url(p))
        return _verteilung_zeigen(request, p)
    if not hat_rolle(request.user, SCHREIB_ROLLEN):
        raise PermissionDenied
    if (weg := _gesperrt(request, p)) is not None:
        return weg
    aktion = request.POST.get('aktion')
    namen = dict(Verteilschluessel.KOSTENART_CHOICES)
    ziel = _url(p, 'verteilung')

    if aktion == 'schluessel':
        ka, typ = request.POST.get('kostenart', ''), request.POST.get('typ', '')
        if ka not in namen or ka == 'heizung' or typ not in nkw.SEGMENT_WERTE:
            messages.error(request, gettext('Kostenart oder Verteilung unbekannt.'))
            return redirect(ziel)
        s, geaendert = nkw.schluessel_setzen(lg, ka, typ, p)
        if not lg.verteilschluessel_aktiv:
            Liegenschaft.objects.filter(pk=lg.pk).update(verteilschluessel_aktiv=True)
            messages.info(request, gettext('Die Schlüssel je Kostenart sind für diese Liegenschaft jetzt eingeschaltet.'))
        if geaendert:
            log_aktion(request, 'Verteilschlüssel gesetzt', str(lg), f'{ka}: {typ} ab {s.gueltig_ab:%d.%m.%Y}')
        messages.success(request, gettext('Verteilung für %(ka)s gespeichert.') % {'ka': namen[ka]})
        return redirect(ziel + f'#ka-{ka}')

    if aktion == 'prozente':
        from .verteilschluessel import _raster_pruefen
        ka = request.POST.get('kostenart', '')
        s = nkw.schluessel_der_periode(lg, ka, p.ende_datum)
        if s is None or s.typ != 'prozent':
            messages.error(request, gettext('Für diese Kostenart ist «Eigene %» nicht gewählt.'))
            return redirect(ziel)
        einheiten = list(lg.einheiten.all())
        werte, fehler, summe = _raster_pruefen(request.POST, einheiten)
        if fehler or summe:
            raster = {ka: {'werte': {e.id: request.POST.get(f'pct_{e.id}', '') for e in einheiten},
                           'fehler': fehler, 'summe': summe}}
            return _verteilung_zeigen(request, p, raster=raster, status=400)
        nkw.prozente_speichern(lg, s, werte)
        log_aktion(request, 'Prozentverteilung gespeichert', str(lg), ka)
        messages.success(request, gettext('Prozentanteile gespeichert.'))
        return redirect(ziel + f'#ka-{ka}')

    if aktion == 'aktiv':
        an = request.POST.get('an') == '1'
        Liegenschaft.objects.filter(pk=lg.pk).update(verteilschluessel_aktiv=an)
        log_aktion(request, 'Verteilschlüssel der Liegenschaft ' + ('eingeschaltet' if an else 'ausgeschaltet'), str(lg), '')
        messages.success(request, gettext('Gespeichert.'))
        return redirect(ziel)

    if aktion == 'ausschluss':
        ka = request.POST.get('kostenart', '')
        v = get_object_or_404(Mietvertrag.objects.filter(einheit__liegenschaft=lg), pk=request.POST.get('vertrag_id') or 0)
        if ka not in namen:
            messages.error(request, gettext('Kostenart unbekannt.'))
            return redirect(ziel)
        liste = [x for x in (v.ausgeschlossene_kostenarten or []) if x in namen]
        if request.POST.get('an') == '1':
            if ka not in liste:
                liste.append(ka)
        else:
            liste = [x for x in liste if x != ka]
        v.ausgeschlossene_kostenarten = sorted(liste)
        v.save(update_fields=['ausgeschlossene_kostenarten'])
        log_aktion(request, 'Vertrag: ausgeschlossene Kostenarten', str(v), ', '.join(liste) or '—', ziel=v)
        messages.success(request, gettext('Vertrag %(v)s gespeichert.') % {'v': v.mieter.display_name})
        return redirect(ziel + f'#ka-{ka}')

    if aktion == 'leerstand_personen':
        wert = request.POST.get('leerstand_personen', '')
        if wert not in dict(AbrechnungsPeriode.LEERSTAND_PERSONEN_CHOICES):
            messages.error(request, gettext('Unbekannte Auswahl.'))
            return redirect(ziel)
        p.leerstand_personen = wert
        p.save(update_fields=['leerstand_personen'])
        log_aktion(request, 'NK: Leerstand bei Kosten nach Personen', p.bezeichnung, wert)
        messages.success(request, gettext('Gespeichert.'))
        return redirect(ziel + '#leerstand')

    messages.error(request, gettext('Unbekannte Aktion.'))
    return redirect(ziel)


# --------------------------------------------------------------------------- Schritt 4

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_heizung(request, pk):
    """Schritt 4 — Grundkostenanteil (frei 0–100 %, E4) und Zählerstände je Zähler."""
    from core.services import nk_wizard as nkw
    from portfolio.models import Liegenschaft, Zaehler
    p = _periode(pk)
    lg = p.liegenschaft
    if request.method != 'POST':
        if p.abgeschlossen:
            return redirect(_url(p))
        return _zeigen(request, p, 4, 'schritt_heizung', raster=nkw.staende_raster(p))
    if not hat_rolle(request.user, SCHREIB_ROLLEN):
        raise PermissionDenied
    if (weg := _gesperrt(request, p)) is not None:
        return weg
    aktion = request.POST.get('aktion')
    ziel = _url(p, 'heizung')

    if aktion == 'hkvo':
        try:
            prozent = int((request.POST.get('hkvo_grundkosten_prozent') or '').strip())
        except ValueError:
            prozent = -1
        if not 0 <= prozent <= 100:
            return _zeigen(request, p, 4, 'schritt_heizung', status=400, raster=nkw.staende_raster(p),
                           hkvo_fehler=gettext('Der Grundkostenanteil liegt zwischen 0 und 100 %.'))
        an = request.POST.get('hkvo_aktiv') == 'on'
        # E4: keine kantonale Bandbreite — frei von 0 bis 100 %, mit Hinweis in der Seite.
        Liegenschaft.objects.filter(pk=lg.pk).update(hkvo_aktiv=an, hkvo_grundkosten_prozent=prozent)
        log_aktion(request, 'HKVO-Einstellung', str(lg), f"{'aktiv' if an else 'aus'}, Grundkosten {prozent} %")
        messages.success(request, gettext('Heizkosten-Einstellung gespeichert.'))
        return redirect(ziel)

    if aktion == 'staende':
        z = get_object_or_404(Zaehler.objects.filter(einheit__liegenschaft=lg), pk=request.POST.get('zaehler_id') or 0)
        raster = nkw.staende_raster(p)
        eintrag = next((r for r in raster if r['z'].id == z.id), None)
        if eintrag is None:
            messages.error(request, gettext('Das ist kein Heizungs- oder Wärmezähler.'))
            return redirect(ziel)
        eingaben, fehler = nkw.staende_aus_post(request.POST, eintrag)
        meldung = '' if fehler else nkw.staende_speichern(z, eingaben)
        if fehler or meldung:
            return _zeigen(request, p, 4, 'schritt_heizung', status=400,
                           raster=nkw.staende_raster(p, eingabe={z.id: request.POST.dict()}),
                           stand_fehler={z.id: {'felder': fehler, 'meldung': meldung}})
        log_aktion(request, 'Zählerstände erfasst', f'{z.typ} {z.zaehler_nummer}', f'{len(eingaben)} Stände')
        messages.success(request, gettext('Zählerstände gespeichert.'))
        return redirect(ziel + f'#zaehler-{z.id}')

    messages.error(request, gettext('Unbekannte Aktion.'))
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_import(request, pk):
    """Schritt 4, CSV-Import der Zählerstände (E5): hochladen → Spalten zuordnen → Vorschau →
    übernehmen. Die Datei wird nicht gespeichert; ihr Inhalt reist bis zur Übernahme im
    Formular mit. Die letzte Zuordnung bleibt an der Liegenschaft."""
    from core.services import nk_wizard as nkw
    p = _periode(pk)
    lg = p.liegenschaft
    if request.method != 'POST':
        if p.abgeschlossen:
            return redirect(_url(p))
        return _zeigen(request, p, 4, 'schritt_import', felder=nkw.IMPORT_FELDER)
    if not hat_rolle(request.user, SCHREIB_ROLLEN):
        raise PermissionDenied
    if (weg := _gesperrt(request, p)) is not None:
        return weg
    aktion = request.POST.get('aktion', 'hochladen')
    if aktion == 'hochladen':
        datei = request.FILES.get('datei')
        if datei is None:
            return _zeigen(request, p, 4, 'schritt_import', status=400, felder=nkw.IMPORT_FELDER,
                           import_fehler=gettext('Bitte eine CSV-Datei wählen.'))
        roh = datei.read(nkw.IMPORT_MAX_BYTES + 1)
    else:
        roh = (request.POST.get('inhalt') or '').encode('utf-8')
    try:
        spalten, daten = nkw.csv_lesen(roh)
    except nkw.ImportFehler as exc:
        return _zeigen(request, p, 4, 'schritt_import', status=400, felder=nkw.IMPORT_FELDER, import_fehler=str(exc))
    inhalt = roh.decode('utf-8-sig') if aktion != 'hochladen' else _als_text(roh)

    if aktion == 'hochladen':
        zuordnung, fehler = nkw.zuordnung_vorschlag(spalten, lg.zaehler_import_zuordnung), {}
        zeilen = None
    else:
        zuordnung, fehler = nkw.zuordnung_aus_post(request.POST, spalten)
        zeilen = None if fehler else nkw.vorschau(lg, daten, zuordnung)
    if aktion == 'uebernehmen' and zeilen is not None:
        n = nkw.uebernehmen(lg, zeilen, zuordnung)
        abgelehnt = sum(1 for z in zeilen if z['fehler'])
        log_aktion(request, 'Zählerstände importiert', str(lg), f'{n} übernommen, {abgelehnt} abgelehnt')
        messages.success(request, gettext('%(n)s Zählerstände übernommen.') % {'n': n})
        if abgelehnt:
            messages.warning(request, gettext('%(n)s Zeilen mit Fehler wurden nicht übernommen.') % {'n': abgelehnt})
        return redirect(_url(p, 'heizung'))
    return _zeigen(request, p, 4, 'schritt_import', status=400 if fehler else 200, felder=nkw.IMPORT_FELDER,
                   spalten=spalten, zuordnung=zuordnung, zuordnung_fehler=fehler, inhalt=inhalt, zeilen=zeilen,
                   n_ok=sum(1 for z in zeilen or [] if not z['fehler'] and not z['doppelt']),
                   n_fehler=sum(1 for z in zeilen or [] if z['fehler']),
                   n_doppelt=sum(1 for z in zeilen or [] if z['doppelt']))


def _als_text(roh):
    for kodierung in ('utf-8-sig', 'cp1252'):
        try:
            return roh.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return ''


# --------------------------------------------------------------------------- Schritt 5 und 6

def _karten(result, vorschlaege=None):
    """Die Zeilen der Abrechnung als Karten: Mieter, Eigentümer, Leerstand — mit Namen der Kostenarten."""
    from portfolio.models import Verteilschluessel
    namen = dict(Verteilschluessel.KOSTENART_CHOICES)
    karten = []
    for a in result.get('abrechnungen', []):
        k = dict(a)
        k['positionen'] = [{'name': namen.get(t.get('kostenart'), t.get('kostenart')), 'betrag': Decimal(str(t.get('betrag', 0)))}
                           for t in a.get('aufschluesselung', [])]
        k['ausgeschlossen_namen'] = [namen.get(x, x) for x in a.get('ausgeschlossen', [])]
        for feld in ('kosten_anteil', 'akonto', 'saldo'):
            k[feld] = Decimal(str(a.get(feld, 0)))
        k['vorschlag'] = (vorschlaege or {}).get(a.get('vertrag_id'))
        karten.append(k)
    return karten


def kennzahlen(result):
    """Kosten total, verteilt in %, Differenz; Saldo der Mieter mit Nachzahlungen/Guthaben."""
    total = Decimal(str(result.get('total_kosten', 0) or 0))
    verteilt = Decimal(str(result.get('kontroll_summe', 0) or 0))
    mieter = [a for a in result.get('abrechnungen', []) if a.get('vertrag_id')]
    saldo = sum((Decimal(str(a.get('saldo', 0))) for a in mieter), Decimal('0.00'))
    return {
        'total': total, 'verteilt_pct': (verteilt / total * 100).quantize(Decimal('0.1')) if total else Decimal('0'),
        'differenz': Decimal(str(result.get('differenz', 0) or 0)), 'saldo': saldo,
        'n_nach': sum(1 for a in mieter if Decimal(str(a.get('saldo', 0))) > 0),
        'n_gut': sum(1 for a in mieter if Decimal(str(a.get('saldo', 0))) < 0),
        'eigentuemer': sum((Decimal(str(a.get('kosten_anteil', 0))) for a in result.get('abrechnungen', [])
                            if a.get('typ') in ('leerstand', 'eigentuemer')), Decimal('0.00')),
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_pruefen(request, pk):
    """Schritt 5 — Kennzahlen und eine Karte je Mieter; Leerstand und Eigentümer eigene Karten."""
    p = _periode(pk)
    if p.abgeschlossen:
        return redirect(_url(p))
    ctx = _kontext(request, p, 5)
    ctx.update({'karten': _karten(ctx['result'], ctx['akonto_vorschlaege']), 'kz': kennzahlen(ctx['result'])})
    return render(request, 'fw/nk/schritt_pruefen.html', ctx)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_abschluss(request, pk):
    """Schritt 6 — Verbuchen, PDF, E-Mail, Zustellung: die bestehenden Aktionen an einem Ort."""
    p = _periode(pk)
    ctx = _kontext(request, p, 6)
    ctx.update({'kz': kennzahlen(ctx['result']),
                'pauschal': [a for a in ctx['result'].get('abrechnungen', []) if a.get('typ') == 'mieter_pauschal']})
    return render(request, 'fw/nk/schritt_abschluss.html', ctx)


SCHRITT_VIEWS = {
    'periode': fw_nebenkosten_periode, 'kosten': fw_nebenkosten_kosten,
    'verteilung': fw_nebenkosten_verteilung, 'heizung': fw_nebenkosten_heizung,
    'pruefen': fw_nebenkosten_pruefen, 'abschluss': fw_nebenkosten_abschluss,
}
