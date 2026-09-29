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
from django.utils.translation import gettext, gettext_noop, ngettext

TYP_META = {
    'geld':    {'label': gettext_noop('Geld'),    'chip': 'fw-krit-flaeche fw-kritisch'},
    'frist':   {'label': gettext_noop('Frist'),   'chip': 'fw-warn-flaeche fw-warnton'},
    'schaden': {'label': gettext_noop('Schaden'), 'chip': 'fw-warn-flaeche fw-warnton'},
    'prozess': {'label': gettext_noop('Prozess'), 'chip': 'fw-markenflaeche fw-marke'},
    'aufgabe': {'label': gettext_noop('Aufgabe'), 'chip': 'fw-flaeche2 fw-mutet'},
}


def _eintrag(typ, titel, sub, url, cta, dringend=False, faellig=None,
             chf=None, modal=False, wide=False, ordnung=50):
    meta = TYP_META[typ]
    return {'typ': typ, 'typ_label': gettext(meta['label']), 'chip_cls': meta['chip'],
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
        n_ueberf = len(deb_ueberf)
        titel = (ngettext('%(n)s Mieter hat noch nicht bezahlt', '%(n)s Mieter haben noch nicht bezahlt', n_ueberf)
                 if einfach else
                 ngettext('%(n)s überfällige Forderung mahnen', '%(n)s überfällige Forderungen mahnen', n_ueberf)
                 ) % {'n': n_ueberf}
        eintraege.append(_eintrag('geld', titel,
                                  gettext('Mahnvorschläge bereit') if einfach
                                  else gettext('Fällige Debitoren mit Mahnung anstossen'),
                                  '/neu/mahnwesen/' + lg_query,
                                  gettext('Erinnerung senden') if einfach else gettext('Mahnen'),
                                  dringend=True, chf=chf, ordnung=10))
    if deb:
        chf = sum((r.offener_betrag for r in deb), Decimal('0.00'))
        titel = (ngettext('%(n)s offene Zahlung abgleichen', '%(n)s offene Zahlungen abgleichen', len(deb))
                 if einfach else
                 ngettext('%(n)s offene Forderung mit der Bank abgleichen',
                          '%(n)s offene Forderungen mit der Bank abgleichen', len(deb))
                 ) % {'n': len(deb)}
        eintraege.append(_eintrag('geld', titel,
                                  gettext('Bankgutschriften den Mietern zuordnen'),
                                  '/neu/bankabgleich/' + lg_query, gettext('Abgleichen'),
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
                                  ngettext('%(n)s Rechnung bezahlen', '%(n)s Rechnungen bezahlen',
                                           len(zur_zahlung)) % {'n': len(zur_zahlung)},
                                  gettext('Zahlung auslösen') if einfach
                                  else gettext('Zahllauf ausführen (pain.001)'),
                                  '/neu/kreditoren/' + lg_query, gettext('Zahlen'),
                                  dringend=dringend, chf=chf, ordnung=35))

    kaut = Pendenz.objects.filter(erledigt=False, quelle__startswith='auto:kautionfreigabe:')
    if aktive_lg:
        kaut = kaut.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    kaut_faellig = kaut.filter(faellig_am__lte=heute).count()
    if kaut_faellig:
        eintraege.append(_eintrag('geld',
                                  ngettext('%(n)s Kaution zur Rückzahlung fällig',
                                           '%(n)s Kautionen zur Rückzahlung fällig',
                                           kaut_faellig) % {'n': kaut_faellig},
                                  gettext('Rückzahlungsfrist nach Auszug (Art. 257e)'),
                                  '/neu/kautionen/' + lg_query, gettext('Kautionen'),
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
        # `soll_titel` oben ist ein Datenbank-Schlüssel und bleibt deutsch;
        # übersetzt wird nur die Anzeige.
        titel = (gettext('Monatsmieten %(periode)s erzeugen') if einfach
                 else gettext('Sollstellung %(periode)s ausführen')) % {'periode': f'{m:02d}/{j}'}
        eintraege.append(_eintrag('prozess', titel,
                                  gettext('Mietrechnungen für diesen Monat verbuchen'),
                                  '/neu/sollstellung/' + lg_query, gettext('Starten'), ordnung=45))

    portal_kuend = Kuendigung.objects.filter(status='erfasst', absender='mieter')
    if aktive_lg:
        portal_kuend = portal_kuend.filter(vertrag__einheit__liegenschaft=aktive_lg)
    n = portal_kuend.count()
    if n:
        eintraege.append(_eintrag('prozess',
                                  ngettext('%(n)s Kündigung über das Portal eingegangen',
                                           '%(n)s Kündigungen über das Portal eingegangen', n) % {'n': n},
                                  gettext('Bestätigen und Mieterwechsel starten'),
                                  '/neu/vertraege/' + lg_query, gettext('Prüfen'),
                                  dringend=True, ordnung=15))

    # ---------- SCHADEN ----------
    schaeden_neu = SchadenMeldung.objects.filter(gelesen=False)
    if aktive_lg:
        schaeden_neu = schaeden_neu.filter(liegenschaft=aktive_lg)
    n = schaeden_neu.count()
    if n:
        eintraege.append(_eintrag('schaden',
                                  ngettext('%(n)s neue Schadenmeldung', '%(n)s neue Schadenmeldungen', n) % {'n': n},
                                  gettext('Prüfen und Handwerker beauftragen'),
                                  '/neu/schaeden/' + lg_query, gettext('Ansehen'),
                                  dringend=True, ordnung=12))
    freigaben = HandwerkerAuftrag.objects.filter(freigabe_status='ausstehend')
    if aktive_lg:
        freigaben = freigaben.filter(ticket__liegenschaft=aktive_lg)
    n = freigaben.count()
    if n:
        eintraege.append(_eintrag('schaden',
                                  ngettext('%(n)s Reparatur wartet auf Eigentümer-Freigabe',
                                           '%(n)s Reparaturen warten auf Eigentümer-Freigabe', n) % {'n': n},
                                  gettext('Freigabe nachfassen oder selbst entscheiden'),
                                  '/neu/schaeden/' + lg_query, gettext('Ansehen'), ordnung=42))

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
            'aufgabe', ngettext('%(n)s Aufgabe ohne Frist', '%(n)s Aufgaben ohne Frist',
                                anzahl_ohne_frist) % {'n': anzahl_ohne_frist},
            gettext('Liegen ohne Termin — im Pendenzen-Center datieren oder erledigen'),
            '/neu/pendenzen/' + lg_query, gettext('Ansehen'), ordnung=60))
    mehr_pendenzen = 0

    # ---------- Sortierung: dringend zuerst, dann Fälligkeit, dann Prozessreihenfolge ----------
    eintraege.sort(key=lambda e: (0 if e['dringend'] else 1,
                                  e['faellig'] or date.max, e['ordnung']))
    typ_counts = {}
    for e in eintraege:
        typ_counts[e['typ']] = typ_counts.get(e['typ'], 0) + 1
    return eintraege, mehr_pendenzen, typ_counts
