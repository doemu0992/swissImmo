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
from django.utils.translation import gettext, gettext_lazy
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Organisation
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num
from core.tenancy import aktuelle_organisation


# ============================================================
# ETAPPE D: MIETZINS (Anpassungspotenzial + amtliches Formular)
# ============================================================

POTENZIAL_PILL = {
    'increase': (gettext_lazy('Erhöhung möglich'), 'fw-gut-flaeche fw-gut', 'trend'),
    'decrease': (gettext_lazy('Senkungsanspruch'), 'fw-krit-flaeche fw-kritisch', 'zurueck'),
    'neutral':  (gettext_lazy('Aktuell'), 'fw-flaeche2 fw-mutet', 'bericht'),
    # Index- und Staffelmieten haben kein Referenzzins-Potenzial (Befund D):
    # Ihr Mietzins folgt dem Index bzw. den vereinbarten Stufen.
    'index':    (gettext_lazy('Indexmiete — einzeln'), 'fw-flaeche2 fw-mutet', 'trend'),
    'staffel':  (gettext_lazy('Staffelmiete'), 'fw-flaeche2 fw-mutet', 'bericht'),
}

#: Mietzinsmodelle, die die Massenanpassung nach Referenzzins/LIK nicht erfasst
#: (Art. 269b/269c OR). Eine Indexanpassung geht einzeln über den Assistenten.
MODELLE_OHNE_MASSENLAUF = ('index', 'staffel')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mietzins(request):
    from crm.models import Organisation
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    vw = aktuelle_organisation()
    curr_zins = vw.aktueller_referenzzinssatz if vw else None
    curr_lik = vw.aktueller_lik_punkte if vw else None

    # MIET-14: Ist die LIK-Tabelle mehr als drei Monate hinter dem Kalender, steht hier ein Hinweis
    # (statt dass Anpassungen stillschweigend unterbleiben).
    from core.services.lik import tabelle_hinweis
    _lik_hinweis = tabelle_hinweis(heute)
    if _lik_hinweis and request.method == 'GET':
        from django.contrib import messages
        messages.warning(request, '⚠️ ' + _lik_hinweis)

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
        if v.mietzins_modell in MODELLE_OHNE_MASSENLAUF:
            return v.mietzins_modell
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
        # Nur gebuchte Anpassungen: Ein Entwurf aus dem Assistenten oder dem
        # Massenlauf ist keine «letzte Anpassung» — er steht unten bei den
        # offenen Entwürfen. Python-Filter, damit der Prefetch greift.
        letzte = [a for a in v.anpassungen.all() if a.ist_gebucht]
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
            'massenlauf': v.mietzins_modell not in MODELLE_OHNE_MASSENLAUF,
        })

    # Offene Entwürfe (meist aus der Massenanpassung): Sie buchen erst, wenn sie
    # als versandt erfasst sind — hier gesammelt, damit keiner liegen bleibt.
    from rentals.models import MietzinsAnpassung
    entwuerfe = (MietzinsAnpassung.objects.filter(status=MietzinsAnpassung.STATUS_ENTWURF)
                 .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
                 .order_by('wirksam_ab', 'id'))
    if aktive_lg:
        entwuerfe = entwuerfe.filter(vertrag__einheit__liegenschaft=aktive_lg)

    chips = [('', 'Alle'), ('increase', 'Erhöhung möglich'), ('decrease', 'Senkungsanspruch'), ('neutral', 'Aktuell')]
    return render(request, 'fw/mietzins.html', {
        **basis, 'nav': 'mietzins', 'rows': rows, 'entwuerfe': list(entwuerfe),
        'heute_iso': heute.isoformat(),
        'pot_filter': pot_filter, 'pot_chips': chips,
        'curr_zins': curr_zins, 'curr_lik': curr_lik,
        'n_inc': n_inc, 'n_dec': n_dec, 'anzahl': len(rows),
    })




def _dec(x, default='0'):
    """Dezimalwert aus einem Formularfeld; `default` bei leer/unlesbar."""
    try:
        return Decimal(_num(x))
    except Exception:
        return Decimal(default)


def _dec_oder_none(x):
    """Wie `_dec`, aber None bei leerem Feld — «nicht erfasst» ist nicht 0."""
    if x in (None, ''):
        return None
    try:
        return Decimal(_num(x))
    except Exception:
        return None


def _datum(x):
    try:
        return date.fromisoformat(x) if x else None
    except ValueError:
        return None


def _marktstand(vw):
    """(Referenzzins, LIK, LIK-Stand, LIK-Basis) der Verwaltung — an ihm wird die
    Anpassung nach OR 269a begründet."""
    from core.utils import get_current_ref_zins, get_current_lik
    from core.services.lik import aktueller_lik_wert
    aktuell_ref = _dec(get_current_ref_zins(vw))
    aktuell_lik = _dec(get_current_lik(vw))
    _auto_stand, _auto_lik, _auto_basis = aktueller_lik_wert()
    stand = _auto_stand or (vw.aktueller_lik_stand if vw else None)
    lik_basis = _auto_basis or (vw.lik_basis if vw else 'Dezember 2020')
    return aktuell_ref, aktuell_lik, stand, lik_basis


def _vorbehalt_satz(anp):
    """Der bezifferte Vorbehalt als Satz für das Formular (Rechtstext: deutsch)."""
    teile = []
    if anp.vorbehalt_betrag is not None:
        teile.append(f"CHF {anp.vorbehalt_betrag:.2f}")
    if anp.vorbehalt_prozent is not None:
        teile.append(f"{anp.vorbehalt_prozent:.2f} %")
    if not teile:
        return ''
    satz = 'Vorbehalten bleibt eine nicht ausgeschöpfte Erhöhung von ' + ' bzw. '.join(teile)
    if (anp.vorbehalt_text or '').strip():
        satz += f" ({anp.vorbehalt_text.strip()})"
    return satz + '.'


def _formular_daten(v, anp, lik_basis):
    """Die Felder des amtlichen Formulars aus der (Entwurfs-)Anpassung.

    «Bisher» kommt aus der Anpassung selbst (`alter_*`) — dort steht der
    effektive Stand vor dem Wirksamwerden, nicht das Ursprungsfeld des Vertrags
    (Befund A). Der LIK-Stand «bisher» ist der der letzten gebuchten Anpassung.
    """
    stichtag = anp.wirksam_ab - _timedelta(days=1)
    # E1 (NK-Wizard): Wird mit der Anpassung ein neues Akonto mitgeteilt, steht es in der Spalte
    # «neu»; «bisher» bleibt das bisherige. Ohne Akonto-Änderung sind beide Spalten wie bis anhin.
    nk_neu = anp.neue_nebenkosten if anp.neue_nebenkosten is not None else v.effektive_nebenkosten(anp.wirksam_ab)
    nk_alt = anp.alte_nebenkosten if anp.neue_nebenkosten is not None and anp.alte_nebenkosten is not None else nk_neu
    daten = {
        'alt_netto': anp.alter_netto_mietzins, 'neu_netto': anp.neuer_netto_mietzins,
        'nebenkosten': nk_neu, 'alt_nebenkosten': nk_alt,
        'alt_zins': anp.alter_referenzzinssatz, 'neu_zins': anp.neuer_referenzzinssatz,
        'alt_lik': anp.alter_lik_index, 'neu_lik': anp.neuer_lik_index,
        'lik_basis': lik_basis,
        'alt_lik_stand': v.effektiver_lik_stand(stichtag), 'neu_lik_stand': anp.neuer_lik_stand,
        'zins_pct': anp.zins_prozent, 'lik_pct': anp.lik_prozent,
        'kosten_pct': anp.kosten_prozent, 'total_pct': anp.erhoehung_prozent_total,
        'wirksam_ab': anp.wirksam_ab, 'begruendung': anp.begruendung or '',
        'schlichtungsbehoerde': anp.schlichtungsbehoerde or '',
        'mit_vorbehalt': anp.vorbehalt_betrag is not None or anp.vorbehalt_prozent is not None,
        'vorbehalt_text': _vorbehalt_satz(anp),
    }
    if v.mietzins_modell == 'index':
        # Indexmiete (Art. 269b OR): Der einzige Grund ist der LIK mit der vollen
        # Weitergabe. Die Füller der Kantonsformulare schreiben zu einer LIK-Änderung
        # «40 % anrechenbar» (Teuerungsausgleich im Sinne von Art. 269a lit. e OR) und
        # zu Referenzzins und Kostensteigerung eigene Gründe — alles falsch für den
        # Index. Ohne diese Werte steht nur die Begründung der Anpassung im Formular.
        daten.update(alt_zins=None, neu_zins=None, alt_lik=None, neu_lik=None,
                     zins_pct=None, lik_pct=None, kosten_pct=None)
    return daten


def _formular_pdf(v, anp, vw, lik_basis, formular):
    """Das amtliche Formular — Kantonsoriginal, sonst die Nachbildung MIT Wasserzeichen."""
    from core.services.formular_fill import fill_mietzins, mit_wasserzeichen
    daten = _formular_daten(v, anp, lik_basis)
    if formular['original']:
        pdf = fill_mietzins(v, daten, verwaltung=vw, kanton=formular['kanton'])
        if pdf is not None:
            return pdf
    from core.services.amtliche_formulare_so import mietzins_so_pdf
    return mit_wasserzeichen(mietzins_so_pdf(v, daten, verwaltung=vw))


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mietzins_anpassung(request, vertrag_id):
    """Amtliche Mietzinsanpassung (Art. 269d OR / Art. 19 VMWG) als Assistent.

    GET: Grundlagen → Vorbehalt → Termin & Zustellung → Prüfen & Formular,
    vorbefüllt aus dem offenen Entwurf oder aus dem Vorschlag.

    POST `aktion`:
      `entwurf`   — Entwurf anlegen/fortschreiben. Bucht NICHTS.
      `pdf`       — wie `entwurf`, dazu das Formular als PDF. Bucht NICHTS und
                    legt nichts ab: Eine Vorschau ist kein Versand (Befund C).
      `versandt`  — Entwurf fortschreiben und als versandt erfassen: bucht
                    (`core.services.mietzinsanpassung.versand_erfassen`).
      `speichern` — Altname aus der Fassung vor dem Assistenten = `entwurf`.
    """
    from django.contrib import messages
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from core.auth import log_aktion
    from core.services import index_anpassung as idx
    from core.services import mietzinsanpassung as ablauf
    from core.services.formular_status import formular_status, kanton_fehlt_meldung
    from core.services.mietzins_rechner import kostensteigerung_pauschal_pct
    from rentals.models import MietzinsAnpassung
    from rentals.services import (TERMINE_FEHLEN, ZUSTELL_PUFFER_TAGE, berechne_mietpotenzial,
                                  bisheriger_stand, kuendigungstermine_fuer,
                                  naechster_anpassungstermin)

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    # Die Mietzinsanpassung wird gegen den Stand DIESER Verwaltung
    # begruendet (OR 269a) und traegt ihren Briefkopf.
    vw = v.organisation
    lg = v.einheit.liegenschaft
    heute = timezone.localdate()
    aktuell_ref, aktuell_lik, aktuell_lik_stand, lik_basis = _marktstand(vw)
    formular = formular_status(lg, 'mietzins')
    zurueck = f'/neu/mietzins/{v.id}/anpassung/'

    if request.method == 'POST':
        P = request.POST
        aktion = P.get('aktion', 'pdf')
        if aktion == 'speichern':
            aktion = 'entwurf'
        if aktion not in ('entwurf', 'pdf', 'versandt'):
            messages.error(request, gettext('Unbekannte Aktion.'))
            return redirect(zurueck)

        # Der Entwurf, an dem weitergearbeitet wird — über `objects` UND den
        # Vertrag gesucht, also nie der Entwurf eines fremden Vertrags.
        entwurf = None
        if P.get('entwurf'):
            entwurf = MietzinsAnpassung.objects.filter(
                vertrag=v, pk=P.get('entwurf'), status=MietzinsAnpassung.STATUS_ENTWURF).first()
            if entwurf is None:
                messages.error(request, gettext('Dieser Entwurf ist nicht mehr offen.'))
                return redirect(zurueck)

        # Vertragsbasis (Ref-Zins/LIK, auf denen der Vertrag beruht) — editierbar,
        # damit sie bei Alt-/Importverträgen ergänzt/korrigiert werden kann.
        if P.get('basis_zins') not in (None, ''):
            v.basis_referenzzinssatz = _dec(P.get('basis_zins'), str(v.basis_referenzzinssatz or aktuell_ref))
        if P.get('basis_lik') not in (None, ''):
            v.basis_lik_punkte = _dec(P.get('basis_lik'), str(v.basis_lik_punkte or aktuell_lik))
        stand_raw = (P.get('basis_lik_stand') or '').strip()  # 'YYYY-MM'
        if stand_raw:
            try:
                _jy, _jm = stand_raw.split('-')[:2]
                v.basis_lik_stand = date(int(_jy), int(_jm), 1)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        v.save(update_fields=['basis_referenzzinssatz', 'basis_lik_punkte', 'basis_lik_stand'])

        index_modus = v.mietzins_modell == 'index'
        if index_modus:
            # Art. 17 Abs. 3 VMWG: 30 Tage auf ein Monatsende, nicht die 10 Tage des Art. 269d OR.
            wirksam_ab = _datum(P.get('wirksam_ab')) or idx.frueheste_wirksamkeit(heute)
        else:
            wirksam_ab = _datum(P.get('wirksam_ab')) or naechster_anpassungstermin(v, heute)
        alt_netto, alt_zins, alt_lik = bisheriger_stand(v, wirksam_ab)
        neu_netto = _dec(P.get('neu_netto'), str(alt_netto))
        # E1 (NK-Wizard): neues Nebenkosten-Akonto, leer = bleibt.
        neu_nk = _dec_oder_none(P.get('neu_nk'))
        if neu_nk is not None and neu_nk < 0:
            messages.error(request, gettext('Das Nebenkosten-Akonto kann nicht negativ sein.'))
            return redirect(zurueck)
        alt_nk = v.effektive_nebenkosten(wirksam_ab - _timedelta(days=1)) if neu_nk is not None else None
        neu_zins = _dec(P.get('neu_zins'), str(aktuell_ref))
        neu_lik = _dec(P.get('neu_lik'), str(aktuell_lik))
        kosten_pct = _dec(P.get('kosten_pct'), '0')

        # Server-seitige Fristenkontrolle (Art. 269d OR): eine Mietzinserhöhung darf
        # frühestens auf den nächsten ordentlichen Kündigungstermin nach Ablauf der
        # 10-tägigen Ankündigungsfrist wirksam werden — gemessen an einem Versand
        # HEUTE. Beim Versand prüft `versand_erfassen` mit dem echten Datum nach.
        # Verglichen wird mit dem EFFEKTIVEN bisherigen Mietzins (Befund A).
        if index_modus:
            # Indexmiete: LIK veröffentlicht, Höchstbetrag, Termin — alles serverseitig.
            # Entwurf und PDF gelten als Versand HEUTE; beim Versand prüft
            # `versand_erfassen` mit dem echten Datum nach.
            stand = idx.stand_aus_text(P.get('lik_stand'))
            versand = (_datum(P.get('versand_am')) or heute) if aktion == 'versandt' else heute
            zugang = _datum(P.get('zugang_am')) if aktion == 'versandt' else None
            meldungen = idx.pruefe(v, heute=heute, stand=stand, wirksam_ab=wirksam_ab, neu_netto=neu_netto,
                                   versand_am=versand, zugang_am=zugang)
            if neu_netto == (alt_netto or Decimal('0')) and (neu_nk is None or neu_nk == alt_nk):
                meldungen.append(gettext('Der Nettomietzins bleibt unverändert — es gibt nichts mitzuteilen.'))
            if neu_nk is not None and alt_nk is not None and neu_nk > alt_nk:
                frueh_nk = naechster_anpassungstermin(v, heute)
                if wirksam_ab < frueh_nk:
                    meldungen.append(gettext(
                        'Das höhere Nebenkosten-Akonto folgt nicht dem Index: Es kann frühestens auf %(datum)s '
                        'wirksam werden (Kündigungsfrist + 10 Tage, Art. 269d OR).') % {
                            'datum': frueh_nk.strftime('%d.%m.%Y')})
            if meldungen:
                for meldung in meldungen:
                    messages.error(request, '❌ ' + meldung)
                return redirect(zurueck)
        elif neu_netto > (alt_netto or Decimal('0')) or (neu_nk is not None and neu_nk > alt_nk):
            frueh = naechster_anpassungstermin(v, heute)
            if wirksam_ab < frueh:
                messages.error(request, '❌ ' + gettext(
                    'Wirksamkeitsdatum zu früh: Eine Mietzinserhöhung kann frühestens auf %(datum)s '
                    'wirksam werden (Kündigungsfrist + 10-Tage-Ankündigung, Art. 269d OR).') % {
                        'datum': frueh.strftime('%d.%m.%Y')})
                return redirect(zurueck)

        # Vorbehalt: wer ihn macht, beziffert ihn (CHF oder %). Bei der Indexmiete gibt es
        # keine ordentlichen Anpassungsgründe, die sich vorbehalten liessen.
        mit_vorbehalt = P.get('mit_vorbehalt') == 'on' and not index_modus
        vb_betrag = _dec_oder_none(P.get('vorbehalt_betrag')) if mit_vorbehalt else None
        vb_prozent = _dec_oder_none(P.get('vorbehalt_prozent')) if mit_vorbehalt else None
        if mit_vorbehalt and vb_betrag is None and vb_prozent is None:
            messages.error(request, gettext(
                'Ein Vorbehalt muss beziffert sein — bitte den vorbehaltenen Betrag in CHF oder in % angeben.'))
            return redirect(zurueck)

        # Die Anteile werden auf den Werten DIESES Formulars gerechnet (neu_zins,
        # neu_lik) — bis hierher auf dem Marktstand der Verwaltung, während das
        # Formular die eingegebenen Werte nannte.
        pot = {} if index_modus else (
            berechne_mietpotenzial(v, neu_zins, neu_lik, kosten_pct, wirksam_ab=wirksam_ab) or {})
        werte = {
            'wirksam_ab': wirksam_ab, 'neuer_netto_mietzins': neu_netto,
            'alter_netto_mietzins': alt_netto,
            'alter_referenzzinssatz': alt_zins, 'neuer_referenzzinssatz': neu_zins,
            'alter_lik_index': alt_lik, 'neuer_lik_index': neu_lik,
            'neuer_lik_stand': aktuell_lik_stand,
            'erhoehung_prozent_total': pot.get('delta_prozent'),
            'zins_prozent': pot.get('zins_pct'), 'lik_prozent': pot.get('lik_pct'),
            'kosten_prozent': pot.get('kosten_pct'),
            'kosten_ausgeglichen_bis': heute if kosten_pct > 0 else None,
            'begruendung': (P.get('begruendung') or '').strip() or 'Anpassung an Referenzzinssatz und Teuerung',
            'vorbehalt_betrag': vb_betrag, 'vorbehalt_prozent': vb_prozent,
            'vorbehalt_text': (P.get('vorbehalt_text') or '').strip() if mit_vorbehalt else '',
            'schlichtungsbehoerde': (P.get('schlichtungsbehoerde') or '').strip()[:300],
            'neue_nebenkosten': neu_nk, 'alte_nebenkosten': alt_nk,
        }
        if index_modus:
            lage = idx.lage(v, heute=heute, stand=stand, wirksam_ab=wirksam_ab, versand_am=versand,
                            zugang_am=zugang)
            rechnung = lage['rechnung']
            delta = ((neu_netto - alt_netto) / alt_netto * Decimal('100')).quantize(Decimal('0.01')) \
                if alt_netto else Decimal('0')
            zusatz = (P.get('begruendung') or '').strip()
            werte.update({
                'alter_lik_index': rechnung.basis_lik, 'neuer_lik_index': rechnung.neu_lik,
                'neuer_lik_stand': stand,
                'alter_referenzzinssatz': alt_zins, 'neuer_referenzzinssatz': alt_zins,
                'erhoehung_prozent_total': delta, 'lik_prozent': delta,
                'zins_prozent': None, 'kosten_prozent': None, 'kosten_ausgeglichen_bis': None,
                'begruendung': (idx.begruendung(rechnung, stand, neu_netto, lage['alt_stand'])
                                + (' ' + zusatz if zusatz else '')),
            })
        neu_angelegt = entwurf is None and ablauf.offener_entwurf(v) is None
        try:
            anp = ablauf.entwurf_speichern(v, werte, entwurf)
        except ValueError as fehler:
            messages.error(request, f'❌ {fehler}')
            return redirect(zurueck)
        log_aktion(request, "Mietzinsanpassung: Entwurf " + ("erstellt" if neu_angelegt else "aktualisiert"),
                   str(v), f"neu CHF {neu_netto}, wirksam {wirksam_ab}", ziel=v)

        if aktion == 'entwurf':
            messages.success(request, '✅ ' + gettext(
                'Entwurf gespeichert — neu CHF %(neu_netto)s ab %(datum)s. Gebucht wird erst beim Versand.') % {
                    'neu_netto': neu_netto, 'datum': wirksam_ab.strftime('%d.%m.%Y')})
            return redirect(zurueck)

        # Formular: Kanton aus dem FELD der Liegenschaft, sonst keines (Befund G).
        if formular['kanton_fehlt']:
            messages.error(request, '⛔ ' + kanton_fehlt_meldung(lg))
            return redirect(zurueck)
        # Ohne Kantonsoriginal nur nach ausdrücklicher Bestätigung (Befund J).
        if not formular['original']:
            if index_modus and aktion == 'pdf':
                # Die Lücke wird genannt, nicht überbrückt: kein generisches Formular,
                # auch keine Nachbildung mit Wasserzeichen (Art. 19 Abs. 2 VMWG).
                messages.error(request, '⛔ ' + formular['warnung'] + ' ' + gettext(
                    'Für die Indexanpassung erzeugt die Anwendung kein Ersatzformular.'))
                return redirect(zurueck)
            if P.get('nachbildung_bestaetigt') != 'on':
                messages.error(request, '⛔ ' + formular['warnung'])
                return redirect(zurueck)

        if aktion == 'pdf':
            pdf = _formular_pdf(v, anp, vw, lik_basis, formular)
            resp = HttpResponse(pdf, content_type='application/pdf')
            resp['Content-Disposition'] = f'inline; filename="Mietzinsanpassung_Entwurf_{v.mieter.nachname}.pdf"'
            return resp

        # aktion == 'versandt'
        try:
            ablauf.versand_erfassen(anp, _datum(P.get('versand_am')), _datum(P.get('zugang_am')),
                                    benutzer=request.user if request.user.is_authenticated else None)
        except ValueError as fehler:
            messages.error(request, f'❌ {fehler}')
            return redirect(zurueck)
        if formular['original']:
            # Abgelegt wird, was versandt wurde — das Kantonsoriginal. Eine
            # Nachbildung ist nicht das versandte Formular und kommt nicht in die Akte.
            from core.services.ablage import ablegen
            ablegen(_formular_pdf(v, anp, vw, lik_basis, formular),
                    f"Mietzinsanpassung wirksam {anp.wirksam_ab:%d.%m.%Y}",
                    kategorie='vertrag', vertrag=v, dedup=True, im_portal_sichtbar=True)
        # Modul 5: Regel «Mietzinsanpassung versandt» — Begleitschreiben zum
        # amtlichen Formular, das unverändert bleibt.
        from core.services.dokument_regeln import dokument_fuer_ereignis
        dokument_fuer_ereignis('mza_versandt', organisation=v.organisation, vertrag=v)
        log_aktion(request, "Mietzinsanpassung versandt", str(v),
                   f"neu CHF {anp.neuer_netto_mietzins}, wirksam {anp.wirksam_ab}, "
                   f"versandt {anp.versand_am}", ziel=v)
        messages.success(request, '✅ ' + gettext(
            'Mietzinsanpassung als versandt erfasst — neu CHF %(neu_netto)s ab %(datum)s.') % {
                'neu_netto': anp.neuer_netto_mietzins, 'datum': anp.wirksam_ab.strftime('%d.%m.%Y')})
        return redirect(f'/neu/vertraege/{v.id}/?tab=mietzins')

    # --- GET: Assistent, vorbefüllt aus dem offenen Entwurf oder dem Vorschlag ---
    entwurf = ablauf.offener_entwurf(v)
    index_lage = None
    if v.mietzins_modell == 'index':
        # Indexmiete (Art. 269b OR, Art. 17 VMWG): Termin, Stand und Höchstbetrag kommen aus
        # `index_anpassung.lage` — dieselbe Rechnung wie in der Live-Nachrechnung und beim Speichern.
        index_lage = idx.lage(
            v, heute=heute,
            stand=idx.stand_aus_text(request.GET.get('lik_stand')) or (entwurf.neuer_lik_stand if entwurf else None),
            wirksam_ab=entwurf.wirksam_ab if entwurf else None)
        naechster_termin = index_lage['frueh']
        termin = index_lage['termin']
    else:
        naechster_termin = naechster_anpassungstermin(v, heute)
        termin = entwurf.wirksam_ab if entwurf else naechster_termin
    vortag = termin - _timedelta(days=1)
    alt_netto, alt_zins, alt_lik = bisheriger_stand(v, termin)
    # Allgemeine Kostensteigerung: Pauschale (0.5 %/Jahr) seit «ausgeglichen bis», sonst seit
    # Vertragsbeginn — als editierbarer Vorschlag, nicht automatisch weitergegeben.
    kosten_vorschlag = kostensteigerung_pauschal_pct(v.kostensteigerung_datum or v.beginn, heute)
    if index_lage is None:
        pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik, kosten_vorschlag, wirksam_ab=termin) or {}
        for hinweis in pot.get('hinweise', []):
            messages.warning(request, hinweis)
    else:
        # Referenzzins und Kostensteigerung sind keine Gründe einer Indexanpassung.
        pot = {}
    vorschlag_netto = pot.get('neu_chf', alt_netto)

    # Indexmiete (Art. 269b): die amtliche Index-Mitteilung (Art. 269d) wird direkt
    # aus der LIK-Entwicklung vorbefüllt — neuer Nettomietzins + fertige Begründung.
    index_vorschlag = None
    if index_lage is not None:
        from core.services.mietrecht import index_anpassung_vorschlag
        if index_lage['rechnung'] is not None:
            index_vorschlag = index_anpassung_vorschlag(v, wirksam_ab=termin, stand=index_lage['stand'])
        if index_vorschlag:
            vorschlag_netto = index_vorschlag['neu_netto']

    # Basis-Vorbelegung: fehlt sie am Vertrag (Alt-/Importvertrag), aktuelle
    # Marktwerte vorschlagen, damit der Sachbearbeiter sie ergänzen kann.
    basis_fehlt = not ((v.basis_referenzzinssatz or 0) > 0 and (v.basis_lik_punkte or 0) > 0)
    _termine, termine_herkunft = kuendigungstermine_fuer(v)
    # E1 (NK-Wizard): Vorbelegung des neuen Akontos aus der Nebenkostenabrechnung (?nk=…).
    nk_vorschlag = _dec_oder_none(request.GET.get('nk'))
    if nk_vorschlag is not None and nk_vorschlag < 0:
        nk_vorschlag = None
    nk_periode = None
    if request.GET.get('nk_periode', '').isdigit():
        from finance.models import AbrechnungsPeriode
        nk_periode = AbrechnungsPeriode.objects.filter(pk=request.GET['nk_periode'], liegenschaft=lg).first()
    if entwurf and entwurf.neue_nebenkosten is not None and nk_vorschlag is None:
        nk_vorschlag = entwurf.neue_nebenkosten
    hat_vorbehalt = bool(entwurf and (entwurf.vorbehalt_betrag is not None
                                      or entwurf.vorbehalt_prozent is not None))
    return render(request, 'fw/mietzins_anpassung.html', {
        **basis, 'nav': 'mietzins', 'v': v, 'lg': lg,
        'alt_netto': alt_netto,
        'alt_zins': alt_zins if (alt_zins or 0) > 0 else aktuell_ref,
        'alt_lik': alt_lik if (alt_lik or 0) > 0 else aktuell_lik,
        'basis_vertrag_zins': v.basis_referenzzinssatz if (v.basis_referenzzinssatz or 0) > 0 else aktuell_ref,
        'basis_vertrag_lik': v.basis_lik_punkte if (v.basis_lik_punkte or 0) > 0 else aktuell_lik,
        'basis_fehlt': basis_fehlt,
        'hat_anpassung': v._wirksame_anpassung(vortag) is not None,
        'neu_zins': entwurf.neuer_referenzzinssatz if entwurf else aktuell_ref,
        'neu_lik': entwurf.neuer_lik_index if entwurf else aktuell_lik,
        'aktuell_ref': aktuell_ref, 'aktuell_lik': aktuell_lik,
        'lik_basis': lik_basis,
        'alt_lik_stand': v.effektiver_lik_stand(vortag),
        'aktuell_lik_stand': aktuell_lik_stand,
        'vorschlag_netto': vorschlag_netto,
        'neu_netto': entwurf.neuer_netto_mietzins if entwurf else vorschlag_netto,
        'naechster_termin': naechster_termin, 'termin': termin,
        'pot': pot, 'index_vorschlag': index_vorschlag,
        'kosten_vorschlag': (entwurf.kosten_prozent if (entwurf and entwurf.kosten_prozent is not None)
                             else kosten_vorschlag),
        'entwurf': entwurf,
        # Indexmiete: Die Begründung baut der Server (Rechtsgrundlage, beide Stände, Zunahme,
        # Weitergabe); im Feld steht nur der eigene Zusatz.
        'begruendung': ((idx.zusatz_aus(entwurf.begruendung) if index_lage is not None else entwurf.begruendung)
                        if entwurf else ''),
        'idx': index_lage,
        'idx_luecke': idx.formular_luecke(formular) if index_lage is not None else None,
        'idx_stand_optionen': ([(d, idx.lik_punkte(d)) for d in index_lage['staende']]
                               if index_lage is not None else []),
        'schlichtungsbehoerde': entwurf.schlichtungsbehoerde if entwurf else '',
        'mit_vorbehalt': hat_vorbehalt,
        'vorbehalt_betrag': entwurf.vorbehalt_betrag if entwurf else v.mietzinsreserve_betrag,
        'vorbehalt_prozent': entwurf.vorbehalt_prozent if entwurf else v.mietzinsreserve_prozent,
        'vorbehalt_text': entwurf.vorbehalt_text if entwurf else '',
        'formular': formular,
        'kanton_fehlt_meldung': kanton_fehlt_meldung(lg) if formular['kanton_fehlt'] else '',
        'termine_fehlen': termine_herkunft == TERMINE_FEHLEN,
        'heute_iso': heute.isoformat(),
        'zustell_puffer': ZUSTELL_PUFFER_TAGE,
        'alt_nk': v.effektive_nebenkosten(vortag), 'neu_nk': nk_vorschlag, 'nk_periode': nk_periode,
    })


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mietzins_anpassung_rechnen(request, vertrag_id):
    """Live-Neuberechnung für den Assistenten (JSON). Rechnet auf dem Server mit
    derselben Funktion wie das Speichern — eine zweite Rechnung im Browser wäre
    die Gelegenheit, verschieden zu rechnen (wie beim Fristenwächter)."""
    from django.http import JsonResponse
    from rentals.services import berechne_mietpotenzial, bisheriger_stand, naechster_anpassungstermin
    v = get_object_or_404(Mietvertrag.objects.select_related('einheit__liegenschaft'), id=vertrag_id)
    heute = timezone.localdate()
    G = request.GET
    versand_am = _datum(G.get('versand_am')) or heute
    zugang_am = _datum(G.get('zugang_am'))
    if v.mietzins_modell == 'index':
        from core.services import index_anpassung as idx
        return JsonResponse(idx.lage_json(idx.lage(
            v, heute=heute, stand=idx.stand_aus_text(G.get('lik_stand')), wirksam_ab=_datum(G.get('wirksam_ab')),
            versand_am=versand_am, zugang_am=zugang_am, basis_lik=_dec_oder_none(G.get('basis_lik')))))
    wirksam_ab = _datum(G.get('wirksam_ab')) or naechster_anpassungstermin(v, heute)
    alt_netto, alt_zins, alt_lik = bisheriger_stand(v, wirksam_ab)
    pot = berechne_mietpotenzial(v, _dec(G.get('neu_zins'), str(alt_zins or 0)),
                                 _dec(G.get('neu_lik'), str(alt_lik or 0)),
                                 _dec(G.get('kosten_pct'), '0'), wirksam_ab=wirksam_ab) or {}

    def _s(x):
        return None if x is None else str(x)
    return JsonResponse({
        'alt_netto': _s(alt_netto), 'basis_zins': _s(alt_zins), 'basis_lik': _s(alt_lik),
        'neu_chf': _s(pot.get('neu_chf')), 'delta_prozent': _s(pot.get('delta_prozent')),
        'zins_pct': _s(pot.get('zins_pct')), 'lik_pct': _s(pot.get('lik_pct')),
        'kosten_pct': _s(pot.get('kosten_pct')), 'hinweise': pot.get('hinweise', []),
        'fruehester_termin': naechster_anpassungstermin(v, versand_am, zugang_am=zugang_am).isoformat(),
    })


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_anpassung_status(request, pk):
    """Statuswechsel einer Anpassung aus der Vertragsakte (nur POST).

    `aktion`: `versandt` (Entwurf, z. B. aus der Massenanpassung — mit
    Versanddatum), `zugang` (Zugang nachtragen), `wirksam`, `angefochten`.
    """
    from django.contrib import messages
    from django.shortcuts import redirect
    from core.auth import log_aktion
    from core.services import mietzinsanpassung as ablauf
    from core.services.formular_status import formular_status
    from rentals.models import MietzinsAnpassung
    anp = get_object_or_404(MietzinsAnpassung.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    v = anp.vertrag
    ziel = f'/neu/vertraege/{v.id}/?tab=mietzins'
    if request.method != 'POST':
        return redirect(ziel)
    aktion = request.POST.get('aktion')
    benutzer = request.user if request.user.is_authenticated else None
    try:
        if aktion == 'versandt':
            formular = formular_status(v.einheit.liegenschaft, 'mietzins')
            if not formular['original'] and request.POST.get('nachbildung_bestaetigt') != 'on':
                raise ValueError(formular['warnung'] or gettext(
                    'Bitte bestätigen, dass das amtliche Formular des Kantons verwendet wurde.'))
            ablauf.versand_erfassen(anp, _datum(request.POST.get('versand_am')),
                                    _datum(request.POST.get('zugang_am')), benutzer=benutzer)
        elif aktion == 'zugang':
            zugang = _datum(request.POST.get('zugang_am'))
            if zugang is None or not anp.ist_gebucht:
                raise ValueError(gettext('Bitte das Zugangsdatum einer versandten Anpassung angeben.'))
            ablauf.zugang_nachtragen(anp, zugang)
        elif aktion in ('wirksam', 'angefochten'):
            ablauf.status_setzen(anp, aktion, benutzer=benutzer)
        else:
            raise ValueError(gettext('Unbekannte Aktion.'))
    except ValueError as fehler:
        messages.error(request, f'❌ {fehler}')
        return redirect(ziel)
    log_aktion(request, f"Mietzinsanpassung: {aktion}", str(v),
               f"wirksam {anp.wirksam_ab}, CHF {anp.neuer_netto_mietzins}", ziel=v)
    messages.success(request, '✅ ' + gettext('Mietzinsanpassung aktualisiert: %(status)s.') % {
        'status': anp.get_status_display()})
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mietzins_versand(request):
    """Mehrere Entwürfe (meist aus der Massenanpassung) als versandt erfassen."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from core.auth import log_aktion
    from core.services import mietzinsanpassung as ablauf
    from core.services.formular_status import formular_status
    from rentals.models import MietzinsAnpassung
    if request.method != 'POST':
        return redirect('fw_mietzins')
    versand_am = _datum(request.POST.get('versand_am'))
    bestaetigt = request.POST.get('nachbildung_bestaetigt') == 'on'
    entwuerfe = (MietzinsAnpassung.objects
                 .filter(pk__in=[i for i in request.POST.getlist('anpassung') if i.isdigit()],
                         status=MietzinsAnpassung.STATUS_ENTWURF)
                 .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'))
    benutzer = request.user if request.user.is_authenticated else None
    ok, fehler = 0, []
    for anp in entwuerfe:
        formular = formular_status(anp.vertrag.einheit.liegenschaft, 'mietzins')
        try:
            if formular['kanton_fehlt']:
                raise ValueError(gettext('Kanton der Liegenschaft fehlt.'))
            if not formular['original'] and not bestaetigt:
                raise ValueError(formular['warnung'])
            ablauf.versand_erfassen(anp, versand_am, benutzer=benutzer)
            ok += 1
        except ValueError as e:
            fehler.append(f"{anp.vertrag.mieter.display_name}: {e}")
    if ok:
        log_aktion(request, "Mietzinsanpassungen versandt", f"{ok} Verträge", f"versandt {versand_am}")
        messages.success(request, '✅ ' + gettext('%(n)s Anpassung(en) als versandt erfasst.') % {'n': ok})
    for f in fehler:
        messages.error(request, f'❌ {f}')
    if not ok and not fehler:
        messages.error(request, gettext('Keine offenen Entwürfe ausgewählt.'))
    return redirect('fw_mietzins')


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mietzins_massenanpassung(request):
    """Mietzins-Massenanpassung nach Referenzzins-/LIK-Änderung: für die in der
    Mietzins-Liste angehakten Verträge wird das Potenzial berechnet (Vorschau) und
    per Bestätigung je Vertrag ein ENTWURF + amtliches Formular erzeugt
    (Sammel-PDF). Gebucht wird erst, wenn die Entwürfe als versandt erfasst sind
    (`fw_mietzins_versand`). Fristen nach Art. 269d OR werden je Vertrag einzeln
    bestimmt.

    Index- und Staffelmieten sind ausgenommen (Befund D): Ihr Mietzins folgt dem
    Index bzw. den vereinbarten Stufen (Art. 269b/269c OR), nicht dem
    Referenzzins. Bis hierher rechnete der Massenlauf sie mit, als wären sie
    feste Mietzinse."""
    from django.contrib import messages
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from core.auth import log_aktion
    from core.services import mietzinsanpassung as ablauf
    from core.services.formular_status import formular_status
    from rentals.models import MietzinsAnpassung
    from rentals.services import berechne_mietpotenzial, bisheriger_stand, naechster_anpassungstermin

    if request.method != 'POST':
        return redirect('fw_mietzins')
    basis = _global_filter(request)
    vw = aktuelle_organisation()
    aktuell_ref, aktuell_lik, aktuell_lik_stand, lik_basis = _marktstand(vw)

    ids = request.POST.getlist('vertrag_id')
    gewaehlt = (Mietvertrag.objects.filter(id__in=ids, status='aktiv')
                .select_related('mieter', 'einheit__liegenschaft'))
    vertraege = [v for v in gewaehlt if v.mietzins_modell not in MODELLE_OHNE_MASSENLAUF]
    ausgenommen = [v for v in gewaehlt if v.mietzins_modell in MODELLE_OHNE_MASSENLAUF]
    if ausgenommen:
        messages.info(request, gettext(
            '%(n)s Index- oder Staffelmiete(n) ausgenommen — deren Mietzins folgt dem Index bzw. '
            'den vereinbarten Stufen (Art. 269b/269c OR), nicht dem Referenzzins.') % {'n': len(ausgenommen)})
    if not vertraege:
        messages.error(request, gettext('Keine Verträge ausgewählt.'))
        return redirect('fw_mietzins')

    heute = timezone.localdate()
    rows = []
    for v in vertraege:
        termin = naechster_anpassungstermin(v, heute)
        alt_netto, alt_zins, alt_lik = bisheriger_stand(v, termin)
        pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik, wirksam_ab=termin) or {}
        neu_netto = pot.get('neu_chf')
        delta = (neu_netto - (alt_netto or Decimal('0'))) if neu_netto is not None else None
        formular = formular_status(v.einheit.liegenschaft, 'mietzins')
        rows.append({
            'v': v, 'pot': pot, 'neu_netto': neu_netto, 'termin': termin,
            'alt_netto': alt_netto, 'alt_zins': alt_zins, 'alt_lik': alt_lik,
            'delta': delta, 'formular': formular,
            'basis_fehlt': not ((v.basis_referenzzinssatz or 0) > 0 and (v.basis_lik_punkte or 0) > 0),
            'kanton_fehlt': formular['kanton_fehlt'],
            'unveraendert': (delta is not None and delta == 0),
        })

    def _machbar(r):
        return not r['basis_fehlt'] and not r['kanton_fehlt'] and r['neu_netto'] is not None and r['delta']

    aktion = request.POST.get('aktion', 'vorschau')
    machbar = [r for r in rows if _machbar(r)]
    nachbildungen = [r for r in machbar if not r['formular']['original']]
    if aktion != 'ausfuehren':
        return render(request, 'fw/mietzins_massen.html', {
            **basis, 'nav': 'mietzins', 'rows': rows, 'machbar': len(machbar),
            'nachbildungen': nachbildungen, 'ausgenommen': ausgenommen,
            'aktuell_ref': aktuell_ref, 'aktuell_lik': aktuell_lik,
        })
    if nachbildungen and request.POST.get('nachbildung_bestaetigt') != 'on':
        messages.error(request, '⛔ ' + nachbildungen[0]['formular']['warnung'])
        return redirect('fw_mietzins')

    # --- Ausführen: je Vertrag ein Entwurf + Formular, dann Sammel-PDF. Bucht NICHTS. ---
    import io as _io
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    erfasst = 0
    for r in machbar:
        v = r['v']
        pot = r['pot']
        if MietzinsAnpassung.objects.filter(vertrag=v, wirksam_ab=r['termin'],
                                            status__in=MietzinsAnpassung.GEBUCHT).exists():
            # Schon versandt (zweiter Massenlauf): nicht ein zweites Mal anlegen.
            continue
        anp = ablauf.entwurf_speichern(v, {
            'wirksam_ab': r['termin'], 'neuer_netto_mietzins': r['neu_netto'],
            'alter_netto_mietzins': r['alt_netto'],
            'alter_referenzzinssatz': r['alt_zins'], 'neuer_referenzzinssatz': aktuell_ref,
            'alter_lik_index': r['alt_lik'], 'neuer_lik_index': aktuell_lik,
            'neuer_lik_stand': aktuell_lik_stand,
            'erhoehung_prozent_total': pot.get('delta_prozent'),
            'zins_prozent': pot.get('zins_pct'), 'lik_prozent': pot.get('lik_pct'),
            'kosten_prozent': pot.get('kosten_pct'),
            'begruendung': 'Anpassung an Referenzzinssatz und Teuerung (Massenanpassung)',
        })
        log_aktion(request, "Mietzinsanpassung: Entwurf (Massenlauf)", str(v),
                   f"neu CHF {anp.neuer_netto_mietzins}, wirksam {anp.wirksam_ab}", ziel=v)
        pdf = _formular_pdf(v, anp, vw, lik_basis, r['formular'])
        try:
            for page in PdfReader(_io.BytesIO(pdf)).pages:
                writer.add_page(page)
        except Exception:
            logger.warning("Sammel-PDF: Formular von Vertrag %s nicht anfügbar", v.pk, exc_info=True)
        erfasst += 1

    if not erfasst:
        messages.error(request, gettext('Keine Anpassung möglich (Basisdaten oder Kanton fehlen, oder kein Potenzial).'))
        return redirect('fw_mietzins')

    log_aktion(request, "Mietzins-Massenanpassung (Entwürfe)", f"{erfasst} Verträge",
               f"Ref {aktuell_ref}% · LIK {aktuell_lik}")
    out = _io.BytesIO()
    writer.write(out)
    resp = HttpResponse(out.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="Mietzinsanpassungen_Entwuerfe.pdf"'
    return resp


def _vormiete_fuer(vertrag):
    """Der Vormieter-Vertrag desselben Objekts (ohne Entwürfe) — siehe `core/services/anfangsformular.py`."""
    from core.services.anfangsformular import vormiete_fuer
    return vormiete_fuer(vertrag)


def anfangsmietzins_auto_ablegen(vertrag, verwaltung=None):
    """Erzeugt bei Vertrags-Aktivierung automatisch das amtliche Anfangsmietzins-
    Formular (Art. 270 Abs. 2 OR) und legt es in der Akte ab — aber NUR wenn im
    Kanton der Liegenschaft Formularpflicht besteht und es sich um Wohnraum handelt
    (kein Gewerbe, kein Einstellplatz). So steht das Formular spätestens zur
    Schlüsselübergabe bereit (30-Tage-Anfechtungsfrist ab Erhalt). Vormiete wird
    aus dem letzten beendeten Vertrag gezogen, sonst «unbekannt» (Art. 270 zulässig).
    Gibt (True, pflicht) bei Erzeugung zurück, sonst (False, grund)."""
    from crm.models import Organisation
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
    # Automatisch abgelegt wird nur ein KANTONSORIGINAL eines ERFASSTEN Kantons
    # (Befunde G, J). Bis hierher lag für 23 Kantone still eine Nachbildung in
    # der Akte, die wie das zugestellte amtliche Formular aussah.
    from core.services.formular_status import formular_status
    formular = formular_status(einheit.liegenschaft, 'anfangsmietzins')
    if formular['kanton_fehlt']:
        return False, 'kanton_fehlt'
    if not formular['original']:
        return False, 'kein_original'
    # Anfangsmiete aus der datierten Sollmietzins-Tabelle zum Vertragsbeginn.
    soll = einheit.aktueller_sollmietzins(vertrag.beginn)
    anf_netto = (soll.netto_mietzins if soll else vertrag.netto_mietzins) or Decimal('0')
    anf_nk = (soll.nebenkosten if soll else vertrag.nebenkosten) or Decimal('0')
    # MIET-05: «bisheriger Mietzins» ist der LETZTE vor dem neuen Vertrag gültige (Staffelstufe, gebuchte
    # Anpassung), nicht der Wert zu Beginn der Vormiete; Referenzzins und LIK aus der damals wirksamen Basis.
    from core.services.anfangsformular import vormiete_werte
    vor = vormiete_werte(vertrag)
    from core.services.lik import LIK_BASIS
    daten = {
        'anfang_netto': anf_netto,
        'anfang_nk': anf_nk,
        'vormiete_netto': vor['netto'] if vor else Decimal('0'),
        'vormiete_nk': vor['nk'] if vor else Decimal('0'),
        'beginn': vertrag.beginn,
        'grund_choice': 'unbekannt' if not vor else 'anpassung',
        'begruendung': '',
        'basis_ref': vor['ref'] if vor else vertrag.basis_referenzzinssatz,
        'basis_lik': vor['lik'] if vor else vertrag.basis_lik_punkte,
        'basis_lik_basis': LIK_BASIS,
        'pflicht_info': info,
    }
    vw = verwaltung or (einheit.liegenschaft.organisation if einheit.liegenschaft else None)
    pdf = fill_anfangsmietzins(vertrag, daten, verwaltung=vw)
    ablegen(pdf, f"Anfangsmietzins-Formular {vertrag.beginn:%d.%m.%Y}" if vertrag.beginn else "Anfangsmietzins-Formular",
            kategorie='vertrag', vertrag=vertrag, dedup=True)
    return True, pflicht


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_anfangsmietzins(request, vertrag_id):
    """Amtliches Formular zur Mitteilung des Anfangsmietzinses (Art. 270 OR /
    Art. 19 VMWG) — bei Neuabschluss dem neuen Mieter mit Angabe der Vormiete und
    Hinweis auf das 30-Tage-Anfechtungsrecht zuzustellen. GET: Formular · POST: PDF."""
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.formular_fill import fill_anfangsmietzins, hat_original
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    vw = v.organisation
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
    # MIET-05: der LETZTE vor dem neuen Vertrag gültige Mietzins der Vormiete (Staffelstufe, gebuchte
    # Anpassung), nicht der Wert zu Beginn der Vormiete — `core/services/anfangsformular.py`.
    from core.services.anfangsformular import vormiete_werte
    vor_werte = vormiete_werte(v)
    vormiete = vor_werte['vertrag'] if vor_werte else None
    if vor_werte:
        vor_netto, vor_nk = vor_werte['netto'], vor_werte['nk']
    else:
        vor_netto = vor_nk = ''

    # Berechnungsgrundlagen: Referenzzinssatz + LIK-Punkte + LIK-Basis. Quelle = die Basis, auf der der
    # bisherige Mietzins am Stichtag beruhte (Art. 19 Abs. 3 VMWG), sonst der aktuelle Vertrag.
    from core.services.lik import LIK_BASIS
    basis_ref = vor_werte['ref'] if vor_werte else v.basis_referenzzinssatz
    basis_lik = vor_werte['lik'] if vor_werte else v.basis_lik_punkte
    basis_lik_basis = LIK_BASIS

    from core.services.formular_fill import mit_wasserzeichen
    from core.services.formular_status import formular_status, kanton_fehlt_meldung
    formular = formular_status(lg, 'anfangsmietzins')

    if request.method == 'POST':
        from django.contrib import messages
        from django.shortcuts import redirect
        # Kanton aus dem FELD, Nachbildung nur nach Bestätigung (Befunde G, J).
        if formular['kanton_fehlt']:
            messages.error(request, '⛔ ' + kanton_fehlt_meldung(lg))
            return redirect(f'/neu/mietzins/{v.id}/anfangsmietzins/')
        if not formular['original'] and request.POST.get('nachbildung_bestaetigt') != 'on':
            messages.error(request, '⛔ ' + formular['warnung'])
            return redirect(f'/neu/mietzins/{v.id}/anfangsmietzins/')
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
        # Immer das Original-Formular des Kantons, wenn hinterlegt — sonst die
        # Nachbildung, dann aber als Entwurf gekennzeichnet und NICHT abgelegt:
        # In der Akte stünde sie sonst wie ein zugestelltes amtliches Formular.
        pdf = fill_anfangsmietzins(v, daten, verwaltung=vw, kanton=formular['kanton'])
        if formular['original']:
            ablegen(pdf, f"Anfangsmietzins-Formular {v.beginn:%d.%m.%Y}" if v.beginn else "Anfangsmietzins-Formular",
                    kategorie='vertrag', vertrag=v, dedup=True)
        else:
            pdf = mit_wasserzeichen(pdf)
        log_aktion(request, "Anfangsmietzins-Formular erstellt", str(v),
                   f"Anfangsmiete CHF {daten['anfang_netto']}"
                   + ("" if formular['original'] else " (Nachbildung, Entwurf)"), ziel=v)
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
        'vor_stichtag': vor_werte['stichtag'] if vor_werte else None,
        'vormiete_netto': vor_netto,
        'vormiete_nk': vor_nk,
        'pflicht': pflicht, 'pflicht_info': pflicht_info,
        'pflicht_label': pflicht_label(pflicht),
        'hat_original': hat_original(kanton_fuer_liegenschaft(lg), 'anfangsmietzins'),
        'formular': formular,
        'kanton_fehlt_meldung': kanton_fehlt_meldung(lg) if formular['kanton_fehlt'] else '',
        'basis_ref': basis_ref, 'basis_lik': basis_lik, 'basis_lik_basis': basis_lik_basis,
    })
