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


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerbungen(request):
    """Bewerbungen-Board, nach Status gruppiert."""
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (Mietbewerbung.objects.select_related('einheit__liegenschaft')
          .order_by('-erstellt_am'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    alle = list(qs)
    spalten = []
    for key, label, cls in BEWERBUNG_SPALTEN:
        eintraege = [b for b in alle if b.status == key]
        spalten.append({'key': key, 'label': label, 'cls': cls, 'items': eintraege, 'anzahl': len(eintraege)})

    return render(request, 'fw/bewerbungen.html', {
        **basis, **_vermietung_pipeline('bewerbungen', basis['lg_query']), 'nav': 'bewerbungen', 'spalten': spalten, 'gesamt': len(alle),
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
    offene_n = sum(1 for k in kandidaten if k['status'] in ('neu', 'geprueft'))

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
    from core.utils.email_service import send_ticket_email
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
    b.status = ziel_status
    b.save(update_fields=['status'])
    ok = False
    if b.email:
        betreff, body = _bewerber_mail(b, entscheid)
        ok = send_ticket_email(b.email, betreff, body)
        if ok:
            from core.utils.email_service import journal_email
            journal_email(betreff, body, user=request.user,
                          empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    log_aktion(request, f"Bewerber-{entscheid.capitalize()}", f"{b.vorname} {b.nachname}",
               b.einheit.bezeichnung if b.einheit_id else '')
    meldung = gettext('Zusage gesetzt.') if entscheid == 'zusage' else gettext('Absage gesetzt.')
    if ok:
        meldung += ' ' + gettext('E-Mail an %(email)s gesendet.') % {'email': b.email}
    messages.success(request, '✅ ' + meldung)
    return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_absage_uebrige(request, einheit_id):
    """Sendet allen noch offenen (neu/geprüft) Bewerbern eines Objekts eine Absage
    — z. B. nach der Zusage an den gewählten Bewerber."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.utils.email_service import send_ticket_email
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
    offene = Mietbewerbung.objects.filter(einheit_id=einheit_id, status__in=['neu', 'geprueft'])
    n = mails = 0
    for b in offene.select_related('einheit__liegenschaft'):
        b.status = 'abgelehnt'
        b.save(update_fields=['status'])
        n += 1
        if b.email:
            betreff, body = _bewerber_mail(b, 'absage')
            if send_ticket_email(b.email, betreff, body):
                mails += 1
                from core.utils.email_service import journal_email
                journal_email(betreff, body, user=request.user,
                              empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    log_aktion(request, "Bewerber-Sammelabsage", f"Objekt #{einheit_id}", f"{n} abgesagt")
    meldung = gettext('%(n)s offene Bewerbung(en) abgesagt.') % {'n': n}
    if mails:
        meldung += ' ' + gettext('%(mails)s E-Mail(s) versendet.') % {'mails': mails}
    messages.success(request, '✅ ' + meldung)
    return redirect(f'/neu/vermarktung/{einheit_id}/bewerber/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerbung_detail(request, pk):
    from mietprozess.models import Mietbewerbung
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    basis = _global_filter(request)

    dokumente = []
    for feld, label in [('betreibungsauszug', 'Betreibungsauszug'), ('ausweiskopie', 'Ausweiskopie'),
                        ('lohnausweis', 'Lohnausweis'), ('weitere_dokumente', 'Weitere Dokumente')]:
        f = getattr(b, feld, None)
        if f:
            dokumente.append({'label': label, 'url': f.url})

    status_label = dict((k, l) for k, l, _ in BEWERBUNG_SPALTEN).get(b.status, b.status)
    from django.contrib import messages
    return render(request, 'fw/bewerbung_detail.html', {
        **basis, 'nav': 'bewerbungen', 'b': b, 'dokumente': dokumente,
        'status_label': status_label, 'status_wahl': BEWERBUNG_SPALTEN,
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
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{pk}/')
    b = get_object_or_404(Mietbewerbung, id=pk)
    neu = request.POST.get('status')
    gueltig = {k for k, _, _ in BEWERBUNG_SPALTEN}
    if neu in gueltig:
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


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerbung_zu_vertrag(request, pk):
    """Zusage: Mieter aus der Bewerbung anlegen (oder finden) und einen
    Vertragsentwurf auf der Einheit erstellen — mit den Objekt-Defaults vorbefüllt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{pk}/')

    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    einheit = b.einheit
    lg = einheit.liegenschaft

    # Idempotenz am ECHTEN Marker (nicht am Status): existiert für DIESEN Bewerber
    # bereits ein Vertragsentwurf auf dieser Einheit, nicht erneut anlegen.
    # Wichtig: `fw_bewerber_entscheid` (Bewerber-Vergleich) setzt 'zugesagt' OHNE
    # Entwurf — der Status allein blockierte dann fälschlich die Umwandlung und
    # leitete auf einen fremden Entwurf derselben Einheit um.
    _bestehender = None
    if b.email:
        _bestehender = (Mietvertrag.objects
                        .filter(einheit=einheit, status='entwurf',
                                mieter__email__iexact=b.email,
                                mieter__nachname__iexact=b.nachname)
                        .order_by('-id').first())
    if _bestehender is None:
        _bestehender = (Mietvertrag.objects
                        .filter(einheit=einheit, status='entwurf',
                                mieter__vorname__iexact=b.vorname or '',
                                mieter__nachname__iexact=b.nachname or '')
                        .order_by('-id').first())
    if _bestehender:
        messages.info(request, gettext('Für diese Bewerbung existiert bereits ein Vertragsentwurf.'))
        return redirect(f'/neu/vertraege/{_bestehender.id}/')

    # 1. Mieter finden oder anlegen (Duplikat-Schutz über E-Mail + Name)
    mieter = None
    if b.email:
        mieter = Mieter.objects.filter(email__iexact=b.email, nachname__iexact=b.nachname).first()
    if not mieter:
        mieter = Mieter.objects.create(
            typ='person',
            anrede='Frau' if b.geschlecht == 'weiblich' else 'Herr',
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

    b.status = 'zugesagt'
    b.save()
    # Objekt ist vergeben → aus der Vermarktung/Feed/Exposé nehmen.
    if einheit.zur_ausschreibung:
        einheit.zur_ausschreibung = False
        einheit.save(update_fields=['zur_ausschreibung'])
    log_aktion(request, "Bewerbung → Vertragsentwurf", f"{mieter.display_name}",
               f"{einheit.bezeichnung}, Entwurf #{vertrag.id}", ziel=vertrag)
    messages.success(request,
        '✅ ' + gettext('Mieter angelegt und Vertragsentwurf für %(bezeichnung)s erstellt — bitte Konditionen prüfen und aktivieren.') % {'bezeichnung': einheit.bezeichnung})
    return redirect(f'/neu/vertraege/{vertrag.id}/')
