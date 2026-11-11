# core/views/fw/sollmietzins.py
#
# Sollmietzins, Staffelvorlagen, Staffeln und Mietzinsanpassung.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       VERWALTUNGS_ROLLEN)
from portfolio.models import Einheit

from ._basis import (_num)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_sollmietzins_add(request):
    """Erfasst eine datierte Sollmietzins-Zeile (gültig ab) für ein Objekt.
    Der aktuell gültige Wert wird automatisch auf die Einheit abgeleitet;
    neue Verträge übernehmen ihn ab dem Mietbeginn (Bestand bleibt unberührt)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Sollmietzins
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return Decimal('0.00')

    e = get_object_or_404(Einheit, id=request.POST.get('einheit_id'))
    ziel = f'/neu/objekte/{e.id}/?tab=mietzins'
    ab_raw = (request.POST.get('gueltig_ab') or '').strip()
    try:
        ab = date.fromisoformat(ab_raw)
    except ValueError:
        messages.error(request, gettext('Bitte ein gültiges «gültig ab»-Datum angeben.'))
        return redirect(ziel)
    netto = _dec(request.POST.get('netto_mietzins'))
    # Einstellplatz → keine Nebenkosten
    nk = Decimal('0.00') if e.ist_einstellplatz else _dec(request.POST.get('nebenkosten'))
    # Rabatt/Erlass (Gratismonat): mindert nur die Verrechnung, nicht die Referenz.
    # "mietzinsfrei" = voller Netto-Erlass → Rabatt = Netto-Referenz.
    if request.POST.get('mietzinsfrei'):
        rabatt_netto = netto
    else:
        rabatt_netto = _dec(request.POST.get('rabatt_netto'))
    rabatt_nk = _dec(request.POST.get('rabatt_nk'))
    rabatt_netto = min(max(rabatt_netto, Decimal('0.00')), netto)   # 0..Referenz
    rabatt_nk = min(max(rabatt_nk, Decimal('0.00')), nk)

    def _dec_opt(x):
        v = _num(x)
        try:
            return Decimal(v) if v else None
        except Exception:
            return None

    Sollmietzins.objects.create(
        einheit=e, gueltig_ab=ab, netto_mietzins=netto, nebenkosten=nk,
        rabatt_netto=rabatt_netto, rabatt_nk=rabatt_nk,
        basis_referenzzinssatz=_dec_opt(request.POST.get('basis_referenzzinssatz')),
        basis_lik_punkte=_dec_opt(request.POST.get('basis_lik_punkte')),
        notiz=(request.POST.get('notiz') or '').strip()[:200],
    )
    zu_zahlen = max(Decimal('0'), netto - rabatt_netto) + max(Decimal('0'), nk - rabatt_nk)
    log_aktion(request, "Sollmietzins erfasst", e.bezeichnung,
               f"ab {ab}: Referenz {netto}+{nk}, Rabatt {rabatt_netto}/{rabatt_nk}, zu zahlen {zu_zahlen}")
    # Ein Erlass ist eine Geld-Entscheidung — die Bestätigung muss ihn benennen
    # und nicht nur eine Summe zeigen, in der er schon verrechnet ist. Ein voller
    # Erlass bekommt zusätzlich einen Warnton statt eines Häkchens.
    if rabatt_netto >= netto > 0:
        messages.warning(
            request,
            '⚠️ ' + gettext('Sollmietzins ab %(strftime)s erfasst — Nettomietzins CHF %(netto)s VOLLSTÄNDIG ERLASSEN (Gratismonat). Verrechnet wird nur CHF %(zu_zahlen)s. War das nicht beabsichtigt, Zeile löschen und ohne Rabatt neu erfassen.') % {'strftime': ab.strftime('%d.%m.%Y'), 'netto': netto, 'zu_zahlen': zu_zahlen})
    elif rabatt_netto > 0 or rabatt_nk > 0:
        messages.success(
            request,
            '✅ ' + gettext('Sollmietzins ab %(strftime)s erfasst — Referenz CHF %(wert)s, davon CHF %(wert2)s Rabatt, zu zahlen CHF %(zu_zahlen)s.') % {'strftime': ab.strftime('%d.%m.%Y'), 'wert': netto + nk, 'wert2': rabatt_netto + rabatt_nk, 'zu_zahlen': zu_zahlen})
    else:
        messages.success(request, '✅ ' + gettext('Sollmietzins ab %(strftime)s erfasst (CHF %(zu_zahlen)s).') % {'strftime': ab.strftime('%d.%m.%Y'), 'zu_zahlen': zu_zahlen})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_sollmietzins_del(request, pk):
    """Entfernt eine Sollmietzins-Zeile und führt den Aktuellwert der Einheit nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Sollmietzins
    s = get_object_or_404(Sollmietzins, id=pk)
    e = s.einheit
    if request.method == 'POST':
        s.delete()
        e.sync_aktuelle_miete()
        messages.success(request, gettext('Sollmietzins-Zeile entfernt.'))
    return redirect(f'/neu/objekte/{e.id}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffelvorlage_add(request):
    """Erfasst eine datierte Stufe der OBJEKT-Staffelmiete-Vorlage (Plan). Belegt
    neue Verträge im Wizard vor — wird selbst nicht verrechnet."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import StaffelVorlage
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    e = get_object_or_404(Einheit, id=request.POST.get('einheit_id'))
    ziel = f'/neu/objekte/{e.id}/?tab=mietzins'
    try:
        ab = date.fromisoformat((request.POST.get('gueltig_ab') or '').strip())
    except ValueError:
        messages.error(request, gettext('Bitte ein gültiges «gültig ab»-Datum angeben.'))
        return redirect(ziel)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None

    netto = _dec(request.POST.get('netto_mietzins'))
    if netto is None or netto <= 0:
        messages.error(request, gettext('Bitte einen gültigen Netto-Mietzins angeben.'))
        return redirect(ziel)
    StaffelVorlage.objects.create(
        einheit=e, gueltig_ab=ab, netto_mietzins=netto,
        notiz=(request.POST.get('notiz') or '').strip()[:200])
    log_aktion(request, "Staffel-Vorlage erfasst", e.bezeichnung, f"ab {ab}: {netto}")
    messages.success(request, '✅ ' + gettext('Staffel-Vorlage ab %(strftime)s erfasst.') % {'strftime': ab.strftime('%d.%m.%Y')})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffelvorlage_del(request, pk):
    """Entfernt eine Stufe der Objekt-Staffelmiete-Vorlage."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import StaffelVorlage
    s = get_object_or_404(StaffelVorlage, id=pk)
    eid = s.einheit_id
    if request.method == 'POST':
        s.delete()
        messages.success(request, gettext('Staffel-Vorlage-Zeile entfernt.'))
    return redirect(f'/neu/objekte/{eid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_add(request):
    """Erfasst eine Staffelstufe (Art. 269c) für den AKTIVEN Vertrag eines Objekts.
    Staffelmiete ist vertragsgebunden — die Stufe treibt direkt die Sollstellung
    (effektiver_netto_mietzins ab Stichtag)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Mietvertrag, Staffelstufe
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    v = get_object_or_404(Mietvertrag, id=request.POST.get('vertrag_id'))
    ziel = f'/neu/objekte/{v.einheit_id}/?tab=mietzins'
    try:
        ab = date.fromisoformat((request.POST.get('ab_datum') or '').strip())
    except ValueError:
        messages.error(request, gettext('Bitte ein gültiges Stichtag-Datum angeben.'))
        return redirect(ziel)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None

    netto = _dec(request.POST.get('netto_mietzins'))
    if netto is None or netto <= 0:
        messages.error(request, gettext('Bitte einen gültigen Netto-Mietzins angeben.'))
        return redirect(ziel)
    netto = netto.quantize(Decimal('0.01'))
    # Die Erhöhung in CHF ist die Quelle der Wahrheit (Art. 269c lit. c OR); die Maske liefert den
    # neuen Netto-Mietzins, die Erhöhung folgt aus dem Stand davor.
    from core.services.mietzinsmodell import Stufe, pruefe_vertrag, sperren
    bisher = list(v.staffelstufen.all())
    davor = [s for s in bisher if s.ab_datum < ab]
    vorstand = max(davor, key=lambda s: (s.ab_datum, s.id)).netto_mietzins if davor else v.netto_mietzins
    erhoehung = netto - (vorstand or Decimal('0'))
    # Geprüft wird der Vertrag so, wie er nach dem Speichern wäre. Ein Altvertrag, der schon
    # Staffelvertrag ist, wird nicht wegen früherer Verstösse blockiert, nur wegen neuer.
    altes_modell = v.mietzins_modell
    stufen_neu = [Stufe(ab=s.ab_datum, erhoehung_chf=s.erhoehung_chf) for s in bisher]
    vorher = (set((b.regel, b.zeile) for b in sperren(pruefe_vertrag(v, stufen=stufen_neu)))
              if altes_modell == 'staffel' else set())
    stufen_neu.append(Stufe(ab=ab, erhoehung_chf=erhoehung))
    v.mietzins_modell = 'staffel'
    try:
        neue_sperren = [b for b in sperren(pruefe_vertrag(v, stufen=stufen_neu))
                        if (b.regel, b.zeile) not in vorher]
    finally:
        v.mietzins_modell = altes_modell
    if neue_sperren:
        for b in neue_sperren:
            messages.error(request, '❌ ' + b.volltext)
        return redirect(ziel)
    Staffelstufe.objects.create(vertrag=v, ab_datum=ab, netto_mietzins=netto, erhoehung_chf=erhoehung)
    # Damit die Stufe im Mietenlauf greift, muss das Vertragsmodell 'staffel' sein.
    if v.mietzins_modell != 'staffel':
        v.mietzins_modell = 'staffel'
        v.save(update_fields=['mietzins_modell'])
    messages.success(request, '✅ ' + gettext('Staffelstufe ab %(strftime)s erfasst.') % {'strftime': ab.strftime('%d.%m.%Y')})
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_del(request, pk):
    """Entfernt eine Staffelstufe des aktiven Vertrags."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Staffelstufe
    s = get_object_or_404(Staffelstufe, id=pk)
    eid = s.vertrag.einheit_id
    if request.method == 'POST':
        s.delete()
        messages.success(request, gettext('Staffelstufe entfernt.'))
    return redirect(f'/neu/objekte/{eid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_anpassung_del(request, pk):
    """Entfernt eine (versehentlich erstellte) Mietzinsanpassung. Danach folgt die
    Sollstellung wieder dem vorherigen Mietzins — bereits gestellte Rechnungen
    bleiben unverändert (nur künftige Sollläufe).

    Seit dem Production-Check (27.10.2026): Einen Entwurf darf entfernen, wer
    schreiben darf. Eine VERSANDTE Anpassung ist dem Mieter mitgeteilt — sie
    entfernt nur die Verwaltung (Verwalter/Inhaber), etwa nach einem Fehler beim
    Erfassen, und mit ihr die Anfechtungs-Pendenz (Art. 270b OR), die sonst
    weiter im Arbeitsvorrat stünde."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import MietzinsAnpassung
    from core.auth import log_aktion, hat_rolle
    from core.models import Pendenz
    from core.services.mietzinsanpassung import quelle_anfechtung
    from portfolio.models import Sollmietzins
    a = get_object_or_404(MietzinsAnpassung, id=pk)
    vid = a.vertrag_id
    if request.method == 'POST':
        if a.status in MietzinsAnpassung.GEBUCHT and not hat_rolle(request.user, VERWALTUNGS_ROLLEN):
            messages.error(request, gettext('Eine versandte Mietzinsanpassung kann nur die Verwaltung '
                                            '(Verwalter/Inhaber) entfernen.'))
            return redirect(f'/neu/vertraege/{vid}/?tab=mietzins')
        log_aktion(request, "Mietzinsanpassung gelöscht", str(a.vertrag),
                   f"{a.get_status_display()}, wirksam {a.wirksam_ab}: CHF {a.neuer_netto_mietzins}")
        Pendenz.objects.filter(vertrag_id=vid, quelle__in=[quelle_anfechtung(a), f'270b-verfahren:{a.pk}'],
                               erledigt=False).delete()
        # Die aus dieser Anpassung erzeugte Sollmietzins-Zeile im Objekt
        # ebenfalls entfernen und den aktuellen Mietzins der Einheit neu ableiten.
        einheiten = {z.einheit for z in a.sollmietzins_zeilen.all()}
        Sollmietzins.objects.filter(quelle_anpassung=a).delete()
        a.delete()
        for e in einheiten:
            if e:
                e.sync_aktuelle_miete()
        messages.success(request, gettext('Mietzinsanpassung entfernt.'))
    return redirect(f'/neu/vertraege/{vid}/?tab=mietzins')
