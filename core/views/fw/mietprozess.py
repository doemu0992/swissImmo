# core/views/fw/mietprozess.py
#
# Von der Bewerbung ueber die Auswahl zum Vertrag: Bewerbungsliste,
# Vergleich, Besichtigung, Entscheid, Absagen, Unterlagen.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Beruehrt die DSG-Seite (P5): Bewerberunterlagen sind besonders
# schuetzenswerte Personendaten. Reiner Umzug, Blockinhalt gegen HEAD
# geprueft.

from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy, gettext_noop
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from portfolio.models import Einheit
from rentals.models import Mietvertrag

from ._basis import _global_filter, _vermietung_pipeline
from core.tenancy import aktuelle_organisation


# ============================================================
# MIETPROZESS: BEWERBUNGEN → MIETER → VERTRAG (in der /neu/-Shell)
# ============================================================

BEWERBUNG_SPALTEN = [
    ('neu', gettext_lazy('Neu eingegangen'), 'fw-info-flaeche fw-info'),
    ('geprueft', gettext_lazy('Bonität geprüft'), 'fw-warn-flaeche fw-warnton'),
    ('besichtigung', gettext_lazy('Besichtigung'), 'fw-info-flaeche fw-info'),
    ('zugesagt', gettext_lazy('Zusage erteilt'), 'fw-gut-flaeche fw-gut'),
    ('abgelehnt', gettext_lazy('Abgelehnt'), 'fw-krit-flaeche fw-kritisch'),
]


#: Die Liste zeigt alles, auch ältere Absagen — bis zu dieser Zahl.
BEWERBUNG_LISTE_MAX = 300

_STATUS_LABEL = {k: l for k, l, _c in BEWERBUNG_SPALTEN}
#: Chipfarbe je Status in der Liste (fw-chip-Modifikatoren aus der Schicht).
_STATUS_CLS = {'neu': 'fw-info', 'geprueft': 'fw-warn', 'besichtigung': 'fw-info',
               'zugesagt': 'fw-good', 'abgelehnt': 'fw-crit'}


def _bewerbung_karte(b, heute):
    """Was eine Karte des Boards (und eine Zeile der Liste) über eine Bewerbung zeigt.

    Keine Abfrage je Karte: Die Punktezahl rechnet `bewerte_bewerbung` aus den
    Feldern der Bewerbung und der vorgeladenen Einheit, und die Löschfrist
    entsteht für Abgelehnte allein aus `aktualisiert_am` (siehe
    `core.services.bewerbung_aufbewahrung.entschieden_am`). Für andere Status
    würde `naechste_frist` die Verträge der Einheit lesen — sie wird deshalb
    nur für Abgelehnte gerufen.
    """
    from core.services.bewerber_scoring import bewerte_bewerbung
    from core.services.bewerbung_aufbewahrung import DOKUMENT_FELDER, naechste_frist
    from mietprozess.workflow import erlaubte_spalten, spalte_von

    e = b.einheit
    brutto = (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0'))
    bewertung = bewerte_bewerbung(b, brutto)
    faktor = bewertung['tragbarkeit_faktor']
    karte = {
        'b': b, 'spalte': spalte_von(b),
        'score': bewertung['score'], 'ampel': bewertung['ampel'],
        # Anteil der Bruttomiete am Einkommen, als Kehrwert des Faktors aus
        # `bewerte_bewerbung` — keine eigene Regel, nur eine andere Schreibweise.
        'tragbarkeit': (Decimal('100') / faktor).quantize(Decimal('1')) if faktor else None,
        'auszug_fehlt': not (b.betreibungsauszug or b.digitaler_betreibungsauszug),
        'pruefpunkte': b.pruefpunkte(),
        'status_label': _STATUS_LABEL.get(b.status, b.status),
        'status_cls': _STATUS_CLS.get(b.status, 'fw-mut'),
        'ziele': erlaubte_spalten(b),
        'frist': None, 'frist_dokumente': False,
    }
    karte['pruefung_ok'] = sum(1 for p in karte['pruefpunkte'] if p['ok'])
    if karte['spalte'] == 'abgelehnt':
        karte['frist'] = naechste_frist(b, heute)
        karte['frist_dokumente'] = any(getattr(b, f, None) for f in DOKUMENT_FELDER)
    return karte


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerbungen(request):
    """Bewerbungen als Board in vier Spalten — oder als Liste.

    Das Board ist die Arbeitsfläche: Eingegangen, Geprüft, Abgelehnt (nur
    `ABGELEHNT_TAGE` lang) und Vertrag generiert. Die Liste (`?ansicht=liste`)
    zeigt dieselben Bewerbungen chronologisch und ohne die Frist, also auch
    ältere Absagen bis zur Anonymisierung — dort sucht, wer Auskunft geben
    muss, ob von einer Person noch Daten da sind.

    Filter: `?lg=` (Liegenschaft, `_global_filter`) und `?einheit=` (Objekt).
    """
    from datetime import timedelta
    from mietprozess.models import Mietbewerbung
    from mietprozess.workflow import ABGELEHNT_TAGE, SPALTEN

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    ansicht = 'liste' if request.GET.get('ansicht') == 'liste' else 'board'

    qs = (Mietbewerbung.objects.select_related('einheit__liegenschaft', 'vertrag')
          .order_by('-erstellt_am'))
    objekte = (Einheit.objects.filter(bewerbungen__isnull=False).distinct()
               .select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)
        objekte = objekte.filter(liegenschaft=aktive_lg)

    # Eine fremde Einheit findet der Mandantenfilter nicht — dann gilt kein
    # Objektfilter, wie bei einer fremden `?lg=`.
    einheit_roh = (request.GET.get('einheit') or '').strip()
    aktive_einheit = (Einheit.objects.select_related('liegenschaft').filter(id=einheit_roh).first()
                      if einheit_roh.isdigit() else None)
    if aktive_einheit:
        qs = qs.filter(einheit=aktive_einheit)

    heute = timezone.localdate()
    ausgeblendet = 0
    if ansicht == 'board':
        grenze = timezone.now() - timedelta(days=ABGELEHNT_TAGE)
        alt = dict(status='abgelehnt', vertrag__isnull=True, aktualisiert_am__lt=grenze)
        ausgeblendet = qs.filter(**alt).count()
        qs = qs.exclude(**alt)
        karten = [_bewerbung_karte(b, heute) for b in qs]
    else:
        zeilen = list(qs[:BEWERBUNG_LISTE_MAX + 1])
        ausgeblendet = max(0, len(zeilen) - BEWERBUNG_LISTE_MAX)
        karten = [_bewerbung_karte(b, heute) for b in zeilen[:BEWERBUNG_LISTE_MAX]]

    spalten = []
    if ansicht == 'board':
        reihenfolge = {
            # Geprüfte nach Punkten — dort wird ausgewählt. Sonst das Neueste zuerst.
            'geprueft': lambda k: (-k['score'], -k['b'].erstellt_am.timestamp()),
            'abgelehnt': lambda k: -k['b'].aktualisiert_am.timestamp(),
        }
        for key, label, _ziel in SPALTEN:
            eigene = [k for k in karten if k['spalte'] == key]
            if key in reihenfolge:
                eigene.sort(key=reihenfolge[key])
            spalten.append({'key': key, 'label': label, 'karten': eigene, 'anzahl': len(eigene)})

    from urllib.parse import urlencode
    filter_query = urlencode([(k, v) for k, v in (
        ('lg', aktive_lg.id if aktive_lg else ''),
        ('einheit', aktive_einheit.id if aktive_einheit else '')) if v])

    return render(request, 'fw/bewerbungen.html', {
        **basis, **_vermietung_pipeline('bewerbungen', basis['lg_query']), 'nav': 'bewerbungen',
        'ansicht': ansicht, 'spalten': spalten, 'karten': karten, 'gesamt': len(karten),
        'ausgeblendet': ausgeblendet, 'abgelehnt_tage': ABGELEHNT_TAGE,
        'liste_max': BEWERBUNG_LISTE_MAX,
        'objekte': objekte, 'aktive_einheit': aktive_einheit,
        'filter_query': ('?' + filter_query) if filter_query else '',
        'filter_amp': ('&' + filter_query) if filter_query else '',
        'kann_verschieben': basis['kann_schreiben'],
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerber_vergleich(request, einheit_id):
    """Vergleicht alle Bewerber eines Objekts mit Eignungs-Score (Tragbarkeit,
    Betreibungen, Anstellung, Unterlagen) als Entscheidungshilfe für die Mieterwahl."""
    from mietprozess.models import Mietbewerbung
    from core.services.bewerber_scoring import bewerte_bewerbung
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=einheit_id)
    basis = _global_filter(request)
    brutto_monat = (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0'))

    qs = Mietbewerbung.objects.filter(einheit=e).order_by('-erstellt_am')
    mit_abgelehnt = request.GET.get('alle') == '1'
    if not mit_abgelehnt:
        qs = qs.exclude(status='abgelehnt')

    kandidaten = []
    for b in qs:
        bewertung = bewerte_bewerbung(b, brutto_monat)
        s_label, s_cls = dict((k, (l, c)) for k, l, c in BEWERBUNG_SPALTEN).get(b.status, (b.status, 'fw-flaeche2 fw-mutet'))
        kandidaten.append({
            'b': b, 'name': f"{b.vorname} {b.nachname}",
            'haushalt': b.anzahl_erwachsene + b.anzahl_kinder,
            'bezug': b.gewuenschter_bezugstermin,
            'haustiere': b.haustiere, 'status': b.status,
            's_label': s_label, 's_cls': s_cls,
            **bewertung,
        })
    kandidaten.sort(key=lambda k: -k['score'])
    # Indikator-Spaltentitel aus dem ersten Kandidaten (fixe Reihenfolge)
    indikator_labels = [i['label'] for i in kandidaten[0]['indikatoren']] if kandidaten else []
    offene_n = sum(1 for k in kandidaten
                   if k['status'] in SAMMELABSAGE_STATUS and not k['b'].vertrag_id)

    from django.contrib import messages
    return render(request, 'fw/bewerber_vergleich.html', {
        **basis, 'nav': 'vermarktung', 'e': e,
        'objekt': f"{e.liegenschaft.strasse}, {e.liegenschaft.ort}" if e.liegenschaft_id else e.bezeichnung,
        'brutto_monat': brutto_monat, 'jahresmiete': brutto_monat * 12,
        'kandidaten': kandidaten, 'indikator_labels': indikator_labels,
        'mit_abgelehnt': mit_abgelehnt, 'offene_n': offene_n,
        'meldung': list(messages.get_messages(request)),
    })


def _termin_text(termin):
    """«Dienstag, 01.10.2026 um 14:00 Uhr» für die Einladung.

    Nicht `strftime('%A')`: das richtet sich nach der Server-Locale und gab
    «Tuesday» in einer deutschen E-Mail. Bis Dokumente der Sprache des
    Empfängers folgen (D11), bleibt die Einladung Deutsch.
    """
    from django.utils import dateformat, translation
    lokal = timezone.localtime(termin)
    with translation.override('de'):
        return f"{dateformat.format(lokal, 'l, d.m.Y')} um {dateformat.format(lokal, 'H:i')} Uhr"


def _bewerber_mail(b, entscheid):
    """Baut (betreff, body) für Zusage/Absage — aus Vorlage (falls vorhanden) mit
    Platzhaltern, sonst Standardtext."""
    from crm.models import Vorlage, Organisation
    vw = aktuelle_organisation()
    e = b.einheit
    lg = e.liegenschaft if e else None
    objekt = f"{e.bezeichnung}" + (f", {lg.strasse}, {lg.plz} {lg.ort}" if lg else "")
    brutto = (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0')) if e else Decimal('0')
    ctx = {
        'bewerber_name': f"{b.vorname} {b.nachname}",
        'objekt': objekt, 'liegenschaft': lg.strasse if lg else '',
        'miete': f"CHF {brutto:.2f}", 'vermieter': (vw.firma if vw else 'Ihre Liegenschaftsverwaltung'),
        'datum': timezone.now().strftime('%d.%m.%Y'),
    }
    kat = 'bewerber_zusage' if entscheid == 'zusage' else 'bewerber_absage'
    v = Vorlage.objects.filter(kategorie=kat).first()
    if v and v.inhalt:
        body = v.inhalt
        betreff = v.betreff or (f"Ihre Bewerbung für {objekt}")
        for k, val in ctx.items():
            body = body.replace('{' + k + '}', str(val))
            betreff = betreff.replace('{' + k + '}', str(val))
    elif entscheid == 'zusage':
        betreff = f"Zusage für Ihre Wohnungsbewerbung – {objekt}"
        body = (f"Guten Tag {ctx['bewerber_name']}\n\nWir freuen uns, Ihnen das Mietobjekt "
                f"{objekt} zusagen zu können. Wir melden uns in Kürze mit den Vertragsunterlagen.\n\n"
                f"Freundliche Grüsse\n{ctx['vermieter']}")
    else:
        betreff = f"Ihre Wohnungsbewerbung – {objekt}"
        body = (f"Guten Tag {ctx['bewerber_name']}\n\nVielen Dank für Ihre Bewerbung für {objekt} "
                f"und Ihr Interesse. Wir haben uns für eine andere Bewerbung entschieden und wünschen "
                f"Ihnen bei der weiteren Wohnungssuche viel Erfolg.\n\nFreundliche Grüsse\n{ctx['vermieter']}")
    return betreff, body


def _entscheid_anwenden(request, b, entscheid):
    """Zusage oder Absage setzen und die Mail dazu schicken. True = Mail ging raus.

    Ein Weg für alle, die entscheiden: Vergleich, Sammelabsage und Board.
    Die Mail kommt aus der Vorlage `bewerber_zusage`/`bewerber_absage`
    (`_bewerber_mail`); der Versand steht im Journal.

    `aktualisiert_am` wird ausdrücklich mitgeschrieben. `auto_now` greift bei
    `update_fields` nur für genannte Felder — bis 10/2026 behielt eine Absage
    so den Zeitstempel der letzten früheren Änderung. Daran hängen aber die
    Löschfrist (`bewerbung_aufbewahrung.entschieden_am`: «Zeitpunkt der
    letzten Änderung») und die 30 Tage, die eine Absage auf dem Board steht.

    Bei einer Absage wird eine offene Besichtigungs-Pendenz erledigt: Der
    Termin mit einer abgelehnten Person findet nicht mehr statt.
    """
    from core.utils.email_service import journal_email, send_ticket_email
    b.status = 'zugesagt' if entscheid == 'zusage' else 'abgelehnt'
    b.save(update_fields=['status', 'aktualisiert_am'])
    if entscheid == 'absage':
        from core.models import Pendenz
        Pendenz.objects.filter(quelle=f'besichtigung:{b.id}', erledigt=False).update(
            erledigt=True, erledigt_am=timezone.localdate())
    if not b.email:
        return False
    betreff, body = _bewerber_mail(b, entscheid)
    ok = send_ticket_email(b.email, betreff, body)
    if ok:
        journal_email(betreff, body, user=request.user,
                      empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    return ok


def _kein_wechsel_text(b, ziel_label):
    """Meldung für einen Statuswechsel, den `mietprozess.workflow` nicht vorsieht."""
    if b.vertrag_id:
        return gettext('Aus dieser Bewerbung ist bereits ein Vertrag entstanden. '
                       'Den Stand ändern Sie im Vertrag.')
    return gettext('Von «%(von)s» nach «%(nach)s» ist kein Wechsel vorgesehen.') % {
        'von': b.get_status_display(), 'nach': ziel_label}


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_besichtigung(request, pk):
    """Lädt einen Bewerber zur Besichtigung ein: Termin speichern, Status setzen,
    Einladung per E-Mail (mit Journal-Eintrag)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.utils.email_service import send_ticket_email, journal_email
    from core.auth import log_aktion
    from datetime import datetime as _dt
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    termin_raw = (request.POST.get('termin') or '').strip()   # datetime-local: YYYY-MM-DDTHH:MM
    termin = None
    if termin_raw:
        try:
            termin = timezone.make_aware(_dt.fromisoformat(termin_raw))
        except Exception:
            termin = None
    if termin is None:
        messages.error(request, gettext('Bitte einen gültigen Besichtigungstermin wählen.'))
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    b.besichtigung_am = termin
    if b.status in ('neu', 'geprueft'):
        b.status = 'besichtigung'
    b.save(update_fields=['besichtigung_am', 'status'])
    lg = b.einheit.liegenschaft
    ok = False
    if b.email:
        betreff = f"Einladung zur Besichtigung — {lg.strasse}, {b.einheit.bezeichnung}"
        body = (f"Guten Tag {b.vorname} {b.nachname}\n\n"
                f"Gerne laden wir Sie zur Besichtigung des Objekts "
                f"{lg.strasse}, {lg.plz} {lg.ort} ({b.einheit.bezeichnung}) ein.\n\n"
                f"Termin: {_termin_text(termin)}\n"
                f"Treffpunkt: Hauseingang {lg.strasse}\n\n"
                f"Bitte bestätigen Sie uns den Termin kurz per E-Mail. Falls er Ihnen "
                f"nicht passt, melden Sie sich für eine Alternative.\n\n"
                f"Freundliche Grüsse\nIhre Verwaltung")
        ok = send_ticket_email(b.email, betreff, body)
        if ok:
            journal_email(betreff, body, user=request.user,
                          empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    # Termin ins Fristen-Center (idempotent pro Bewerbung — Termin-Änderung
    # aktualisiert die bestehende Pendenz statt eine zweite zu erzeugen).
    from core.models import Pendenz
    Pendenz.objects.update_or_create(
        quelle=f'besichtigung:{b.id}',
        defaults={
            'titel': f"Besichtigung {b.vorname} {b.nachname} — {b.einheit.bezeichnung}",
            'beschreibung': (f"Besichtigungstermin {timezone.localtime(termin).strftime('%d.%m.%Y %H:%M')} · "
                             f"{lg.strasse}, {lg.plz} {lg.ort}. Treffpunkt Hauseingang."),
            'kategorie': 'frist', 'faellig_am': termin.date(),
            'liegenschaft': lg, 'erledigt': False,
            'erstellt_von': request.user if request.user.is_authenticated else None,
        })
    log_aktion(request, "Besichtigung eingeladen", f"{b.vorname} {b.nachname}",
               timezone.localtime(termin).strftime('%d.%m.%Y %H:%M'))
    wann = timezone.localtime(termin).strftime('%d.%m.%Y %H:%M')
    if ok:
        meldung = gettext('Besichtigung %(wann)s erfasst · Einladung an %(email)s gesendet.') % {
            'wann': wann, 'email': b.email}
    else:
        meldung = gettext('Besichtigung %(wann)s erfasst.') % {'wann': wann}
    messages.success(request, '✅ ' + meldung)
    return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_entscheid(request, pk):
    """Zusage/Absage einer Bewerbung: setzt Status + sendet dem Bewerber eine
    (Vorlagen-)E-Mail. entscheid = 'zusage' | 'absage'."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from mietprozess.workflow import status_erlaubt
    from core.auth import log_aktion
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    entscheid = request.POST.get('entscheid')
    if entscheid not in ('zusage', 'absage'):
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    ziel_status = 'zugesagt' if entscheid == 'zusage' else 'abgelehnt'
    # Idempotenz: dieselbe Entscheidung nicht doppelt setzen (sonst geht bei jedem
    # Klick erneut eine Zu-/Absage-Mail an den Bewerber raus).
    if b.status == ziel_status:
        messages.info(request, gettext('Diese Bewerbung wurde bereits zugesagt.') if entscheid == 'zusage' else gettext('Diese Bewerbung wurde bereits abgesagt.'))
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    if not status_erlaubt(b, ziel_status):
        messages.error(request, _kein_wechsel_text(b, _STATUS_LABEL[ziel_status]))
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    ok = _entscheid_anwenden(request, b, entscheid)
    if entscheid == 'zusage':
        # Modul 5: Begleitdokument nach Regel; Fehler protokolliert der Dienst.
        from core.services.dokument_regeln import dokument_fuer_ereignis
        dokument_fuer_ereignis('bewerber_zugesagt', organisation=b.organisation, bewerbung=b)
    log_aktion(request, f"Bewerber-{entscheid.capitalize()}", f"{b.vorname} {b.nachname}",
               b.einheit.bezeichnung if b.einheit_id else '')
    meldung = gettext('Zusage gesetzt.') if entscheid == 'zusage' else gettext('Absage gesetzt.')
    if ok:
        meldung += ' ' + gettext('E-Mail an %(email)s gesendet.') % {'email': b.email}
    messages.success(request, '✅ ' + meldung)
    return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')


#: Wer bei der Sammelabsage eine Absage bekommt. «besichtigung» kam 10/2026
#: dazu: Wer zur Besichtigung eingeladen war und nicht genommen wird, wartete
#: sonst ohne Antwort.
SAMMELABSAGE_STATUS = ('neu', 'geprueft', 'besichtigung')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_absage_uebrige(request, einheit_id):
    """Sendet allen noch offenen Bewerbern eines Objekts eine Absage — z. B. nach
    der Zusage an den gewählten Bewerber. Offen heisst: neu, geprüft oder zur
    Besichtigung eingeladen (`SAMMELABSAGE_STATUS`), und noch ohne Vertrag."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/vermarktung/{einheit_id}/bewerber/')
    # Gehört die Einheit überhaupt hierher? Die Bewerbungsabfrage unten ist
    # zwar gefiltert und fand bei einer fremden Einheit ohnehin nichts — aber
    # der Lauf schrieb trotzdem einen Logbucheintrag „Bewerber-Sammelabsage,
    # Objekt #<fremde id>". Ein Eintrag über einen fremden Datensatz gehört
    # nicht ins eigene Logbuch, und die Rückmeldung „0 abgesagt" verrät
    # ausserdem, dass die ID existiert.
    from portfolio.models import Einheit
    get_object_or_404(Einheit, id=einheit_id)
    offene = Mietbewerbung.objects.filter(einheit_id=einheit_id, status__in=SAMMELABSAGE_STATUS,
                                          vertrag__isnull=True)
    n = mails = 0
    for b in offene.select_related('einheit__liegenschaft'):
        n += 1
        if _entscheid_anwenden(request, b, 'absage'):
            mails += 1
    log_aktion(request, "Bewerber-Sammelabsage", f"Objekt #{einheit_id}", f"{n} abgesagt")
    meldung = gettext('%(n)s offene Bewerbung(en) abgesagt.') % {'n': n}
    if mails:
        meldung += ' ' + gettext('%(mails)s E-Mail(s) versendet.') % {'mails': mails}
    messages.success(request, '✅ ' + meldung)
    return redirect(f'/neu/vermarktung/{einheit_id}/bewerber/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerbung_detail(request, pk):
    from mietprozess.models import Mietbewerbung
    from mietprozess.workflow import erlaubte_status
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft', 'vertrag'), id=pk)
    basis = _global_filter(request)

    dokumente = []
    for feld, label in [('betreibungsauszug', 'Betreibungsauszug'), ('ausweiskopie', 'Ausweiskopie'),
                        ('lohnausweis', 'Lohnausweis'), ('weitere_dokumente', 'Weitere Dokumente')]:
        f = getattr(b, feld, None)
        if f:
            dokumente.append({'label': label, 'url': f.url})

    status_label = dict((k, l) for k, l, _ in BEWERBUNG_SPALTEN).get(b.status, b.status)
    # Nur der heutige Status und die erlaubten Ziele (`mietprozess.workflow`).
    erlaubt = {b.status, *erlaubte_status(b)}
    status_wahl = [(k, l, c) for k, l, c in BEWERBUNG_SPALTEN if k in erlaubt]
    from django.contrib import messages
    return render(request, 'fw/bewerbung_detail.html', {
        **basis, 'nav': 'bewerbungen', 'b': b, 'dokumente': dokumente,
        'status_label': status_label, 'status_wahl': status_wahl,
        'pruefpunkte': b.pruefpunkte(),
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerbung_unterlagen(request, pk):
    """Zweite Stufe: Ausweis und Einkommensnachweis nachtragen.

    Das öffentliche Formular fragt diese Unterlagen nicht mehr ab — der EDÖB
    lässt sie erst von der ausgewählten Person oder einer engeren Auswahl
    verlangen, «sobald sich ein Vertragsabschluss konkretisiert». Damit das
    keine leere Zusage bleibt, gibt es den Weg hier: Die Bewirtschaftung legt
    die nachgereichten Unterlagen am Dossier ab. Für die Löschfristen zählen
    sie wie alle anderen (siehe core.services.bewerbung_aufbewahrung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.auth import log_aktion
    b = get_object_or_404(Mietbewerbung, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{b.id}/')
    abgelegt = []
    for feld, label in (('ausweiskopie', gettext_noop('Ausweiskopie')),
                        ('lohnausweis', gettext_noop('Einkommensnachweis')),
                        ('weitere_dokumente', gettext_noop('Weitere Unterlagen'))):
        datei = request.FILES.get(feld)
        if datei:
            getattr(b, feld).save(datei.name, datei, save=False)
            abgelegt.append(label)
    if abgelegt:
        b.save()
        log_aktion(request, "Bewerbungsunterlagen nachgetragen",
                   f"{b.vorname} {b.nachname}", ", ".join(abgelegt))
        messages.success(request, '✅ ' + gettext('Abgelegt: %(unterlagen)s.')
                         % {'unterlagen': ', '.join(gettext(label) for label in abgelegt)})
    else:
        messages.info(request, gettext('Keine Datei gewählt.'))
    return redirect(f'/neu/bewerbungen/{b.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerbung_status(request, pk):
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from mietprozess.workflow import status_erlaubt
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{pk}/')
    b = get_object_or_404(Mietbewerbung, id=pk)
    neu = request.POST.get('status')
    gueltig = {k for k, _, _ in BEWERBUNG_SPALTEN}
    if neu in gueltig and not status_erlaubt(b, neu):
        # Dieselben Übergänge wie auf dem Board (`mietprozess.workflow`).
        messages.error(request, _kein_wechsel_text(b, _STATUS_LABEL[neu]))
    elif neu in gueltig:
        b.status = neu
        b.save()
        log_aktion(request, "Bewerbungsstatus geändert", f"{b.vorname} {b.nachname}", neu)
        messages.success(request, gettext('Status auf „%(wert)s“ gesetzt.') % {'wert': dict((k,l) for k,l,_ in BEWERBUNG_SPALTEN)[neu]})
    return redirect(f'/neu/bewerbungen/{pk}/')


def _aktuelle_basis(einheit):
    """(Referenzzinssatz, LIK) der Verwaltung der Einheit — der Stand HEUTE.

    Fehlt der Verwaltung ein Wert, wird der Stand der Einheit genommen, und nur
    wenn auch der fehlt, bleibt das Feld leer statt mit einem geratenen Wert
    gefüllt zu werden (ein leeres Basisfeld fällt auf, ein falscher Satz nicht)."""
    org = getattr(einheit.liegenschaft, 'organisation', None) if einheit.liegenschaft_id else None
    zins = getattr(org, 'aktueller_referenzzinssatz', None) or einheit.ref_zinssatz
    lik = getattr(org, 'aktueller_lik_punkte', None) or einheit.lik_punkte
    return zins, lik


def _vertrag_aus_bewerbung(request, b):
    """Mieter aus der Bewerbung anlegen (oder finden) und den Vertragsentwurf
    erstellen. Gibt (vertrag, neu_angelegt) zurück.

    Idempotent am Verweis `b.vertrag`: Steht er, entsteht nichts Neues. Bis
    10/2026 suchte diese Stelle einen Entwurf über Name und E-Mail des Mieters
    auf derselben Einheit — und traf damit auch den Entwurf einer anderen
    Bewerbung mit gleichem Namen. Der Bestand ist über die Migration
    `mietprozess.0010_vertrag_aus_bestand_zuordnen` zugeordnet, wo das
    eindeutig ging.

    Den Mieter sucht die Stelle weiterhin über E-Mail und Nachname: Das ist der
    Duplikatschutz im Personenstamm (eine Person, die schon Mieter ist, wird
    nicht ein zweites Mal angelegt), nicht die Zuordnung zum Vertrag.

    Die Prüfung, ob der Wechsel erlaubt ist, macht der Aufrufer.
    """
    from core.auth import log_aktion
    if b.vertrag_id:
        return b.vertrag, False
    einheit = b.einheit

    # 1. Mieter finden oder anlegen (Duplikat-Schutz über E-Mail + Name)
    mieter = None
    if b.email:
        mieter = Mieter.objects.filter(email__iexact=b.email, nachname__iexact=b.nachname).first()
    if not mieter:
        mieter = Mieter.objects.create(
            typ='person',
            # Seit MIET-13 wird das Geschlecht nicht mehr erfragt: ohne Angabe bleibt die Anrede leer
            # (der Vertragsassistent erhebt sie), statt «Herr» zu raten.
            anrede={'weiblich': 'Frau', 'maennlich': 'Herr'}.get(b.geschlecht, ''),
            vorname=b.vorname, nachname=b.nachname,
            geburtsdatum=b.geburtsdatum, zivilstand=b.zivilstand or '',
            nationalitaet=b.nationalitaet or '', heimatort=b.heimatort or '',
            erwerbsstatus=b.erwerbsstatus or '', beruf=b.beruf or '',
            arbeitgeber=b.arbeitgeber or '', einkommen_jahr=b.einkommen_jahr or '',
            email=b.email or '', mobile=b.mobilnummer or '',
            strasse=b.adresse or '', plz=b.plz or '', ort=b.ort or '',
            # Haushalt/Haustiere aus der Bewerbung in den Mieter-Stamm übernehmen.
            haushalt_erwachsene=b.anzahl_erwachsene or 0, haushalt_kinder=b.anzahl_kinder or 0,
            haustiere=bool(b.haustiere), haustiere_details=(b.haustiere_details or ''),
            # Bonität + Vorvermieter-Referenz aus der Bewerbung übernehmen (sonst
            # gehen sie beim Übergang Bewerber → Mieter verloren).
            betreibung_ergebnis=('offen' if b.hat_betreibungen else 'keine'),
            ref_vermieter_name=(b.aktueller_vermieter or ''),
            ref_vermieter_telefon=(b.telefon_vermieter or ''),
            ref_vermieter_email=(b.email_vermieter or ''),
        )

    # 2. Vertragsentwurf anlegen (mit Objekt-Defaults)
    from decimal import Decimal as _D
    beginn = b.gewuenschter_bezugstermin or timezone.localdate()
    kautionsmonate = einheit.standard_kautionsmonate or 0
    netto = einheit.nettomiete_aktuell or _D('0')
    nk = einheit.nebenkosten_aktuell or _D('0')
    kaution = (netto + nk) * kautionsmonate if kautionsmonate else None

    vertrag = Mietvertrag.objects.create(
        mieter=mieter, einheit=einheit, status='entwurf', beginn=beginn,
        netto_mietzins=netto, nebenkosten=nk,
        nk_abrechnungsart=einheit.nk_abrechnungsart or 'akonto',
        anzahl_personen=(b.anzahl_erwachsene or 1) + (b.anzahl_kinder or 0),
        kautions_betrag=kaution,
        # BASIS EINES NEUEN VERTRAGS = STAND BEI ABSCHLUSS, nicht der Stand, der beim
        # Anlegen der Einheit galt (Stresstest 30.09.2026: Der Nachmieter startete
        # mit 1.25 %, obwohl der Satz bei 1.00 % lag — jede spätere Anpassung nach
        # Art. 269a OR rechnet von dieser Basis aus). `Einheit.ref_zinssatz` ist nur
        # der Wert vom Tag der Erfassung der Einheit.
        basis_referenzzinssatz=_aktuelle_basis(einheit)[0],
        basis_lik_punkte=_aktuelle_basis(einheit)[1],
        besondere_vereinbarungen=(f"Haustiere: {b.haustiere_details}" if b.haustiere and b.haustiere_details else ''),
    )

    b.vertrag = vertrag
    b.status = 'zugesagt'
    b.save()
    # Objekt ist vergeben → aus der Vermarktung/Feed/Exposé nehmen.
    if einheit.zur_ausschreibung:
        einheit.zur_ausschreibung = False
        einheit.save(update_fields=['zur_ausschreibung'])
    log_aktion(request, "Bewerbung → Vertragsentwurf", f"{mieter.display_name}",
               f"{einheit.bezeichnung}, Entwurf #{vertrag.id}", ziel=vertrag)
    return vertrag, True


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerbung_zu_vertrag(request, pk):
    """Zusage: Mieter aus der Bewerbung anlegen (oder finden) und einen
    Vertragsentwurf auf der Einheit erstellen — mit den Objekt-Defaults vorbefüllt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from mietprozess.workflow import status_erlaubt
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{pk}/')

    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft', 'vertrag'), id=pk)
    if b.vertrag_id:
        messages.info(request, gettext('Für diese Bewerbung existiert bereits ein Vertragsentwurf.'))
        return redirect(f'/neu/vertraege/{b.vertrag_id}/')
    if not status_erlaubt(b, 'zugesagt'):
        messages.error(request, _kein_wechsel_text(b, _STATUS_LABEL['zugesagt']))
        return redirect(f'/neu/bewerbungen/{b.id}/')

    vertrag, _neu = _vertrag_aus_bewerbung(request, b)
    messages.success(request,
        '✅ ' + gettext('Mieter angelegt und Vertragsentwurf für %(bezeichnung)s erstellt — bitte Konditionen prüfen und aktivieren.') % {'bezeichnung': b.einheit.bezeichnung})
    return redirect(f'/neu/vertraege/{vertrag.id}/')


def _verschieben_antwort(request, b, ok, text, status=200, weiter=None):
    """JSON für das Ziehen, Weiterleitung mit Meldung für das Auswahlfeld —
    wie `tickets_board._antwort`."""
    from django.contrib import messages
    from django.http import JsonResponse
    from django.shortcuts import redirect
    from mietprozess.workflow import erlaubte_spalten, spalte_von
    als_json = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('accept', ''))
    if als_json:
        return JsonResponse({
            'ok': ok, 'meldung': str(text), 'spalte': spalte_von(b), 'status': b.status,
            'ziele': [[k, str(label)] for k, label in erlaubte_spalten(b)],
            'weiter': weiter or ''}, status=status)
    (messages.success if ok else messages.error)(request, text)
    if ok and weiter:
        return redirect(weiter)
    # Zurück auf das Board mit denselben Filtern — nur Ziffern übernehmen.
    from urllib.parse import urlencode
    filter_ = [(k, request.POST.get(k, '')) for k in ('lg', 'einheit')]
    query = urlencode([(k, v) for k, v in filter_ if v.isdigit()])
    return redirect('/neu/bewerbungen/' + (f'?{query}' if query else ''))


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_bewerbung_verschieben(request, pk):
    """Spaltenwechsel vom Board — als Ziehen (JSON) oder Auswahlfeld (Formular).

    * **Geprüft** setzt `geprueft`.
    * **Abgelehnt** setzt die Absage samt Mail (`_entscheid_anwenden`). Im
      Browser fragt vorher ein Dialog nach.
    * **Vertrag generiert** legt Mieter und Vertragsentwurf an
      (`_vertrag_aus_bewerbung`) und nennt die Vertragsseite als `weiter`.
    * Alles, was `mietprozess.workflow` nicht vorsieht, ergibt 400; die Karte
      springt zurück.
    """
    from mietprozess.models import Mietbewerbung
    from mietprozess.workflow import SPALTEN, spalte_erlaubt, spalte_von
    from core.auth import log_aktion

    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft', 'vertrag'), id=pk)
    spalte = request.POST.get('spalte', '')
    labels = {k: label for k, label, _z in SPALTEN}

    def antwort(ok, text, status=200, weiter=None):
        return _verschieben_antwort(request, b, ok, text, status, weiter)

    if spalte not in labels:
        return antwort(False, gettext('Unbekannte Spalte.'), 400)
    if spalte == spalte_von(b):
        return antwort(True, gettext('Keine Änderung.'))
    if not spalte_erlaubt(b, spalte):
        return antwort(False, _kein_wechsel_text(b, labels[spalte]), 400)

    name = f"{b.vorname} {b.nachname}"
    if spalte == 'abgelehnt':
        mail = _entscheid_anwenden(request, b, 'absage')
        log_aktion(request, "Bewerber-Absage", name,
                   f"{b.einheit.bezeichnung} (Board)")
        text = gettext('Absage gesetzt.')
        if mail:
            text += ' ' + gettext('E-Mail an %(email)s gesendet.') % {'email': b.email}
        return antwort(True, text)
    if spalte == 'vertrag':
        vertrag, _neu = _vertrag_aus_bewerbung(request, b)
        return antwort(True, gettext('Vertragsentwurf für %(bezeichnung)s erstellt — bitte '
                                     'Konditionen prüfen und aktivieren.') % {
                           'bezeichnung': b.einheit.bezeichnung},
                       weiter=f'/neu/vertraege/{vertrag.id}/')

    b.status = 'geprueft'
    b.save(update_fields=['status', 'aktualisiert_am'])
    log_aktion(request, "Bewerbungsstatus geändert", name, 'geprueft (Board)')
    return antwort(True, gettext('%(name)s: %(status)s.') % {
        'name': name, 'status': b.get_status_display()})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_bewerbung_pruefung(request, pk):
    """Einen Punkt der Prüf-Checkliste abhaken oder zurücknehmen.

    Entscheid E7: Die Checkliste zeigt den Stand und ist kein Riegel — der
    Status bleibt unberührt. Gespeichert wird nur `pruefung`; `aktualisiert_am`
    bleibt stehen, weil an ihm die Löschfrist und die Sichtbarkeit einer
    Absage auf dem Board hängen.
    """
    from django.contrib import messages
    from django.shortcuts import redirect
    from mietprozess.models import Mietbewerbung, PRUEFPUNKTE
    from core.auth import log_aktion

    b = get_object_or_404(Mietbewerbung, id=pk)
    punkte = dict(PRUEFPUNKTE)
    punkt = request.POST.get('pruefung', '')
    if punkt not in punkte:
        messages.error(request, gettext('Unbekannter Prüfpunkt.'))
        return redirect(f'/neu/bewerbungen/{b.id}/')
    ok = request.POST.get('ok') == '1'
    wer = (request.user.get_full_name() or request.user.get_username()).strip()
    stand = dict(b.pruefung) if isinstance(b.pruefung, dict) else {}
    stand[punkt] = {'ok': ok, 'von': wer, 'am': timezone.now().isoformat(timespec='seconds')}
    b.pruefung = stand
    b.save(update_fields=['pruefung'])
    log_aktion(request, "Bewerbung geprüft", f"{b.vorname} {b.nachname}",
               f"{punkte[punkt]}: {'ja' if ok else 'nein'}")
    messages.success(request, (gettext('«%(punkt)s» abgehakt.') if ok
                               else gettext('«%(punkt)s» zurückgenommen.')) % {'punkt': punkte[punkt]})
    return redirect(f'/neu/bewerbungen/{b.id}/')
