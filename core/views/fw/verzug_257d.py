# core/views/fw/verzug_257d.py
#
# Zahlungsverzug nach Art. 257d OR mit Zugangs- und Sendungsnachweis.
# Aus kuendigung.py herausgeloest (reiner Umzug ohne Aenderung am Code).

import logging
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN,
                       VERWALTUNGS_ROLLEN)
from rentals.models import Mietvertrag

from ._basis import _global_filter
from core.services.unterschrift import UNTERSCHRIFT_HINWEIS_257D
from core.services.zahlungsverzug import ABHOLFRIST_TAGE, FRIST_TAGE, POSTWEG_TAGE

logger = logging.getLogger(__name__)


# Die Fristansetzung nach Art. 257d OR ist Inhabern und Verwaltern vorbehalten
# (seit 28.09.2026, vorher auch der Sachbearbeitung): Sie setzt die Frist in
# Gang, nach deren Ablauf ausserordentlich gekündigt werden kann — dieselbe
# Stufe wie «Mahnlauf und Betreibung» und «Kündigung» in docs/KONZEPT-UI.md §8.
# `fw_verzug_zugang` und `fw_verzug_sendung` bleiben bei SCHREIB_ROLLEN: Sie
# tragen Tatsachen aus der Post nach (Zugang, Sendungsnummer), damit die
# bereits angesetzte Frist richtig berechnet ist — keine Entscheidung.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_verzug_257d(request, vertrag_id):
    """Zahlungsverzug (Art. 257d OR): fällige Miete offen → Zahlungsaufforderung mit
    Fristansetzung (Dokument + Fristen-Pendenz). Nach fruchtlosem Ablauf kann
    ausserordentlich gekündigt werden (Abs. 2). GET: Formular · POST: Frist ansetzen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from datetime import timedelta
    from finance.models import DebitorenRechnung
    from crm.models import Organisation
    from core.models import Pendenz
    from core.auth import log_aktion
    from core.services.serienbrief import generate_serienbrief_pdf
    from core.services.ablage import ablegen

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    heute = timezone.localdate()
    lg = v.einheit.liegenschaft if v.einheit_id else None

    # Fristansetzung nach Art. 257d Abs. 1 OR: Genannt und summiert werden nur die fälligen **Mietzinse und
    # Nebenkosten** (Audit MIET-02) — dieselbe Auswahl wie `zahlungsverzug.gedeckte_forderungen`, die über die
    # Wahrung der Frist entscheidet. Weiterverrechnung, Selbstbehalt, Schlussabrechnung, Mahngebühr und Zins
    # gehören nicht in die Androhung; die Seite sagt, was ausgenommen ist.
    from core.services.zahlungsverzug import provisorisches_fristende, verzugsforderungen
    from core.services.fristen import fristende as _fristende, naechster_werktag
    faellige = [r for r in verzugsforderungen(v, heute) if r.status in ('offen', 'teilbezahlt')]
    offen_total = sum((r.offener_betrag for r in faellige), Decimal('0.00'))
    ids_gedeckt = {r.pk for r in faellige}
    ausgenommen = [r for r in DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
                   if r.pk not in ids_gedeckt and (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= heute]
    ausgenommen_total = sum((r.offener_betrag for r in ausgenommen), Decimal('0.00'))

    # Mindestfrist: Wohn-/Geschäftsräume 30 Tage, sonst 10 Tage (Art. 257d Abs. 1).
    # Die Frist läuft ab ZUGANG beim Mieter (Empfangstheorie), nicht ab Absendetag. Beim Einschreiben ist der
    # Zugang die tatsächliche Abholung, bei Nichtabholung der letzte Tag der siebentägigen Abholfrist
    # (BGE 119 II 147 E. 2) — nicht die Abholeinladung. Das vorläufige Fristende rechnet darum vom
    # ungünstigsten Fall: Postweg + Abholfrist + Frist. Es ist nie zu kurz (Audit MIET-01); den genauen Zugang
    # trägt «Zugang bestätigen» nach.
    min_frist = 30 if v.ist_geschuetzt else 10
    zustell_tage = POSTWEG_TAGE + ABHOLFRIST_TAGE
    # Standard-Frist: mindestens 30 Tage ab Zugang (30 Tage sind für alle Objektarten sicher, da ≥ der
    # gesetzlichen Mindestfrist), zuzüglich Postweg und Abholfrist.
    default_frist = _fristende(heute, max(FRIST_TAGE, min_frist) + zustell_tage).isoformat()

    if request.method == 'POST':
        # Ohne fälligen Rückstand an Mietzins oder Nebenkosten gibt es nichts anzudrohen (Art. 257d Abs. 1 OR).
        # Weiterverrechnung, Selbstbehalt oder Mahngebühr allein tragen keine Fristansetzung.
        if offen_total <= 0:
            messages.error(request, '⛔ ' + gettext(
                'Es gibt keinen fälligen Rückstand an Mietzins oder Nebenkosten. Eine Fristansetzung mit '
                'Kündigungsandrohung nach Art. 257d OR setzt einen solchen voraus; andere Forderungen '
                '(Weiterverrechnung, Selbstbehalt, Mahngebühr) zählen nicht.'))
            return redirect(f'/neu/vertraege/{v.id}/verzug/')
        _min_frist_bis = _fristende(heute, min_frist + zustell_tage)
        try:
            frist = date.fromisoformat(request.POST.get('frist_bis') or default_frist)
        except ValueError:
            frist = _min_frist_bis
        # Gesetzliche Mindestfrist SERVERSEITIG erzwingen: Für Wohn-/Geschäftsräume sind es 30 Tage
        # (Art. 257d Abs. 1 OR) ab ZUGANG. Ein aus dem Formular übermittelter zu kurzer Wert würde die
        # Fristansetzung zu kurz machen (Live-Test I). Ohne Versanddatum ist der Zugang unbekannt: Das
        # vorläufige Fristende muss deshalb den Postweg und die siebentägige Abholfrist enthalten.
        if frist < _min_frist_bis:
            frist = _min_frist_bis
            messages.info(request, gettext(
                'Die Frist wurde verlängert: Sie läuft %(tage)s Tage ab Zugang (Art. 257d Abs. 1 OR), und der Zugang '
                'liegt frühestens nach Postweg und siebentägiger Abholfrist des Einschreibens.') % {'tage': min_frist})

        # Einschreiben-Zustellung: Die Frist läuft ab ZUGANG (Empfangstheorie): bei Zustellung oder Abholung
        # der Tag, an dem der Mieter das Schreiben erhält, bei Nichtabholung der letzte Tag der siebentägigen
        # Abholfrist (BGE 119 II 147 E. 2) — NICHT ab der Abholeinladung. Beim Erfassen ist der Zugang noch
        # unbekannt → faellig_am ist PROVISORISCH (Versand + Postweg + Abholfrist + Frist, nie zu kurz) und
        # wird über «Zugang bestätigen» (aus Track & Trace) auf den Zugang + frist_tage nachgezogen.
        # FRIST_TAGE = 30 = Brieftext «innert 30 Tagen ab Erhalt».
        sendungsnummer = (request.POST.get('sendungsnummer') or '').strip()[:40]
        try:
            versand_am = date.fromisoformat(request.POST.get('versand_am')) if request.POST.get('versand_am') else None
        except ValueError:
            versand_am = None
        if versand_am:
            frist = provisorisches_fristende(versand_am, FRIST_TAGE)
        # Art. 78 OR: Das letzte Tag der Frist ist ein Werktag.
        frist = naechster_werktag(frist)
        vw = v.organisation      # Briefkopf des Vertrags, nicht der aeltesten Verwaltung
        m = v.mieter
        # Dasselbe 257d-PDF wie /vertrag/<id>/mahnung/ (sauberer Brief mit
        # Kuendigungsandrohung + QR-Rechnung) statt eines generischen Serienbriefs.
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        from core.utils.qr_code import sammelreferenz

        # Empfaenger: Primaer (Mieter) + separat adressierte Kopien. Art. 266n OR
        # erfasst die Fristansetzung nach 257d: bei FAMILIENWOHNUNG muss sie Mieter
        # UND Ehegatten SEPARAT zugestellt werden (sonst nichtig, Art. 266o), ebenso
        # solidarisch haftende Mitmieter (WG). empfaenger=None → vertrag.mieter.
        def _ovr(person=None, name=None):
            if person is not None:
                return {'firma': getattr(person, 'firma', None), 'name': person.display_name,
                        'strasse': person.strasse or m.strasse,
                        'ort_line': f"{person.plz or m.plz} {person.ort or m.ort}",
                        'nachname': person.nachname, 'anrede': getattr(person, 'anrede', '')}
            return {'firma': None, 'name': name, 'strasse': m.strasse,
                    'ort_line': f"{m.plz} {m.ort}", 'nachname': name, 'anrede': ''}
        zustellungen = [None]
        if v.familienwohnung:
            if v.mitmieter_id:
                zustellungen.append(_ovr(person=v.mitmieter))
            elif (v.mitmieter_name or '').strip():
                zustellungen.append(_ovr(name=v.mitmieter_name.strip()))
        elif v.mitmieter_id:
            zustellungen.append(_ovr(person=v.mitmieter))
        for wm in (v.weitere_mieter.all() if v.pk else []):
            zustellungen.append(_ovr(person=wm))

        _monat = (min((r.faellig_am or r.datum) for r in faellige)).strftime('%m/%Y') if faellige else heute.strftime('%m/%Y')
        _betrag = f"{offen_total:.2f}"
        # Jede verzugsbegründende Forderung einzeln mit Monat und Betrag (Audit MIET-02).
        _positionen = [(r.titel, r.faellig_am or r.datum, r.offener_betrag) for r in faellige]
        pdf = None
        abgelegt = []
        for i, ovr in enumerate(zustellungen):
            # Eine einzelne QRR trägt nur EINE Forderung: Bei mehreren gemahnten
            # Forderungen steht die Sammelreferenz des Vertrags auf dem Schein.
            # Sie ist gültig, wird aber keiner Einzelforderung zugeschlagen. Eine
            # LEERE Referenz ergäbe zur QR-IBAN einen Einzahlungsschein mit «NON»,
            # den das E-Banking ablehnt — der Mieter könnte nicht zahlen, und die
            # darauf gestützte Kündigung wäre angreifbar (FIN-11).
            _ref = (faellige[0].qr_referenz if len(faellige) == 1 else '') or sammelreferenz(v.id)
            try:
                _p = generate_mahnung_combined_pdf_bytes(v, vw, _monat, _betrag, heute,
                                                         empfaenger=ovr, reference=_ref,
                                                         positionen=_positionen)
            except Exception:
                logger.exception("257d: Zahlungsaufforderung für Vertrag %s nicht erzeugt", v.pk)
                messages.error(request, '⛔ ' + gettext(
                    'Die Zahlungsaufforderung wurde nicht erzeugt, weil der Einzahlungsschein fehlerhaft wäre. '
                    'Bitte IBAN und Anschrift der Verwaltung prüfen; es wurde nichts gespeichert oder versandt.'))
                return redirect(f'/neu/vertraege/{v.id}/')
            if i == 0:
                pdf = _p
            _to = ovr['name'] if ovr else m.display_name
            abgelegt.append(ablegen(_p, f"Zahlungsaufforderung 257d – {_to} – Frist {frist:%d.%m.%Y}",
                                    kategorie='korrespondenz', vertrag=v, dedup=False,
                                    zugang_pflichtig=True))
        if len(zustellungen) > 1:
            messages.info(request, f"📮 {len(zustellungen)} separat adressierte 257d-Briefe erzeugt "
                                   "(Art. 266n OR: Familienwohnung/Mitmieter) — jede Kopie einzeln "
                                   "per Einschreiben zustellen.")
        # Fristen-Pendenz: läuft am Fristende ab → dann ausserordentliche Kündigung möglich.
        # Bei Einschreiben ist faellig_am provisorisch (siehe oben) und wird über
        # «Zugang bestätigen» definitiv gesetzt (Zugang + frist_tage).
        _provisorisch = bool(versand_am or sendungsnummer)
        _bt = (f"Offene Miete CHF {offen_total:.2f}. "
               + (f"Einschreiben {sendungsnummer or '—'}"
                  + (f", versandt {versand_am:%d.%m.%Y}" if versand_am else "")
                  + f". PROVISORISCH bis {frist:%d.%m.%Y} — gerechnet vom spätestmöglichen Zugang (Versand + "
                    f"{POSTWEG_TAGE} Tag Postweg + {ABHOLFRIST_TAGE} Tage Abholfrist + {FRIST_TAGE} Tage). Die "
                    f"definitive {FRIST_TAGE}-Tage-Frist läuft ab bestätigtem Zugang: tatsächliche Abholung, bei "
                    "Nichtabholung der letzte Tag der Abholfrist (BGE 119 II 147). "
                  if _provisorisch else
                  f"Zahlungsfrist bis {frist:%d.%m.%Y} (Art. 257d Abs. 1 OR), gerechnet mit Postweg und "
                  f"Abholfrist eines Einschreibens. ")
               + "Nach fruchtlosem Ablauf: ausserordentliche Kündigung mit 30 Tagen auf Monatsende "
                 "(Art. 257d Abs. 2 OR). Das Schreiben ist vor dem Versand eigenhändig zu unterschreiben.")
        from core.services.zahlungsverzug import fall_eroeffnen, quelle_fuer, vorschlaege_erledigen
        _benutzer = request.user if request.user.is_authenticated else None
        _frist_pendenz = Pendenz.objects.create(
            titel=f"Art. 257d: Zahlungsfrist läuft ab – {v.mieter.display_name}",
            beschreibung=_bt, quelle=quelle_fuer(v),
            kategorie='frist', faellig_am=frist, vertrag=v, liegenschaft=lg,
            sendungsnummer=sendungsnummer, versand_am=versand_am, frist_tage=FRIST_TAGE,
            erstellt_von=_benutzer,
        )
        # Die abgelegten Briefe gehören zu dieser Frist: Ihr Zustellstand in der Akte folgt
        # Sendungsnummer und «Zugang bestätigen» der Pendenz (`Dokument.zustellstatus`).
        for _dok in (d for d in abgelegt if d is not None):
            _dok.frist_pendenz_id = _frist_pendenz.pk
            _dok.save(update_fields=['frist_pendenz_id'])
        # Der Gesamtvorgang: Fall «Zahlungsverzug» an der Vertragsakte. Eine
        # Zahlung innert Frist schliesst Frist und Fall zusammen
        # (core/services/zahlungsverzug.py, ausgelöst in finance/signals.py).
        vorschlaege_erledigen(v, 'Fristansetzung nach Art. 257d OR erfolgt.')
        fall_eroeffnen(v, benutzer=_benutzer, frist=frist,
                       betreff=f"Zahlungsverzug {v.mieter.display_name} – CHF {offen_total:.2f}")
        log_aktion(request, "Zahlungsaufforderung 257d erstellt", str(v.mieter),
                   f"Frist bis {frist:%d.%m.%Y}, offen CHF {offen_total:.2f}", ziel=v)
        if request.POST.get('als_pdf') == '1':
            from django.http import HttpResponse
            resp = HttpResponse(pdf, content_type='application/pdf')
            resp['Content-Disposition'] = f'inline; filename="Zahlungsaufforderung_{v.mieter.nachname}.pdf"'
            return resp
        messages.success(request, '✅ ' + gettext('Zahlungsaufforderung erstellt – Frist bis %(frist)s. Fristen-Pendenz angelegt.') % {'frist': format(frist, '%d.%m.%Y')})
        messages.warning(request, UNTERSCHRIFT_HINWEIS_257D)
        return redirect(f'/neu/vertraege/{v.id}/')

    return render(request, 'fw/verzug_257d.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'lg': lg,
        'offen_total': offen_total, 'anzahl_faellig': len(faellige),
        'faellige': faellige, 'ausgenommen_total': ausgenommen_total, 'ausgenommen_anzahl': len(ausgenommen),
        'zustell_tage': zustell_tage, 'abholfrist_tage': ABHOLFRIST_TAGE,
        'min_frist': min_frist, 'default_frist': default_frist,
        'heute_iso': heute.isoformat(),
    })


def _zugang_setzen(p, zugang, fingiert=False):
    """Trägt den bestätigten Zugang an der Fristen-Pendenz ein und zieht die Frist nach:
    definitive Zahlungsfrist = Zugang + `frist_tage` (ein Samstag, Sonntag oder Feiertag rückt auf den nächsten
    Werktag, Art. 78 OR). Gibt das neue Fristende zurück.

    `zugang` ist der Tag, an dem der Mieter das Schreiben erhalten hat — bei Nichtabholung (`fingiert=True`) der
    letzte Tag der siebentägigen Abholfrist (BGE 119 II 147 E. 2), nicht die Abholeinladung."""
    from core.services.zahlungsverzug import definitives_fristende
    from core.services.brief_aus_vorlage import ist_brief_pendenz
    if ist_brief_pendenz(p):
        return _brief_zugang_setzen(p, zugang, fingiert)
    tage = p.frist_tage or 30
    neu_frist = definitives_fristende(zugang, tage)
    p.zugang_am = zugang
    p.zugang_fingiert = bool(fingiert)
    p.faellig_am = neu_frist
    p.beschreibung = ((f"Zugang fingiert am {zugang:%d.%m.%Y} (Einschreiben nicht abgeholt: letzter Tag der "
                       f"{ABHOLFRIST_TAGE}-tägigen Abholfrist)" if fingiert
                       else f"Zugang bestätigt am {zugang:%d.%m.%Y} (Abholung/Zustellung)")
                      + (f" (Einschreiben {p.sendungsnummer})" if p.sendungsnummer else "")
                      + f". Definitive {tage}-Tage-Zahlungsfrist bis {neu_frist:%d.%m.%Y} "
                        "(Art. 257d Abs. 1 OR, Empfangstheorie; ein Wochenend- oder Feiertag rückt auf den "
                        "nächsten Werktag, Art. 78 OR). Nach fruchtlosem Ablauf: "
                        "ausserordentliche Kündigung mit 30 Tagen auf Monatsende (Art. 257d Abs. 2 OR).")
    p.save(update_fields=['zugang_am', 'zugang_fingiert', 'faellig_am', 'beschreibung'])
    if p.vertrag_id:
        from core.services.zahlungsverzug import fall_frist_nachfuehren
        fall_frist_nachfuehren(p.vertrag, neu_frist)
    return neu_frist


def _brief_zugang_setzen(p, zugang, fingiert=False):
    """Zugang eines Briefs aus einer Vorlage (Einschreiben, `quelle` «brief:…»). Gibt das Fristende zurück (oder None).

    Frist «Tage ab Zugang» (`frist_tage` gesetzt): Fristende = Zugang + Tage, ein Nicht-Werktag rückt auf den nächsten
    (Art. 78 OR). Frist «festes Datum» oder keine Frist: das Fristende bleibt, wie es im Brief steht. Kein 257d-Fall,
    kein Fall an der Vertragsakte."""
    from core.services.zahlungsverzug import definitives_fristende
    p.zugang_am = zugang
    p.zugang_fingiert = bool(fingiert)
    felder = ['zugang_am', 'zugang_fingiert', 'beschreibung']
    art = (f"Einschreiben nicht abgeholt: Zugang fingiert am {zugang:%d.%m.%Y} (letzter Tag der "
           f"{ABHOLFRIST_TAGE}-tägigen Abholfrist)" if fingiert
           else f"Zugang bestätigt am {zugang:%d.%m.%Y} (Abholung/Zustellung)")
    neu_frist = None
    if p.frist_tage:
        neu_frist = definitives_fristende(zugang, p.frist_tage)
        p.faellig_am = neu_frist
        felder.append('faellig_am')
        art += f". Frist von {p.frist_tage} Tagen läuft bis {neu_frist:%d.%m.%Y}"
    p.beschreibung = (art + (f" (Einschreiben {p.sendungsnummer})" if p.sendungsnummer else '') + '.')
    p.save(update_fields=felder)
    return neu_frist or p.faellig_am


def _zugang_aus_formular(post, versand_am, heute):
    """(Zugangsdatum, fingiert, Fehlertext) aus den Feldern `zugang_am` und `zugang_art`.

    `zugang_art`:
    · `abgeholt` (Vorgabe) — `zugang_am` ist der Tag der Zustellung oder Abholung.
    · `nicht_abgeholt` — `zugang_am` ist der Tag der Abholeinladung; der Zugang wird auf den letzten Tag der
      siebentägigen Abholfrist fingiert. Das geht erst, wenn die Abholfrist abgelaufen ist; vorher kann der
      Mieter das Schreiben noch abholen (und der Zugang wäre früher).
    Ein Zugang vor dem Versand ist unmöglich; ein Zugang in der Zukunft wird auf heute geklemmt (wie bisher)."""
    from core.services.zahlungsverzug import fiktiver_zugang
    roh = post.get('zugang_am')
    try:
        tag = date.fromisoformat(roh) if roh else heute
    except ValueError:
        tag = heute
    if post.get('zugang_art') == 'nicht_abgeholt':
        if tag > heute:
            tag = heute
        fiktiv = fiktiver_zugang(tag)
        if versand_am and tag < versand_am:
            return None, False, gettext('Die Abholeinladung kann nicht vor dem Versand liegen.')
        if fiktiv > heute:
            return None, False, gettext(
                'Die Abholfrist läuft noch bis %(datum)s: Bis dahin kann der Mieter das Einschreiben noch '
                'abholen. Den Zugang erst danach als «nicht abgeholt» erfassen — oder die Abholung eintragen.'
            ) % {'datum': f'{tag + _timedelta(days=ABHOLFRIST_TAGE):%d.%m.%Y}'}
        return fiktiv, True, ''
    if tag > heute:
        tag = heute          # Zugang kann frühestens heute erfolgt sein — kein Zukunftsdatum
    if versand_am and tag < versand_am:
        return None, False, gettext('Der Zugang kann nicht vor dem Versand liegen.')
    return tag, False, ''


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_verzug_zugang(request, pk):
    """Bestätigt den ZUGANG eines 257d-Einschreibens (Empfangstheorie, BGE 119 II 147 E. 2).

    Die 30-Tage-Zahlungsfrist läuft ab dem Tag, an dem der Mieter das Schreiben erhalten hat — NICHT ab Versand
    und NICHT ab der Abholeinladung:

    · `zugang_art=abgeholt` (Vorgabe): `zugang_am` ist der Tag der Zustellung bzw. tatsächlichen Abholung
      (Track & Trace).
    · `zugang_art=nicht_abgeholt`: `zugang_am` ist der Tag der Abholeinladung; der Zugang wird auf den letzten
      Tag der siebentägigen Abholfrist fingiert (erst möglich, wenn diese Frist abgelaufen ist).

    Setzt zugang_am und zieht faellig_am auf Zugang + frist_tage nach (Fristende auf den nächsten Werktag,
    Art. 78 OR) — so steht im Fristen-Center die korrekte, verlässliche Frist."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.models import Pendenz
    from core.auth import log_aktion
    p = get_object_or_404(Pendenz.objects.select_related('vertrag__mieter'), id=pk)
    if request.method != 'POST':
        return redirect('fw_fristen')
    heute = timezone.localdate()
    nxt = request.POST.get('next') or ''
    ziel = nxt if nxt.startswith('/neu/') and '//' not in nxt[1:] else None
    zugang, fingiert, fehler = _zugang_aus_formular(request.POST, p.versand_am, heute)
    if fehler:
        messages.error(request, '⛔ ' + fehler)
        return redirect(ziel or 'fw_fristen')
    neu_frist = _zugang_setzen(p, zugang, fingiert=fingiert)
    from core.services.brief_aus_vorlage import ist_brief_pendenz
    if ist_brief_pendenz(p):
        log_aktion(request, "Einschreiben: Zugang fingiert (nicht abgeholt)" if fingiert else "Einschreiben: Zugang bestätigt",
                   p.titel, f"Zugang {zugang:%d.%m.%Y}{' (fingiert)' if fingiert else ''}"
                   + (f", Frist bis {neu_frist:%d.%m.%Y}" if neu_frist else ''),
                   ziel=p.vertrag if p.vertrag_id else None)
        messages.success(request, '✅ ' + (gettext('Einschreiben nicht abgeholt: Zugang fingiert am %(datum)s.')
                                           if fingiert else gettext('Zugang bestätigt (%(datum)s).'))
                         % {'datum': f'{zugang:%d.%m.%Y}'}
                         + ((' ' + gettext('Frist bis %(frist)s.') % {'frist': f'{neu_frist:%d.%m.%Y}'}) if p.frist_tage and neu_frist else ''))
        return redirect(ziel or 'fw_fristen')
    log_aktion(request, "257d-Zugang fingiert (nicht abgeholt)" if fingiert else "257d-Zugang bestätigt",
               str(p.vertrag.mieter) if p.vertrag_id and p.vertrag and p.vertrag.mieter_id else p.titel,
               f"Zugang {zugang:%d.%m.%Y}{' (fingiert)' if fingiert else ''}, Frist neu bis {neu_frist:%d.%m.%Y}",
               ziel=p.vertrag if p.vertrag_id else None)
    if fingiert:
        messages.success(request, f"✅ Einschreiben nicht abgeholt: Zugang fingiert am {zugang:%d.%m.%Y} "
                                  f"(letzter Tag der Abholfrist) — Zahlungsfrist läuft bis {neu_frist:%d.%m.%Y} "
                                  "(Art. 257d Abs. 1 OR).")
    else:
        messages.success(request, f"✅ Zugang bestätigt ({zugang:%d.%m.%Y}) — Zahlungsfrist läuft neu bis "
                                  f"{neu_frist:%d.%m.%Y} (Art. 257d Abs. 1 OR).")
    # Zurück zur aufrufenden Seite (Fristen-Center, Vertrag oder Kontakt) statt stur
    # ins Fristen-Center — nur seiten-relative /neu/-Ziele zulassen (kein Open-Redirect).
    return redirect(ziel or 'fw_fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_verzug_sendung(request, pk):
    """Korrigiert die Einschreiben-Sendungsnummer (und optional das Versanddatum)
    einer 257d-Frist-Pendenz — z.B. wenn die Track-&-Trace-Nummer vertippt wurde.
    Solange der Zugang noch nicht bestätigt ist, wird die provisorische Frist aus
    dem neuen Versanddatum neu berechnet (Versand + 1 Tag Postweg + 7 Tage Abholfrist + frist_tage, auf den
    nächsten Werktag gerückt)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from datetime import timedelta
    from core.models import Pendenz
    from core.auth import log_aktion
    p = get_object_or_404(Pendenz.objects.select_related('vertrag__mieter'), id=pk)
    if request.method != 'POST':
        return redirect('fw_fristen')
    heute = timezone.localdate()
    p.sendungsnummer = (request.POST.get('sendungsnummer') or '').strip()[:40]
    felder = ['sendungsnummer']
    # Versanddatum nur vor bestätigtem Zugang anpassbar (danach zählt zugang_am).
    if not p.zugang_am and request.POST.get('versand_am'):
        try:
            vs = date.fromisoformat(request.POST['versand_am'])
        except ValueError:
            vs = None
        if vs and vs <= heute:
            from core.services.zahlungsverzug import provisorisches_fristende
            from core.services.brief_aus_vorlage import ist_brief_pendenz
            p.versand_am = vs
            felder.append('versand_am')
            # Brief mit festem Fristdatum (oder ohne Frist): das Datum steht im Brief, es wird nicht neu gerechnet.
            if not ist_brief_pendenz(p) or p.frist_tage:
                p.faellig_am = provisorisches_fristende(vs, p.frist_tage)
                felder.append('faellig_am')
    p.save(update_fields=felder)
    from core.services.brief_aus_vorlage import ist_brief_pendenz as _brief
    if 'faellig_am' in felder and p.vertrag_id and not _brief(p):
        from core.services.zahlungsverzug import fall_frist_nachfuehren
        fall_frist_nachfuehren(p.vertrag, p.faellig_am)
    log_aktion(request, "Einschreiben-Sendungsnummer erfasst" if _brief(p) else "257d-Sendungsnummer korrigiert",
               str(p.vertrag.mieter) if p.vertrag_id and p.vertrag and p.vertrag.mieter_id else p.titel,
               p.sendungsnummer or '—', ziel=p.vertrag if p.vertrag_id else None)
    messages.success(request, '✅ ' + (gettext('Sendungsnummer aktualisiert.') if p.sendungsnummer
                                       else gettext('Sendungsnummer entfernt.')))
    nxt = request.POST.get('next') or ''
    if nxt.startswith('/neu/') and '//' not in nxt[1:]:
        return redirect(nxt)
    return redirect('fw_fristen')
