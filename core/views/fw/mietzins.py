# core/views/fw/mietzins.py
#
# Mietzins-Anpassungspotenzial aus Referenzzins und LIK, Einzel- und
# Massenanpassung, Anfangsmietzins mit amtlichem Formular.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Fachlich einer der heikelsten Bereiche ueberhaupt: Referenzzins-Schritte,
# LIK-Basis und die kantonale Formularpflicht beim Anfangsmietzins stehen im
# Skill schweizer-fachlogik unter "niemals raten oder umrechnen". Der Umzug
# aendert nichts -- Blockinhalt gegen HEAD Zeile fuer Zeile geprueft.

import logging
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTUNG, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Verwaltung
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num


# ============================================================
# ETAPPE D: MIETZINS (Anpassungspotenzial + amtliches Formular)
# ============================================================

POTENZIAL_PILL = {
    'increase': ('Erhöhung möglich', 'bg-emerald-50 text-emerald-700', 'fa-arrow-trend-up'),
    'decrease': ('Senkungsanspruch', 'bg-rose-50 text-rose-600', 'fa-arrow-trend-down'),
    'neutral':  ('Aktuell', 'bg-slate-100 text-slate-500', 'fa-equals'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mietzins(request):
    from crm.models import Verwaltung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    vw = Verwaltung.objects.first()
    curr_zins = vw.aktueller_referenzzinssatz if vw else None
    curr_lik = vw.aktueller_lik_punkte if vw else None

    # N+1 vermeiden: alle datierten Relationen vorladen, damit die Mietzins-Methoden
    # (effektive_basis / effektiver_netto_mietzins / _sollmietzins_zeile) den
    # Prefetch-Cache nutzen statt pro Vertrag zu queryen.
    qs = (Mietvertrag.objects.filter(status='aktiv')
          .select_related('mieter', 'einheit__liegenschaft')
          .prefetch_related('anpassungen', 'staffelstufen',
                            'mietzins_komponenten', 'einheit__sollmietzinse')
          .order_by('einheit__liegenschaft__strasse'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    pot_filter = request.GET.get('potenzial', '')
    # Verwaltung genau EINMAL laden (statt pro Vertrag via v.mietzinspotenzial).
    curr_zins_vw = vw.aktueller_referenzzinssatz if vw else None
    curr_lik_vw = vw.aktueller_lik_punkte if vw else None

    def _potenzial(v):
        if curr_zins_vw is None:
            return 'neutral'
        basis_zins, basis_lik = v.effektive_basis(heute)
        if curr_zins_vw < basis_zins:
            return 'decrease'
        if curr_zins_vw > basis_zins:
            return 'increase'
        if curr_lik_vw is not None and curr_lik_vw > (basis_lik + Decimal('1.5')):
            return 'increase'
        return 'neutral'

    rows = []
    n_inc = n_dec = 0
    for v in qs:
        pot = _potenzial(v)
        if pot == 'increase':
            n_inc += 1
        elif pot == 'decrease':
            n_dec += 1
        if pot_filter and pot_filter != pot:
            continue
        label, cls, icon = POTENZIAL_PILL.get(pot, POTENZIAL_PILL['neutral'])
        letzte = list(v.anpassungen.all())
        letzte_anpassung = max((a.wirksam_ab for a in letzte), default=None)
        # EFFEKTIVE Werte zeigen (wirksame Anpassungen + Staffelstufen) — nicht
        # die eingefrorene Vertragsbasis. Sonst stimmen die Zahlen hier nicht mit
        # den tatsächlich verrechneten/erfassten Mietzinsen überein.
        eff_zins, eff_lik = v.effektive_basis(heute)
        rows.append({
            'v': v, 'mieter': v.mieter.display_name,
            'objekt': f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}",
            'netto': v.effektiver_netto_mietzins(heute) or Decimal('0'),
            'basis_zins': eff_zins, 'basis_lik': eff_lik,
            'pot': pot, 'pot_label': label, 'pot_cls': cls, 'pot_icon': icon,
            'letzte_anpassung': letzte_anpassung,
            'anpassungen': len(letzte),
        })

    chips = [('', 'Alle'), ('increase', 'Erhöhung möglich'), ('decrease', 'Senkungsanspruch'), ('neutral', 'Aktuell')]
    return render(request, 'fw/mietzins.html', {
        **basis, 'nav': 'mietzins', 'rows': rows,
        'pot_filter': pot_filter, 'pot_chips': chips,
        'curr_zins': curr_zins, 'curr_lik': curr_lik,
        'n_inc': n_inc, 'n_dec': n_dec, 'anzahl': len(rows),
    })




@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mietzins_anpassung(request, vertrag_id):
    """Amtliches Mietzinsanpassungs-Formular (Art. 269d OR / Art. 19 VMWG) in der /neu/-Shell.
    GET: Berechnungs-Formular · POST action=pdf: Formular als PDF · POST action=speichern:
    Anpassung erfassen (und optional Vertragsbasis fortschreiben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from rentals.models import MietzinsAnpassung
    from rentals.services import berechne_mietpotenzial, naechster_anpassungstermin
    from core.utils import get_current_ref_zins, get_current_lik
    from core.services.mietzins_formular import generate_amtliches_formular_pdf
    from core.auth import log_aktion

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    vw = Verwaltung.objects.first()
    lg = v.einheit.liegenschaft
    eigentuemer = lg.eigentuemer

    def _dec(x, default='0'):
        try:
            return Decimal(_num(x))
        except Exception:
            return Decimal(default)

    aktuell_ref = _dec(get_current_ref_zins())
    aktuell_lik = _dec(get_current_lik())
    # Automatischer LIK-Stand (Live-Abruf → BFS-Tabelle) für die Anzeige
    from core.services.lik import aktueller_lik_wert
    _auto_stand, _auto_lik, _auto_basis = aktueller_lik_wert()
    aktuell_lik_stand = _auto_stand or (vw.aktueller_lik_stand if vw else None)
    lik_basis = _auto_basis or (vw.lik_basis if vw else 'Dezember 2020')

    if request.method == 'POST':
        aktion = request.POST.get('aktion', 'pdf')
        # Vertragsbasis (Ref-Zins/LIK, auf denen der Vertrag beruht) — editierbar,
        # damit sie bei Alt-/Importverträgen ergänzt/korrigiert werden kann. Wird
        # auf dem Vertrag gespeichert, bevor das Potenzial gerechnet wird.
        if request.POST.get('basis_zins') not in (None, ''):
            v.basis_referenzzinssatz = _dec(request.POST.get('basis_zins'), str(v.basis_referenzzinssatz or aktuell_ref))
        if request.POST.get('basis_lik') not in (None, ''):
            v.basis_lik_punkte = _dec(request.POST.get('basis_lik'), str(v.basis_lik_punkte or aktuell_lik))
        stand_raw = (request.POST.get('basis_lik_stand') or '').strip()  # 'YYYY-MM'
        if stand_raw:
            try:
                _jy, _jm = stand_raw.split('-')[:2]
                v.basis_lik_stand = date(int(_jy), int(_jm), 1)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        v.save(update_fields=['basis_referenzzinssatz', 'basis_lik_punkte', 'basis_lik_stand'])
        neu_netto = _dec(request.POST.get('neu_netto'), str(v.netto_mietzins))
        neu_zins = _dec(request.POST.get('neu_zins'), str(aktuell_ref))
        neu_lik = _dec(request.POST.get('neu_lik'), str(aktuell_lik))
        wirksam_str = request.POST.get('wirksam_ab') or ''
        try:
            wirksam_ab = date.fromisoformat(wirksam_str)
        except Exception:
            wirksam_ab = naechster_anpassungstermin(v, timezone.localdate())
        begruendung = (request.POST.get('begruendung') or '').strip()
        mit_vorbehalt = request.POST.get('mit_vorbehalt') == 'on'
        vorbehalt_text = (request.POST.get('vorbehalt_text') or '').strip()

        # Server-seitige Fristenkontrolle (Art. 269d OR): eine Mietzinserhöhung darf
        # frühestens auf den nächsten ordentlichen Kündigungstermin nach Ablauf der
        # 10-tägigen Ankündigungsfrist wirksam werden. Ein zu frühes Datum (Client
        # manipuliert / Tippfehler) würde ein rechtlich anfechtbares Formular erzeugen.
        if neu_netto > (v.netto_mietzins or Decimal('0')):
            frueh = naechster_anpassungstermin(v, timezone.localdate())
            if wirksam_ab < frueh:
                messages.error(request, f"❌ Wirksamkeitsdatum zu früh: Eine Mietzinserhöhung kann "
                                        f"frühestens auf {frueh.strftime('%d.%m.%Y')} wirksam werden "
                                        f"(Kündigungsfrist + 10-Tage-Ankündigung, Art. 269d OR).")
                return redirect(f'/neu/mietzins/{v.id}/anpassung/')

        pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik,
                                     _dec(request.POST.get('kosten_pct'), '0')) or {}
        daten = {
            'alt_netto': v.netto_mietzins, 'neu_netto': neu_netto,
            'nebenkosten': v.nebenkosten,
            'alt_zins': v.basis_referenzzinssatz, 'neu_zins': neu_zins,
            'alt_lik': v.basis_lik_punkte, 'neu_lik': neu_lik,
            'lik_basis': lik_basis,
            'alt_lik_stand': v.basis_lik_stand, 'neu_lik_stand': aktuell_lik_stand,
            'zins_pct': None, 'lik_pct': None,
            'kosten_pct': request.POST.get('kosten_pct') or None,
            'total_pct': pot.get('delta_prozent'),
            'wirksam_ab': wirksam_ab, 'begruendung': begruendung,
            'schlichtungsbehoerde': request.POST.get('schlichtungsbehoerde') or '',
            'mit_vorbehalt': mit_vorbehalt, 'vorbehalt_text': vorbehalt_text,
        }

        # Idempotent pro (Vertrag, wirksam_ab, neuer Mietzins): Mehrfaches Generieren
        # des PDF (Vorschau) darf keine Duplikate der Anpassung + Anfechtungs-Pendenz
        # erzeugen. Nur beim erstmaligen Erfassen werden Pendenz + Log geschrieben.
        anp, anp_created = MietzinsAnpassung.objects.get_or_create(
            vertrag=v, wirksam_ab=wirksam_ab, neuer_netto_mietzins=neu_netto,
            defaults={
                'alter_netto_mietzins': v.netto_mietzins,
                'alter_referenzzinssatz': v.basis_referenzzinssatz, 'neuer_referenzzinssatz': neu_zins,
                'alter_lik_index': v.basis_lik_punkte, 'neuer_lik_index': neu_lik,
                'erhoehung_prozent_total': pot.get('delta_prozent'),
                'begruendung': begruendung or 'Anpassung an Referenzzinssatz und Teuerung',
            })
        # Die Objekt-Sollmietzins-Zeile (gültig ab = wirksam_ab) wird jetzt zentral
        # in MietzinsAnpassung.save() geführt — über ALLE Erfassungswege. Hier kein
        # separater Aufruf mehr nötig.
        if anp_created:
            log_aktion(request, "Mietzinsanpassung erstellt", str(v),
                       f"neu CHF {neu_netto}, wirksam {wirksam_ab}", ziel=v)

        # Anfechtungsfrist-Pendenz bei einer Erhöhung: der Mieter kann die
        # Mietzinserhöhung innert 30 Tagen ab Empfang anfechten (Art. 270b OR).
        if anp_created and neu_netto > (v.netto_mietzins or Decimal('0')):
            from core.models import Pendenz
            frist = timezone.localdate() + _timedelta(days=30)
            Pendenz.objects.create(
                titel=f"Anfechtungsfrist Mietzinserhöhung läuft ab – {v.mieter.display_name}",
                beschreibung=(f"Erhöhung auf CHF {neu_netto} (wirksam {wirksam_ab:%d.%m.%Y}). Der Mieter kann "
                              "sie innert 30 Tagen ab Empfang des amtlichen Formulars bei der "
                              "Schlichtungsbehörde anfechten (Art. 270b OR)."),
                kategorie='frist', faellig_am=frist, vertrag=v,
                liegenschaft=lg,
                erstellt_von=request.user if request.user.is_authenticated else None,
            )

        if aktion == 'speichern':
            messages.success(request, f"✅ Mietzinsanpassung erfasst — neu CHF {neu_netto} ab {wirksam_ab.strftime('%d.%m.%Y')}.")
            return redirect(f'/neu/vertraege/{v.id}/')

        # Kanton mit eingebautem Original (SO/ZH/BE/…) → Original ausfüllen;
        # sonst kantonsabhängige Nachbildung mit korrektem Schlichtungsblock.
        from core.services.formular_fill import fill_mietzins
        pdf = None
        if request.POST.get('formular') != 'generisch':
            pdf = fill_mietzins(v, daten, verwaltung=vw)
        if pdf is None:
            from core.services.amtliche_formulare_so import mietzins_so_pdf
            pdf = mietzins_so_pdf(v, daten, verwaltung=vw)
        from core.services.ablage import ablegen
        ablegen(pdf, f"Mietzinsanpassung wirksam {wirksam_ab:%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=True)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Mietzinsanpassung_{v.mieter.nachname}.pdf"'
        return resp

    # --- GET: Vorschlag berechnen ---
    pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik, Decimal('0.00')) or {}
    vorschlag_netto = pot.get('neu_chf', v.netto_mietzins)
    naechster_termin = naechster_anpassungstermin(v, timezone.localdate())

    # Indexmiete (Art. 269b): die amtliche Index-Mitteilung (Art. 269d) wird direkt
    # aus der LIK-Entwicklung vorbefüllt — neuer Nettomietzins + fertige Begründung.
    index_vorschlag = None
    if v.mietzins_modell == 'index':
        from core.services.mietrecht import index_anpassung_vorschlag
        index_vorschlag = index_anpassung_vorschlag(v, aktuell_lik)
        if index_vorschlag:
            vorschlag_netto = index_vorschlag['neu_netto']

    # Basis-Vorbelegung: fehlt sie am Vertrag (Alt-/Importvertrag), aktuelle
    # Marktwerte vorschlagen, damit der Sachbearbeiter sie ergänzen kann.
    basis_zins = v.basis_referenzzinssatz if (v.basis_referenzzinssatz or 0) > 0 else aktuell_ref
    basis_lik = v.basis_lik_punkte if (v.basis_lik_punkte or 0) > 0 else aktuell_lik
    return render(request, 'fw/mietzins_anpassung.html', {
        **basis, 'nav': 'mietzins', 'v': v, 'lg': lg,
        'alt_netto': v.netto_mietzins,
        'alt_zins': basis_zins, 'alt_lik': basis_lik,
        'basis_fehlt': not ((v.basis_referenzzinssatz or 0) > 0 and (v.basis_lik_punkte or 0) > 0),
        'aktuell_ref': aktuell_ref, 'aktuell_lik': aktuell_lik,
        'lik_basis': lik_basis,
        'alt_lik_stand': v.basis_lik_stand, 'aktuell_lik_stand': aktuell_lik_stand,
        'vorschlag_netto': vorschlag_netto, 'naechster_termin': naechster_termin,
        'pot': pot, 'index_vorschlag': index_vorschlag,
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mietzins_massenanpassung(request):
    """Mietzins-Massenanpassung nach Referenzzins-/LIK-Änderung: für die in der
    Mietzins-Liste angehakten Verträge wird das Potenzial berechnet (Vorschau) und
    per Bestätigung je Vertrag eine MietzinsAnpassung + amtliches Formular erzeugt
    (Sammel-PDF). Fristen nach Art. 269d OR werden je Vertrag einzeln bestimmt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from rentals.models import MietzinsAnpassung
    from rentals.services import berechne_mietpotenzial, naechster_anpassungstermin
    from core.utils import get_current_ref_zins, get_current_lik
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_mietzins')
    basis = _global_filter(request)
    vw = Verwaltung.objects.first()

    def _dec(x, default='0'):
        try:
            return Decimal(_num(x))
        except Exception:
            return Decimal(default)

    aktuell_ref = _dec(get_current_ref_zins())
    aktuell_lik = _dec(get_current_lik())
    from core.services.lik import aktueller_lik_wert
    _auto_stand, _auto_lik, _auto_basis = aktueller_lik_wert()
    aktuell_lik_stand = _auto_stand or (vw.aktueller_lik_stand if vw else None)
    lik_basis = _auto_basis or (vw.lik_basis if vw else 'Dezember 2020')

    ids = request.POST.getlist('vertrag_id')
    vertraege = list(Mietvertrag.objects.filter(id__in=ids, status='aktiv')
                     .select_related('mieter', 'einheit__liegenschaft'))
    if not vertraege:
        messages.error(request, "Keine Verträge ausgewählt.")
        return redirect('fw_mietzins')

    heute = timezone.localdate()
    rows = []
    for v in vertraege:
        pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik) or {}
        neu_netto = pot.get('neu_chf')
        termin = naechster_anpassungstermin(v, heute)
        delta = (neu_netto - (v.netto_mietzins or Decimal('0'))) if neu_netto is not None else None
        rows.append({
            'v': v, 'pot': pot, 'neu_netto': neu_netto, 'termin': termin,
            'delta': delta,
            'basis_fehlt': not ((v.basis_referenzzinssatz or 0) > 0 and (v.basis_lik_punkte or 0) > 0),
            'unveraendert': (delta is not None and delta == 0),
        })

    aktion = request.POST.get('aktion', 'vorschau')
    if aktion != 'ausfuehren':
        machbar = [r for r in rows if not r['basis_fehlt'] and r['neu_netto'] is not None and r['delta']]
        return render(request, 'fw/mietzins_massen.html', {
            **basis, 'nav': 'mietzins', 'rows': rows, 'machbar': len(machbar),
            'aktuell_ref': aktuell_ref, 'aktuell_lik': aktuell_lik,
        })

    # --- Ausführen: je Vertrag Anpassung erfassen + amtliches Formular, dann Sammel-PDF ---
    from core.services.formular_fill import fill_mietzins
    from core.services.amtliche_formulare_so import mietzins_so_pdf
    from core.services.ablage import ablegen
    from core.models import Pendenz
    import io as _io
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    erfasst = uebersprungen = 0
    for r in rows:
        v = r['v']
        if r['basis_fehlt'] or r['neu_netto'] is None or not r['delta']:
            uebersprungen += 1
            continue
        neu_netto = r['neu_netto']
        wirksam_ab = r['termin']
        pot = r['pot']
        anp, anp_created = MietzinsAnpassung.objects.get_or_create(
            vertrag=v, wirksam_ab=wirksam_ab, neuer_netto_mietzins=neu_netto,
            defaults={
                'alter_netto_mietzins': v.netto_mietzins,
                'alter_referenzzinssatz': v.basis_referenzzinssatz, 'neuer_referenzzinssatz': aktuell_ref,
                'alter_lik_index': v.basis_lik_punkte, 'neuer_lik_index': aktuell_lik,
                'erhoehung_prozent_total': pot.get('delta_prozent'),
                'begruendung': 'Anpassung an Referenzzinssatz und Teuerung (Massenanpassung)',
            })
        if anp_created:
            log_aktion(request, "Mietzinsanpassung erstellt (Massenlauf)", str(v),
                       f"neu CHF {neu_netto}, wirksam {wirksam_ab}", ziel=v)
            if neu_netto > (v.netto_mietzins or Decimal('0')):
                Pendenz.objects.create(
                    titel=f"Anfechtungsfrist Mietzinserhöhung läuft ab – {v.mieter.display_name}",
                    beschreibung=(f"Erhöhung auf CHF {neu_netto} (wirksam {wirksam_ab:%d.%m.%Y}). Der Mieter kann "
                                  "sie innert 30 Tagen ab Empfang des amtlichen Formulars bei der "
                                  "Schlichtungsbehörde anfechten (Art. 270b OR)."),
                    kategorie='frist', faellig_am=heute + _timedelta(days=30), vertrag=v,
                    liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                    erstellt_von=request.user if request.user.is_authenticated else None,
                )
        daten = {
            'alt_netto': v.netto_mietzins, 'neu_netto': neu_netto,
            'nebenkosten': v.nebenkosten,
            'alt_zins': v.basis_referenzzinssatz, 'neu_zins': aktuell_ref,
            'alt_lik': v.basis_lik_punkte, 'neu_lik': aktuell_lik,
            'lik_basis': lik_basis,
            'alt_lik_stand': v.basis_lik_stand, 'neu_lik_stand': aktuell_lik_stand,
            'zins_pct': None, 'lik_pct': None, 'kosten_pct': None,
            'total_pct': pot.get('delta_prozent'),
            'wirksam_ab': wirksam_ab,
            'begruendung': 'Anpassung an Referenzzinssatz und Teuerung',
            'schlichtungsbehoerde': '', 'mit_vorbehalt': False, 'vorbehalt_text': '',
        }
        pdf = fill_mietzins(v, daten, verwaltung=vw)
        if pdf is None:
            pdf = mietzins_so_pdf(v, daten, verwaltung=vw)
        ablegen(pdf, f"Mietzinsanpassung wirksam {wirksam_ab:%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=True)
        try:
            for page in PdfReader(_io.BytesIO(pdf)).pages:
                writer.add_page(page)
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        erfasst += 1

    if not erfasst:
        messages.error(request, "Keine Anpassung möglich (Basisdaten fehlen oder kein Potenzial).")
        return redirect('fw_mietzins')

    log_aktion(request, "Mietzins-Massenanpassung", f"{erfasst} Verträge",
               f"Ref {aktuell_ref}% · LIK {aktuell_lik}")
    out = _io.BytesIO()
    writer.write(out)
    resp = HttpResponse(out.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="Mietzinsanpassungen_Sammel.pdf"'
    return resp


def _vormiete_fuer(vertrag):
    """Letzter beendeter Vertrag desselben Objekts (für die Vormiete-Angabe)."""
    if not vertrag.einheit_id:
        return None
    return (Mietvertrag.objects.filter(einheit=vertrag.einheit).exclude(id=vertrag.id)
            .filter(beginn__lt=vertrag.beginn or timezone.localdate())
            .order_by('-beginn').first())


def anfangsmietzins_auto_ablegen(vertrag, verwaltung=None):
    """Erzeugt bei Vertrags-Aktivierung automatisch das amtliche Anfangsmietzins-
    Formular (Art. 270 Abs. 2 OR) und legt es in der Akte ab — aber NUR wenn im
    Kanton der Liegenschaft Formularpflicht besteht und es sich um Wohnraum handelt
    (kein Gewerbe, kein Einstellplatz). So steht das Formular spätestens zur
    Schlüsselübergabe bereit (30-Tage-Anfechtungsfrist ab Erhalt). Vormiete wird
    aus dem letzten beendeten Vertrag gezogen, sonst «unbekannt» (Art. 270 zulässig).
    Gibt (True, pflicht) bei Erzeugung zurück, sonst (False, grund)."""
    from crm.models import Verwaltung
    from core.services.formular_fill import fill_anfangsmietzins
    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
    from core.services.ablage import ablegen
    einheit = vertrag.einheit
    if not einheit:
        return False, 'kein_objekt'
    if getattr(einheit, 'mietrecht_kategorie', '') == 'gewerbe' or getattr(einheit, 'ist_einstellplatz', False):
        return False, 'kein_wohnraum'
    pflicht, info = formularpflicht_fuer_liegenschaft(einheit.liegenschaft)
    if pflicht not in ('ja', 'teilweise'):
        return False, 'keine_pflicht'
    # Anfangsmiete aus der datierten Sollmietzins-Tabelle zum Vertragsbeginn.
    soll = einheit.aktueller_sollmietzins(vertrag.beginn)
    anf_netto = (soll.netto_mietzins if soll else vertrag.netto_mietzins) or Decimal('0')
    anf_nk = (soll.nebenkosten if soll else vertrag.nebenkosten) or Decimal('0')
    vor = _vormiete_fuer(vertrag)
    vor_soll = vor.einheit.aktueller_sollmietzins(vor.beginn) if (vor and vor.einheit_id) else None
    from core.services.lik import LIK_BASIS
    _bq = vor or vertrag  # Berechnungsgrundlagen: Vorvertrag, sonst aktueller Vertrag
    daten = {
        'anfang_netto': anf_netto,
        'anfang_nk': anf_nk,
        'vormiete_netto': ((vor_soll.netto_mietzins if vor_soll else (vor.netto_mietzins if vor else 0)) or Decimal('0')),
        'vormiete_nk': ((vor_soll.nebenkosten if vor_soll else (vor.nebenkosten if vor else 0)) or Decimal('0')),
        'beginn': vertrag.beginn,
        'grund_choice': 'unbekannt' if not vor else 'anpassung',
        'begruendung': '',
        'basis_ref': _bq.basis_referenzzinssatz,
        'basis_lik': _bq.basis_lik_punkte,
        'basis_lik_basis': LIK_BASIS,
        'pflicht_info': info,
    }
    vw = verwaltung or (einheit.liegenschaft.verwaltung if einheit.liegenschaft else None) or Verwaltung.objects.first()
    pdf = fill_anfangsmietzins(vertrag, daten, verwaltung=vw)
    ablegen(pdf, f"Anfangsmietzins-Formular {vertrag.beginn:%d.%m.%Y}" if vertrag.beginn else "Anfangsmietzins-Formular",
            kategorie='vertrag', vertrag=vertrag, dedup=True)
    return True, pflicht


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_anfangsmietzins(request, vertrag_id):
    """Amtliches Formular zur Mitteilung des Anfangsmietzinses (Art. 270 OR /
    Art. 19 VMWG) — bei Neuabschluss dem neuen Mieter mit Angabe der Vormiete und
    Hinweis auf das 30-Tage-Anfechtungsrecht zuzustellen. GET: Formular · POST: PDF."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.formular_fill import fill_anfangsmietzins, hat_original
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    vw = Verwaltung.objects.first()
    lg = v.einheit.liegenschaft

    def _dec(x, d='0'):
        try:
            return Decimal(_num(x) or d)
        except Exception:
            return Decimal(d)

    # Anfangsmiete aus der datierten Sollmietzins-Tabelle («Mietzins gültig ab»)
    # zum Vertragsbeginn ziehen — Fallback auf die Vertrags-/Objektwerte.
    soll = v.einheit.aktueller_sollmietzins(v.beginn) if v.einheit_id else None
    soll_netto = soll.netto_mietzins if soll else (v.netto_mietzins or Decimal('0'))
    soll_nk = soll.nebenkosten if soll else (v.nebenkosten or Decimal('0'))

    # Vormiete-Vorschlag: letzter beendeter Vertrag desselben Objekts (Sollmietzins
    # per dessen Beginn, sonst dessen Vertragswerte).
    vormiete = _vormiete_fuer(v)
    if vormiete and vormiete.einheit_id:
        vsoll = vormiete.einheit.aktueller_sollmietzins(vormiete.beginn)
        vor_netto = vsoll.netto_mietzins if vsoll else (vormiete.netto_mietzins or Decimal('0'))
        vor_nk = vsoll.nebenkosten if vsoll else (vormiete.nebenkosten or Decimal('0'))
    else:
        vor_netto = vor_nk = ''

    # Berechnungsgrundlagen: Referenzzinssatz + LIK-Punkte + LIK-Basis. Quelle =
    # Vorvertrag (falls vorhanden), sonst der aktuelle Vertrag (immer gesetzt).
    from core.services.lik import LIK_BASIS
    _bq = vormiete or v
    basis_ref = _bq.basis_referenzzinssatz
    basis_lik = _bq.basis_lik_punkte
    basis_lik_basis = LIK_BASIS

    if request.method == 'POST':
        daten = {
            'anfang_netto': _dec(request.POST.get('anfang_netto'), str(soll_netto or 0)),
            'anfang_nk': _dec(request.POST.get('anfang_nk'), str(soll_nk or 0)),
            'vormiete_netto': _dec(request.POST.get('vormiete_netto')),
            'vormiete_nk': _dec(request.POST.get('vormiete_nk')),
            'beginn': v.beginn,
            'grund_choice': request.POST.get('grund_choice') or 'anpassung',
            'begruendung': (request.POST.get('begruendung') or '').strip(),
            'basis_ref': (request.POST.get('basis_ref') or basis_ref or ''),
            'basis_lik': (request.POST.get('basis_lik') or basis_lik or ''),
            'basis_lik_basis': (request.POST.get('basis_lik_basis') or basis_lik_basis or ''),
            'vorbehalte': (request.POST.get('vorbehalte') or '').strip(),
        }
        from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
        _pflicht, pflicht_info = formularpflicht_fuer_liegenschaft(lg)
        daten['pflicht_info'] = pflicht_info
        # Immer das Original-Formular des Kantons, wenn hinterlegt — sonst
        # kanton-adaptives Fallback-Formular.
        pdf = fill_anfangsmietzins(v, daten, verwaltung=vw)
        ablegen(pdf, f"Anfangsmietzins-Formular {v.beginn:%d.%m.%Y}" if v.beginn else "Anfangsmietzins-Formular",
                kategorie='vertrag', vertrag=v, dedup=True)
        log_aktion(request, "Anfangsmietzins-Formular erstellt", str(v),
                   f"Anfangsmiete CHF {daten['anfang_netto']}", ziel=v)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Anfangsmietzins_{v.mieter.nachname}.pdf"'
        return resp

    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft, pflicht_label
    from core.services.kantone import kanton_fuer_liegenschaft
    pflicht, pflicht_info = formularpflicht_fuer_liegenschaft(lg)
    return render(request, 'fw/anfangsmietzins.html', {
        **basis, 'nav': 'mietzins', 'v': v, 'lg': lg,
        'anfang_netto': soll_netto, 'anfang_nk': soll_nk,
        'soll': soll,
        'vormiete': vormiete,
        'vormiete_netto': vor_netto,
        'vormiete_nk': vor_nk,
        'pflicht': pflicht, 'pflicht_info': pflicht_info,
        'pflicht_label': pflicht_label(pflicht),
        'hat_original': hat_original(kanton_fuer_liegenschaft(lg), 'anfangsmietzins'),
        'basis_ref': basis_ref, 'basis_lik': basis_lik, 'basis_lik_basis': basis_lik_basis,
    })
