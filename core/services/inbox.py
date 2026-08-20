"""Die EINE Aufgaben-Inbox für «Heute».

Führt die vier bisherigen Aufgaben-Flächen zusammen:
Dashboard-Widgets («Heute zu tun», Cockpit), Pendenzen, Fristen-Center und
den Finanz-Arbeitskorb. Jede Zeile ist direkt erledigbar (Link/Modal),
typisiert (geld / frist / schaden / prozess / aufgabe) und nach Dringlichkeit
sortiert. Pendenzen/Fristen-Detailseiten bleiben als «Alle ansehen»-Ziele.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

TYP_META = {
    'geld':    {'label': 'Geld',    'chip': 'bg-rose-50 text-rose-700'},
    'frist':   {'label': 'Frist',   'chip': 'bg-amber-50 text-amber-700'},
    'schaden': {'label': 'Schaden', 'chip': 'bg-orange-50 text-orange-700'},
    'prozess': {'label': 'Prozess', 'chip': 'bg-indigo-50 text-indigo-700'},
    'aufgabe': {'label': 'Aufgabe', 'chip': 'bg-slate-100 text-slate-600'},
}


def _eintrag(typ, titel, sub, url, cta, dringend=False, faellig=None,
             chf=None, modal=False, wide=False, ordnung=50):
    meta = TYP_META[typ]
    return {'typ': typ, 'typ_label': meta['label'], 'chip_cls': meta['chip'],
            'titel': titel, 'sub': sub, 'url': url, 'cta': cta,
            'dringend': dringend, 'faellig': faellig, 'chf': chf,
            'modal': modal, 'wide': wide, 'ordnung': ordnung}


def sammle_inbox(aktive_lg=None, lg_query='', modus='profi', pendenz_ziel=None,
                 max_pendenzen=8):
    """Alle offenen Aufgaben als eine sortierte Liste.

    Rückgabe: (eintraege, mehr_pendenzen, typ_counts)
    - `pendenz_ziel(p)` → (url, label, wide, modal) wird aus fw.py hereingereicht
      (vermeidet zirkulären Import).
    - `modus` steuert nur die Formulierung (Einfach = Klartext).
    """
    from core.models import Pendenz
    from finance.models import DebitorenRechnung, KreditorenRechnung
    from tickets.models import HandwerkerAuftrag, SchadenMeldung
    from rentals.models import Kuendigung

    heute = timezone.localdate()
    einfach = (modus == 'einfach')
    eintraege = []

    # ---------- GELD (Aggregate aus dem Finanz-Arbeitskorb) ----------
    deb_qs = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
    if aktive_lg:
        deb_qs = deb_qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    deb = [r for r in deb_qs.select_related('liegenschaft__eigentuemer',
                                            'vertrag__einheit__liegenschaft__eigentuemer')
                             .prefetch_related('zahlungseingaenge') if r.offener_betrag > 0]
    deb_ueberf = [r for r in deb if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute]
    # «Mahnen» nur für Forderungen, deren für die Überfälligkeit fällige Mahnstufe
    # noch NICHT in der Historie erfasst ist. Sonst bleibt die Aufgabe stehen,
    # obwohl der Nutzer die Mahnung bereits erfasst hat (Nutzer-Bug).
    if deb_ueberf:
        from django.db.models import Max
        from finance.models import Mahnung
        from core.services.mahnstufen import stufe_fuer_tage, eigentuemer_von_rechnung
        _ids = [r.id for r in deb_ueberf]
        _hoechste = {row['debitoren_rechnung_id']: row['mx'] for row in
                     Mahnung.objects.filter(debitoren_rechnung_id__in=_ids)
                     .values('debitoren_rechnung_id').annotate(mx=Max('stufe'))}

        def _zu_mahnen(r):
            tage = (heute - (r.faellig_am or r.datum)).days
            s = stufe_fuer_tage(tage, eigentuemer_von_rechnung(r))
            return bool(s) and s['stufe'] > (_hoechste.get(r.id) or 0)
        deb_ueberf = [r for r in deb_ueberf if _zu_mahnen(r)]
    if deb_ueberf:
        chf = sum((r.offener_betrag for r in deb_ueberf), Decimal('0.00'))
        titel = (f"{len(deb_ueberf)} Mieter haben noch nicht bezahlt" if einfach
                 else f"{len(deb_ueberf)} überfällige Forderungen mahnen")
        eintraege.append(_eintrag('geld', titel,
                                  'Mahnvorschläge bereit' if einfach else 'Fällige Debitoren mit Mahnung anstossen',
                                  '/neu/mahnwesen/' + lg_query,
                                  'Erinnerung senden' if einfach else 'Mahnen',
                                  dringend=True, chf=chf, ordnung=10))
    if deb:
        chf = sum((r.offener_betrag for r in deb), Decimal('0.00'))
        titel = (f"{len(deb)} offene Zahlungen abgleichen" if einfach
                 else f"{len(deb)} offene Forderungen mit der Bank abgleichen")
        eintraege.append(_eintrag('geld', titel,
                                  'Bankgutschriften den Mietern zuordnen',
                                  '/neu/bankabgleich/' + lg_query, 'Abgleichen',
                                  chf=chf, ordnung=20))

    kred_qs = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred_qs = kred_qs.filter(liegenschaft=aktive_lg)
    kred = list(kred_qs.prefetch_related('zahlungen'))
    zur_zahlung = [k for k in kred if k.status in ('freigegeben', 'teilbezahlt') and k.offener_betrag > 0]
    # Die Sammelzeile «X Rechnungen prüfen & freigeben» stand hier bis zum
    # 20.08.2026. Sie ist nach «Wartet auf Freigabe» gewandert (Prototyp
    # `konzept-struktur.html`, Screen «Heute») und zeigt dort die EINZELNEN
    # Rechnungen mit Betrag und Liegezeit statt einer Zahl. Zwei Listen
    # nebeneinander verbietet G2 — und eine Zahl sagt nicht, welche Rechnung
    # seit acht Tagen liegt.
    #
    # Der Zahllauf bleibt hier: Er ist ein LAUF, kein Einzelentscheid.
    if zur_zahlung:
        chf = sum((k.offener_betrag or Decimal('0.00') for k in zur_zahlung), Decimal('0.00'))
        dringend = any((k.faellig_am and k.faellig_am < heute) for k in zur_zahlung)
        eintraege.append(_eintrag('geld',
                                  f"{len(zur_zahlung)} Rechnungen bezahlen",
                                  'Zahlung auslösen' if einfach else 'Zahllauf ausführen (pain.001)',
                                  '/neu/kreditoren/' + lg_query, 'Zahlen',
                                  dringend=dringend, chf=chf, ordnung=35))

    kaut = Pendenz.objects.filter(erledigt=False, quelle__startswith='auto:kautionfreigabe:')
    if aktive_lg:
        kaut = kaut.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    kaut_faellig = kaut.filter(faellig_am__lte=heute).count()
    if kaut_faellig:
        eintraege.append(_eintrag('geld',
                                  f"{kaut_faellig} Kautionen zur Rückzahlung fällig",
                                  'Rückzahlungsfrist nach Auszug (Art. 257e)',
                                  '/neu/kautionen/' + lg_query, 'Kautionen',
                                  dringend=True, ordnung=40))

    # ---------- PROZESS ----------
    j, m = heute.year, heute.month
    soll_titel = f"Miete & NK {m:02d}/{j}"
    soll_qs = DebitorenRechnung.objects.filter(titel=soll_titel).exclude(status='storniert')
    if aktive_lg:
        soll_qs = soll_qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    from rentals.models import Mietvertrag
    hat_aktive = Mietvertrag.objects.filter(status='aktiv').exists()
    if hat_aktive and not soll_qs.exists():
        titel = (f"Monatsmieten {m:02d}/{j} erzeugen" if einfach
                 else f"Sollstellung {m:02d}/{j} ausführen")
        eintraege.append(_eintrag('prozess', titel,
                                  'Mietrechnungen für diesen Monat verbuchen',
                                  '/neu/sollstellung/' + lg_query, 'Starten', ordnung=45))

    portal_kuend = Kuendigung.objects.filter(status='erfasst', absender='mieter')
    if aktive_lg:
        portal_kuend = portal_kuend.filter(vertrag__einheit__liegenschaft=aktive_lg)
    n = portal_kuend.count()
    if n:
        eintraege.append(_eintrag('prozess',
                                  f"{n} Kündigung(en) über das Portal eingegangen",
                                  'Bestätigen und Mieterwechsel starten',
                                  '/neu/vertraege/' + lg_query, 'Prüfen',
                                  dringend=True, ordnung=15))

    # ---------- SCHADEN ----------
    schaeden_neu = SchadenMeldung.objects.filter(gelesen=False)
    if aktive_lg:
        schaeden_neu = schaeden_neu.filter(liegenschaft=aktive_lg)
    n = schaeden_neu.count()
    if n:
        eintraege.append(_eintrag('schaden',
                                  f"{n} neue Schadenmeldung(en)",
                                  'Prüfen und Handwerker beauftragen',
                                  '/neu/schaeden/' + lg_query, 'Ansehen',
                                  dringend=True, ordnung=12))
    freigaben = HandwerkerAuftrag.objects.filter(freigabe_status='ausstehend')
    if aktive_lg:
        freigaben = freigaben.filter(ticket__liegenschaft=aktive_lg)
    n = freigaben.count()
    if n:
        eintraege.append(_eintrag('schaden',
                                  f"{n} Reparaturen warten auf Eigentümer-Freigabe",
                                  'Freigabe nachfassen oder selbst entscheiden',
                                  '/neu/schaeden/' + lg_query, 'Ansehen', ordnung=42))

    # ---------- AUFGABEN OHNE FRIST (Sammelposten) ----------
    #
    # Hier standen bis zum 20.08.2026 zwei Blöcke: einzelne Pendenzen im
    # 14-Tage-Fenster und Wartungsfristen im 30-Tage-Fenster. Beide sind in
    # `faelle/arbeitsvorrat.py` gewandert — NICHT kopiert.
    #
    # Grund: Der neue Abschnitt «Was reisst» auf der Startseite zeigt genau
    # dieselben Vorgänge. Nebeneinander stand dieselbe Pendenz zweimal auf
    # einem Bildschirm. `KONZEPT-UI.md` G2 verbietet das: «Ein Arbeitsvorrat,
    # nicht zwei Listen.»
    #
    # Die Arbeitsteilung: EINZELNE datierte Vorgänge gehören in den
    # Arbeitsvorrat, SAMMELPOSTEN in die Inbox. Aufgaben **ohne** Frist sind
    # deshalb hier geblieben — sie reissen nichts, sie liegen nur da. Ohne
    # diesen Sammelposten wären sie beim Umbau ersatzlos verschwunden.
    ohne_frist = (Pendenz.objects.filter(erledigt=False, faellig_am__isnull=True)
                  .exclude(quelle__startswith='auto:kautionfreigabe:'))
    if aktive_lg:
        ohne_frist = ohne_frist.filter(
            Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg)
            | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    anzahl_ohne_frist = ohne_frist.count()
    if anzahl_ohne_frist:
        eintraege.append(_eintrag(
            'aufgabe', f'{anzahl_ohne_frist} Aufgabe'
                       f'{"n" if anzahl_ohne_frist > 1 else ""} ohne Frist',
            'Liegen ohne Termin — im Pendenzen-Center datieren oder erledigen',
            '/neu/pendenzen/' + lg_query, 'Ansehen', ordnung=60))
    mehr_pendenzen = 0

    # ---------- Sortierung: dringend zuerst, dann Fälligkeit, dann Prozessreihenfolge ----------
    eintraege.sort(key=lambda e: (0 if e['dringend'] else 1,
                                  e['faellig'] or date.max, e['ordnung']))
    typ_counts = {}
    for e in eintraege:
        typ_counts[e['typ']] = typ_counts.get(e['typ'], 0) + 1
    return eintraege, mehr_pendenzen, typ_counts
