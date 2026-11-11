# core/views/fw/vertrag_detail.py
#
# Die Vertrags-Akte: Detailseite, Kennzahlen im Kopf, Formulare und Prozesse.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md. Herausgeloest aus detailseiten.py.

from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils import dateformat, timezone
from django.utils.translation import gettext, ngettext

from core.auth import (darf_oeffnen, rolle_erforderlich, TEAM_ROLLEN)
from finance.models import DebitorenRechnung, Zahlungseingang
from rentals.models import Mietvertrag

from ._basis import (_global_filter, _pendenz_ziel,
                     STATUS_PILL)
from core.services.schluessel import akte as _schluessel_akte, ausgaben_von as _ausgaben_von
from .objekt_detail import _vertrag_status_pill


def _erstellbare_dokumente(v):
    """Verlinkt die bestehenden PDF-/Prozess-Endpunkte als 'Erstellbare Dokumente'."""
    docs = [
        {'titel': 'Mietvertrag (PDF)', 'icon': 'vertrag',
         'url': f'/vertrag/{v.id}/pdf/', 'sub': 'Kompletter Vertrag als PDF'},
        {'titel': 'QR-Rechnung', 'icon': 'bank',
         'url': f'/vertrag/{v.id}/qr/', 'sub': 'Einzahlungsschein mit QR-IBAN'},
        {'titel': 'Mahnung (Art. 257d OR)', 'icon': 'warnung',
         'url': f'/vertrag/{v.id}/mahnung/', 'sub': 'Zahlungsfrist mit Kündigungsandrohung'},
        {'titel': 'Mietzinsanpassung', 'icon': 'bericht',
         'url': f'/mietzins/{v.id}/', 'sub': 'Amtliches Formular berechnen'},
        {'titel': 'Begleitbrief Mietvertrag', 'icon': 'senden',
         'url': f'/vertrag/{v.id}/dokument/begleitbrief/', 'sub': 'Anschreiben zur Unterzeichnung'},
        {'titel': 'Begleitbrief unterzeichnet', 'icon': 'gut',
         'url': f'/vertrag/{v.id}/dokument/begleitbrief-signiert/', 'sub': 'Zustellung des signierten Vertrags'},
        {'titel': 'Allgemeine Bedingungen', 'icon': 'dokument',
         'url': f'/vertrag/{v.id}/dokument/allgemeine-bedingungen/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Hausordnung', 'icon': 'arbeit',
         'url': f'/vertrag/{v.id}/dokument/hausordnung/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Merkblatt Lüften & Pflegen', 'icon': 'zaehler',
         'url': f'/vertrag/{v.id}/dokument/merkblatt-lueften/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Wohnungsausweis', 'icon': 'person',
         'url': f'/vertrag/{v.id}/dokument/wohnungsausweis/', 'sub': 'Mieter- und Objektdaten'},
    ]
    if v.kuendigungen.exists():
        docs.append({'titel': 'Kündigungsbestätigung', 'icon': 'dokument',
                     'url': f'/vertrag/{v.id}/dokument/kuendigungsbestaetigung/', 'sub': 'Bestätigung mit Vertragsende'})
    return docs


def _formulare_prozesse(v, user=None):
    """Bündelt ALLE für diesen Vertrag zutreffenden Formulare/Prozesse in Gruppen —
    kontextabhängig nach Status/Objektart, mit «bereits erstellt»-Kennzeichnung.
    Ein Ort für alles: der «Formulare & Prozesse»-Tab am Vertrag."""
    from rentals.models import Dokument
    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
    e = v.einheit
    lg = e.liegenschaft if e else None
    wohnraum = bool(e) and getattr(e, 'mietrecht_kategorie', '') != 'gewerbe' and not getattr(e, 'ist_einstellplatz', False)
    aktiv = v.status == 'aktiv'
    gek = v.status == 'gekuendigt'
    beendet = v.status in ('gekuendigt', 'archiviert')
    hat_kaution = bool(v.kautions_einbezahlt_am)
    sperrkonto = hat_kaution and not getattr(v, 'ist_kautionsversicherung', False)
    pflicht = formularpflicht_fuer_liegenschaft(lg)[0] if lg else 'unbekannt'

    labels = [b or '' for b in Dokument.objects.filter(vertrag=v).values_list('bezeichnung', flat=True)]

    def hat(prefix):
        return any(b.startswith(prefix) for b in labels)

    gruppen = [
        {'titel': 'Mietrechtliche Formulare', 'icon': 'recht', 'items': [
            {'titel': 'Anfangsmietzins (Art. 270)', 'icon': 'rechnung',
             'url': f'/neu/mietzins/{v.id}/anfangsmietzins/', 'erledigt': hat('Anfangsmietzins'),
             'pflicht': (pflicht == 'ja' and wohnraum),
             'sub': ('Formularpflicht' if (pflicht == 'ja' and wohnraum) else 'Mitteilung des Anfangsmietzinses')},
            {'titel': 'Mietzinsanpassung (Art. 269d)', 'icon': 'trend',
             'url': f'/neu/mietzins/{v.id}/anpassung/', 'verfuegbar': aktiv,
             'sub': 'Erhöhung / Senkung amtlich mitteilen'},
            {'titel': 'Kündigung (Art. 266)', 'icon': 'dokument',
             'url': f'/neu/vertraege/{v.id}/kuendigen/', 'verfuegbar': not gek,
             'erledigt': v.kuendigungen.exists(), 'sub': 'Vermieter- / Mieterkündigung'},
        ]},
        {'titel': 'Kaution (Art. 257e)', 'icon': 'geld', 'items': [
            {'titel': 'Hinterlegungsbestätigung', 'icon': 'drucken',
             'url': f'/neu/vertraege/{v.id}/kaution-beleg/hinterlegung/', 'verfuegbar': hat_kaution,
             'erledigt': hat('Kaution-Bestätigung'), 'sub': 'an die Mieterschaft', 'ablegen_post': True},
            {'titel': 'Freigabe an Bank', 'icon': 'bank',
             'url': f'/neu/vertraege/{v.id}/kaution-beleg/freigabe/', 'verfuegbar': sperrkonto,
             'erledigt': hat('Kaution-Freigabe'), 'sub': 'Sperrkonto freigeben', 'ablegen_post': True},
        ]},
        {'titel': 'Prozesse', 'icon': 'einstellungen', 'items': [
            {'titel': 'Zahlungsverzug (Art. 257d)', 'icon': 'recht',
             'url': f'/neu/vertraege/{v.id}/verzug/', 'sub': 'Frist + Kündigungsandrohung'},
            {'titel': 'Zahlungsvereinbarung', 'icon': 'geld',
             'url': f'/neu/vertraege/{v.id}/zahlungsvereinbarung/', 'sub': 'Ratenplan für einen Rückstand'},
            {'titel': 'Herabsetzungsbegehren (Art. 270a)', 'icon': 'trend',
             'url': f'/neu/vertraege/{v.id}/herabsetzung/', 'sub': 'Begehren des Mieters, 30 Tage Antwortfrist'},
            {'titel': 'Verfahren (Art. 271a)', 'icon': 'recht',
             'url': f'/neu/vertraege/{v.id}/verfahren/', 'sub': 'Schlichtung / Gericht: Kündigungssperre'},
            {'titel': 'Nutzungsentschädigung', 'icon': 'geld',
             'url': f'/neu/vertraege/{v.id}/nutzungsentschaedigung/', 'verfuegbar': v.ist_beendet,
             'sub': 'Mieter nach Vertragsende nicht ausgezogen'},
            {'titel': 'Mängelrüge (Art. 259)', 'icon': 'warnung',
             'url': f'/neu/vertraege/{v.id}/maengelruege/', 'erledigt': hat('Mängelrüge'),
             'sub': 'Fristansetzung zur Mängelbehebung'},
            {'titel': 'Untermiete (Art. 262)', 'icon': 'person',
             'url': f'/neu/vertraege/{v.id}/untermiete/', 'erledigt': hat('Untermiete-'),
             'sub': 'Zustimmung / Ablehnung'},
            # Hauptweg ist die Abnahme vor Ort (Raum für Raum, Unterschriften am
            # Gerät); das klassische Formular bleibt im Menü der Vertragsakte.
            {'titel': 'Wohnungsabnahme', 'icon': 'dokument',
             'url': f'/neu/vertraege/{v.id}/abnahme/vorort/', 'sub': 'Ein- / Auszugsprotokoll vor Ort'},
            {'titel': 'Schlussabrechnung', 'icon': 'rechnung',
             'url': f'/neu/vertraege/{v.id}/schlussabrechnung/', 'verfuegbar': (aktiv or beendet),
             'sub': 'beim Auszug'},
        ]},
        {'titel': 'Vertrag & Beilagen', 'icon': 'vertrag', 'items': [
            {'titel': 'Mietvertrag (PDF)', 'icon': 'vertrag', 'url': f'/vertrag/{v.id}/pdf/', 'sub': 'kompletter Vertrag'},
            {'titel': 'QR-Rechnung', 'icon': 'bank', 'url': f'/vertrag/{v.id}/qr/', 'sub': 'Einzahlungsschein QR-IBAN'},
            {'titel': 'Begleitbrief', 'icon': 'senden', 'url': f'/vertrag/{v.id}/dokument/begleitbrief/', 'sub': 'Anschreiben zur Unterzeichnung'},
            {'titel': 'Allgemeine Bedingungen', 'icon': 'dokument', 'url': f'/vertrag/{v.id}/dokument/allgemeine-bedingungen/', 'sub': 'Vertragsbeilage'},
            {'titel': 'Hausordnung', 'icon': 'arbeit', 'url': f'/vertrag/{v.id}/dokument/hausordnung/', 'sub': 'Vertragsbeilage'},
            {'titel': 'Wohnungsausweis', 'icon': 'person', 'url': f'/vertrag/{v.id}/dokument/wohnungsausweis/', 'sub': 'Mieter- und Objektdaten'},
        ]},
    ]
    for g in gruppen:
        for it in g['items']:
            it.setdefault('verfuegbar', True)
            it.setdefault('erledigt', False)
            it.setdefault('pflicht', False)
            # Was die Rolle ohnehin nicht öffnen darf, gar nicht erst als
            # Verknüpfung anbieten — sonst führt der Klick in eine Absage.
            # Die Rollen stehen an der View selbst (siehe `darf_oeffnen`), es
            # gibt hier also keine zweite Liste, die veralten könnte.
            if user is not None and not darf_oeffnen(user, it['url']):
                it['verfuegbar'] = False
                it['gesperrt'] = True
    return gruppen


def _wg_kandidaten(vertrag):
    """Personen, die als weitere WG-Mieter hinzugefügt werden können — alle Mieter
    ausser den bereits am Vertrag beteiligten Parteien (max. 50 für die Auswahl)."""
    from crm.models import Mieter
    aus = {vertrag.mieter_id, vertrag.mitmieter_id}
    if vertrag.pk:
        aus |= {m.id for m in vertrag.weitere_mieter.all()}
    return list(Mieter.objects.exclude(id__in=[i for i in aus if i])
                .order_by('nachname', 'vorname')[:50])


def _mietzins_grundlage(v):
    """Referenzzins und LIK, auf denen der verrechnete Mietzins beruht (Basis), samt
    «ausgeglichen bis» und dem aktuellen Stand der Verwaltung zum Vergleich."""
    from core.services.lik import lik_bezeichnung, stand_label
    zins, lik = v.effektive_basis()
    # Nur GEBUCHTE Anpassungen (nicht Entwürfe) — dieselbe Auswahl wie die Basis.
    letzte = v._wirksame_anpassung(date.today())
    org = v.organisation
    stand = None if letzte else v.basis_lik_stand
    return {
        'zins': zins, 'lik': lik,
        'lik_text': lik_bezeichnung(lik, basis=getattr(org, 'lik_basis', None) or 'Dezember 2020', stand=stand),
        'teuerung_bis': stand_label(stand),
        'angepasst_per': letzte.wirksam_ab if letzte else None,
        'kosten_bis': v.kostensteigerung_datum,
        'aktuell_zins': getattr(org, 'aktueller_referenzzinssatz', None),
        'aktuell_lik': getattr(org, 'aktueller_lik_punkte', None),
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vertrag_detail(request, pk):
    from rentals.models import Dokument as RentalsDokument
    v = get_object_or_404(
        Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=pk)
    basis = _global_filter(request)

    rechnungen = (DebitorenRechnung.objects.filter(vertrag=v)
                  .exclude(status='storniert').order_by('-datum')[:15])
    offene = [r for r in rechnungen if r.status in ('offen', 'teilbezahlt')]
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects.filter(vertrag=v, status='verbucht')
                 .order_by('-datum_eingang')[:15])
    anpassungen = v.anpassungen.order_by('-wirksam_ab')[:10]
    mietzins_komponenten = list(v.mietzins_komponenten.all())
    from core.services.archiv import ausblenden
    dokumente = ausblenden(RentalsDokument.objects.neueste()).filter(vertrag=v).order_by('-datum')[:15]

    rechnungs_rows = []
    for r in rechnungen:
        label, pill_cls = STATUS_PILL.get(r.status, (r.status, 'fw-flaeche2 fw-mutet'))
        rechnungs_rows.append({'r': r, 'status_label': label, 'pill_cls': pill_cls,
                               'offen': r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')})

    from core.models import AktivitaetsLog
    verlauf = list(AktivitaetsLog.objects.filter(ziel_typ='vertrag', ziel_id=v.id)
                   .select_related('benutzer')[:50])
    # Meilensteine, die NICHT über log_aktion laufen (z.B. der Webhook-Rücklauf
    # der digitalen Unterschrift), als synthetische Ereignisse einmischen — der
    # Rücklauf-Zeitstempel gehört in den Verlauf, nicht in den Seitenkopf.
    from types import SimpleNamespace
    if v.unterzeichnet_am:
        verlauf.append(SimpleNamespace(
            benutzer=None,
            aktion="Unterschriebener Vertrag zurückerhalten",
            details=f"Digital unterzeichnet von {v.mieter.display_name} — Rücklauf via DocuSeal, automatisch abgelegt.",
            zeitpunkt=v.unterzeichnet_am))
    verlauf.sort(key=lambda x: x.zeitpunkt, reverse=True)

    # Akte komplettieren: Schäden am Mietobjekt + offene Pendenzen/Fristen zum
    # Vertrag — alles zum Mietverhältnis an EINEM Ort (kein Menü-Wechsel nötig).
    from tickets.models import SchadenMeldung
    from core.models import Pendenz
    schaeden = list(ausblenden(SchadenMeldung.objects.filter(betroffene_einheit=v.einheit))
                    .order_by('-erstellt_am')[:15]) if v.einheit_id else []
    vertrag_pendenzen = []
    _heute = timezone.localdate()
    for p in Pendenz.objects.filter(erledigt=False, vertrag=v).order_by('faellig_am'):
        _purl, _plabel, _pwide, _pmodal = _pendenz_ziel(p)
        vertrag_pendenzen.append({'p': p, 'url': _purl, 'label': _plabel or 'Öffnen',
                                  'wide': _pwide, 'modal': _pmodal,
                                  'ueberfaellig': bool(p.faellig_am and p.faellig_am < _heute)})
    # Datierte Fristen (Teilmenge) für die Finanzen-Karte — analog zum Kontakt, damit
    # die 257d-Frist + Track & Trace auch unter «Finanzen» direkt sichtbar ist.
    vertrag_fristen = [e for e in vertrag_pendenzen if e['p'].faellig_am]

    # ---- Phase 4b: Was die Akte von selbst bemerken soll --------------
    # Die Kennzahlenleiste und die Chips zeigen im Konzept KEINE Felder,
    # sondern Zustaende. Alles hier stammt aus Feldern, die es laengst gibt —
    # `mietzinspotenzial` etwa steht seit Langem im Modell und wurde auf der
    # Vertragsakte nirgends abgefragt.
    _kopf = _akte_kopfzahlen(v, total_offen, offene, vertrag_pendenzen)

    # Etappe 4a.5b: Reiter aus dem Aktenregister statt aus dieser View.
    # Die Panels in fw/vertrag_detail.html sind auf denselben Satz umbenannt —
    # beides muss gemeinsam wandern, sonst zeigt ein Reiter auf kein Panel und
    # der Klick hinterlaesst eine leere Seite.
    from faelle.akten import aus_alt as _reiter_aus_alt
    from core.tenancy import aktuelle_organisation as _akt_org
    tab_liste = _reiter_aus_alt('mietverhaeltnis', [
        ('uebersicht', 'Übersicht', None),
        ('finanzen', 'Finanzen', len(offene) or None),
        ('mietzins', 'Mietzins', anpassungen.count() or None),
        ('schaeden', 'Schäden', len(schaeden) or None),
        ('pendenzen', 'Pendenzen', len(vertrag_pendenzen) or None),
        ('formulare', 'Formulare', None),
        ('dokumente', 'Dokumente', None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())
    from core.services.docuseal_service import docuseal_konfiguriert
    # konzept-v8 (#mv-…): Kontoblatt dieses Mietverhaeltnisses — nur lesend,
    # zwei Abfragen (`core.services.mieterkonto.berechne_vertragskonto`).
    from core.services.mieterkonto import berechne_vertragskonto
    konto_zeilen, konto_saldo = berechne_vertragskonto(v)
    # Inkasso auf der Akte: Betreibungen dieses Vertrags (auch solche, deren
    # `vertrag` leer blieb, über die Hauptforderung) und ein laufender Ratenplan.
    # Zwei Abfragen; der Einstieg «Betreibung einleiten» nimmt die älteste offene
    # Hauptforderung — der Assistent bietet die übrigen zur Auswahl an.
    from django.db.models import Q as _Q
    from finance.models import Betreibung
    betreibungen = list(Betreibung.objects.filter(_Q(vertrag=v) | _Q(debitoren_rechnung__vertrag=v))
                        .distinct().select_related('debitoren_rechnung').order_by('-begehren_am', '-id')[:10])
    zv_aktiv = v.zahlungsvereinbarungen.filter(status='aktiv').first()
    betreibung_start = min((r for r in offene if r.stammrechnung_id is None),
                           key=lambda r: (r.faellig_am or r.datum, r.id), default=None)
    # Staffelmiete: je Stufe das Fenster der schriftlichen Mitteilung (Art. 269d Abs. 5 OR, Art. 19a VMWG).
    staffel_mitteilungen = []
    if v.mietzins_modell == 'staffel':
        from core.services import staffel_mitteilung as _sm
        staffel_mitteilungen = _sm.uebersicht(v, _heute)
    return render(request, 'fw/vertrag_detail.html', {
        'staffel_mitteilungen': staffel_mitteilungen,
        'betreibungen': betreibungen,
        'zv_aktiv': zv_aktiv,
        'betreibung_start': betreibung_start,
        'konto_zeilen': konto_zeilen,
        'konto_saldo': konto_saldo,
        'formular_gruppen': _formulare_prozesse(v, request.user),
        **basis, 'nav': 'vertraege', 'v': v, 'verlauf': verlauf,
        'vertrag_pill': _vertrag_status_pill(v),
        'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0')),
        'mz_grundlage': _mietzins_grundlage(v),
        'rechnungs_rows': rechnungs_rows,
        'total_offen': total_offen,
        'anzahl_offen': len(offene),
        **_kopf,
        'zahlungen': zahlungen,
        'anpassungen': anpassungen,
        'mietzins_komponenten': mietzins_komponenten,
        'heute_iso': timezone.localdate().isoformat(),
        'dokumente': dokumente,
        'nebenobjekte': v.nebenobjekte.all(),
        'weitere_mieter': list(v.weitere_mieter.all()),
        'wg_kandidaten': _wg_kandidaten(v),
        'erstellbare_dokumente': _erstellbare_dokumente(v),
        'kuendigungen': v.kuendigungen.all(),
        'formular_kanton': _formular_kanton_label(v),
        'tab_liste': tab_liste,
        'vertrag_schaeden': schaeden,
        'vertrag_pendenzen': vertrag_pendenzen,
        'vertrag_fristen': vertrag_fristen,
        'vt_zugang_next': f'/neu/vertraege/{v.id}/?tab=pendenzen',
        'vt_fin_zugang_next': f'/neu/vertraege/{v.id}/?tab=finanzen',
        'docuseal_konfiguriert': docuseal_konfiguriert(),
        # Modul 2: Schlüssel dieses Vertrags mit Verlauf
        'schluessel_akte': _schluessel_akte(_ausgaben_von({'vertrag': v})),
        'schluessel_ausgabe_url': (f'/neu/liegenschaften/{v.einheit.liegenschaft_id}/schluessel/ausgabe/'
                                   f'?an=vertrag:{v.id}&einheit={v.einheit_id}' if v.einheit_id else ''),
    })


def _formular_kanton_label(vertrag):
    """Kürzel des Kantons für das amtliche Formular (SO/ZH/BE/…). Leer, wenn
    keine Liegenschaft/kein Kanton bestimmbar."""
    from core.services.kantone import kanton_fuer_liegenschaft
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    return kanton_fuer_liegenschaft(lg) if lg else ''


def _akte_kopfzahlen(v, total_offen, offene, pendenzen):
    """Kennzahlen, Chips und Hinweise der Vertragsakte.

    Alles gerechnet, nichts neu gespeichert. Die Trennung von der View haelt
    sie testbar und macht sichtbar, dass hier keine Abfrage dazukommt, die
    nicht schon vorher lief.
    """
    from decimal import Decimal

    from django.utils import timezone

    brutto = (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0'))
    heute = timezone.localdate()

    # --- Saldo: Monat der aeltesten offenen Position und hoechste Mahnstufe --
    aelteste = min((r for r in offene if getattr(r, 'faellig_am', None)),
                   key=lambda r: r.faellig_am, default=None)
    # `Mahnung` haengt direkt am Vertrag (FK `vertrag`), nicht ueber eine
    # Rechnung. Die erste Fassung filterte auf `rechnung__vertrag` — ein Feld,
    # das es nicht gibt. Django wirft dafuer FieldError, und ein blankes
    # `except Exception` fing ihn ab: Die Stufe blieb IMMER 0, die Anzeige
    # «Mahnstufe X» konnte nie erscheinen. Ein stummer except-Block ist in
    # diesem Haus ohnehin verboten (Befund P6), deshalb faengt er jetzt nur
    # noch den einen Fall, den es wirklich geben kann.
    from finance.models import Mahnung
    stufe = (Mahnung.objects.filter(vertrag=v)
             .order_by('-stufe').values_list('stufe', flat=True).first() or 0)
    monatsmieten = (total_offen / brutto) if brutto else Decimal('0')

    # --- Kaution: Betrag und Herkunft in einer Zeile -------------------------
    kaution_wert = f'CHF {v.kautions_betrag:,.2f}'.replace(',', "'") \
        if v.kautions_betrag else gettext('keine')
    if v.kautions_art == 'versicherung' and v.kautions_versicherer:
        kaution_fuss = v.kautions_versicherer
    elif v.kautions_konto:
        kaution_fuss = gettext('Sperrkonto %(konto)s…') % {'konto': v.kautions_konto[:8]}
    else:
        kaution_fuss = gettext(v.kautions_status_label)
    if v.kautions_betrag and brutto:
        kaution_fuss += ' · ' + gettext('%(n)s Monatsmieten') % {'n': round(v.kautions_betrag / brutto, 1)}

    # --- Naechste Frist: die frueheste offene, datierte Pendenz --------------
    datiert = [e for e in pendenzen if e['p'].faellig_am]
    naechste = min(datiert, key=lambda e: e['p'].faellig_am) if datiert else None

    # --- Chips: gerechnete Zustaende, nicht das Statusfeld -------------------
    # Der Zustandschip folgt dem ANZEIGE-Status. Sonst stuende auf der Akte
    # «Gekuendigt per 14.08.», waehrend die Liste denselben Vertrag als
    # «Beendet» fuehrt. Die Kuendigung bleibt in den Stammdaten sichtbar —
    # sie ist geschehen, auch wenn der Vertrag heute beendet ist.
    anzeige = v.anzeige_status
    chips = []
    if anzeige == v.ANZEIGE_BEENDET:
        chips.append(('mut', gettext('Beendet per %(d)s') % {'d': v.ende.strftime('%d.%m.%Y')}
                      if v.ende else gettext('Beendet')))
    elif anzeige == 'gekuendigt' and v.ende:
        chips.append(('crit', gettext('Gekündigt per %(d)s') % {'d': v.ende.strftime('%d.%m.%Y')}))
    elif anzeige == 'aktiv':
        chips.append(('good', gettext('Aktiv')))
    elif anzeige == 'entwurf':
        chips.append(('warn', gettext('Entwurf')))
    if monatsmieten >= 1:
        _n = int(monatsmieten)
        chips.append(('crit', ngettext('%(n)s Monatsmiete offen', '%(n)s Monatsmieten offen', _n) % {'n': _n}))
    elif total_offen:
        chips.append(('warn', gettext('CHF %(betrag)s offen') % {
            'betrag': f'{total_offen:,.2f}'.replace(',', "'")}))
    potenzial = v.mietzinspotenzial
    # Senkungsanspruch/Erhöhung und die Hinweise dazu sind mietrechtliche
    # Einschätzungen — bleiben deutsch bis zur juristischen Prüfung.
    if potenzial == 'decrease':
        chips.append(('info', 'Senkungsanspruch offen'))
    elif potenzial == 'increase':
        chips.append(('info', 'Erhöhung möglich'))

    # --- Hinweise: was die Akte bemerkt --------------------------------------
    hinweise = []
    if potenzial == 'decrease':
        hinweise.append({
            'art': 'info', 'ikon': 'hinweis',
            'titel': 'Offener Senkungsanspruch des Mieters',
            'text': ('Der Referenzzinssatz ist seit der Festsetzung dieses '
                     'Mietzinses gesunken. Ein Senkungsbegehren wäre begründet, '
                     'solange Teuerung und Kostensteigerung es nicht aufwiegen.'),
            'url': f'/neu/mietzins/{v.id}/anpassung/', 'knopf': gettext('Berechnung öffnen')})
    elif potenzial == 'increase':
        hinweise.append({
            'art': 'info', 'ikon': 'trend',
            'titel': 'Erhöhung wäre begründbar',
            'text': ('Referenzzins oder Teuerung liegen über der Basis dieses '
                     'Mietzinses.'),
            'url': f'/neu/mietzins/{v.id}/anpassung/', 'knopf': gettext('Berechnung öffnen')})
    if v.kautions_art and v.kautions_art != 'keine' and not v.kautions_einbezahlt_am:
        hinweise.append({
            'art': 'warn', 'ikon': 'gesperrt',
            'titel': 'Kaution vereinbart, aber nicht bestätigt',
            'text': ('Es ist eine Sicherheit vereinbart; Einzahlung oder '
                     'Zertifikat sind nicht erfasst. Bis dahin fehlt der '
                     'Nachweis nach Art. 257e OR.'),
            'url': f'/neu/vertraege/{v.id}/#kaution', 'knopf': gettext('Erfassen')})
    # Anfangsmietzins-Formular (Art. 270 Abs. 2 OR, MIET-04): Pflicht und Nachweis am Vertrag. Ohne Original
    # und ohne Nachweis sagt die Akte es oben, nicht erst im Reiter «Mietzins».
    from core.services.anfangsformular import anfangsformular_lage
    af_lage = anfangsformular_lage(v.einheit if v.einheit_id else None, v)
    if af_lage['gesperrt']:
        chips.append(('crit', gettext('Formular-Nachweis fehlt')))
        hinweise.append({
            'art': 'warn', 'ikon': 'recht',
            'titel': gettext('Anfangsmietzins-Formular erforderlich'),
            'text': af_lage['hinweis'],
            'url': f'/neu/vertraege/{v.id}/?tab=mietzins#vt-anfangsformular-nachweis', 'knopf': gettext('Nachweis erfassen')})
    # KEIN Hinweis auf eine fehlende Referenzzins-Basis: `basis_referenzzinssatz`
    # ist NOT NULL mit Vorgabewert aus `get_current_ref_zins`. Die Bedingung
    # koennte nie zutreffen — ein Hinweis, der nie erscheint, ist toter Code.
    # (Gefunden, weil der Test dazu mit IntegrityError abbrach.)

    eigentuemer = getattr(getattr(v.einheit, 'liegenschaft', None), 'eigentuemer', None)
    return {
        'af_lage': af_lage,
        'kopf_chips': chips,
        'kopf_hinweise': hinweise,
        'kopf_netto': v.netto_mietzins or Decimal('0'),
        'kopf_nk': v.nebenkosten or Decimal('0'),
        # `dateformat` statt `strftime('%B')`: strftime nimmt die Locale des
        # Prozesses — auf dem Server Englisch («May 2024») auch in der
        # deutschen Oberfläche. `dateformat` folgt der aktiven Sprache.
        'kopf_saldo_monat': (dateformat.format(aelteste.faellig_am, 'F Y')
                             if aelteste is not None else ''),
        'kopf_mahnstufe': stufe,
        'kopf_kaution_wert': kaution_wert,
        'kopf_kaution_fuss': kaution_fuss,
        'kopf_frist': naechste,
        'kopf_eigentuemer': eigentuemer,
        'kopf_potenzial': potenzial,
    }
