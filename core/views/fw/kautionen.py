# core/views/fw/kautionen.py
#
# Kautions-Register nach Art. 257e OR — bewusst SEPARAT vom
# Verwaltungs-Hauptbuch gefuehrt, weil Kautionen kein Vermoegen der
# Verwaltung sind. Dazu Maengelruege, WG-Vertraege, Untermiete.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Art. 257e und die Trennung vom Hauptbuch stehen im Skill
# schweizer-fachlogik. Der Umzug aendert daran nichts: Blockinhalt gegen
# HEAD Zeile fuer Zeile geprueft.

import logging
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _kaution_bilanziert, _num

logger = logging.getLogger(__name__)


# ============================================================
# KAUTIONS-REGISTER (Art. 257e OR — separat vom Verwaltungs-Hauptbuch)
# ============================================================

KAUTION_PILL = {
    'erwartet':       ('Erwartet',       'bg-amber-50 text-amber-700'),
    'einbezahlt':     ('Einbezahlt',     'bg-emerald-50 text-emerald-700'),
    'zurueckbezahlt': ('Zurückbezahlt',  'bg-slate-100 text-slate-500'),
}

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kautionen(request):
    """Register aller Mietzinsdepots — separate Führung nach Art. 257e OR."""
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    qs = (Mietvertrag.objects.filter(kautions_betrag__gt=0)
          .select_related('mieter', 'einheit__liegenschaft').order_by('-beginn'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    rows, sum_erwartet, sum_gehalten = [], Decimal('0.00'), Decimal('0.00')
    for v in qs:
        st = v.kautions_status
        label, cls = KAUTION_PILL.get(st, (st, 'bg-slate-100 text-slate-500'))
        rows.append({'v': v, 'status': st, 'label': label, 'cls': cls})
        if st == 'erwartet':
            sum_erwartet += v.kautions_betrag or Decimal('0.00')
        elif st == 'einbezahlt':
            sum_gehalten += v.kautions_betrag or Decimal('0.00')
    return render(request, 'fw/kautionen.html', {
        **basis, 'nav': 'kautionen', 'rows': rows,
        'sum_erwartet': sum_erwartet, 'sum_gehalten': sum_gehalten,
        'anzahl': len(rows),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kaution_aktion(request, vertrag_id):
    """Einzahlung bestätigen oder Rückzahlung (mit Einbehalt) erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    P = request.POST
    aktion = P.get('aktion')

    def d(key):
        val = P.get(key)
        try:
            return date.fromisoformat(val) if val else None
        except ValueError:
            return None

    def dec(key):
        try:
            return Decimal((_num(P.get(key)) or '0'))
        except Exception:
            return Decimal('0.00')

    if aktion == 'einzahlung':
        # Sperrkonto: Einzahlung auf Mietkonto bestätigen.
        # Statusänderung UND Bilanzbuchung (1015 an 2010) in EINER Transaktion —
        # scheitert die Buchung (z.B. Periodensperre), wird die Statusänderung
        # zurückgerollt und der Fehler angezeigt (kein stiller Nebenbuch-Drift).
        v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = d('einbezahlt_am') or timezone.localdate()
        v.kautions_konto = P.get('kautions_konto', v.kautions_konto).strip() or v.kautions_konto
        try:
            with transaction.atomic():
                v.save(update_fields=['kautions_art', 'kautions_einbezahlt_am', 'kautions_konto'])
                from core.services.automation import buche_kaution_einzahlung
                buche_kaution_einzahlung(v, v.kautions_einbezahlt_am, user=request.user)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        except Exception as exc:
            messages.error(request, f"❌ Kautions-Einzahlung konnte nicht gebucht werden: {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        log_aktion(request, "Kaution einbezahlt (Sperrkonto)", str(v.mieter), f"CHF {v.kautions_betrag}", ziel=v)
        messages.success(request, "✅ Kautions-Einzahlung auf Sperrkonto erfasst (bilanziert).")

    elif aktion == 'versicherung':
        # Kautionsversicherung: bestätigen, sobald das Zertifikat/die Police vorliegt
        versicherer = P.get('kautions_versicherer', '').strip()
        police = P.get('kautions_policennummer', '').strip()
        zertifikat = request.FILES.get('kautions_zertifikat')
        if not versicherer:
            messages.error(request, "❌ Bitte den Versicherer/Anbieter angeben.")
            return redirect(f'/neu/vertraege/{v.id}/')
        if not zertifikat and not v.kautions_zertifikat:
            messages.error(request, "❌ Bitte das Zertifikat / die Police hochladen — erst dann kann bestätigt werden.")
            return redirect(f'/neu/vertraege/{v.id}/')
        v.kautions_art = 'versicherung'
        v.kautions_versicherer = versicherer
        v.kautions_policennummer = police
        if zertifikat:
            v.kautions_zertifikat = zertifikat
        v.kautions_einbezahlt_am = d('einbezahlt_am') or timezone.localdate()  # = Police aktiv ab
        v.kautions_konto = ''  # kein Sperrkonto bei Versicherung
        v.save(update_fields=['kautions_art', 'kautions_versicherer', 'kautions_policennummer',
                              'kautions_zertifikat', 'kautions_einbezahlt_am', 'kautions_konto'])
        log_aktion(request, "Kautionsversicherung bestätigt", str(v.mieter),
                   f"{versicherer} · Police {police} · CHF {v.kautions_betrag}", ziel=v)
        messages.success(request, f"✅ Kautionsversicherung bestätigt ({versicherer}) — Zertifikat hinterlegt.")

    elif aktion == 'rueckzahlung':
        abzug = dec('abzug_betrag')
        total = v.kautions_betrag or Decimal('0.00')
        # Nur auflösen, was bilanziert ist. Dieser Pfad und die Schlussabrechnung
        # hatten je eine EIGENE Belegtext-Sperre — jeder durfte einmal auflösen,
        # zusammen also zweimal (Audit). Der Saldo von 2010 ist die gemeinsame
        # Wahrheit und schliesst zugleich eine nie einbezahlte Kaution aus.
        if not v.ist_kautionsversicherung:
            bilanziert = _kaution_bilanziert(v)
            if bilanziert <= 0:
                messages.error(request, "❌ Für diesen Vertrag ist keine Kaution bilanziert "
                                        "(nicht einbezahlt oder bereits aufgelöst).")
                return redirect(f'/neu/vertraege/{v.id}/')
            total = min(total, bilanziert)
        # Bei Versicherung wird die Police aufgelöst — es gibt keine Rückzahlung an
        # den Mieter (er hat nur Prämien bezahlt); ein Einbehalt ist eine Schadenforderung.
        if v.ist_kautionsversicherung:
            rueck = Decimal('0.00')
        else:
            rueck = dec('rueckzahlung_betrag') if P.get('rueckzahlung_betrag') else (total - abzug)
        # Betragsvalidierung (B9): keine negativen Werte, und Rückzahlung + Einbehalt
        # dürfen die Kaution nicht übersteigen (sonst 2010/1015 mit falschem Saldo).
        if not v.ist_kautionsversicherung:
            if rueck < 0 or abzug < 0:
                messages.error(request, "❌ Rückzahlung und Einbehalt dürfen nicht negativ sein.")
                return redirect(f'/neu/vertraege/{v.id}/')
            # VOLLABDECKUNG: Rückzahlung + Einbehalt müssen die einbezahlte Kaution
            # exakt abdecken. Bei einer Unter-Allokation (rueck+abzug < total) würde
            # das Sperrkonto (1015) voll freigegeben, aber die Kautionsverbindlichkeit
            # (2010) bliebe teilweise offen stehen — das Restgeld läge unerklärt auf
            # dem Bankkonto (1020), während der Mieter buchhalterisch weiter Geld zugut
            # hätte. Die Auflösung ist ein einmaliger Vorgang, kein Tranchen-Modell.
            if abs((rueck + abzug) - total) > Decimal('0.01'):
                messages.error(request, f"❌ Rückzahlung (CHF {rueck}) + Einbehalt (CHF {abzug}) "
                                        f"müssen die einbezahlte Kaution (CHF {total}) vollständig "
                                        f"abdecken.")
                return redirect(f'/neu/vertraege/{v.id}/')
        v.kautions_zurueckbezahlt_am = d('zurueckbezahlt_am') or timezone.localdate()
        v.kautions_rueckzahlung_betrag = rueck
        v.kautions_abzug_betrag = abzug
        v.kautions_abzug_grund = P.get('abzug_grund', '').strip()
        # Statusfelder + alle Bilanz-/Ertragsbuchungen in EINER Transaktion — bricht
        # eine der (bis zu 3) Buchungen ab, wird nichts persistiert (kein Teilzustand:
        # Sperrkonto freigegeben, aber Rückzahlung fehlt). Der frühere Pfad buchte in
        # try/except: pass und liess bei Fehler den Vertrag «zurückbezahlt» ohne Hauptbuch.
        #  Sperrkonto:   1020 Bank an 1015 Sperrkonto (Freigabe des Depots)
        #  Rückzahlung:  2010 Kautionsverbindlichkeit an 1020 Bank (an Mieter)
        #  Einbehalt:    2010 Kautionsverbindlichkeit an 3600 (Ertrag Eigentümer)
        try:
            with transaction.atomic():
                v.save(update_fields=['kautions_zurueckbezahlt_am', 'kautions_rueckzahlung_betrag',
                                      'kautions_abzug_betrag', 'kautions_abzug_grund'])
                from finance.booking import buche as _buche
                from finance.models import Buchung as _B, DebitorenRechnung
                lg_k = v.einheit.liegenschaft if v.einheit_id else None
                # Vertrags-ID im Belegtext: nur so erkennt die Saldo-Prüfung
                # (_kaution_bilanziert) diese Auflösung und verhindert, dass die
                # Schlussabrechnung dieselbe Kaution ein zweites Mal freigibt.
                beleg = f"Kaution Auflösung [V{v.pk}] {v.mieter}"
                dat_k = v.kautions_zurueckbezahlt_am
                already = _B.objects.filter(beleg_text__startswith=beleg, ist_storno=False,
                                            storniert_am__isnull=True).exists()
                if v.ist_kautionsversicherung:
                    # Kein Depot → Einbehalt ist eine echte Schadenforderung an den Mieter.
                    if abzug > 0 and P.get('abzug_verrechnen') == 'on':
                        rech_e = DebitorenRechnung.objects.create(
                            vertrag=v, liegenschaft=lg_k, einheit=v.einheit,
                            betrag=abzug, datum=dat_k, faellig_am=dat_k + _timedelta(days=30),
                            status='offen', titel="Schadenersatz (Kautionsversicherung)",
                            beschreibung=v.kautions_abzug_grund or "Einbehalt aus Kaution")
                        _buche("1100", "3600", abzug, f"Schadenersatz {v.mieter}",
                               datum=dat_k, liegenschaft=lg_k, debitor=rech_e, user=request.user)
                elif (v.kautions_betrag or 0) > 0 and not already:
                    _buche("1020", "1015", v.kautions_betrag, f"{beleg} — Sperrkonto freigegeben",
                           datum=dat_k, liegenschaft=lg_k, user=request.user)
                    if rueck > 0:
                        _buche("2010", "1020", rueck, f"{beleg} — Rückzahlung an Mieter",
                               datum=dat_k, liegenschaft=lg_k, user=request.user)
                    if abzug > 0:
                        _buche("2010", "3600", abzug, f"{beleg} — Einbehalt (Ertrag)",
                               datum=dat_k, liegenschaft=lg_k, user=request.user)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        except Exception as exc:
            messages.error(request, f"❌ Kautions-Rückzahlung konnte nicht gebucht werden: {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        from core.services.automation import erledige_pendenzen_fuer
        erledige_pendenzen_fuer(v, ['Kaution'], user=request.user)
        log_aktion(request, "Kaution zurückbezahlt", str(v.mieter),
                   f"Rückzahlung CHF {rueck}, Abzug CHF {abzug}", ziel=v)
        messages.success(request, f"✅ Rückzahlung erfasst: CHF {rueck} an Mieter, CHF {abzug} einbehalten.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kaution_beleg(request, vertrag_id, art):
    """Kautions-Beleg als PDF (Art. 257e OR): `hinterlegung` = Bestätigung an die
    Mieterschaft, `freigabe` = Freigabeschreiben an die Bank. Wird in der Akte abgelegt."""
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.mietprozess_briefe import kaution_hinterlegung_pdf, kaution_freigabe_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    # Die Verwaltung des VERTRAGS, nicht die aelteste im Bestand: Ein Brief
    # traegt den Briefkopf dessen, der ihn schreibt.
    vw = v.organisation
    if art == 'freigabe':
        pdf = kaution_freigabe_pdf(v, verwaltung=vw)
        titel = f"Kaution-Freigabe (Bank) {v.mieter.nachname}"
    else:
        pdf = kaution_hinterlegung_pdf(v, verwaltung=vw)
        titel = f"Kaution-Bestätigung {v.mieter.nachname}"
    ablegen(pdf, titel, kategorie='vertrag', vertrag=v, dedup=True)
    log_aktion(request, "Kautions-Beleg erstellt", str(v.mieter), titel, ziel=v)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{titel.replace(" ", "_")}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_maengelruege(request, vertrag_id):
    """Mängelrüge / Fristansetzung (Art. 259 OR). GET: Formular · POST: PDF + Frist-Pendenz.

    Nur Schreib-Rollen: Die Rüge ist eine Erklärung der Vermieterschaft, die
    eine Frist in Gang setzt, wird in der Vertragsakte abgelegt und erzeugt
    eine Pendenz. Die Rolle «Lesend» (Treuhand/Revision) darf so etwas nicht
    auslösen."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Organisation
    from core.services.mietprozess_briefe import maengelruege_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    from datetime import timedelta
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    if request.method == 'POST':
        mangel = (request.POST.get('mangel') or '').strip()
        try:
            frist = max(1, int(request.POST.get('frist_tage') or 14))
        except ValueError:
            frist = 14
        if not mangel:
            messages.error(request, "❌ Bitte den Mangel beschreiben.")
            return redirect(f'/neu/vertraege/{v.id}/maengelruege/')
        vw = v.organisation
        pdf = maengelruege_pdf(v, mangel, frist_tage=frist, verwaltung=vw)
        ablegen(pdf, f"Mängelrüge {v.mieter.nachname} {timezone.localdate():%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=False)
        # Frist-Pendenz zur Nachkontrolle der Mängelbehebung.
        try:
            from core.models import Pendenz
            faellig = timezone.localdate() + timedelta(days=frist)
            Pendenz.objects.create(
                titel=f"Mängelbehebung prüfen — {v.einheit.bezeichnung if v.einheit_id else ''}",
                beschreibung=(mangel[:200]), vertrag=v, faellig_am=faellig, kategorie='frist')
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        log_aktion(request, "Mängelrüge erstellt", str(v.mieter), f"Frist {frist} Tage", ziel=v)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Maengelruege_{v.mieter.nachname}.pdf"'
        return resp
    return render(request, 'fw/maengelruege.html', {**basis, 'nav': 'vertraege', 'v': v})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_wg(request, vertrag_id):
    """WG-Mieter verwalten: weitere gleichberechtigte Mitmieter hinzufügen/entfernen
    und die Solidarhaftung (Art. 143 ff. OR) umschalten. Additiv zum FK-Mitmieter
    (2. Mieter/Ehegatte)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mieter
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter'), id=vertrag_id)
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    aktion = request.POST.get('aktion', '')
    if aktion == 'hinzufuegen':
        pid = request.POST.get('mieter_id')
        person = Mieter.objects.filter(id=pid).first() if (pid or '').isdigit() else None
        ausgeschlossen = {v.mieter_id, v.mitmieter_id}
        if not person:
            messages.error(request, "❌ Bitte eine bestehende Person auswählen.")
        elif person.id in ausgeschlossen:
            messages.warning(request, "Diese Person ist bereits Vertragspartei.")
        else:
            v.weitere_mieter.add(person)
            # Wohnadresse ab Mietbeginn auch für den WG-Mieter setzen.
            try:
                from crm.models import MieterAdresse
                e = v.einheit
                obj_strasse = f"{e.liegenschaft.strasse}{(', ' + e.etage) if e.etage else ''}"
                MieterAdresse.objects.get_or_create(
                    mieter=person, art='wohn', gueltig_ab=v.beginn,
                    defaults=dict(strasse=obj_strasse, plz=e.liegenschaft.plz, ort=e.liegenschaft.ort,
                                  quelle=f'vertrag:{v.id}', notiz='Einzug (WG) gemäss Mietvertrag'))
                person.sync_effektive_adresse()
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
            log_aktion(request, "WG-Mieter hinzugefügt", str(person), str(v), ziel=v)
            messages.success(request, f"✅ {person.display_name} als WG-Mieter erfasst.")
    elif aktion == 'entfernen':
        pid = request.POST.get('mieter_id')
        person = Mieter.objects.filter(id=pid).first() if (pid or '').isdigit() else None
        if person:
            v.weitere_mieter.remove(person)
            log_aktion(request, "WG-Mieter entfernt", str(person), str(v), ziel=v)
            messages.info(request, f"{person.display_name} als WG-Mieter entfernt.")
    elif aktion == 'solidarhaftung':
        v.solidarhaftung = request.POST.get('wert') == 'on'
        v.save(update_fields=['solidarhaftung'])
        messages.success(request, "Solidarhaftung aktualisiert.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_untermiete(request, vertrag_id):
    """Zustimmung/Ablehnung zur Untervermietung (Art. 262 OR). GET: Formular · POST: PDF.

    Nur Schreib-Rollen: Zustimmung oder Ablehnung sind rechtsverbindliche
    Erklärungen der Vermieterschaft und werden in der Vertragsakte abgelegt —
    nichts, was die Rolle «Lesend» abgeben können soll."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Organisation
    from core.services.mietprozess_briefe import untermiete_zustimmung_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    if request.method == 'POST':
        untermieter = (request.POST.get('untermieter') or '').strip()
        entscheid = request.POST.get('entscheid') if request.POST.get('entscheid') in ('zustimmung', 'ablehnung') else 'zustimmung'
        bedingungen = (request.POST.get('bedingungen') or '').strip()
        if not untermieter:
            messages.error(request, "❌ Bitte die untermietende Person angeben.")
            return redirect(f'/neu/vertraege/{v.id}/untermiete/')
        vw = v.organisation
        pdf = untermiete_zustimmung_pdf(v, untermieter, entscheid=entscheid, bedingungen=bedingungen, verwaltung=vw)
        wort = 'Zustimmung' if entscheid == 'zustimmung' else 'Ablehnung'
        ablegen(pdf, f"Untermiete-{wort} {v.mieter.nachname}", kategorie='vertrag', vertrag=v, dedup=False)
        log_aktion(request, f"Untermiete-{wort}", str(v.mieter), untermieter, ziel=v)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Untermiete_{v.mieter.nachname}.pdf"'
        return resp
    return render(request, 'fw/untermiete.html', {**basis, 'nav': 'vertraege', 'v': v})
