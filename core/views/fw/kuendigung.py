# core/views/fw/kuendigung.py
#
# Kuendigung erfassen, Fristen berechnen, Verzug nach Art. 257d OR mit
# Zugangs- und Sendungsnachweis, Zuruecknahme, Bestaetigung, amtliches
# Formular. Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Der fachlich heikelste Block bisher: Art. 257d (Zahlungsverzug), die
# ortsueblichen Kuendigungstermine und die kantonale Formularpflicht stehen
# alle im Skill schweizer-fachlogik als "niemals raten". Genau deshalb ist
# der Nachweis wichtig, dass hier NICHTS geaendert wurde -- Blockinhalt
# gegen HEAD Zeile fuer Zeile identisch.

from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTUNG, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter


# ============================================================
# KÜNDIGUNGSPROZESS (Erfassung + Fristenberechnung + Bestätigung)
# ============================================================

def _auszugscheckliste_anlegen(vertrag, kuendigung, per, user, mit_leerstand=False):
    """Legt die Standard-Auszugscheckliste als Pendenzen an (mit Fälligkeit relativ
    zum Vertragsende). Gibt die Anzahl erstellter Pendenzen zurück."""
    from core.models import Pendenz
    heute = timezone.localdate()
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    ist_vermieter = getattr(kuendigung, 'absender', '') == 'vermieter'

    def tage(offset):
        return (per + _timedelta(days=offset)) if per else heute

    # Erste Aufgabe je Kündigungs-Richtung UND Objektart: das amtliche Formular ist
    # nur bei Wohn-/Geschäftsräumen Pflicht (Art. 266l), nicht bei Nebenobjekten.
    if ist_vermieter:
        erste = "Amtliches Kündigungsformular versenden" if vertrag.ist_geschuetzt \
                else "Kündigung schriftlich mitteilen"
    else:
        erste = "Kündigung schriftlich bestätigen"
    aufgaben = [
        (erste, heute, 'vertrag'),
        ("Abnahmetermin mit Mieter vereinbaren", tage(-30), 'aufgabe'),
        ("Wohnungsabnahme durchführen (Protokoll)", per or heute, 'protokoll' if False else 'aufgabe'),
        # Art. 267a Abs. 1 OR: Mängel, für die der Mieter einzustehen hat, müssen
        # SOFORT nach der Rückgabe gerügt werden — sonst sind die Ersatzansprüche
        # verwirkt (Praxis: 2-3 Arbeitstage; versteckte Mängel bleiben vorbehalten).
        ("Mängelrüge Art. 267a: sofort nach Abnahme versenden", tage(2), 'frist'),
        ("Zählerstände ablesen & Ummeldung", per or heute, 'aufgabe'),
        ("Schlüssel-Rückgabe kontrollieren", per or heute, 'aufgabe'),
        ("Schlussabrechnung erstellen", tage(7), 'finanzen'),
        ("Kaution abrechnen / freigeben", tage(14), 'finanzen'),
    ]
    if mit_leerstand:
        aufgaben.append(("Nachmieter suchen / Inserat aufschalten", heute, 'aufgabe'))

    n = 0
    for titel, faellig, kat in aufgaben:
        # Duplikatschutz: gleiche Pendenz für diesen Vertrag nicht doppelt
        if Pendenz.objects.filter(vertrag=vertrag, titel=titel, erledigt=False).exists():
            continue
        Pendenz.objects.create(
            titel=titel, kategorie=(kat if kat in dict(Pendenz.KATEGORIE_CHOICES) else 'aufgabe'),
            faellig_am=faellig, liegenschaft=lg, vertrag=vertrag,
            beschreibung=f"Auszug {vertrag.mieter.display_name} · {vertrag.einheit.bezeichnung}",
            erstellt_von=user,
        )
        n += 1
    return n


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kuendigung_erfassen(request, vertrag_id):
    """Erfasst eine Kündigung, berechnet den Termin und setzt den Vertrag auf 'gekuendigt'."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from rentals.services import berechne_kuendigungstermin
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST

        def d(key):
            val = P.get(key)
            if not val:
                return None
            try:
                return date.fromisoformat(val)
            except ValueError:
                return None
        eingang = d('eingang_datum') or timezone.localdate()
        termin = berechne_kuendigungstermin(v, eingang)
        gewuenscht = d('gewuenschtes_ende')
        ausserord = P.get('ausserordentlich') == 'on'
        # Wirksames Ende: ausserordentlich → gewünschtes Datum. Ordentlich: ein zu
        # FRÜH gewünschtes Ende gilt von Gesetzes wegen auf den nächstmöglichen
        # Termin (Art. 266a Abs. 2 OR) — serverseitig auf den berechneten
        # ordentlichen Termin klemmen, sonst führen Vertragsende/Leerstand/
        # Sollstellung ein rechtlich unwirksames Datum.
        if ausserord and gewuenscht:
            per = gewuenscht
        elif gewuenscht and termin and gewuenscht < termin:
            per = termin
            messages.warning(request, f"⚠️ Gewünschtes Ende {gewuenscht:%d.%m.%Y} liegt vor dem "
                                      f"nächsten zulässigen Termin — die Kündigung gilt auf "
                                      f"{termin:%d.%m.%Y} (Art. 266a Abs. 2 OR).")
        else:
            per = gewuenscht or termin

        k = Kuendigung.objects.create(
            vertrag=v, absender=P.get('absender', 'mieter'),
            eingang_datum=eingang, zustellung=P.get('zustellung', 'einschreiben'),
            gewuenschtes_ende=gewuenscht, berechneter_termin=termin, per_datum=per,
            ende_vorher=v.ende,   # Snapshot der bisherigen Laufzeit (für Rücknahme)
            ausserordentlich=ausserord, ausserordentlich_grund=P.get('ausserordentlich_grund', '').strip(),
            erstreckung_bis=d('erstreckung_bis'), status='bestaetigt' if P.get('bestaetigen') == 'on' else 'erfasst',
            bemerkung=P.get('bemerkung', '').strip(),
        )
        # Vertrag auf gekündigt setzen
        v.status = 'gekuendigt'
        v.aktiv = False
        v.ende = per
        v.save(update_fields=['status', 'aktiv', 'ende'])

        # Anfechtungsfrist-Pendenz bei Vermieterkündigung geschützter Räume:
        # der Mieter kann die Kündigung innert 30 Tagen anfechten (Art. 271/273 OR).
        if k.absender == 'vermieter' and v.ist_geschuetzt:
            from core.models import Pendenz
            frist = eingang + _timedelta(days=30)
            Pendenz.objects.create(
                titel=f"Anfechtungsfrist Kündigung läuft ab – {v.mieter.display_name}",
                beschreibung=("Der Mieter kann die Vermieterkündigung innert 30 Tagen ab Empfang bei der "
                              "Schlichtungsbehörde anfechten (Art. 271/271a/273 OR) und eine Erstreckung "
                              "verlangen (Art. 272). Danach wird die Kündigung grundsätzlich rechtskräftig."),
                kategorie='frist', faellig_am=frist, vertrag=v,
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                erstellt_von=request.user if request.user.is_authenticated else None,
            )

        # Auszugscheckliste automatisch als Pendenzen anlegen
        leerstand_gewuenscht = P.get('leerstand_anlegen') == 'on'
        n_pendenzen = _auszugscheckliste_anlegen(v, k, per, request.user, mit_leerstand=leerstand_gewuenscht)

        # Leerstand ab Tag nach Vertragsende (opt-in)
        hinweis = ""
        if leerstand_gewuenscht and per and v.einheit_id:
            from rentals.models import Leerstand
            beginn = per + _timedelta(days=1)
            if not Leerstand.objects.filter(einheit=v.einheit, beginn=beginn, ende__isnull=True).exists():
                Leerstand.objects.create(einheit=v.einheit, beginn=beginn, grund='mietersuche',
                                         bemerkung=f"Automatisch aus Kündigung (Ende {per.strftime('%d.%m.%Y')})")
                hinweis = " · Leerstand ab " + beginn.strftime('%d.%m.%Y') + " angelegt"

        log_aktion(request, "Kündigung erfasst", str(v.mieter),
                   f"per {per.strftime('%d.%m.%Y') if per else '—'}, {n_pendenzen} Pendenzen{hinweis}", ziel=v)
        if P.get('embed'):
            return render(request, 'fw/_modal_done.html', {
                'msg': f"Kündigung erfasst · {n_pendenzen} Auszugs-Pendenzen"})
        messages.success(request, f"✅ Kündigung erfasst — Vertragsende {per.strftime('%d.%m.%Y') if per else '—'} · "
                         f"{n_pendenzen} Auszugs-Pendenzen erstellt{hinweis}.")
        return redirect(f'/neu/vertraege/{v.id}/')

    # Vorschau des nächsten Termins für heute
    vorschau_termin = berechne_kuendigungstermin(v, timezone.localdate())
    # Aus dem Verzugsprozess kommend → ausserordentliche Kündigung wegen Zahlungsverzug vorbelegen
    verzug = request.GET.get('grund') in ('verzug', '257d')
    from rentals.services import termin_257d
    ao_termin = termin_257d(timezone.localdate()) if verzug else None
    return render(request, 'fw/kuendigung_form.html', {
        **basis, 'nav': 'vertraege', 'v': v,
        'vorschau_termin': vorschau_termin, 'heute_iso': timezone.localdate().isoformat(),
        'prefill_ao': verzug,
        'prefill_grund': 'Zahlungsverzug (Art. 257d OR)' if verzug else '',
        'ao_termin': ao_termin,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
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

    # Offene, fällige Forderungen dieses Vertrags
    offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
    faellige = [r for r in offene if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= heute]
    offen_total = sum((r.offener_betrag for r in faellige), Decimal('0.00'))

    # Mindestfrist: Wohn-/Geschäftsräume 30 Tage, sonst 10 Tage (Art. 257d Abs. 1).
    # Die Frist läuft ab ZUGANG beim Mieter (Empfangstheorie), nicht ab Absendetag —
    # daher einen Zustellpuffer (Postweg + 7-tägige Abholfrist beim eingeschriebenen
    # Brief) aufschlagen, sonst wäre die Fristansetzung und eine darauf gestützte
    # ausserordentliche Kündigung zu kurz und damit nichtig.
    ZUSTELL_PUFFER = 7
    min_frist = 30 if v.ist_geschuetzt else 10
    # Standard-Frist: immer mindestens 30 Tage ab heute (Nutzerwunsch — 30 Tage ist
    # für alle Objektarten sicher, da ≥ der gesetzlichen Mindestfrist). Bei Wohn-/
    # Geschäftsräumen bleibt zusätzlich der Zustellpuffer erhalten (30+7 = 37 Tage),
    # damit die Frist ab Zugang die gesetzlichen 30 Tage nicht unterschreitet.
    default_frist = (heute + timedelta(days=max(30, min_frist + ZUSTELL_PUFFER))).isoformat()

    if request.method == 'POST':
        try:
            frist = date.fromisoformat(request.POST.get('frist_bis') or default_frist)
        except ValueError:
            frist = heute + timedelta(days=min_frist)
        # Gesetzliche Mindestfrist SERVERSEITIG erzwingen: Für Wohn-/Geschäftsräume
        # sind es 30 Tage (Art. 257d Abs. 1 OR). Ein aus dem Formular übermittelter
        # zu kurzer Wert (z.B. 10 Tage) würde die Fristansetzung — und eine darauf
        # gestützte ausserordentliche Kündigung — nichtig machen (Live-Test I).
        _min_frist_bis = heute + timedelta(days=min_frist)
        if frist < _min_frist_bis:
            frist = _min_frist_bis
            messages.info(request, f"Die Frist wurde auf die gesetzliche Mindestdauer "
                                   f"({min_frist} Tage, Art. 257d Abs. 1 OR) verlängert.")

        # Einschreiben-Zustellung + STRIKTE Empfangstheorie (Nutzerwunsch): Die
        # 30-Tage-Frist läuft ab ZUGANG (Eintritt in den Machtbereich = Zustellung /
        # Abholeinladung bei der Post), nicht ab Versand und OHNE 7-Tage-Abholfiktion.
        # Beim Erfassen ist der Zugang noch unbekannt → faellig_am ist PROVISORISCH und
        # wird über «Zugang bestätigen» (aus Track & Trace) auf zugang_am + frist_tage
        # nachgezogen. FRIST_TAGE = 30 = Brieftext «innert 30 Tagen ab Erhalt».
        sendungsnummer = (request.POST.get('sendungsnummer') or '').strip()[:40]
        try:
            versand_am = date.fromisoformat(request.POST.get('versand_am')) if request.POST.get('versand_am') else None
        except ValueError:
            versand_am = None
        FRIST_TAGE = 30
        POSTWEG_TAGE = 1  # geschätzter Postweg bis Zustellung/Abholeinladung (nur provisorisch)
        if versand_am:
            frist = versand_am + timedelta(days=POSTWEG_TAGE + FRIST_TAGE)
        vw = Organisation.objects.first()
        m = v.mieter
        # Dasselbe 257d-PDF wie /vertrag/<id>/mahnung/ (sauberer Brief mit
        # Kuendigungsandrohung + QR-Rechnung) statt eines generischen Serienbriefs.
        from core.views.email_views import generate_mahnung_combined_pdf_bytes

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
        pdf = None
        for i, ovr in enumerate(zustellungen):
            _p = generate_mahnung_combined_pdf_bytes(v, vw, _monat, _betrag, heute, empfaenger=ovr)
            if i == 0:
                pdf = _p
            _to = ovr['name'] if ovr else m.display_name
            ablegen(_p, f"Zahlungsaufforderung 257d – {_to} – Frist {frist:%d.%m.%Y}",
                    kategorie='korrespondenz', vertrag=v, dedup=False)
        if len(zustellungen) > 1:
            messages.info(request, f"📮 {len(zustellungen)} separat adressierte 257d-Briefe erzeugt "
                                   "(Art. 266n OR: Familienwohnung/Mitmieter) — jede Kopie einzeln "
                                   "per Einschreiben zustellen.")
        # Fristen-Pendenz: läuft am Fristende ab → dann ausserordentliche Kündigung möglich.
        # Bei Einschreiben ist faellig_am provisorisch (siehe oben) und wird über
        # «Zugang bestätigen» definitiv gesetzt (zugang_am + frist_tage).
        _provisorisch = bool(versand_am or sendungsnummer)
        _bt = (f"Offene Miete CHF {offen_total:.2f}. "
               + (f"Einschreiben {sendungsnummer or '—'}"
                  + (f", versandt {versand_am:%d.%m.%Y}" if versand_am else "")
                  + f". PROVISORISCH bis {frist:%d.%m.%Y} — definitive {FRIST_TAGE}-Tage-Frist läuft ab "
                    "bestätigtem Zugang (strikte Empfangstheorie: Zustellung/Abholeinladung). "
                  if _provisorisch else
                  f"Zahlungsfrist bis {frist:%d.%m.%Y} (Art. 257d Abs. 1 OR). ")
               + "Nach fruchtlosem Ablauf: ausserordentliche Kündigung mit 30 Tagen auf Monatsende "
                 "(Art. 257d Abs. 2 OR).")
        Pendenz.objects.create(
            titel=f"Art. 257d: Zahlungsfrist läuft ab – {v.mieter.display_name}",
            beschreibung=_bt,
            kategorie='frist', faellig_am=frist, vertrag=v, liegenschaft=lg,
            sendungsnummer=sendungsnummer, versand_am=versand_am, frist_tage=FRIST_TAGE,
            erstellt_von=request.user if request.user.is_authenticated else None,
        )
        log_aktion(request, "Zahlungsaufforderung 257d erstellt", str(v.mieter),
                   f"Frist bis {frist:%d.%m.%Y}, offen CHF {offen_total:.2f}", ziel=v)
        if request.POST.get('als_pdf') == '1':
            from django.http import HttpResponse
            resp = HttpResponse(pdf, content_type='application/pdf')
            resp['Content-Disposition'] = f'inline; filename="Zahlungsaufforderung_{v.mieter.nachname}.pdf"'
            return resp
        messages.success(request, f"✅ Zahlungsaufforderung erstellt – Frist bis {frist:%d.%m.%Y}. "
                                  "Fristen-Pendenz angelegt.")
        return redirect(f'/neu/vertraege/{v.id}/')

    return render(request, 'fw/verzug_257d.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'lg': lg,
        'offen_total': offen_total, 'anzahl_faellig': len(faellige),
        'min_frist': min_frist, 'default_frist': default_frist,
        'heute_iso': heute.isoformat(),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_verzug_zugang(request, pk):
    """Bestätigt den ZUGANG eines 257d-Einschreibens (strikte Empfangstheorie):
    Die 30-Tage-Zahlungsfrist läuft ab dem bestätigten Zugangsdatum (Eintritt in den
    Machtbereich = Zustellung/Abholeinladung laut Track & Trace), NICHT ab Versand und
    ohne 7-Tage-Fiktion. Setzt zugang_am und zieht faellig_am auf zugang_am + frist_tage
    nach — so steht im Fristen-Center die korrekte, verlässliche Frist."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from datetime import timedelta
    from core.models import Pendenz
    from core.auth import log_aktion
    p = get_object_or_404(Pendenz.objects.select_related('vertrag__mieter'), id=pk)
    if request.method != 'POST':
        return redirect('fw_fristen')
    heute = timezone.localdate()
    try:
        zugang = date.fromisoformat(request.POST.get('zugang_am')) if request.POST.get('zugang_am') else heute
    except ValueError:
        zugang = heute
    # Zugang kann frühestens heute erfolgt sein — kein Zukunftsdatum.
    if zugang > heute:
        zugang = heute
    tage = p.frist_tage or 30
    neu_frist = zugang + timedelta(days=tage)
    p.zugang_am = zugang
    p.faellig_am = neu_frist
    p.beschreibung = (f"Zugang bestätigt am {zugang:%d.%m.%Y}"
                      + (f" (Einschreiben {p.sendungsnummer})" if p.sendungsnummer else "")
                      + f". Definitive {tage}-Tage-Zahlungsfrist bis {neu_frist:%d.%m.%Y} "
                        "(Art. 257d Abs. 1 OR, strikte Empfangstheorie). Nach fruchtlosem Ablauf: "
                        "ausserordentliche Kündigung mit 30 Tagen auf Monatsende (Art. 257d Abs. 2 OR).")
    p.save(update_fields=['zugang_am', 'faellig_am', 'beschreibung'])
    log_aktion(request, "257d-Zugang bestätigt",
               str(p.vertrag.mieter) if p.vertrag_id and p.vertrag and p.vertrag.mieter_id else p.titel,
               f"Zugang {zugang:%d.%m.%Y}, Frist neu bis {neu_frist:%d.%m.%Y}",
               ziel=p.vertrag if p.vertrag_id else None)
    messages.success(request, f"✅ Zugang bestätigt ({zugang:%d.%m.%Y}) — Zahlungsfrist läuft neu bis "
                              f"{neu_frist:%d.%m.%Y} (Art. 257d Abs. 1 OR).")
    # Zurück zur aufrufenden Seite (Fristen-Center, Vertrag oder Kontakt) statt stur
    # ins Fristen-Center — nur seiten-relative /neu/-Ziele zulassen (kein Open-Redirect).
    nxt = request.POST.get('next') or ''
    if nxt.startswith('/neu/') and '//' not in nxt[1:]:
        return redirect(nxt)
    return redirect('fw_fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_verzug_sendung(request, pk):
    """Korrigiert die Einschreiben-Sendungsnummer (und optional das Versanddatum)
    einer 257d-Frist-Pendenz — z.B. wenn die Track-&-Trace-Nummer vertippt wurde.
    Solange der Zugang noch nicht bestätigt ist, wird die provisorische Frist aus
    dem neuen Versanddatum neu berechnet (Versand + 1 Tag Postweg + frist_tage)."""
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
            p.versand_am = vs
            p.faellig_am = vs + timedelta(days=1 + (p.frist_tage or 30))
            felder += ['versand_am', 'faellig_am']
    p.save(update_fields=felder)
    log_aktion(request, "257d-Sendungsnummer korrigiert",
               str(p.vertrag.mieter) if p.vertrag_id and p.vertrag and p.vertrag.mieter_id else p.titel,
               p.sendungsnummer or '—', ziel=p.vertrag if p.vertrag_id else None)
    messages.success(request, "✅ Sendungsnummer aktualisiert." if p.sendungsnummer
                     else "✅ Sendungsnummer entfernt.")
    nxt = request.POST.get('next') or ''
    if nxt.startswith('/neu/') and '//' not in nxt[1:]:
        return redirect(nxt)
    return redirect('fw_fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kuendigung_zuruecknehmen(request, pk):
    """Nimmt eine Kündigung zurück und reaktiviert den Vertrag."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    k = get_object_or_404(Kuendigung, id=pk)
    v = k.vertrag
    if request.method == 'POST':
        k.status = 'zurueckgezogen'
        k.save(update_fields=['status'])
        # Vertrag reaktivieren, wenn keine andere aktive Kündigung besteht
        andere = v.kuendigungen.exclude(id=k.id).exclude(status='zurueckgezogen').exists()
        if not andere:
            v.status = 'aktiv'
            v.aktiv = True
            # Vertragsende wiederherstellen. Ein UNbefristeter Vertrag läuft nach
            # der Rücknahme wieder auf unbestimmte Zeit (ende = None). Bei einem
            # BEFRISTETEN Vertrag wird die ursprünglich vereinbarte Laufzeit aus dem
            # Snapshot (`ende_vorher`, bei Kündigungserfassung gesichert) restauriert
            # — sonst bliebe der bei einer ausserordentlichen Kündigung gesetzte
            # frühere Termin stehen und die vereinbarte Dauer wäre verloren (QS-Befund).
            if not v.ist_befristet:
                v.ende = None
            elif k.ende_vorher is not None:
                v.ende = k.ende_vorher
            # (befristet ohne Snapshot = Alt-Kündigung: `ende` unverändert lassen —
            #  nicht auf None, der Vertrag ist befristet.)
            v.save(update_fields=['status', 'aktiv', 'ende'])
        log_aktion(request, "Kündigung zurückgezogen", str(v.mieter), '', ziel=v)
        messages.success(request, "✅ Kündigung zurückgezogen, Vertrag reaktiviert.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kuendigung_bestaetigen(request, pk):
    """Bestätigt eine (i.d.R. über das Mieterportal eingegangene) Kündigung:
    setzt den Vertrag auf 'gekuendigt' und legt die Auszugs-Pendenzen an."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    k = get_object_or_404(Kuendigung.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    v = k.vertrag
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    if k.status == 'zurueckgezogen':
        messages.error(request, "Zurückgezogene Kündigung kann nicht bestätigt werden.")
        return redirect(f'/neu/vertraege/{v.id}/')

    per = k.per_datum or k.berechneter_termin
    k.status = 'bestaetigt'
    k.save(update_fields=['status'])
    v.status = 'gekuendigt'
    v.aktiv = False
    v.ende = per
    v.save(update_fields=['status', 'aktiv', 'ende'])

    n_pendenzen = _auszugscheckliste_anlegen(v, k, per, request.user, mit_leerstand=False)
    # Bestätigung erfolgt → 'Kündigung schriftlich bestätigen' abhaken
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(v, ['schriftlich', 'Kündigungsformular'], user=request.user)
    log_aktion(request, "Kündigung bestätigt", str(v.mieter),
               f"per {per.strftime('%d.%m.%Y') if per else '—'}, {n_pendenzen} Pendenzen", ziel=v)
    messages.success(request, f"✅ Kündigung bestätigt — Vertragsende {per.strftime('%d.%m.%Y') if per else '—'} · "
                     f"{n_pendenzen} Auszugs-Pendenzen erstellt.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kuendigung_formular(request, pk):
    """Amtliches Kündigungsformular (PDF) — Original des zuständigen Kantons ausfüllen.
    Art. 266n OR: Kündigt der Vermieter eine Familienwohnung, werden zwei separat an
    Mieter UND Ehegatte adressierte Kopien erzeugt (sonst ist die Kündigung nichtig)."""
    from django.http import HttpResponse
    from django.contrib import messages
    from rentals.models import Kuendigung
    from crm.models import Organisation
    k = get_object_or_404(Kuendigung.objects.select_related(
        'vertrag__mieter', 'vertrag__mitmieter', 'vertrag__einheit__liegenschaft'), id=pk)
    vw = Organisation.objects.first()
    from core.services.formular_fill import kuendigung_zustellkopien
    from core.services.ablage import ablegen
    kopien = kuendigung_zustellkopien(k.vertrag, k, verwaltung=vw)

    for empf_name, pdf in kopien:
        suffix = f" — Zustellung an {empf_name}" if empf_name else ""
        ablegen(pdf, f"Kündigung {k.get_absender_display()} {k.eingang_datum:%d.%m.%Y}{suffix}",
                kategorie='vertrag', vertrag=k.vertrag, dedup=True)

    # Amtliches Formular erstellt → 'schriftlich bestätigen / Formular versenden' abhaken
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(k.vertrag, ['schriftlich', 'Kündigungsformular'],
                            user=request.user)

    if len(kopien) > 1:
        # Art. 266n: alle Kopien in EIN PDF bündeln (jede Seite separat versenden).
        from pypdf import PdfReader, PdfWriter
        import io as _io
        writer = PdfWriter()
        for _n, pdf in kopien:
            for page in PdfReader(_io.BytesIO(pdf)).pages:
                writer.add_page(page)
        out = _io.BytesIO(); writer.write(out); pdf_bytes = out.getvalue()
        messages.info(request, "Familienwohnung (Art. 266n OR): Es wurden zwei separat adressierte "
                               "Kopien erstellt — je Ehegatte einzeln und mit separater Post zustellen, "
                               "sonst ist die Kündigung nichtig.")
    else:
        pdf_bytes = kopien[0][1]

    resp = HttpResponse(bytes(pdf_bytes), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Kuendigung_{k.vertrag.mieter.nachname}.pdf"'
    return resp
