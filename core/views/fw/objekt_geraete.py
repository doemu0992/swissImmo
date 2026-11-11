# core/views/fw/objekt_geraete.py
#
# Geraete, Zaehler und Schluesselausgabe am Objekt.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN)
from portfolio.models import Einheit, Liegenschaft

from ._basis import (_num)


GERAET_KATEGORIEN = [
    'Heizung', 'Boiler / Wassererwärmer', 'Wärmepumpe', 'Lüftung', 'Klimaanlage',
    'Aufzug', 'Waschmaschine', 'Tumbler', 'Geschirrspüler', 'Backofen', 'Kochfeld',
    'Kühlschrank', 'Dampfabzug', 'Rauchmelder', 'Solaranlage', 'Photovoltaik',
    'Gartengerät', 'Tor / Antrieb', 'Sonstiges',
]
ZAEHLER_TYPEN = [
    'Allgemeinstrom', 'Strom', 'Wasser kalt', 'Wasser warm', 'Gas',
    'Wärmezähler', 'Öl', 'Fernwärme', 'Sonstiges',
]


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_add(request):
    """Erfasst ein Gerät. Ziel ist entweder ein Objekt (`einheit_id`) oder eine
    Liegenschaft (`liegenschaft_id`, z.B. Heizung, Boiler, Lüftung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/liegenschaften/')

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    eid = request.POST.get('einheit_id')
    lid = request.POST.get('liegenschaft_id')
    kategorie = (request.POST.get('kategorie') or '').strip()
    if not kategorie:
        kategorie = (request.POST.get('sonstiges_bezeichnung') or 'sonstiges').strip() or 'sonstiges'

    kwargs = dict(
        kategorie=kategorie,
        sonstiges_bezeichnung=(request.POST.get('sonstiges_bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        seriennummer=(request.POST.get('seriennummer') or '').strip(),
        kapazitaet=(request.POST.get('kapazitaet') or '').strip(),
        standort=(request.POST.get('standort') or '').strip(),
        installations_datum=_date(request.POST.get('installations_datum')),
        garantie_bis=_date(request.POST.get('garantie_bis')),
        notiz=(request.POST.get('notiz') or '').strip(),
    )
    if eid:
        e = get_object_or_404(Einheit, id=eid)
        Geraet.objects.create(einheit=e, **kwargs)
        log_aktion(request, "Gerät erfasst", e.bezeichnung, kategorie)
        messages.success(request, '✅ ' + gettext('Gerät «%(kategorie)s» erfasst.') % {'kategorie': kategorie})
        return redirect(f'/neu/objekte/{e.id}/?tab=geraete')
    if lid:
        lg = get_object_or_404(Liegenschaft, id=lid)
        Geraet.objects.create(liegenschaft=lg, **kwargs)
        log_aktion(request, "Gerät erfasst", str(lg), kategorie)
        messages.success(request, '✅ ' + gettext('Gerät «%(kategorie)s» erfasst.') % {'kategorie': kategorie})
        return redirect(f'/neu/liegenschaften/{lg.id}/?tab=technik')
    messages.error(request, gettext('Kein Ziel angegeben.'))
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_del(request, pk):
    """Entfernt ein Gerät (Objekt- oder Liegenschaftsebene)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    g = get_object_or_404(Geraet, id=pk)
    eid, lid = g.einheit_id, g.liegenschaft_id
    if request.method == 'POST':
        from core.models import Pendenz
        # Verwaiste Auto-Garantie-Pendenz mitlöschen (hängt nur über `quelle`).
        Pendenz.objects.filter(quelle=f"auto:garantie:{g.id}").delete()
        g.delete()
        messages.success(request, gettext('Gerät entfernt.'))
    if eid:
        return redirect(f'/neu/objekte/{eid}/?tab=geraete')
    return redirect(f'/neu/liegenschaften/{lid}/?tab=technik')


# --- Zähler (Objekt + allgemeine Liegenschafts-Zähler wie Allgemeinstrom) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_add(request):
    """Erfasst einen Zähler. Ziel ist entweder ein Objekt (`einheit_id`) oder eine
    Liegenschaft (`liegenschaft_id`, z.B. Allgemeinstrom, Hauptwasser)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/liegenschaften/')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return Decimal('0.00')

    typ = (request.POST.get('typ') or '').strip()
    nummer = (request.POST.get('zaehler_nummer') or '').strip()
    if not typ or not nummer:
        messages.error(request, gettext('Typ und Zähler-Nr. sind Pflichtfelder.'))
        ref = request.META.get('HTTP_REFERER') or '/neu/liegenschaften/'
        return redirect(ref)

    kwargs = dict(
        typ=typ, zaehler_nummer=nummer,
        standort=(request.POST.get('standort') or '').strip(),
        aktueller_stand=_dec(request.POST.get('aktueller_stand')),
    )
    eid = request.POST.get('einheit_id')
    lid = request.POST.get('liegenschaft_id')
    if eid:
        e = get_object_or_404(Einheit, id=eid)
        Zaehler.objects.create(einheit=e, **kwargs)
        log_aktion(request, "Zähler erfasst", e.bezeichnung, f"{typ} · {nummer}")
        messages.success(request, '✅ ' + gettext('Zähler «%(typ)s» erfasst.') % {'typ': typ})
        return redirect(f'/neu/objekte/{e.id}/?tab=zaehler')
    if lid:
        lg = get_object_or_404(Liegenschaft, id=lid)
        Zaehler.objects.create(liegenschaft=lg, **kwargs)
        log_aktion(request, "Zähler erfasst", str(lg), f"{typ} · {nummer}")
        messages.success(request, '✅ ' + gettext('Zähler «%(typ)s» erfasst.') % {'typ': typ})
        return redirect(f'/neu/liegenschaften/{lg.id}/?tab=technik')
    messages.error(request, gettext('Kein Ziel angegeben.'))
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_edit(request, pk):
    """Bearbeitet einen bestehenden Zähler (Typ/Nr./Standort/Stand)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    from core.auth import log_aktion
    z = get_object_or_404(Zaehler, id=pk)
    eid, lid = z.einheit_id, z.liegenschaft_id
    ziel = (f'/neu/objekte/{eid}/?tab=zaehler' if eid
            else f'/neu/liegenschaften/{lid}/?tab=technik')
    if request.method != 'POST':
        return redirect(ziel)

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return z.aktueller_stand

    typ = (request.POST.get('typ') or '').strip()
    nummer = (request.POST.get('zaehler_nummer') or '').strip()
    if not typ or not nummer:
        messages.error(request, gettext('Typ und Zähler-Nr. sind Pflichtfelder.'))
        return redirect(ziel)
    z.typ = typ
    z.zaehler_nummer = nummer
    z.standort = (request.POST.get('standort') or '').strip()
    z.aktueller_stand = _dec(request.POST.get('aktueller_stand'))
    z.save()
    log_aktion(request, "Zähler bearbeitet", f"{typ} · {nummer}", '')
    messages.success(request, '✅ ' + gettext('Zähler «%(typ)s» aktualisiert.') % {'typ': typ})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_del(request, pk):
    """Entfernt einen Zähler (Objekt- oder Liegenschaftsebene)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    z = get_object_or_404(Zaehler, id=pk)
    eid, lid = z.einheit_id, z.liegenschaft_id
    if request.method == 'POST':
        z.delete()
        messages.success(request, gettext('Zähler entfernt.'))
    if eid:
        return redirect(f'/neu/objekte/{eid}/?tab=zaehler')
    return redirect(f'/neu/liegenschaften/{lid}/?tab=technik')


# --- Schlüsselverwaltung (Register je Objekt; Ausgabe/Rücknahme: core/views/fw/schluessel.py) ---

def _objekt_schluessel_ziel(einheit_id):
    return f'/neu/objekte/{einheit_id}/?tab=ausstattung#schluessel'


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_add(request):
    """Erfasst einen Schlüssel im Register eines Objekts. Schlüssel ohne
    Einheit (Haustür, Briefkasten) entstehen an der Liegenschaft
    (`fw_liegenschaft_schluessel_neu`)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'),
                          id=request.POST.get('einheit_id'))
    nummer = (request.POST.get('schluessel_nummer') or '').strip()[:50]
    typ = (request.POST.get('typ') or 'Wohnung').strip()[:50]
    art = request.POST.get('art') if request.POST.get('art') in dict(Schluessel.ART_CHOICES) else 'einzel'
    try:
        anzahl = max(1, int(request.POST.get('anzahl') or 1))
    except (TypeError, ValueError):
        anzahl = 1
    if not nummer:
        messages.error(request, gettext('Schlüssel-Nr. ist ein Pflichtfeld.'))
        return redirect(_objekt_schluessel_ziel(e.id))
    Schluessel.objects.create(liegenschaft=e.liegenschaft, einheit=e, art=art,
                              typ=typ, schluessel_nummer=nummer, anzahl=anzahl)
    log_aktion(request, "Schlüssel erfasst", f"{e.bezeichnung}", f"{typ} {nummer} × {anzahl}")
    messages.success(request, '✅ ' + gettext('Schlüssel %(nummer)s (%(typ)s, %(anzahl)s×) erfasst.') % {'nummer': nummer, 'typ': typ, 'anzahl': anzahl})
    return redirect(_objekt_schluessel_ziel(e.id))


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_del(request, pk):
    """Entfernt einen Schlüssel aus dem Register.

    Seit Modul 2 (27.10.2026) löscht das den Verlauf nicht mehr mit: Hat der
    Schlüssel Ausgaben, wird er archiviert — wer ihn wann hatte, samt
    Quittungen und Verlusten, bleibt nachweisbar. Nur ein Schlüssel ohne jede
    Ausgabe wird wirklich gelöscht. Solange er ausgegeben ist, geht beides nicht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel
    from core.auth import log_aktion
    sch = get_object_or_404(Schluessel.objects, id=pk)
    eid, lid = sch.einheit_id, sch.liegenschaft_id
    if request.method == 'POST':
        if sch.ausgaben.filter(status='ausgegeben').exists():
            messages.error(request, gettext('Schlüssel ist noch ausgegeben — zuerst Rücknahme erfassen.'))
        elif sch.ausgaben.exists():
            sch.archiviert = True
            sch.save(update_fields=['archiviert'])
            log_aktion(request, "Schlüssel archiviert", sch.typ, sch.schluessel_nummer)
            messages.success(request, gettext('Schlüssel archiviert. Der Verlauf bleibt erhalten.'))
        else:
            log_aktion(request, "Schlüssel entfernt", sch.typ, sch.schluessel_nummer)
            sch.delete()
            messages.success(request, gettext('Schlüssel entfernt.'))
    standard = (_objekt_schluessel_ziel(eid) if eid
                else f'/neu/liegenschaften/{lid}/?tab=stammdaten#schliessanlage')
    ziel = (request.POST.get('next') or '').strip()
    return redirect(ziel if ziel.startswith('/neu/') and not ziel.startswith('//') else standard)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_ausgabe(request, pk):
    """Früher: Ausgabe eines Schlüssels ohne Unterschrift und Quittung.

    Seit Modul 2 gibt es dafür EINEN Weg, die Kartenseite mit Unterschrift
    (`fw_liegenschaft_schluessel_ausgabe`). Diese Adresse führt dorthin, mit
    dem Schlüssel vorgewählt — ein zweiter Weg ohne Quittung bliebe sonst
    offen."""
    from django.shortcuts import redirect
    from portfolio.models import Schluessel
    sch = get_object_or_404(Schluessel.objects, id=pk)
    return redirect(f'/neu/liegenschaften/{sch.liegenschaft_id}/schluessel/ausgabe/?schluessel={sch.pk}')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_rueckgabe(request, pk):
    """Früher: Rücknahme ohne Quittung. Führt jetzt auf die Rücknahmeseite des
    Empfängers dieser Ausgabe (siehe `fw_schluessel_ausgabe`)."""
    from django.shortcuts import redirect
    from portfolio.models import SchluesselAusgabe
    from core.services.schluessel import ruecknahme_url
    a = get_object_or_404(SchluesselAusgabe.objects.select_related('schluessel'), id=pk)
    return redirect(ruecknahme_url(a))


# --- Sollmietzins-Komponenten (datierte Netto-/NK-Historie je Objekt) ---


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_edit(request, pk):
    """Bearbeitet ein bestehendes Gerät (Kategorie/Marke/Modell/Daten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    eid, lid = g.einheit_id, g.liegenschaft_id
    ziel = (f'/neu/objekte/{eid}/?tab=geraete' if eid
            else f'/neu/liegenschaften/{lid}/?tab=technik')
    if request.method != 'POST':
        return redirect(ziel)

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    kategorie = (request.POST.get('kategorie') or '').strip()
    if not kategorie:
        messages.error(request, gettext('Kategorie ist ein Pflichtfeld.'))
        return redirect(ziel)
    g.kategorie = kategorie
    g.sonstiges_bezeichnung = (request.POST.get('sonstiges_bezeichnung') or '').strip()
    g.marke = (request.POST.get('marke') or '').strip()
    g.modell = (request.POST.get('modell') or '').strip()
    g.seriennummer = (request.POST.get('seriennummer') or '').strip()
    g.kapazitaet = (request.POST.get('kapazitaet') or '').strip()
    g.standort = (request.POST.get('standort') or '').strip()
    g.installations_datum = _date(request.POST.get('installations_datum'))
    g.garantie_bis = _date(request.POST.get('garantie_bis'))
    g.notiz = (request.POST.get('notiz') or '').strip()
    g.save()
    log_aktion(request, "Gerät bearbeitet", kategorie, '')
    messages.success(request, '✅ ' + gettext('Gerät «%(kategorie)s» aktualisiert.') % {'kategorie': kategorie})
    return redirect(ziel)
