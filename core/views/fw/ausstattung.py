# core/views/fw/ausstattung.py
#
# Ausstattung und Raumbuch von Objekt und Liegenschaft, samt Lebensdauertabelle.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       TEAM_ROLLEN)
from portfolio.models import Einheit

from ._basis import (_global_filter, _num)


def _raumbuch_zeilen(ausst, zustandsverlauf=None):
    """Die Raumbuch-Elemente als Räume mit Zeilen für die Anzeige (Wohnung und Gemeinschaftsräume gleich).

    `ausst` ist nach Raum sortiert (Meta.ordering); `zustandsverlauf`: Bewertungen aus Abnahmen je Element-ID."""
    zustandsverlauf = zustandsverlauf or {}
    raeume = []
    for a in ausst:
        zw = a.zeitwert()
        n_schaden = a.schaeden.count()
        row = {'a': a, 'zeitwert': zw, 'lebensdauer': a.effektive_lebensdauer(),
               'rest': a.rest_jahre(), 'ersatz_status': a.ersatz_status(),
               'schaden_anzahl': n_schaden,
               'reparaturkosten': a.reparatur_kosten_total() if n_schaden else None,
               'abnahmen': zustandsverlauf.get(a.id, [])}
        if raeume and raeume[-1]['raum'] == a.raum:
            raeume[-1]['elemente'].append(row)
        else:
            raeume.append({'raum': a.raum, 'elemente': [row]})
    for r in raeume:
        r['n_faellig'] = sum(1 for x in r['elemente'] if x['ersatz_status'] == 'faellig')
        r['n_defekt'] = sum(1 for x in r['elemente'] if x['a'].zustand == 'defekt')
    return raeume


def _ausstattung_zurueck(traeger):
    """Wohin es nach einer Raumbuch-Aktion zurückgeht: der Reiter «Ausstattung» der Wohnung bzw. die
    Gemeinschaftsräume im Stammdaten-Reiter der Liegenschaft."""
    if isinstance(traeger, Einheit):
        return f'/neu/objekte/{traeger.id}/?tab=ausstattung'
    return f'/neu/liegenschaften/{traeger.id}/#gemeinschaft'


def _traeger_name(traeger):
    return getattr(traeger, 'bezeichnung', '') or str(traeger)


def _ausstattung_add(request, traeger):
    """Erfasst ein Ausstattungselement (Raumbuch) an Wohnung oder Liegenschaft. Der Raum ergibt sich
    aus dem eingegebenen Raumnamen — kein separates Raum-CRUD nötig."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    from core.services.raumbuch_assistent import bezug
    zurueck = _ausstattung_zurueck(traeger)
    if request.method != 'POST':
        return redirect(zurueck)

    raum = (request.POST.get('raum') or '').strip()
    kategorie = (request.POST.get('kategorie') or '').strip()
    if not raum or not kategorie:
        messages.error(request, gettext('Raum und Kategorie sind Pflichtfelder.'))
        return redirect(zurueck)

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else None
        except Exception:
            return None

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    def _int(x, default=None):
        try:
            return int(x)
        except Exception:
            return default

    fk = bezug(traeger)
    # Sortierung ans Ende des jeweiligen Raums
    letzte = (Ausstattung.objects.filter(raum=raum, **fk)
              .order_by('-sortierung').first())
    sort = (letzte.sortierung + 1) if letzte else 0

    a = Ausstattung.objects.create(
        raum=raum, kategorie=kategorie,
        bezeichnung=(request.POST.get('bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        material=(request.POST.get('material') or '').strip(),
        menge=_int(request.POST.get('menge'), 1) or 1,
        einbau_datum=_date(request.POST.get('einbau_datum')),
        neuwert=_dec(request.POST.get('neuwert')),
        lebensdauer_jahre=_int(request.POST.get('lebensdauer_jahre')),
        zustand=request.POST.get('zustand') or 'gut',
        garantie_bis=_date(request.POST.get('garantie_bis')),
        notiz=(request.POST.get('notiz') or '').strip(),
        sortierung=sort, **fk,
    )
    if request.FILES.get('foto'):
        a.foto = request.FILES['foto']
        a.save(update_fields=['foto'])
    log_aktion(request, "Ausstattung erfasst", _traeger_name(traeger), f"{raum} · {kategorie}")
    messages.success(request, '✅ ' + gettext('«%(kategorie)s» im Raum «%(raum)s» erfasst.') % {'kategorie': kategorie, 'raum': raum})
    return redirect(zurueck)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_add(request, pk):
    return _ausstattung_add(request, get_object_or_404(Einheit, id=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_lg_ausstattung_add(request, pk):
    from portfolio.models import Liegenschaft
    return _ausstattung_add(request, get_object_or_404(Liegenschaft, id=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_edit(request, pk):
    """Bearbeitet ein bestehendes Ausstattungselement (Marke/Modell/Material,
    Neuwert, Einbaudatum, Zustand, Garantie, Lebensdauer, Notiz, Foto). So lassen
    sich die aus dem Katalog geladenen Elemente mit echten Daten ergänzen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    a = get_object_or_404(Ausstattung.objects.select_related('einheit', 'liegenschaft'), id=pk)
    traeger = a.einheit or a.liegenschaft
    zurueck = _ausstattung_zurueck(traeger)
    if request.method != 'POST':
        return redirect(zurueck)

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else None
        except Exception:
            return None

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    def _int(x, default=None):
        try:
            return int(x)
        except Exception:
            return default

    P = request.POST
    raum = (P.get('raum') or '').strip()
    kategorie = (P.get('kategorie') or '').strip()
    if not raum or not kategorie:
        messages.error(request, gettext('Raum und Kategorie sind Pflichtfelder.'))
        return redirect(zurueck)
    a.raum = raum
    a.kategorie = kategorie
    a.bezeichnung = (P.get('bezeichnung') or '').strip()
    a.marke = (P.get('marke') or '').strip()
    a.modell = (P.get('modell') or '').strip()
    a.material = (P.get('material') or '').strip()
    a.menge = _int(P.get('menge'), a.menge) or 1
    a.einbau_datum = _date(P.get('einbau_datum'))
    a.neuwert = _dec(P.get('neuwert'))
    a.lebensdauer_jahre = _int(P.get('lebensdauer_jahre'))
    a.zustand = P.get('zustand') or a.zustand
    a.garantie_bis = _date(P.get('garantie_bis'))
    a.notiz = (P.get('notiz') or '').strip()
    if request.FILES.get('foto'):
        a.foto = request.FILES['foto']
    a.save()
    log_aktion(request, "Ausstattung bearbeitet", _traeger_name(traeger), f"{raum} · {kategorie}")
    messages.success(request, '✅ ' + gettext('«%(kategorie)s» aktualisiert.') % {'kategorie': kategorie})
    return redirect(zurueck)


def _ausstattung_katalog(request, traeger):
    """Legt für einen Raumtyp die Standard-Ausstattung aus dem Katalog an (Schnellerfassung).

    Der Raumname ist getrennt vom Typ (`core/services/raumbuch_assistent.py`): «Zimmer» und «Schlafzimmer» werden
    durchnummeriert, ein angegebener Name gilt wörtlich, alle anderen Typen gibt es einmal je Wohnung bzw. Haus.
    Vorhandene Elemente werden nicht dupliziert."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.services.raumkatalog import RAUM_KATALOG, GEMEINSCHAFT_TYPEN
    from core.services import raumbuch_assistent as ra
    from core.auth import log_aktion
    zurueck = _ausstattung_zurueck(traeger)
    if request.method != 'POST':
        return redirect(zurueck)

    raumtyp = (request.POST.get('raumtyp') or '').strip()
    erlaubt = RAUM_KATALOG if isinstance(traeger, Einheit) else {t: RAUM_KATALOG[t] for t in GEMEINSCHAFT_TYPEN}
    if raumtyp not in erlaubt:
        messages.error(request, gettext('Unbekannter Raumtyp.'))
        return redirect(zurueck)

    wunsch = ra.bereinigt(request.POST.get('raumname'))
    vorhandene = list(dict.fromkeys(Ausstattung.objects.filter(**ra.bezug(traeger)).values_list('raum', flat=True)))
    if wunsch:
        raum = wunsch
    else:
        namen = ra.neue_namen(raumtyp, 1, vorhandene)
        # Ein einmaliger Typ, der schon da ist: wie bisher «bereits vollständig» (ergänzt fehlende Elemente).
        raum = namen[0] if namen else raumtyp
    n = ra.raum_anlegen(traeger, raumtyp, raum)
    if n:
        log_aktion(request, "Raumkatalog geladen", _traeger_name(traeger), f"{raum}: {n} Elemente")
        messages.success(request, '✅ ' + gettext('%(n)s Element(e) für «%(raumtyp)s» angelegt — jetzt Details ergänzen.') % {'n': n, 'raumtyp': raum})
    else:
        messages.info(request, gettext('«%(raumtyp)s» ist bereits vollständig erfasst.') % {'raumtyp': raum})
    return redirect(zurueck)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_katalog(request, pk):
    return _ausstattung_katalog(request, get_object_or_404(Einheit, id=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_lg_ausstattung_katalog(request, pk):
    from portfolio.models import Liegenschaft
    return _ausstattung_katalog(request, get_object_or_404(Liegenschaft, id=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_assistent(request, pk):
    """Raumbuch-Assistent: legt die Räume einer Wohnung aus der Zahl je Raumtyp an (Vorschlag aus der Zimmerzahl)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services import raumbuch_assistent as ra
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method == 'POST':
        angelegt, uebersprungen = ra.anlegen(e, ra.plan_aus_formular(request.POST))
        if angelegt:
            log_aktion(request, "Raumbuch-Assistent", e.bezeichnung, ', '.join(angelegt))
            messages.success(request, '✅ ' + gettext('%(n)s Räume angelegt: %(namen)s. Jetzt Details je Element ergänzen.')
                             % {'n': len(angelegt), 'namen': ', '.join(angelegt)})
        if uebersprungen:
            messages.info(request, gettext('Schon vorhanden und nicht nochmals angelegt: %(namen)s.')
                          % {'namen': ', '.join(uebersprungen)})
        if not angelegt and not uebersprungen:
            messages.error(request, gettext('Kein Raum gewählt.'))
    return redirect(_ausstattung_zurueck(e))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_lg_gemeinschaft_anlegen(request, pk):
    """Gemeinschaftsräume des Hauses anlegen: Waschküche, Trockenraum, Veloraum … — je Typ einer, aus dem Katalog."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Liegenschaft
    from core.services import raumbuch_assistent as ra
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=pk)
    if request.method == 'POST':
        angelegt, uebersprungen = ra.gemeinschaft_anlegen(lg, set(request.POST.getlist('typ')))
        if angelegt:
            log_aktion(request, "Gemeinschaftsräume angelegt", _traeger_name(lg), ', '.join(angelegt))
            messages.success(request, '✅ ' + gettext('%(n)s Räume angelegt: %(namen)s. Jetzt Details je Element ergänzen.')
                             % {'n': len(angelegt), 'namen': ', '.join(angelegt)})
        if uebersprungen:
            messages.info(request, gettext('Schon vorhanden und nicht nochmals angelegt: %(namen)s.')
                          % {'namen': ', '.join(uebersprungen)})
        if not angelegt and not uebersprungen:
            messages.error(request, gettext('Kein Raum gewählt.'))
    return redirect(_ausstattung_zurueck(lg))


def _ausstattung_raum_loeschen(request, traeger):
    """Entfernt einen ganzen Raum (alle seine Elemente) — z. B. wenn er falsch angelegt wurde."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    from core.services.raumbuch_assistent import bezug
    raum = (request.POST.get('raum') or '').strip()
    if request.method == 'POST' and raum:
        anzahl, _einzeln = Ausstattung.objects.filter(raum=raum, **bezug(traeger)).delete()
        if anzahl:
            log_aktion(request, "Raum gelöscht", _traeger_name(traeger), f"{raum}: {anzahl} Elemente")
            messages.success(request, gettext('Raum «%(raum)s» mit %(n)s Elementen entfernt.') % {'raum': raum, 'n': anzahl})
        else:
            messages.info(request, gettext('Den Raum «%(raum)s» gibt es nicht (mehr).') % {'raum': raum})
    return redirect(_ausstattung_zurueck(traeger))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_raum_loeschen(request, pk):
    return _ausstattung_raum_loeschen(request, get_object_or_404(Einheit, id=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_lg_ausstattung_raum_loeschen(request, pk):
    from portfolio.models import Liegenschaft
    return _ausstattung_raum_loeschen(request, get_object_or_404(Liegenschaft, id=pk))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_del(request, pk):
    """Entfernt ein Ausstattungselement."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    a = get_object_or_404(Ausstattung.objects.select_related('einheit', 'liegenschaft'), id=pk)
    zurueck = _ausstattung_zurueck(a.einheit or a.liegenschaft)
    if request.method == 'POST':
        a.delete()
        messages.success(request, gettext('Ausstattungselement entfernt.'))
    return redirect(zurueck)


# --- Geräte (Objekt + allgemeine Liegenschafts-Geräte wie Heizung/Boiler) ---


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lebensdauer(request):
    """Editierbare paritätische Lebensdauertabelle (Mieterverband/HEV).
    Grundlage für den Zeitwert-/Mieteranteil bei der Wohnungsabnahme."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Lebensdauer
    from core.auth import log_aktion, hat_rolle
    basis = _global_filter(request)

    # Seit Etappe 5 gehoert die Lebensdauertabelle der Organisation. Jede Zeile
    # dieses Views muss deshalb auf sie eingeschraenkt sein — sonst saehe und
    # bearbeitete Verwaltung A die Werte von B. Die Middleware setzt
    # `request.organisation` aus der Mitgliedschaft.
    #
    # Seit Etappe 6.2 filtert `Lebensdauer.objects` ohnehin ueber den
    # Mandantenkontext; der Filter hier ist redundant. Er bleibt, weil er
    # NICHT schwaecher ist (ohne Organisation liefert er nichts) und weil das
    # Anlegen unten dieselbe Variable braucht.
    organisation = getattr(request, 'organisation', None)
    eigene = Lebensdauer.objects.filter(organisation=organisation)

    # KEINE Erstbefuellung beim Aufruf (ROUTE-07): Ein GET schreibt nichts.
    # Die Standardwerte entstehen bei der Anlage der Verwaltung
    # (`core/services/onboarding.py`); bei einer leeren Tabelle gibt es den
    # Knopf «Standardwerte ergaenzen» (POST, Aktion `seed` unten).

    if request.method == 'POST':
        if not hat_rolle(request.user, SCHREIB_ROLLEN):
            messages.error(request, gettext('Keine Berechtigung zum Bearbeiten.'))
            return redirect('/neu/lebensdauer/')
        aktion = request.POST.get('aktion')
        if aktion == 'speichern':
            n = 0
            for row in eigene:
                val = request.POST.get(f'jahre_{row.id}')
                bem = request.POST.get(f'bemerkung_{row.id}')
                changed = False
                if val and val.isdigit() and int(val) != row.jahre and int(val) > 0:
                    row.jahre = int(val); changed = True
                if bem is not None and bem.strip() != row.bemerkung:
                    row.bemerkung = bem.strip(); changed = True
                if changed:
                    row.save(); n += 1
            log_aktion(request, "Lebensdauertabelle bearbeitet", f"{n} Werte")
            messages.success(request, ('✅ ' + gettext('%(n)s Wert(e) aktualisiert.') % {'n': n}) if n
                             else gettext('Keine Änderung.'))
        elif aktion == 'neu':
            kat = (request.POST.get('kategorie') or '').strip()
            jahre = request.POST.get('jahre')
            if kat and jahre and jahre.isdigit() and int(jahre) > 0:
                _, created = Lebensdauer.objects.get_or_create(
                    kategorie=kat, organisation=organisation,
                    defaults={'jahre': int(jahre),
                              'bemerkung': (request.POST.get('bemerkung') or '').strip()})
                messages.success(request, ('✅ ' + gettext('«%(kat)s» hinzugefügt.') % {'kat': kat}) if created
                                 else gettext('Kategorie existiert bereits.'))
            else:
                messages.error(request, gettext('Kategorie und Jahre (> 0) sind Pflicht.'))
        elif aktion == 'loeschen':
            # Ueber `eigene`, nicht ueber `objects`: Eine ID aus dem Formular
            # ist eine Nutzereingabe, und eine fremde ID darf nichts loeschen.
            eigene.filter(id=request.POST.get('id') or None).delete()
            messages.success(request, gettext('Kategorie entfernt.'))
        elif aktion == 'seed':
            from core.services.raumkatalog import seed_lebensdauer
            n = seed_lebensdauer(organisation)
            messages.success(request, ('✅ ' + gettext('%(n)s Standardwert(e) ergänzt.') % {'n': n}) if n
                             else gettext('Alle Standardwerte bereits vorhanden.'))
        return redirect('/neu/lebensdauer/')

    from django.contrib import messages as _m
    return render(request, 'fw/lebensdauer.html', {
        **basis, 'nav': 'assets',
        'rows': eigene,
        'meldung': list(_m.get_messages(request)),
    })
