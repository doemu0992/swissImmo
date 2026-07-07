# core/views/dossier.py
"""
Dossier-Seiten: eine Detailseite pro Mieter / Liegenschaft / Vertrag mit
allem an einem Ort (Verträge, Zahlungen, offene Posten, Dokumente, Tickets).

Design-Prinzip (Fairwalter-Stil): Tabellen zum Finden, Dossiers zum Arbeiten.
Server-gerendert (wie das Eigentümer-Portal) — bewusst unabhängig vom
SPA-JavaScript, dadurch stabil und testbar.
"""
from decimal import Decimal

from django.shortcuts import render, get_object_or_404

from core.auth import (rolle_erforderlich, hat_rolle,
                       TEAM_ROLLEN, SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter
from portfolio.models import Liegenschaft, Unterhalt
from portfolio.models import Dokument as PortfolioDokument
from rentals.models import Mietvertrag, Dokument as RentalsDokument
from finance.models import DebitorenRechnung, Zahlungseingang
from tickets.models import SchadenMeldung


def _rollen_flags(user):
    return {
        'kann_schreiben': hat_rolle(user, SCHREIB_ROLLEN),
        'kann_verwalten': hat_rolle(user, VERWALTUNGS_ROLLEN),
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def mieter_dossier(request, mieter_id):
    mieter = get_object_or_404(Mieter, id=mieter_id)

    vertraege = (mieter.vertraege
                 .select_related('einheit__liegenschaft')
                 .order_by('-beginn'))
    aktive = [v for v in vertraege if v.status == 'aktiv']

    offene_rechnungen = (DebitorenRechnung.objects
                         .filter(vertrag__mieter=mieter, status__in=['offen', 'teilbezahlt'])
                         .select_related('vertrag')
                         .order_by('faellig_am'))
    total_offen = sum((r.offener_betrag for r in offene_rechnungen), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects
                 .filter(vertrag__mieter=mieter, status='verbucht')
                 .order_by('-datum_eingang')[:12])

    dokumente = (RentalsDokument.objects
                 .filter(mieter=mieter)
                 .order_by('-datum')[:20])

    tickets = (SchadenMeldung.objects
               .filter(gemeldet_von=mieter)
               .order_by('-erstellt_am')[:8])

    context = {
        'mieter': mieter,
        'vertraege': vertraege,
        'brutto_monat': sum((v.brutto_mietzins for v in aktive), Decimal('0.00')),
        'anzahl_aktive': len(aktive),
        'offene_rechnungen': offene_rechnungen,
        'total_offen': total_offen,
        'zahlungen': zahlungen,
        'dokumente': dokumente,
        'tickets': tickets,
        **_rollen_flags(request.user),
    }
    return render(request, 'core/dossier/mieter.html', context)


@rolle_erforderlich(*TEAM_ROLLEN)
def liegenschaft_dossier(request, liegenschaft_id):
    lg = get_object_or_404(
        Liegenschaft.objects.select_related('mandant', 'verwaltung'),
        id=liegenschaft_id
    )

    einheiten_rows = []
    soll_monat = Decimal('0.00')
    vermietet = 0
    for e in lg.einheiten.all().order_by('bezeichnung'):
        vertrag = (Mietvertrag.objects
                   .filter(einheit=e, status='aktiv')
                   .select_related('mieter')
                   .order_by('-beginn')
                   .first())
        if vertrag:
            vermietet += 1
            soll_monat += vertrag.brutto_mietzins
        einheiten_rows.append({'einheit': e, 'vertrag': vertrag})

    tickets = (SchadenMeldung.objects
               .filter(liegenschaft=lg)
               .exclude(status='erledigt')
               .order_by('-erstellt_am')[:8])

    # Dokumente aus beiden Ablagen zusammenführen (Vertragsablage + Portfolio)
    dokumente = []
    for d in RentalsDokument.objects.filter(liegenschaft=lg).order_by('-datum')[:15]:
        dokumente.append({'titel': d.bezeichnung or d.titel, 'kategorie': d.kategorie,
                          'datum': d.datum, 'url': d.datei.url if d.datei else None})
    for d in PortfolioDokument.objects.filter(liegenschaft=lg).order_by('-datum')[:15]:
        dokumente.append({'titel': d.titel, 'kategorie': d.kategorie,
                          'datum': d.datum, 'url': d.datei.url if d.datei else None})
    dokumente.sort(key=lambda d: d['datum'] or '', reverse=True)

    unterhalt = (Unterhalt.objects
                 .filter(liegenschaft=lg)
                 .order_by('-datum')[:8])

    perioden = lg.abrechnungen.order_by('-start_datum')[:5]

    context = {
        'lg': lg,
        'einheiten_rows': einheiten_rows,
        'total_einheiten': len(einheiten_rows),
        'vermietet': vermietet,
        'leerstand': len(einheiten_rows) - vermietet,
        'soll_monat': soll_monat,
        'tickets': tickets,
        'dokumente': dokumente[:15],
        'unterhalt': unterhalt,
        'perioden': perioden,
        **_rollen_flags(request.user),
    }
    return render(request, 'core/dossier/liegenschaft.html', context)


@rolle_erforderlich(*TEAM_ROLLEN)
def vertrag_dossier(request, vertrag_id):
    vertrag = get_object_or_404(
        Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'),
        id=vertrag_id
    )

    rechnungen = (DebitorenRechnung.objects
                  .filter(vertrag=vertrag)
                  .exclude(status='storniert')
                  .order_by('-datum')[:12])
    offene = [r for r in rechnungen if r.status in ('offen', 'teilbezahlt')]
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects
                 .filter(vertrag=vertrag, status='verbucht')
                 .order_by('-datum_eingang')[:12])

    anpassungen = vertrag.anpassungen.order_by('-wirksam_ab')[:8]

    dokumente = (RentalsDokument.objects
                 .filter(vertrag=vertrag)
                 .order_by('-datum')[:10])

    context = {
        'v': vertrag,
        'rechnungen': rechnungen,
        'total_offen': total_offen,
        'anzahl_offen': len(offene),
        'zahlungen': zahlungen,
        'anpassungen': anpassungen,
        'dokumente': dokumente,
        'nebenobjekte': vertrag.nebenobjekte.all(),
        **_rollen_flags(request.user),
    }
    return render(request, 'core/dossier/vertrag.html', context)
