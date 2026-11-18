# core/views/fw/mietverfahren.py
#
# Nutzungsentschaedigung, Herabsetzung, Mietverfahren.
# Aus kuendigung.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       VERWALTUNGS_ROLLEN)
from rentals.models import Mietvertrag

from ._basis import _global_filter
from core.utils.betrag import betrag_normalisieren
from .dokument_zustellung import _datum_oder_none


# Nutzungsentschädigung: eine Forderung zu stellen ist eine Entscheidung der
# Verwaltung (Ist der Mieter wirklich noch drin?) — dieselbe Stufe wie die
# Fristansetzung nach Art. 257d OR.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_nutzungsentschaedigung(request, vertrag_id):
    """Nutzungsentschädigung nach Vertragsende (core/services/nutzungsentschaedigung.py).
    GET: Vorschau der fehlenden Monate · POST: Forderungen stellen."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from core.services import nutzungsentschaedigung as ne

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'),
                          id=vertrag_id)
    basis = _global_filter(request)
    heute = timezone.localdate()
    offen = ne.ist_offen(v, heute)

    if request.method == 'POST':
        if not offen:
            messages.error(request, gettext(
                'Keine Nutzungsentschädigung geschuldet: Das Vertragsende liegt nicht in der '
                'Vergangenheit oder die Rücknahme ist protokolliert.'))
            return redirect(f'/neu/vertraege/{v.id}/')
        neu = ne.stelle_bis_heute(v, user=request.user)
        if neu:
            total = sum((r.betrag for r in neu), Decimal('0.00'))
            log_aktion(request, 'Nutzungsentschädigung gestellt', str(v.mieter),
                       f'{len(neu)} Monat(e), CHF {total:.2f}', ziel=v)
            messages.success(request, '✅ ' + gettext(
                '%(n)s Forderung(en) über CHF %(total)s gestellt.') % {'n': len(neu), 'total': f'{total:.2f}'})
        else:
            messages.info(request, gettext('Es gibt keine offenen Monate — alles ist bereits gestellt.'))
        return redirect(f'/neu/vertraege/{v.id}/')

    vorschau = []
    for j, m in ne.monate_ohne_forderung(v, heute):
        vorschau.append({'jahr': j, 'monat': m})
    return render(request, 'fw/nutzungsentschaedigung.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'offen': offen,
        'vorschau': vorschau, 'rueckgabe': ne.rueckgabe_datum(v),
    })


#: Art. 270a Abs. 2 OR: Der Vermieter muss das Herabsetzungsbegehren innert 30 Tagen beantworten.
HERABSETZUNG_ANTWORT_TAGE = 30


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_herabsetzung(request, vertrag_id):
    """Herabsetzungsbegehren des Mieters als Vorgang (Art. 270a OR).

    Bisher gab es nur die Potenzialanzeige («Senkung möglich»). Verlangt der Mieter
    eine Herabsetzung, muss der Vermieter innert 30 Tagen antworten — die Frist
    läuft ab Eingang. POST `aktion=eingang`: Begehren erfassen (Frist-Pendenz).
    POST `aktion=antwort`: Antwort erteilt (schliesst die Pendenz, hält das Ergebnis
    fest und zeigt, bis wann der Mieter die Schlichtungsbehörde anrufen kann)."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from core.models import Pendenz

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'),
                          id=vertrag_id)
    basis = _global_filter(request)
    heute = timezone.localdate()
    lg = v.einheit.liegenschaft if v.einheit_id else None

    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        if aktion == 'eingang':
            try:
                eingang = date.fromisoformat(request.POST.get('eingang_datum') or '')
            except ValueError:
                eingang = heute
            if eingang > heute:
                messages.error(request, gettext('Das Eingangsdatum liegt in der Zukunft.'))
                return redirect(f'/neu/vertraege/{v.id}/herabsetzung/')
            quelle = f'270a:{v.pk}:{eingang.isoformat()}'
            if Pendenz.objects.filter(vertrag=v, quelle=quelle).exists():
                messages.info(request, gettext('Dieses Begehren ist bereits erfasst.'))
                return redirect(f'/neu/vertraege/{v.id}/herabsetzung/')
            frist = eingang + _timedelta(days=HERABSETZUNG_ANTWORT_TAGE)
            Pendenz.objects.create(
                titel=f'Art. 270a: Herabsetzungsbegehren beantworten – {v.mieter.display_name}',
                beschreibung=(f'Begehren des Mieters eingegangen am {eingang:%d.%m.%Y}. Der Vermieter '
                              f'muss innert {HERABSETZUNG_ANTWORT_TAGE} Tagen antworten (Art. 270a Abs. 2 OR). '
                              + (f'Notiz: {request.POST.get("notiz").strip()[:300]}'
                                 if (request.POST.get('notiz') or '').strip() else '')).strip(),
                kategorie='frist', faellig_am=frist, vertrag=v, liegenschaft=lg, quelle=quelle,
                erstellt_von=request.user if request.user.is_authenticated else None)
            log_aktion(request, 'Herabsetzungsbegehren erfasst', str(v.mieter),
                       f'eingegangen {eingang:%d.%m.%Y}, Antwort bis {frist:%d.%m.%Y}', ziel=v)
            messages.success(request, '✅ ' + gettext('Begehren erfasst — Antwort bis %(frist)s.') % {'frist': frist.strftime('%d.%m.%Y')})
        elif aktion == 'antwort':
            p = Pendenz.objects.filter(vertrag=v, pk=request.POST.get('pendenz') or 0,
                                       quelle__startswith='270a:', erledigt=False).first()
            ergebnis = request.POST.get('ergebnis')
            if p is None or ergebnis not in ('zustimmung', 'teilweise', 'ablehnung'):
                messages.error(request, gettext('Bitte ein offenes Begehren und das Ergebnis der Antwort wählen.'))
                return redirect(f'/neu/vertraege/{v.id}/herabsetzung/')
            try:
                antwort_am = date.fromisoformat(request.POST.get('antwort_datum') or '')
            except ValueError:
                antwort_am = heute
            text = {'zustimmung': 'Zustimmung', 'teilweise': 'Teilweise Zustimmung',
                    'ablehnung': 'Ablehnung'}[ergebnis]
            p.erledigt = True
            p.erledigt_am = heute
            p.beschreibung = f'Antwort am {antwort_am:%d.%m.%Y}: {text}.\n\n{p.beschreibung}'
            p.save(update_fields=['erledigt', 'erledigt_am', 'beschreibung'])
            if ergebnis != 'zustimmung':
                # Information für die Verwaltung: Bis dahin kann der Mieter anrufen.
                Pendenz.objects.create(
                    titel=f'Art. 270a: Anrufungsfrist des Mieters läuft – {v.mieter.display_name}',
                    beschreibung=(f'{text} am {antwort_am:%d.%m.%Y}. Der Mieter kann die '
                                  f'Schlichtungsbehörde innert 30 Tagen anrufen (Art. 270a Abs. 3 OR). '
                                  'Danach gilt die Antwort als akzeptiert.'),
                    kategorie='frist', faellig_am=antwort_am + _timedelta(days=30), vertrag=v,
                    liegenschaft=lg, quelle=f'270a-anrufung:{v.pk}:{antwort_am.isoformat()}')
            log_aktion(request, 'Herabsetzungsbegehren beantwortet', str(v.mieter), text, ziel=v)
            if request.POST.get('brief'):
                # Antwortbrief (Befund M): abgelegt in der Korrespondenz — die
                # Anrufungsfrist des Mieters läuft ab dieser Antwort, ihr Inhalt
                # gehört in die Akte.
                from django.http import HttpResponse
                from core.services.ablage import ablegen
                from core.services.herabsetzung_brief import antwortbrief_pdf
                try:
                    neu_netto = Decimal(_num_oder_leer(request.POST.get('neu_netto'))) \
                        if _num_oder_leer(request.POST.get('neu_netto')) else None
                except Exception:
                    neu_netto = None
                eingang_am = _datum_oder_none((p.quelle or '').split(':')[-1])
                pdf = antwortbrief_pdf(v, ergebnis, antwort_am, eingang_am=eingang_am,
                                       begruendung=(request.POST.get('begruendung') or '').strip()[:1500],
                                       neu_netto=neu_netto,
                                       wirksam_ab=_datum_oder_none(request.POST.get('wirksam_ab')))
                ablegen(pdf, f"Antwort Herabsetzungsbegehren {antwort_am:%d.%m.%Y}",
                        kategorie='korrespondenz', vertrag=v, dedup=True)
                resp = HttpResponse(pdf, content_type='application/pdf')
                resp['Content-Disposition'] = f'inline; filename="Antwort_Herabsetzung_{v.mieter.nachname}.pdf"'
                return resp
            messages.success(request, '✅ ' + gettext('Antwort festgehalten: %(text)s.') % {'text': text})
            if ergebnis != 'ablehnung':
                messages.info(request, gettext('Die Senkung wird über «Mietzinsanpassung» mit dem amtlichen Formular mitgeteilt.'))
        return redirect(f'/neu/vertraege/{v.id}/herabsetzung/')

    offene = list(Pendenz.objects.filter(vertrag=v, quelle__startswith='270a:', erledigt=False)
                  .order_by('faellig_am'))
    return render(request, 'fw/herabsetzung.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'offene': offene, 'heute_iso': heute.isoformat(),
        'antwort_tage': HERABSETZUNG_ANTWORT_TAGE,
        'netto_aktuell': v.effektiver_netto_mietzins(heute),
        'beantwortet': Pendenz.objects.filter(vertrag=v, quelle__startswith='270a:', erledigt=True).exists(),
    })


def _num_oder_leer(wert):
    """'1''450.50' / '1450,5' → '1450.50'-artig; '' bei leer."""
    return betrag_normalisieren(wert)


# Verfahren um die Mietsache zu erfassen und abzuschliessen ist Inhabern und Verwaltern vorbehalten wie die Kündigung
# selbst: Ein abgeschlossenes Verfahren setzt die Sperrfrist des Art. 271a OR in Gang, ein falsch erfasstes nimmt
# sie weg.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_mietverfahren(request, vertrag_id):
    """Schlichtungs- und Gerichtsverfahren sowie Einigungen am Vertrag (Art. 271a OR, Audit MIET-06).

    Die Erfassung einer Vermieterkündigung (`fw_kuendigung_erfassen`) hält an, wenn sie in ein laufendes Verfahren
    oder in die drei Jahre danach fällt (`core/services/kuendigungsschutz.py`). Dieses Formular ist die Quelle der
    Daten. POST `aktion=neu`: Verfahren oder Einigung erfassen. POST `aktion=abschluss`: ein hängiges Verfahren mit
    Datum und Ausgang abschliessen. Gelöscht wird nichts: Ein Fehler bei der Erfassung wird durch den Abschluss
    mit dem passenden Ausgang berichtigt."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from core.services.kuendigungsschutz import drei_jahre_nach
    from rentals.models import Mietverfahren

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'),
                          id=vertrag_id)
    basis = _global_filter(request)
    heute = timezone.localdate()
    zurueck = f'/neu/vertraege/{v.id}/verfahren/'

    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        if aktion == 'neu':
            art = request.POST.get('art')
            gegenstand = request.POST.get('gegenstand')
            beginn = _datum_oder_none(request.POST.get('eingeleitet_am'))
            if art not in dict(Mietverfahren.ART_CHOICES) or gegenstand not in dict(Mietverfahren.GEGENSTAND_CHOICES):
                messages.error(request, gettext('Bitte Art und Gegenstand des Verfahrens wählen.'))
                return redirect(zurueck)
            if beginn is None or beginn > heute:
                messages.error(request, gettext(
                    'Bitte ein Datum angeben, das nicht in der Zukunft liegt.'))
                return redirect(zurueck)
            felder = dict(vertrag=v, art=art, gegenstand=gegenstand, eingeleitet_am=beginn,
                          aktenzeichen=(request.POST.get('aktenzeichen') or '').strip()[:120],
                          bemerkung=(request.POST.get('bemerkung') or '').strip()[:1000])
            if art == Mietverfahren.ART_EINIGUNG:
                # Art. 271a Abs. 2 OR: eine schriftlich nachgewiesene Einigung ausserhalb eines Verfahrens wirkt wie
                # ein Vergleich — sie ist am selben Tag eingegangen und abgeschlossen.
                felder.update(abgeschlossen_am=beginn, ausgang='vergleich')
            vf = Mietverfahren.objects.create(**felder)
            log_aktion(request, 'Mietrechtliches Verfahren erfasst', str(v.mieter),
                       f'{vf.get_art_display()}, {vf.get_gegenstand_display()}, ab {beginn:%d.%m.%Y}', ziel=v)
            messages.success(request, '✅ ' + gettext('Verfahren erfasst. Eine Kündigung des Vermieters ist ab jetzt '
                                                     'gegen Art. 271a OR geschützt und wird angehalten.'))
            return redirect(zurueck)
        if aktion == 'abschluss':
            vf = v.verfahren.filter(pk=request.POST.get('verfahren') or 0, abgeschlossen_am__isnull=True).first()
            ausgang = request.POST.get('ausgang')
            ende = _datum_oder_none(request.POST.get('abgeschlossen_am'))
            erlaubt = {a for a, _t in Mietverfahren.AUSGANG_CHOICES if a != Mietverfahren.AUSGANG_HAENGIG}
            if vf is None or ausgang not in erlaubt:
                messages.error(request, gettext('Bitte ein hängiges Verfahren und den Ausgang wählen.'))
                return redirect(zurueck)
            if ende is None or ende > heute or ende < vf.eingeleitet_am:
                messages.error(request, gettext(
                    'Das Abschlussdatum darf weder vor Beginn des Verfahrens noch in der Zukunft liegen.'))
                return redirect(zurueck)
            vf.ausgang, vf.abgeschlossen_am = ausgang, ende
            vf.save(update_fields=['ausgang', 'abgeschlossen_am'])
            log_aktion(request, 'Mietrechtliches Verfahren abgeschlossen', str(v.mieter),
                       f'{vf.get_ausgang_display()}, {ende:%d.%m.%Y}', ziel=v)
            if ausgang in Mietverfahren.AUSGAENGE_NACHFRIST:
                messages.warning(request, '⚠️ ' + gettext(
                    'Verfahren abgeschlossen. Eine Kündigung des Vermieters ist bis und mit %(bis)s anfechtbar '
                    '(Art. 271a Abs. 1 lit. e OR, drei Jahre).') % {'bis': f'{drei_jahre_nach(ende):%d.%m.%Y}'})
            else:
                messages.success(request, '✅ ' + gettext('Verfahren abgeschlossen.'))
            return redirect(zurueck)
        return redirect(zurueck)

    from core.services.kuendigungsschutz import ausnahmen_hinweis, sperrfristen
    verfahren = []
    for vf in v.verfahren.all():
        verfahren.append({
            'v': vf, 'haengig': vf.abgeschlossen_am is None,
            'bis': (drei_jahre_nach(vf.abgeschlossen_am)
                    if vf.abgeschlossen_am and vf.ausgang in Mietverfahren.AUSGAENGE_NACHFRIST else None)})
    return render(request, 'fw/verfahren.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'verfahren': verfahren,
        'arten': Mietverfahren.ART_CHOICES, 'gegenstaende': Mietverfahren.GEGENSTAND_CHOICES,
        'ausgaenge': [(a, t) for a, t in Mietverfahren.AUSGANG_CHOICES if a != Mietverfahren.AUSGANG_HAENGIG],
        'heute_iso': heute.isoformat(),
        'sperren': sperrfristen(v, {heute}), 'ausnahmen': ausnahmen_hinweis(),
    })
