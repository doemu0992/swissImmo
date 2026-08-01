"""Zentrale, wiederverwendbare Automatisierungs-Prozesse für swissImmo.

Diese Funktionen sind bewusst request-unabhängig, damit sie sowohl aus den Views
(Button) als auch aus Management-Commands (Scheduler / PythonAnywhere Task)
aufgerufen werden können. Alle Läufe sind idempotent.
"""
import calendar as _calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone


# ============================================================
# 1. SOLLSTELLUNG (monatlicher Mietenlauf)
# ============================================================
def run_sollstellung(jahr, monat, user=None, liegenschaft=None):
    """Erzeugt für alle im Monat aktiven Verträge die Miet-/NK-Rechnung samt
    Buchungssätzen (idempotent — bereits gestellte Verträge werden übersprungen).
    Gibt die Anzahl neu erstellter Rechnungen zurück.

    `liegenschaft` grenzt den Lauf auf ein Objekt ein. Ohne diesen Parameter lief
    der Knopf im UI IMMER über das ganze Portfolio — obwohl die Vorschau darüber
    nur die gefilterten Verträge zeigte und der Bestätigungsdialog deren Anzahl
    nannte. Wer auf eine Liegenschaft gefiltert hatte, stellte damit unbeabsichtigt
    allen Mietern Rechnung (Praxis-Audit). Der Scheduler ruft weiterhin ohne
    Parameter auf und deckt das ganze Portfolio ab."""
    from finance.models import DebitorenRechnung
    from finance.booking import buche, ensure_kontenplan
    from rentals.models import Mietvertrag

    start_date = date(jahr, monat, 1)
    _, last_day = _calendar.monthrange(jahr, monat)
    end_date = date(jahr, monat, last_day)
    titel = f"Miete & NK {monat:02d}/{jahr}"

    ensure_kontenplan()   # Kontenplan garantieren (kein stiller Buchungsverlust)

    erstellt = 0
    with transaction.atomic():
        # Zeilensperre auf die aktiven Verträge: ein gleichzeitiger zweiter
        # Sollstellungs-Lauf (Button + Scheduler) blockiert bis dieser fertig ist,
        # dann greift der exists()-Check → keine doppelten Monatsmieten.
        # Nur PKs sperren (kein Join → kein Nullable-Outer-Join-Problem unter
        # Postgres; auf SQLite ohnehin No-op).
        _basis = (Mietvertrag.objects.filter(status='aktiv', beginn__lte=end_date)
                  .exclude(ende__lt=start_date))
        if liegenschaft is not None:
            _basis = _basis.filter(einheit__liegenschaft=liegenschaft)
        locked_ids = list(_basis.select_for_update().values_list('pk', flat=True))
        vertraege = (Mietvertrag.objects.filter(pk__in=locked_ids)
                     .select_related('mieter', 'einheit__liegenschaft'))
        for v in vertraege:
            if DebitorenRechnung.objects.filter(vertrag=v, titel=titel).exclude(status='storniert').exists():
                continue
            v_start = max(start_date, v.beginn)
            v_ende = min(end_date, v.ende) if v.ende else end_date
            faktor = Decimal((v_ende - v_start).days + 1) / Decimal(last_day)
            # --- Option B: Bruttobuchung ---
            # Referenz = die ECHTE vereinbarte Miete (Mieterspiegel/Bilanz-Ertrag),
            # verrechnet = was der Mieter effektiv zahlt (Referenz − Rabatt/Erlass).
            # Datierte Komponenten (Gratismonate/gestaffelter Start) haben Vorrang;
            # sonst Staffel/Anpassung/Basiswert.
            ref_netto = round((v.effektiver_netto_mietzins(start_date) or Decimal('0')) * faktor, 2)
            ref_nk = round((v.effektive_nebenkosten(start_date) or Decimal('0')) * faktor, 2)
            verr_netto = round((v.verrechneter_netto_mietzins(start_date) or Decimal('0')) * faktor, 2)
            verr_nk = round((v.verrechnete_nebenkosten(start_date) or Decimal('0')) * faktor, 2)
            # Rabatt = Referenz − verrechnet (nie negativ), aus den gerundeten Werten
            # abgeleitet, damit Debitor exakt auf den verrechneten Betrag nettoiert.
            rabatt_netto = max(Decimal('0.00'), ref_netto - verr_netto)
            rabatt_nk = max(Decimal('0.00'), ref_nk - verr_nk)
            if ref_netto + ref_nk <= 0:
                continue
            # MWST folgt dem effektiv verrechneten Betrag (nicht dem Referenzwert).
            mwst = Decimal('0.00')
            if v.mwst_pflichtig and (v.mwst_satz or 0) > 0:
                mwst = round((verr_netto + verr_nk) * (v.mwst_satz / Decimal('100')), 2)
            # Der Debitor schuldet nur den verrechneten Betrag (Gratismonat = 0).
            rechnung = DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=v.einheit.liegenschaft, einheit=v.einheit,
                titel=titel, betrag=verr_netto + verr_nk + mwst, faellig_am=start_date)
            lg = v.einheit.liegenschaft if v.einheit_id else None
            e = v.einheit
            # Mietertrag: Gewerbe/Parkplätze/Nebenobjekte → 3010, Wohnen → 3000.
            ertrag_konto = "3010" if (e and e.mietrecht_kategorie in ('gewerbe', 'nebenobjekt')) else "3000"
            # Nebenkosten: Pauschale ist definitiver Ertrag (keine Jahresabrechnung)
            # → eigenes Konto 3021; Akonto (Vorschuss, wird abgerechnet) → 3020.
            if getattr(v, 'nk_abrechnungsart', 'akonto') == 'pauschal':
                nk_konto, nk_label = "3021", "NK-Pauschal"
            else:
                nk_konto, nk_label = "3020", "NK-Akonto"
            # Vollen Referenzertrag als Ertrag buchen (Bilanz/Mieterspiegel korrekt) …
            buche("1100", ertrag_konto, ref_netto, f"Mietertrag {v.mieter} - {monat:02d}/{jahr}",
                  datum=start_date, liegenschaft=lg, debitor=rechnung, user=user)
            buche("1100", nk_konto, ref_nk, f"{nk_label} {v.mieter} - {monat:02d}/{jahr}",
                  datum=start_date, liegenschaft=lg, debitor=rechnung, user=user)
            # … den Rabatt/Erlass als Ertragsminderung gegen den Debitor buchen
            # (Soll 3090 / Haben 1100 → Debitor nettoiert auf den verrechneten Betrag).
            buche("3090", "1100", rabatt_netto,
                  f"Mietzinserlass {v.mieter} - {monat:02d}/{jahr}",
                  datum=start_date, liegenschaft=lg, debitor=rechnung, user=user)
            # NK-Erlass auf ein EIGENES Konto (3091), nicht auf 3090: Die
            # Honorarbasis rechnet auf dem Netto-Mietertrag (3000/3010) und
            # enthält die Nebenkosten gar nicht. Ein NK-Erlass auf 3090 hätte
            # eine Basis gemindert, in der die Nebenkosten nie standen — das
            # Honorar wurde systematisch zu tief und die Basis konnte bei
            # überwiegend erlassenen Perioden sogar negativ werden (Audit).
            buche("3091", "1100", rabatt_nk,
                  f"NK-Erlass {v.mieter} - {monat:02d}/{jahr}",
                  datum=start_date, liegenschaft=lg, debitor=rechnung, user=user)
            buche("1100", "2200", mwst, f"MWST {v.mwst_satz}% {v.mieter} - {monat:02d}/{jahr}",
                  datum=start_date, liegenschaft=lg, debitor=rechnung, user=user)
            erstellt += 1
    return erstellt


# ============================================================
# 2. MAHNLAUF (Sammellauf über alle fälligen Debitoren)
# ============================================================
MAHN_STUFEN_TAGE = [(3, 60), (2, 30), (1, 14)]   # (Stufe, ab Tagen überfällig)
MAHN_GEBUEHR = {1: Decimal('0.00'), 2: Decimal('20.00'), 3: Decimal('40.00')}
VERZUGSZINS_PROZENT = Decimal('5.0')   # Art. 104 OR


def _stufe_fuer_tage(tage):
    for stufe, ab in MAHN_STUFEN_TAGE:
        if tage >= ab:
            return stufe
    return None


def verzugszins(betrag, tage, prozent=VERZUGSZINS_PROZENT):
    """Verzugszins nach Art. 104 OR: betrag × prozent × tage / 360 (kaufm.)."""
    if betrag <= 0 or tage <= 0:
        return Decimal('0.00')
    return (Decimal(betrag) * prozent / Decimal('100') * Decimal(tage) / Decimal('360')).quantize(Decimal('0.01'))


def run_mahnlauf(aktive_lg=None, send_email=True, mit_zins=False, user=None):
    """Führt einen Sammel-Mahnlauf über alle überfälligen offenen Debitoren aus.
    Für jede fällige Rechnung, die noch keine Mahnung der berechneten Stufe hat,
    wird ein revisionssicherer Mahnung-Eintrag erzeugt (+ optional Mahngebühr als
    Debitor, + optional Zahlungserinnerung per E-Mail). Idempotent pro Stufe.

    Gibt dict zurück: {'gemahnt': n, 'emails': m, 'gebuehren': CHF, 'zins': CHF}.
    """
    from finance.models import DebitorenRechnung, Mahnung
    from django.db.models import Q
    from core.utils.email_service import send_payment_reminder
    from finance.booking import buche

    heute = timezone.localdate()
    qs = (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    res = {'gemahnt': 0, 'emails': 0, 'gebuehren': Decimal('0.00'), 'zins': Decimal('0.00'), 'geprueft': 0}

    for r in qs:
        faellig = r.faellig_am or r.datum
        if not faellig or faellig >= heute:
            continue
        offen = r.offener_betrag
        if offen <= 0:
            continue
        tage = (heute - faellig).days
        # Verjährte Mietzinsforderung (Art. 128 Ziff. 1 OR: 5 Jahre) nicht mehr
        # mahnen — Mahnungen unterbrechen die Verjährung ohnehin nicht; der Fall
        # gehört zur Abschreibung/Betreibung (eigene Verjährungs-Pendenz).
        if tage > 5 * 365:
            continue
        stufe = _stufe_fuer_tage(tage)
        if not stufe:
            continue
        # Mahnsperre: Mieter mit laufender Zahlungsvereinbarung nicht mahnen.
        if r.vertrag and r.vertrag.mieter_id and getattr(r.vertrag.mieter, 'mahnsperre', False):
            continue
        res['geprueft'] += 1
        # Idempotenz: existiert bereits eine Mahnung dieser (oder höherer) Stufe?
        hoechste = r.mahnungen.order_by('-stufe').first()
        if hoechste and hoechste.stufe >= stufe:
            continue

        gebuehr = MAHN_GEBUEHR.get(stufe, Decimal('0.00'))
        # Verzugszins nur als DELTA zur bereits fakturierten Summe (Art. 104 OR:
        # derselbe Verzugszeitraum darf nicht bei jeder Mahnstufe erneut verzinst
        # werden — früher stellte Stufe 3 die vollen 60 Tage nochmals in Rechnung,
        # obwohl Stufe 2 bereits 30 Tage fakturiert hatte).
        zins = Decimal('0.00')
        if mit_zins:
            bereits = sum((m.zins or Decimal('0.00')) for m in r.mahnungen.all())
            zins = max(Decimal('0.00'), verzugszins(offen, tage) - bereits)
        with transaction.atomic():
            Mahnung.objects.create(
                debitoren_rechnung=r, vertrag=r.vertrag, stufe=stufe, datum=heute,
                betrag_offen=offen, gebuehr=gebuehr, zins=zins,
                versandart='email' if (send_email and r.vertrag and r.vertrag.mieter.email) else 'manuell',
                bemerkung=(f"Verzugszins CHF {zins} ({tage} Tage, Delta zu Vorstufen)" if zins > 0 else ''),
                erstellt_von=user,
            )
            zusatz = gebuehr + zins
            if zusatz > 0 and r.vertrag_id:
                lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag.einheit_id else None)
                teile = []
                if gebuehr > 0:
                    teile.append(f"Mahngebühr {stufe}. Mahnung")
                if zins > 0:
                    teile.append(f"Verzugszins {VERZUGSZINS_PROZENT}%")
                gebuehr_rechnung = DebitorenRechnung.objects.create(
                    vertrag=r.vertrag, liegenschaft=lg,
                    titel=" + ".join(teile), beschreibung=f"Zu: {r.titel}",
                    datum=heute, faellig_am=heute + timedelta(days=30),
                    betrag=zusatz, status='offen')
                # Ins Hauptbuch buchen (Forderung an übrigen Ertrag) — sonst driften
                # Nebenbuch (OP/Debitoren) und Hauptbuch (1100) auseinander, der
                # Gebühren-/Zinsertrag fehlt in der Erfolgsrechnung, und eine spätere
                # Zahlung würde 1100 belasten, das nie bebucht wurde.
                buche("1100", "3600", zusatz, f"{' + '.join(teile)} {r.vertrag.mieter}",
                      datum=heute, liegenschaft=lg, debitor=gebuehr_rechnung, user=user)
        res['gemahnt'] += 1
        res['gebuehren'] += gebuehr
        res['zins'] += zins
        if send_email and r.vertrag and r.vertrag.mieter.email:
            try:
                if send_payment_reminder(r.vertrag, faellig, offen):
                    res['emails'] += 1
            except Exception:
                pass
    return res


def run_adress_umzuege():
    """Aktiviert fällige Adresswechsel (Einzug erreicht). Läuft im täglichen
    Scheduler statt in den GET-API-Endpoints — ein Lesezugriff darf keine
    Datenmutation auslösen (GET muss idempotent/seiteneffektfrei sein).
    Gibt die Anzahl aktualisierter Mieter zurück."""
    from crm.models import Mieter
    heute = timezone.localdate()
    n = 0
    # Datierte Adress-Historie: effektive Zustelladresse nachführen. Betrifft jeden
    # Mieter mit hinterlegten Adress-Zeilen (Sync ist idempotent). Die frühere
    # Alt-Mechanik (zukuenftig_ab) ist entfernt — MieterAdresse ist alleinige Quelle.
    for m in Mieter.objects.filter(adressen__isnull=False).distinct():
        if m.sync_effektive_adresse(heute):
            n += 1
    return n


def erledige_pendenzen_fuer(vertrag, keywords, user=None):
    """Hakt offene Pendenzen dieses Vertrags automatisch ab, deren Titel eines der
    `keywords` enthält (case-insensitive). Wird aufgerufen, wenn der zugehörige
    Schritt tatsächlich erledigt wurde (Rücknahme protokolliert, Schlussabrechnung
    verbucht, Kaution abgerechnet, Objekt ausgeschrieben). Idempotent; gibt die
    Anzahl frisch erledigter Pendenzen zurück."""
    from core.models import Pendenz
    from django.db.models import Q
    if not vertrag or not keywords:
        return 0
    q = Q()
    for kw in keywords:
        q |= Q(titel__icontains=kw)
    heute = timezone.localdate()
    n = 0
    for p in Pendenz.objects.filter(vertrag=vertrag, erledigt=False).filter(q):
        p.erledigt = True
        p.erledigt_am = heute
        p.save(update_fields=['erledigt', 'erledigt_am'])
        n += 1
    return n


# ============================================================
# 3. AUTO-PENDENZEN (Fristen aus dem Datenbestand persistieren)
# ============================================================
def generate_auto_pendenzen(horizont_tage=90, user=None):
    """Erzeugt/aktualisiert persistente Pendenzen aus terminierten Ereignissen
    (Vertragsende, Auszug, Geräte-Garantien, Serviceabos). Idempotent über das
    Feld Pendenz.quelle. Gibt die Anzahl neu erstellter Pendenzen zurück."""
    from core.models import Pendenz
    from rentals.models import Mietvertrag, Kuendigung
    from portfolio.models import Geraet, Wartungsfrist

    heute = timezone.localdate()
    grenze = heute + timedelta(days=horizont_tage)
    neu = 0

    def _ensure(quelle, titel, faellig, kategorie, beschreibung='', liegenschaft=None, vertrag=None):
        nonlocal neu
        obj, created = Pendenz.objects.get_or_create(
            quelle=quelle,
            defaults={'titel': titel, 'faellig_am': faellig, 'kategorie': kategorie,
                      'beschreibung': beschreibung, 'liegenschaft': liegenschaft,
                      'vertrag': vertrag, 'erstellt_von': user})
        if created:
            neu += 1
        elif not obj.erledigt:
            # Fälligkeit/Titel aktuell halten, ohne Erledigt-Status zu überschreiben
            if obj.faellig_am != faellig or obj.titel != titel:
                obj.faellig_am = faellig
                obj.titel = titel
                obj.save(update_fields=['faellig_am', 'titel'])
        return obj

    # a) Befristete Vertragsenden (nur echte befristete Verhältnisse)
    for v in (Mietvertrag.objects.filter(status='aktiv', ist_befristet=True, ende__range=[heute, grenze])
              .select_related('mieter', 'einheit__liegenschaft')):
        _ensure(f"auto:vertragsende:{v.id}",
                f"Vertragsende {v.mieter.display_name} ({v.einheit.bezeichnung})",
                v.ende, 'vertrag',
                "Befristeter Vertrag läuft aus — Verlängerung oder Auszug prüfen.",
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None, vertrag=v)

    # b) Gekündigte Verträge → Auszug/Abnahme/Kautionsabrechnung
    for v in (Mietvertrag.objects.filter(status='gekuendigt', ende__range=[heute, grenze])
              .select_related('mieter', 'einheit__liegenschaft')):
        _ensure(f"auto:auszug:{v.id}",
                f"Auszug {v.mieter.display_name} ({v.einheit.bezeichnung})",
                v.ende, 'vertrag',
                "Wohnungsabnahme, Schlussabrechnung und Kautionsabrechnung vorbereiten.",
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None, vertrag=v)

    # b2) Laufende Kündigungen → Wohnungsrücknahme planen (Mieterwechsel-Cockpit).
    # Nur solange noch kein Auszugs-Protokoll erfasst wurde; die Pendenz fällt
    # rechtzeitig VOR dem Mietende an (Rücknahme wird üblicherweise am Endtermin
    # durchgeführt), damit Termin & Nachmietersuche vorbereitet werden können.
    for k in (Kuendigung.objects.filter(status__in=['erfasst', 'bestaetigt'])
              .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')):
        v = k.vertrag
        if not v or not v.einheit_id:
            continue
        ende = k.per_datum or k.berechneter_termin
        if not ende or ende < heute or ende > grenze:
            continue
        if v.abnahmen.filter(typ='auszug').exists():
            continue   # Rücknahme bereits durchgeführt
        _ensure(f"auto:ruecknahme:{k.id}",
                f"Wohnungsrücknahme planen: {v.mieter.display_name} ({v.einheit.bezeichnung})",
                ende, 'vertrag',
                "Kündigung erfasst — Rücknahmetermin vereinbaren, Objekt ausschreiben "
                "und Nachmieter suchen.",
                liegenschaft=v.einheit.liegenschaft, vertrag=v)

    # c) Geräte-Garantien / Serviceabläufe
    for g in Geraet.objects.filter(garantie_bis__range=[heute, grenze]).select_related('liegenschaft', 'einheit__liegenschaft'):
        lg = g.liegenschaft or (g.einheit.liegenschaft if getattr(g, 'einheit_id', None) else None)
        bez = getattr(g, 'sonstiges_bezeichnung', '') or getattr(g, 'get_kategorie_display', lambda: 'Gerät')()
        _ensure(f"auto:garantie:{g.id}",
                f"Garantie läuft ab: {bez}",
                g.garantie_bis, 'unterhalt',
                f"Garantie/Service für {bez} endet — Verlängerung oder Wartung prüfen.",
                liegenschaft=lg)

    # d) Wartungs-/Versicherungsfristen (wiederkehrend)
    for wf in Wartungsfrist.objects.filter(aktiv=True, naechste_faelligkeit__lte=grenze).select_related('liegenschaft'):
        # Überfällige Fristen ins Intervall rollen, bis sie wieder in der Zukunft liegen
        rollen = 0
        while wf.naechste_faelligkeit < heute and (wf.intervall_monate or 0) > 0 and rollen < 60:
            wf.naechste_faelligkeit = _plus_monate(wf.naechste_faelligkeit, wf.intervall_monate)
            rollen += 1
        if rollen:
            wf.save(update_fields=['naechste_faelligkeit'])
        if wf.naechste_faelligkeit > grenze:
            continue
        anbieter = f" ({wf.anbieter})" if wf.anbieter else ""
        _ensure(f"auto:wartung:{wf.id}:{wf.naechste_faelligkeit.isoformat()}",
                f"{wf.get_art_display()}: {wf.bezeichnung}{anbieter}",
                wf.naechste_faelligkeit, 'unterhalt',
                wf.notiz or f"Wiederkehrende Frist ({wf.get_art_display()}) — Termin planen/erneuern.",
                liegenschaft=wf.liegenschaft)

    # e) Indexmieten: fällige Indexanpassung erkennen (Art. 269b). Nicht still
    # umbuchen — Ankündigung mit amtlichem Formular (Art. 269d, 30 Tage Vorlauf).
    try:
        from core.services.lik import aktueller_lik_wert
        _stand, aktuell_pkt, _b = aktueller_lik_wert(live=False)  # Tabellenwert: schnell, offline
    except Exception:
        aktuell_pkt = None
    if aktuell_pkt:
        for v in (Mietvertrag.objects.filter(status='aktiv', mietzins_modell='index')
                  .select_related('mieter', 'einheit__liegenschaft')):
            basis_lik = v.basis_lik_punkte or Decimal('0')
            if basis_lik <= 0 or not v.einheit_id:
                continue
            ref_datum = v.index_letzte_anpassung or v.beginn
            naechste = _plus_monate(ref_datum, v.index_intervall_monate or 12)
            if naechste > grenze:
                continue
            if Decimal(aktuell_pkt) <= basis_lik:
                continue   # LIK nicht gestiegen → keine Erhöhung möglich
            weiter = (v.index_weitergabe_prozent or Decimal('100')) / Decimal('100')
            faktor = Decimal('1') + (Decimal(aktuell_pkt) - basis_lik) / basis_lik * weiter
            neuer_netto = (v.netto_mietzins * faktor).quantize(Decimal('0.01'))
            if neuer_netto <= (v.netto_mietzins or Decimal('0')):
                continue
            _ensure(f"auto:index:{v.id}:{naechste.isoformat()}",
                    f"Indexmiete anpassen: {v.mieter.display_name} ({v.einheit.bezeichnung})",
                    max(naechste, heute), 'vertrag',
                    (f"LIK {basis_lik}→{aktuell_pkt} Pkt.: Netto CHF {v.netto_mietzins}→{neuer_netto} "
                     f"möglich. Mit amtlichem Formular (Art. 269d) ankündigen, 30 Tage vor Termin."),
                    liegenschaft=v.einheit.liegenschaft, vertrag=v)

    # f) Referenzzinssenkung: liegt der aktuelle Referenzzinssatz unter der
    # Vertragsbasis, kann der Mieter eine Herabsetzung verlangen (Art. 270a OR).
    # Informativ — nicht für Index-/Staffelverträge (die folgen anderer Logik).
    try:
        from core.utils import get_current_ref_zins
        aktuell_ref = Decimal(str(get_current_ref_zins()))
    except Exception:
        aktuell_ref = None
    if aktuell_ref is not None:
        for v in (Mietvertrag.objects.filter(status='aktiv', mietzins_modell='fest')
                  .select_related('mieter', 'einheit__liegenschaft')):
            basis_ref = v.basis_referenzzinssatz or Decimal('0')
            if not v.einheit_id or basis_ref <= 0 or aktuell_ref >= basis_ref:
                continue
            # Näherung: ~2.91 % Mietzinssenkung je 0.25-Prozentpunkt-Schritt (VMWG).
            schritte = (basis_ref - aktuell_ref) / Decimal('0.25')
            senkung_pct = (schritte * Decimal('2.91')).quantize(Decimal('0.1'))
            _ensure(f"auto:refsenkung:{v.id}:{aktuell_ref}",
                    f"Referenzzinssenkung prüfen: {v.mieter.display_name} ({v.einheit.bezeichnung})",
                    heute, 'vertrag',
                    (f"Referenzzins {basis_ref}%→{aktuell_ref}%: Der Mieter kann eine "
                     f"Herabsetzung verlangen (Art. 270a OR), Richtwert ca. −{senkung_pct}% "
                     f"(VMWG). Allfällige Anpassung prüfen."),
                    liegenschaft=v.einheit.liegenschaft, vertrag=v)

    # g) Kautions-Freigabefrist (Art. 257e Abs. 3): nach beendetem Mietverhältnis
    # kann der Mieter die Freigabe der Kaution verlangen, wenn der Vermieter nicht
    # innert eines Jahres seit Mietende Ansprüche geltend gemacht/eingeklagt hat.
    # Betrifft nur echte Bardepots (keine Kautionsversicherung), die noch nicht
    # zurückbezahlt sind.
    for v in (Mietvertrag.objects.filter(ende__isnull=False, ende__lt=heute,
                                          kautions_zurueckbezahlt_am__isnull=True)
              .exclude(kautions_art='versicherung')
              .select_related('mieter', 'einheit__liegenschaft')):
        if not v.kautions_betrag or v.kautions_betrag <= 0:
            continue
        frist = v.ende + timedelta(days=365)
        if frist > grenze:
            continue   # noch nicht im Vorlauf-Horizont
        _ensure(f"auto:kautionfreigabe:{v.id}",
                f"Kaution abrechnen/freigeben: {v.mieter.display_name}",
                frist, 'frist',
                ("Mietverhältnis ist über 1 Jahr beendet — der Mieter kann die Freigabe der "
                 "Kaution vom Sperrkonto verlangen, sofern keine Ansprüche geltend gemacht oder "
                 "eingeklagt wurden (Art. 257e Abs. 3 OR). Kaution abrechnen und freigeben."),
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None, vertrag=v)

    # h) Verjährung von Mietzinsforderungen (Art. 128 Ziff. 1 OR: 5 Jahre für
    # periodische Leistungen). Mahnen unterbricht die Verjährung NICHT — nur
    # Betreibung/Klage (Art. 135 OR). 6 Monate vor Ablauf eine Pendenz stellen,
    # damit die Forderung rechtzeitig durch Betreibung gesichert oder bewusst
    # abgeschrieben wird.
    from finance.models import DebitorenRechnung
    verj_warnung_ab = heute - timedelta(days=int(4.5 * 365))   # älter als 4,5 Jahre
    alte = (DebitorenRechnung.objects
            .filter(status__in=['offen', 'teilbezahlt'], faellig_am__lt=verj_warnung_ab)
            .select_related('vertrag__mieter', 'liegenschaft'))
    for r in alte:
        if r.offener_betrag <= 0:
            continue
        ablauf = r.faellig_am + timedelta(days=5 * 365)
        wer = r.vertrag.mieter.display_name if (r.vertrag_id and r.vertrag.mieter_id) else (r.titel or 'Debitor')
        _ensure(f"auto:verjaehrung:{r.id}",
                f"Verjährung droht: {wer} — CHF {r.offener_betrag}",
                min(ablauf, heute + timedelta(days=1)) if ablauf < heute else ablauf, 'frist',
                (f"Forderung «{r.titel}» (fällig {r.faellig_am:%d.%m.%Y}) verjährt am "
                 f"{ablauf:%d.%m.%Y} (Art. 128 Ziff. 1 OR, 5 Jahre). Mahnungen unterbrechen "
                 "die Verjährung NICHT — Betreibung/Klage einleiten (Art. 135 OR) oder "
                 "Forderung bewusst abschreiben."),
                liegenschaft=r.liegenschaft, vertrag=r.vertrag)

    return neu


def _plus_monate(d, monate):
    """Addiert Monate zu einem Datum (Tag wird bei kürzeren Monaten geklemmt)."""
    import calendar
    monat0 = d.month - 1 + int(monate)
    jahr = d.year + monat0 // 12
    monat = monat0 % 12 + 1
    tag = min(d.day, calendar.monthrange(jahr, monat)[1])
    return d.replace(year=jahr, month=monat, day=tag)


# ============================================================
# 4. BUCHHALTER-TIEFE: Kaution-Bilanzierung, AfA, Erneuerungsfonds
# ============================================================
def _konto(nummer, bezeichnung, typ):
    from finance.models import Buchungskonto
    k, _ = Buchungskonto.objects.get_or_create(
        nummer=nummer, defaults={'bezeichnung': bezeichnung, 'typ': typ})
    return k


def buche_kaution_einzahlung(vertrag, datum, user=None):
    """Bilanzbuchung bei Einzahlung auf ein Kautions-Sperrkonto:
    1015 Kautionssperrkonto an 2010 Kautionsverbindlichkeit. Nur für Sperrkonto
    (Versicherung bewegt kein Geld). Idempotent (pro Vertrag nur einmal)."""
    from finance.models import Buchung
    from decimal import Decimal as D
    if vertrag.ist_kautionsversicherung:
        return None
    betrag = vertrag.kautions_betrag or D('0.00')
    if betrag <= 0:
        return None
    soll = _konto('1015', 'Kautionssperrkonten (Mieterkautionen)', 'bilanz')
    haben = _konto('2010', 'Kautionsverbindlichkeiten', 'bilanz')
    # Idempotenz per Vertrags-ID (nicht nur Mietername): sonst würde die Kaution
    # eines zweiten Vertrags desselben Mieters nie gebucht.
    beleg = f"Mietkaution [V{vertrag.pk}] {vertrag.mieter} — Einzahlung Sperrkonto"
    if Buchung.objects.filter(beleg_text__startswith=f"Mietkaution [V{vertrag.pk}] ",
                              ist_storno=False).exists():
        return None
    return Buchung.objects.create(
        datum=datum, beleg_text=beleg,
        liegenschaft=vertrag.einheit.liegenschaft if vertrag.einheit_id else None,
        soll_konto=soll, haben_konto=haben, betrag=betrag, erstellt_von=user)


def buche_kaution_aufloesung(vertrag, datum, user=None):
    """Bilanzbuchung bei Auflösung/Rückzahlung des Sperrkontos:
    2010 Kautionsverbindlichkeit an 1015 Kautionssperrkonto."""
    from finance.models import Buchung
    from decimal import Decimal as D
    if vertrag.ist_kautionsversicherung:
        return None
    betrag = vertrag.kautions_betrag or D('0.00')
    if betrag <= 0:
        return None
    soll = _konto('2010', 'Kautionsverbindlichkeiten', 'bilanz')
    haben = _konto('1015', 'Kautionssperrkonten (Mieterkautionen)', 'bilanz')
    beleg = f"Mietkaution [V{vertrag.pk}] {vertrag.mieter} — Auflösung Sperrkonto"
    if Buchung.objects.filter(beleg_text__startswith=f"Mietkaution [V{vertrag.pk}] {vertrag.mieter} — Auflösung",
                              ist_storno=False).exists():
        return None
    return Buchung.objects.create(
        datum=datum, beleg_text=beleg,
        liegenschaft=vertrag.einheit.liegenschaft if vertrag.einheit_id else None,
        soll_konto=soll, haben_konto=haben, betrag=betrag, erstellt_von=user)


def run_abschreibungen(jahr, user=None):
    """Bucht die lineare Jahres-AfA für alle aktiven Anlagen, sofern für das Jahr
    noch keine Abschreibung existiert (idempotent). 6800 Abschreibungen an 1500
    Sachanlagen. Gibt (anzahl, summe) zurück."""
    from finance.models import Anlage, Abschreibung, Buchung
    from decimal import Decimal as D
    aufwand = _konto('6800', 'Abschreibungen', 'aufwand')
    aktivum = _konto('1500', 'Sachanlagen (Anlagegüter)', 'bilanz')
    buchungsdatum = date(jahr, 12, 31)
    anzahl, summe = 0, D('0.00')
    for a in Anlage.objects.filter(aktiv=True):
        if a.anschaffungsdatum and a.anschaffungsdatum.year > jahr:
            continue
        if a.buchwert <= (a.restwert or D('0')):
            continue   # vollständig abgeschrieben
        if Abschreibung.objects.filter(anlage=a, jahr=jahr).exists():
            continue
        afa = a.jahres_afa
        # nicht unter den Restwert abschreiben
        max_afa = a.buchwert - (a.restwert or D('0'))
        if afa > max_afa:
            afa = max_afa
        if afa <= 0:
            continue
        b = Buchung.objects.create(
            datum=buchungsdatum, beleg_text=f"Abschreibung {jahr}: {a.bezeichnung}",
            liegenschaft=a.liegenschaft, soll_konto=aufwand, haben_konto=aktivum,
            betrag=afa, erstellt_von=user)
        Abschreibung.objects.create(anlage=a, jahr=jahr, betrag=afa, datum=buchungsdatum, buchung=b)
        anzahl += 1
        summe += afa
    return anzahl, summe


def run_erneuerungsfonds_einlage(jahr, user=None):
    """Bucht die jährliche Einlage in den Erneuerungsfonds als Rückstellung:
    6900 Einlage Erneuerungsfonds an 2800 Erneuerungsfonds. Idempotent pro Jahr."""
    from finance.models import Erneuerungsfonds, Buchung
    from decimal import Decimal as D
    aufwand = _konto('6900', 'Einlage Erneuerungsfonds', 'aufwand')
    fonds_konto = _konto('2800', 'Erneuerungsfonds (Rückstellung)', 'bilanz')
    buchungsdatum = date(jahr, 12, 31)
    anzahl, summe = 0, D('0.00')
    for f in Erneuerungsfonds.objects.filter(jaehrliche_einlage__gt=0):
        if f.letzte_einlage_jahr == jahr:
            continue
        einlage = f.jaehrliche_einlage
        Buchung.objects.create(
            datum=buchungsdatum, beleg_text=f"Einlage Erneuerungsfonds {jahr}: {f.liegenschaft}",
            liegenschaft=f.liegenschaft, soll_konto=aufwand, haben_konto=fonds_konto,
            betrag=einlage, erstellt_von=user)
        f.bestand = (f.bestand or D('0')) + einlage
        f.letzte_einlage_jahr = jahr
        f.save(update_fields=['bestand', 'letzte_einlage_jahr'])
        anzahl += 1
        summe += einlage
    return anzahl, summe
