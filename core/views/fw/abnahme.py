# core/views/fw/abnahme.py
#
# Wohnungsabnahme-Protokoll (Einzug/Auszug, fuer das Handy gebaut), dazu
# Vertragsstatus und Vertrag loeschen. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.
#
# Enthaelt die Maengelruege nach Art. 267a OR — eine Frist, an der nichts
# geraten werden darf (Skill schweizer-fachlogik). Der Umzug aendert daran
# nichts: Der Blockinhalt ist gegen HEAD Zeile fuer Zeile geprueft.

import re
from datetime import date
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.utils.translation import gettext
from django.utils import timezone

from core.auth import rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN, TEAM_ROLLEN
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num
from core.services.dokumentsprache import auf_deutsch


# ============================================================
# WOHNUNGSABNAHME-PROTOKOLL (Einzug/Auszug, mobil)
# ============================================================
ABNAHME_RAEUME = ['Eingang/Korridor', 'Wohnzimmer', 'Küche', 'Bad/WC', 'Zimmer 1',
                  'Zimmer 2', 'Zimmer 3', 'Balkon/Terrasse', 'Keller', 'Estrich', 'Allgemein']


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_neu(request, vertrag_id):
    """Wohnungsabnahme erfassen (mobil): Zustand, Mängel je Raum mit Verursacher,
    Fotos, Zählerstände, Unterschriften."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll, AbnahmeMangel
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST

        def _dec(x):
            try:
                return Decimal(_num(x)) if str(x).strip() else None
            except Exception:
                return None
        try:
            datum = date.fromisoformat(P.get('datum') or '')
        except Exception:
            datum = timezone.localdate()
        # Das Formular ERFASST nur. Abgeschlossen wird im Abschluss-Schritt mit
        # Unterschriften (core/services/abnahme_abschluss.py) — das frühere
        # Häkchen «abgeschlossen» schloss ohne jede Unterschrift ab und wird
        # ignoriert, falls ein alter Aufruf es noch mitschickt.
        typ = P.get('typ') if P.get('typ') in dict(Abnahmeprotokoll.TYP_CHOICES) else 'auszug'
        zustand = P.get('allgemein_zustand', 'gut')
        prot = Abnahmeprotokoll.objects.create(
            vertrag=v, typ=typ, datum=datum,
            mieter_anwesend=P.get('mieter_anwesend') == 'on',
            verwalter_name=P.get('verwalter_name', '').strip(),
            allgemein_zustand=(zustand if zustand in dict(Abnahmeprotokoll._meta.get_field('allgemein_zustand').choices)
                               else 'gut'),
            schluessel_anzahl=int(P.get('schluessel_anzahl')) if (P.get('schluessel_anzahl') or '').isdigit() else None,
            zaehler_strom=P.get('zaehler_strom', '').strip(),
            zaehler_wasser=P.get('zaehler_wasser', '').strip(),
            zaehler_gas=P.get('zaehler_gas', '').strip(),
            neue_adresse=P.get('neue_adresse', '').strip(),
            bemerkungen=P.get('bemerkungen', '').strip(),
            unterschrift_mieter=P.get('unterschrift_mieter', '').strip(),
            unterschrift_verwalter=P.get('unterschrift_verwalter', '').strip(),
        )
        # Mängel-Zeilen (parallele Listen). Das Foto hängt an der ZEILE, nicht an
        # der Reihenfolge: Ein leeres Datei-Feld schickt der Browser gar nicht mit,
        # `request.FILES.getlist` rückt dann alle späteren Fotos um eine Zeile nach
        # oben — Foto 2 landete am Mangel 1. Jede Zeile trägt deshalb ihre
        # Nummer (`m_zeile`), und ihr Foto heisst `m_foto_<nummer>`.
        raeume = P.getlist('m_raum')
        beschr = P.getlist('m_beschreibung')
        verurs = P.getlist('m_verursacher')
        kosten = P.getlist('m_kosten')
        assets = P.getlist('m_ausstattung')
        neuwerte = P.getlist('m_neuwert')
        vorsatz = P.getlist('m_vorsatz')  # Auswahlfeld '' / '1' (Checkbox liesse die Listen auseinanderlaufen)
        zeilen_nr = P.getlist('m_zeile')
        from portfolio.models import Ausstattung as _Ausstattung
        for i, b in enumerate(beschr):
            b = (b or '').strip()
            if not b:
                continue
            aid = (assets[i] if i < len(assets) else '').strip()
            element = None
            if aid.isdigit():
                element = _Ausstattung.objects.filter(id=int(aid), einheit=v.einheit).first()
            nw = _dec(neuwerte[i] if i < len(neuwerte) else '')
            if nw is None and element is not None:
                nw = element.neuwert
            nr = (zeilen_nr[i] if i < len(zeilen_nr) else '').strip()
            verursacher = verurs[i] if i < len(verurs) else 'abnutzung'
            mangel = AbnahmeMangel(
                protokoll=prot,
                raum=(raeume[i] if i < len(raeume) else '').strip()[:60],
                beschreibung=b[:255],
                verursacher=(verursacher if verursacher in dict(AbnahmeMangel.VERURSACHER) else 'abnutzung'),
                kostenschaetzung=_dec(kosten[i] if i < len(kosten) else ''),
                ausstattung=element,
                neuwert=nw,
                vorsaetzlich=(vorsatz[i] if i < len(vorsatz) else '') == '1',
                foto=(request.FILES.get(f'm_foto_{nr}') if nr.isdigit() else None),
            )
            # Mieteranteil nach Lebensdauertabelle berechnen und einfrieren
            mangel.mieteranteil = mangel.berechne_mieteranteil(stichtag=datum)
            mangel.save()
        log_aktion(request, "Wohnungsabnahme erfasst", str(v.mieter), f"{auf_deutsch(prot.get_typ_display)} {datum}", ziel=v)
        if P.get('embed'):
            return render(request, 'fw/_modal_done.html', {
                'msg': gettext('%(typ)s erfasst (%(count)s Mängel). Abschliessen mit Unterschriften im Protokoll.')
                % {'typ': prot.get_typ_display(), 'count': prot.maengel.count()}})
        messages.success(request, '✅ ' + gettext('Abnahmeprotokoll erfasst (%(count)s Mängel).') % {'count': prot.maengel.count()}
                         + ' ' + gettext('Jetzt unterschreiben und abschliessen.'))
        # Mieterschaden ohne Alter/Lebensdauer: wird mit dem vollen Betrag belastet,
        # das ist angreifbar (Beweislast des Vermieters) — sichtbar machen statt still rechnen.
        from core.services.abnahme_abschluss import ohne_lebensdauer
        ohne = len(ohne_lebensdauer(prot))
        if ohne:
            messages.warning(request, '⚠️ ' + gettext(
                '%(count)s Mieterschaden ohne Alter oder Lebensdauer des Bauteils: voller Betrag '
                'belastet. Bitte Einbaudatum und Lebensdauer im Raumbuch prüfen.') % {'count': ohne})
        # Weiter zum Abschluss-Schritt (ohne Bauteile ist er der erste Schritt).
        return redirect(f'/neu/abnahme/{prot.id}/vorort/')

    embed = request.GET.get('embed') == '1'
    from portfolio.models import Ausstattung
    elemente = list(Ausstattung.objects.filter(einheit=v.einheit))
    return render(request, 'fw/abnahme_neu.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'raeume': ABNAHME_RAEUME,
        'elemente': elemente,
        'heute': timezone.localdate().isoformat(),
        'verwalter_default': (request.user.get_full_name() or request.user.username),
        'typ_default': (request.GET.get('typ') if request.GET.get('typ') in ('auszug', 'einzug')
                        else ('auszug' if v.status in ('gekuendigt', 'archiviert') else 'einzug')),
        'embed_base': ('fw/base_embed.html' if embed else None),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_detail(request, pk):
    from rentals.models import Abnahmeprotokoll
    from portfolio.models import Ausstattung
    from core.services import abnahme_abschluss as ab
    basis = _global_filter(request)
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    maengel = list(prot.maengel.select_related('ausstattung', 'ticket'))
    ruege_noetig = ab.ruege_noetig(prot)
    return render(request, 'fw/abnahme_detail.html', {
        **basis, 'nav': 'vertraege', 'p': prot, 'v': prot.vertrag,
        # Die bei der Abnahme festgestellten Mängel und die später entdeckten
        # getrennt: Nur die ersten stehen im unterzeichneten Protokoll.
        'maengel': [m for m in maengel if m.entdeckt_am is None],
        'nachmaengel': [m for m in maengel if m.entdeckt_am is not None],
        'positionen': prot.positionen.select_related('vorgaenger_position__protokoll'),
        'schluessel': prot.schluessel.all(),
        'hat_mieter_maengel': ruege_noetig,
        'ruege_frist': ab.ruege_frist(prot.datum),
        'heute': timezone.localdate().isoformat(),
        'elemente': (list(Ausstattung.objects.filter(einheit=prot.vertrag.einheit))
                     if prot.abgeschlossen and prot.typ == 'auszug' else []),
        'raeume': ABNAHME_RAEUME,
        'abschluss_schritt': (_vorort_abschluss_schritt(prot) if not prot.abgeschlossen else None),
    })


def _datum_aus(text, standard=None):
    try:
        return date.fromisoformat((text or '').strip())
    except ValueError:
        return standard


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_ruege_267a(request, pk):
    """Mängelrüge nach Rückgabe (Art. 267a OR) als PDF, abgelegt in der
    Vertragsakte.

    Ohne `mangel`: die Rüge nach der Abnahme — alle dort dem Mieter
    zugeordneten Mängel und die fehlenden Schlüssel. Mit `mangel`: die Rüge
    eines später entdeckten Mangels (Abs. 3).

    Das PDF zu erzeugen erledigt KEINE Pendenz mehr: Gewahrt ist die Frist erst
    mit dem Versand. Dafür gibt es «Rüge versandt am» (fw_abnahme_ruege_versandt)."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.services.mietprozess_briefe import rueckgabe_maengelruege_pdf, versteckter_mangel_ruege_pdf
    from core.services.ablage import ablegen
    from core.services import abnahme_abschluss as ab
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    # Nur POST: Die Rüge ist eine Erklärung, sie wird abgelegt und protokolliert.
    # Ein blosser Seitenaufruf darf das nicht auslösen.
    if request.method != 'POST':
        return redirect(f'/neu/abnahme/{prot.id}/')
    v = prot.vertrag
    mangel_id = request.POST.get('mangel') or ''
    if mangel_id:
        # Fremde oder nicht nachträgliche Mängel: 404 wie jede fremde ID.
        m = get_object_or_404(prot.maengel, id=mangel_id if mangel_id.isdigit() else 0, entdeckt_am__isnull=False)
        pdf = versteckter_mangel_ruege_pdf(v, ab.nachruege_posten(m), verwaltung=v.organisation,
                                           abnahme_datum=prot.datum, entdeckt_am=m.entdeckt_am)
        ablegen(pdf, f"Mängelrüge Art. 267a Abs. 3 {m.entdeckt_am:%d.%m.%Y} ({m.id})",
                kategorie='vertrag', vertrag=v, dedup=True)
        log_aktion(request, "Mängelrüge Art. 267a Abs. 3 erstellt", str(v.mieter), m.beschreibung[:80], ziel=v)
        name = f"Maengelruege_267a3_{v.mieter.nachname}.pdf"
    else:
        posten = ab.ruege_posten(prot)
        if not posten:
            messages.info(request, gettext('Keine dem Mieter zugeordneten Mängel im Protokoll — keine Rüge nötig.'))
            return redirect(f'/neu/abnahme/{prot.id}/')
        pdf = rueckgabe_maengelruege_pdf(v, posten, verwaltung=v.organisation, abnahme_datum=prot.datum)
        ablegen(pdf, f"Mängelrüge Art. 267a {prot.datum:%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=True)
        log_aktion(request, "Mängelrüge Art. 267a erstellt", str(v.mieter), f"{len(posten)} Posten", ziel=v)
        name = f"Maengelruege_267a_{v.mieter.nachname}.pdf"
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{name}"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_abnahme_ruege_versandt(request, pk):
    """«Rüge versandt am»: erst das erledigt die Fristpendenz (Art. 267a OR).

    Das Datum liegt zwischen Abnahme (bzw. Entdeckung) und heute — eine Rüge
    vor dem Mangel oder in der Zukunft gibt es nicht. Mit `mangel` gilt es der
    Rüge eines später entdeckten Mangels."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.services import abnahme_abschluss as ab
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter'), id=pk)
    P = request.POST
    heute = timezone.localdate()
    datum = _datum_aus(P.get('datum'), heute)
    mangel_id = P.get('mangel') or ''
    mangel = None
    if mangel_id:
        mangel = get_object_or_404(prot.maengel, id=mangel_id if mangel_id.isdigit() else 0, entdeckt_am__isnull=False)
    frueheste = mangel.entdeckt_am if mangel is not None else prot.datum
    if datum is None or datum > heute or datum < frueheste:
        messages.error(request, gettext('Versanddatum ungültig: zwischen %(von)s und heute.') % {
            'von': frueheste.strftime('%d.%m.%Y')})
        return redirect(f'/neu/abnahme/{prot.id}/')
    if mangel is not None:
        ab.nachruege_versandt(mangel, datum, user=request.user)
        log_aktion(request, "Mängelrüge Art. 267a Abs. 3 versandt", str(prot.vertrag.mieter),
                   f"{datum:%d.%m.%Y}", ziel=prot.vertrag)
    else:
        if not ab.ruege_noetig(prot):
            messages.info(request, gettext('Keine dem Mieter zugeordneten Mängel im Protokoll — keine Rüge nötig.'))
            return redirect(f'/neu/abnahme/{prot.id}/')
        ab.ruege_versandt(prot, datum, P.get('sendungsnummer', ''), user=request.user)
        log_aktion(request, "Mängelrüge Art. 267a versandt", str(prot.vertrag.mieter),
                   f"{datum:%d.%m.%Y}", ziel=prot.vertrag)
    messages.success(request, '✅ ' + gettext('Versand der Rüge am %(datum)s festgehalten.') % {
        'datum': datum.strftime('%d.%m.%Y')})
    return redirect(f'/neu/abnahme/{prot.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_nachmangel(request, pk):
    """«Später entdeckten Mangel rügen» (Art. 267a Abs. 3 OR) an einem
    abgeschlossenen Auszugsprotokoll: Mangel mit Entdeckungsdatum erfassen,
    Pendenz «sofort versenden» anlegen. Die Rüge selbst entsteht danach über
    fw_abnahme_ruege_267a mit `mangel`."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from portfolio.models import Ausstattung
    from core.services import abnahme_abschluss as ab
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/abnahme/{prot.id}/#nachmangel')
    if not (prot.abgeschlossen and prot.typ == 'auszug'):
        messages.error(request, gettext('Nur an einem abgeschlossenen Auszugsprotokoll möglich.'))
        return redirect(f'/neu/abnahme/{prot.id}/')
    P = request.POST
    heute = timezone.localdate()
    beschreibung = ' '.join((P.get('beschreibung') or '').split())
    entdeckt = _datum_aus(P.get('entdeckt_am'), None)
    fehler = []
    if not beschreibung:
        fehler.append(gettext('Bitte den Mangel beschreiben.'))
    if entdeckt is None or entdeckt > heute or entdeckt < prot.datum:
        fehler.append(gettext('Entdeckungsdatum ungültig: zwischen %(von)s und heute.') % {
            'von': prot.datum.strftime('%d.%m.%Y')})
    try:
        kosten = Decimal(_num(P['kosten'])) if (P.get('kosten') or '').strip() else None
    except Exception:
        kosten = None
        fehler.append(gettext('Kostenschätzung ist keine Zahl.'))
    element = None
    if (P.get('ausstattung') or '').isdigit():
        element = Ausstattung.objects.filter(id=int(P['ausstattung']), einheit=prot.vertrag.einheit).first()
    if fehler:
        for f in fehler:
            messages.error(request, f)
        return redirect(f'/neu/abnahme/{prot.id}/#nachmangel')
    m = ab.nachmangel_erfassen(prot, raum=P.get('raum', ''), beschreibung=beschreibung, entdeckt_am=entdeckt,
                               kosten=kosten, ausstattung=element, foto=request.FILES.get('foto'),
                               user=request.user)
    log_aktion(request, "Später entdeckten Mangel erfasst", str(prot.vertrag.mieter), m.beschreibung[:80],
               ziel=prot.vertrag)
    messages.success(request, '✅ ' + gettext(
        'Mangel erfasst. Rüge jetzt erstellen und bis %(frist)s versenden.') % {
        'frist': ab.ruege_frist(entdeckt).strftime('%d.%m.%Y')})
    return redirect(f'/neu/abnahme/{prot.id}/#nachmaengel')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_abnahme_handwerker(request, pk):
    """«Handwerker beauftragen» aus einem Mangel: legt das Ticket an (einmal je
    Mangel) und führt dorthin — der Auftrag an den Handwerker läuft über die
    bestehende Ticketverwaltung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.services.abnahme_abschluss import ticket_fuer_mangel
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__einheit__liegenschaft'), id=pk)
    mangel_id = request.POST.get('mangel') or ''
    m = get_object_or_404(prot.maengel, id=mangel_id if mangel_id.isdigit() else 0)
    t, neu = ticket_fuer_mangel(m, user=request.user)
    if neu:
        log_aktion(request, "Ticket aus Abnahme-Mangel", f"Ticket #{t.id}", m.beschreibung[:80], ziel=prot.vertrag)
        messages.success(request, '✅ ' + gettext('Ticket #%(id)s angelegt: Handwerker jetzt zuweisen.') % {'id': t.id})
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_abnahme_loeschen(request, pk):
    """Abnahmeprotokoll löschen (inkl. Mängel-Positionen).

    Nur offene Entwürfe, und nur Verwalter/Inhaber: Ein abgeschlossenes
    Protokoll ist unterschrieben und Beweismittel (Art. 267a OR, Kaution) — es
    wird nie gelöscht, auch nicht von der Verwalterrolle."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag'), id=pk)
    vid = prot.vertrag_id
    if request.method == 'POST':
        if prot.abgeschlossen:
            messages.error(request, gettext(
                'Ein abgeschlossenes Abnahmeprotokoll ist unterschrieben und kann nicht gelöscht werden.'))
            return redirect(f'/neu/abnahme/{prot.id}/')
        log_aktion(request, "Abnahmeprotokoll gelöscht", str(prot.vertrag) if vid else '', '')
        prot.delete()
        messages.success(request, '🗑️ ' + gettext('Abnahmeprotokoll gelöscht.'))
    return redirect(f'/neu/vertraege/{vid}/' if vid else '/neu/vertraege/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_pdf(request, pk):
    from django.http import HttpResponse
    from rentals.models import Abnahmeprotokoll
    from crm.models import Organisation
    from core.services.abnahme_pdf import generate_abnahme_pdf
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    pdf = generate_abnahme_pdf(prot, verwaltung=prot.organisation)
    # Auto-Ablage in die Vertrags-Akte (abgeschlossene Protokolle)
    if getattr(prot, 'abgeschlossen', False):
        from core.services.ablage import ablegen
        ablegen(pdf, f"Abnahmeprotokoll ({auf_deutsch(prot.get_typ_display)}) {prot.datum:%d.%m.%Y}",
                kategorie='protokoll', vertrag=prot.vertrag, dedup=True)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Abnahmeprotokoll_{prot.vertrag.mieter.nachname}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_status(request, pk):
    """Setzt den Vertragsstatus: entwurf / aktiv / archiviert (inaktiv)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    if request.method == 'POST':
        neu = request.POST.get('status', '')
        erlaubt = {'entwurf': 'Entwurf', 'aktiv': 'Aktiv', 'archiviert': 'Inaktiv / Archiviert'}
        if neu in erlaubt:
            v.status = neu
            v.aktiv = (neu == 'aktiv')
            v.save(update_fields=['status', 'aktiv'])
            # Aktives Mietverhältnis → Objekt aus der Vermarktung/Feed nehmen.
            if neu == 'aktiv' and v.einheit_id and v.einheit.zur_ausschreibung:
                v.einheit.zur_ausschreibung = False
                v.einheit.save(update_fields=['zur_ausschreibung'])
            log_aktion(request, "Vertragsstatus geändert", str(v.mieter), erlaubt[neu], ziel=v)
            messages.success(request, '✅ ' + gettext('Vertrag ist jetzt: %(wert)s.') % {'wert': erlaubt[neu]})
        else:
            messages.error(request, gettext('Unbekannter Status.'))
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_vertrag_loeschen(request, pk):
    """Löscht einen Mietvertrag. Verknüpfte Rechnungen/Zahlungen bleiben erhalten
    (FK on_delete=SET_NULL) — die revisionssichere Buchhaltung wird nicht zerstört."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    if request.method == 'POST':
        # Abnahmeprotokolle sind Beweismittel und gehören zur Einheit: Ein Vertrag
        # mit Protokoll wird nicht gelöscht. Das Löschen würde sie über CASCADE mit
        # entfernen und die Geschichte der Einheit zerreissen.
        if v.abnahmen.exists():
            messages.error(request, gettext(
                'Der Vertrag hat Abnahmeprotokolle und kann nicht gelöscht werden: Sie gehören zur Einheit.'))
            return redirect(f'/neu/vertraege/{v.id}/')
        name = str(v.mieter)
        einheit = v.einheit.bezeichnung
        log_aktion(request, "Mietvertrag gelöscht", name, einheit)
        # Bereinigung der verwaisten Vertragspaket-Dokumente passiert zentral in
        # Mietvertrag.delete() (greift auch auf dem API-Löschpfad).
        v.delete()
        messages.success(request, '🗑️ ' + gettext('Vertrag (%(name)s · %(einheit)s) wurde gelöscht.') % {'name': name, 'einheit': einheit})
        return redirect('/neu/vertraege/')
    return redirect(f'/neu/vertraege/{v.id}/')


# ============================================================
# ABNAHME VOR ORT (Telefon): Raum für Raum, Ampel je Bauteil
# ============================================================
# Standard-Bauteile, wenn die Einheit noch kein Raumbuch hat. Gespeicherte
# Werte wie die Raumnamen oben: bleiben unübersetzt.
# Die Bauteile je Raum stehen in core/services/abnahme_bauteile.py (nach Raumtyp).
VORORT_STANDARDRAEUME = ['Küche', 'Bad/WC', 'Wohnzimmer', 'Zimmer 1', 'Zimmer 2', 'Zimmer 3',
                         'Eingang/Korridor', 'Balkon/Terrasse', 'Keller', 'Estrich']
# Schlüssel der Ampel, in der Reihenfolge der Anzeige. Quelle ist das Modell.
VORORT_ZUSTAENDE = ('io', 'normal', 'uebermaessig')


VORORT_MAX_RAEUME = 40


def _vorort_vorlagen(einheit, vorgaenger=None):
    """Die Strukturvorlagen: Raumliste je Vorlage. «vorgaenger» gibt es nur mit
    einem früheren Protokoll der Einheit, «raumbuch» nur mit Ausstattung."""
    from portfolio.models import Ausstattung
    aus_raumbuch = []
    for raum in Ausstattung.objects.filter(einheit=einheit).order_by('raum', 'sortierung', 'id') \
            .values_list('raum', flat=True):
        if raum not in aus_raumbuch:
            aus_raumbuch.append(raum)
    vorlagen = {'standard': list(VORORT_STANDARDRAEUME), 'leer': []}
    if aus_raumbuch:
        vorlagen = {'raumbuch': aus_raumbuch, **vorlagen}
    if vorgaenger is not None:
        raeume = []
        for raum in vorgaenger.positionen.values_list('raum', flat=True):
            if raum not in raeume:
                raeume.append(raum)
        if raeume:
            vorlagen = {'vorgaenger': raeume, **vorlagen}
    return vorlagen


def _vorort_raumkatalog(einheit, vorlagen):
    """Alle Räume, die in «Weitere Gruppen» angeboten werden (ohne Doppelte)."""
    from core.services.raumkatalog import RAUMTYPEN
    gesehen, katalog = set(), []
    for name in [*vorlagen.get('raumbuch', []), *ABNAHME_RAEUME, *RAUMTYPEN]:
        # «Bad/WC» und «Bad / WC» sind derselbe Raum in zwei Schreibweisen.
        schluessel = re.sub(r'\s*/\s*', '/', name).casefold()
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            katalog.append(name)
    return katalog


def _vorort_raeume_bereinigen(namen):
    """Räume in Eingabereihenfolge: getrimmt, ohne Leere und Doppelte, begrenzt."""
    gesehen, raeume = set(), []
    for n in namen:
        n = ' '.join((n or '').split())[:60]
        if n and n.casefold() not in gesehen:
            gesehen.add(n.casefold())
            raeume.append(n)
    return raeume[:VORORT_MAX_RAEUME]


def _vorort_abschluss_schritt(prot):
    """Der Index des Abschluss-Schritts = Anzahl der Räume. `order_by()` leert die
    Standardsortierung: Sonst käme sie ins DISTINCT und es würden Zeilen gezählt."""
    return prot.positionen.order_by().values('raum').distinct().count()


def _vorort_positionen_anlegen(prot, raeume=None, vorgaenger=None):
    """Legt die Bauteile für ein neues Protokoll an, Raum für Raum in der
    gewählten Reihenfolge. Quelle je Raum, in dieser Rangfolge:

    1. das Vorgänger-Protokoll (Bauteile samt Bezug zum Vorzustand),
    2. die Bauteile des Raumtyps (Küche: Schränke, Arbeitsplatte, Backofen …),
       wobei passende Raumbuch-Elemente den Standardeintrag ersetzen (mit
       Zeitwert-Bezug) und Elemente ohne Entsprechung dazukommen.

    Ohne `raeume`: die Räume des Vorgängers, sonst Raumbuch, sonst Standard."""
    from portfolio.models import Ausstattung
    from rentals.models import AbnahmePosition
    from core.services.abnahme_bauteile import bauteile_fuer_raum
    if raeume is None:
        vorlagen = _vorort_vorlagen(prot.vertrag.einheit, vorgaenger)
        raeume = next(iter(vorlagen.values()))
        if 'vorgaenger' not in vorlagen:
            raeume = vorlagen.get('raumbuch') or vorlagen['standard']
    je_raum_vorher = {}
    if vorgaenger is not None:
        for vp in vorgaenger.positionen.all():
            je_raum_vorher.setdefault(vp.raum.casefold(), []).append(vp)
    je_raum = {}
    for a in Ausstattung.objects.filter(einheit=prot.vertrag.einheit).order_by('sortierung', 'id'):
        je_raum.setdefault(a.raum.casefold(), []).append(a)
    nr = 0
    for raum in raeume:
        vorher = je_raum_vorher.get(raum.casefold())
        if vorher:
            zeilen = [(vp.bezeichnung, vp.ausstattung, vp) for vp in vorher]
        else:
            # Raumbuch-Elemente ersetzen passende Standard-Bauteile, der Rest des Raumtyps bleibt
            zeilen = [(b, a, None) for b, a in bauteile_fuer_raum(raum, je_raum.get(raum.casefold(), ()))]
        for bezeichnung, element, vp in zeilen:
            # Einzelnes save(): die Organisation wird dort aus der Kette abgeleitet.
            AbnahmePosition.objects.create(protokoll=prot, raum=raum, bezeichnung=bezeichnung[:120],
                                           ausstattung=element, vorgaenger_position=vp, sortierung=nr)
            nr += 1


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_vorort_start(request, vertrag_id):
    """Einrichtung der Abnahme vor Ort (Allgemein, Struktur) und Anlegen.

    GET zeigt den Assistenten; POST legt ein neues Protokoll an — mit Datum, Art
    und der gewählten Raumstruktur. Ein offener Entwurf wird nicht überschrieben,
    sondern oben zum Fortsetzen angeboten.

    Die Art kann «Aus- und Einzug» sein (nur mit einem zweiten Vertrag auf der
    Einheit, von beiden Seiten aus: aus dem Vertrag des Ausziehenden oder aus dem
    des Einziehenden): Dann entsteht das Auszugsprotokoll am Vertrag des
    Ausziehenden, und beim Abschluss wird das Einzugsprotokoll des Einziehenden
    daraus vorbereitet."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.services.abnahme_vorgaenger import vorgaenger_fuer, aus_und_einzug_paar, andere_vertraege
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    standard_typ = 'auszug' if v.status in ('gekuendigt', 'archiviert') else 'einzug'
    P = request.POST if request.method == 'POST' else request.GET
    try:
        partner_id = int(P.get('partner') or 0)
    except ValueError:
        partner_id = 0
    paar = aus_und_einzug_paar(v, partner_id)         # (ausziehender, einziehender) oder None
    ausziehend, einziehend = paar if paar else (None, None)
    erlaubt = ('auszug', 'einzug') + (('beides',) if paar else ())
    typ = P.get('typ') if P.get('typ') in erlaubt else standard_typ
    try:
        datum = date.fromisoformat(P.get('datum') or '')
    except ValueError:
        datum = timezone.localdate()
    # Das Vorgänger-Protokoll hängt vom Datum ab: Es ist das letzte bis dahin.
    vorgaenger = vorgaenger_fuer(v.einheit, datum)
    vorlagen = _vorort_vorlagen(v.einheit, vorgaenger)
    vorlage = P.get('vorlage') if P.get('vorlage') in vorlagen else next(iter(vorlagen))

    if request.method == 'POST':
        # Ohne Raumliste im Aufruf (altes Formular, Skript) gilt die Vorlage.
        raeume = _vorort_raeume_bereinigen(P.getlist('raum')) if 'raum' in P else vorlagen[vorlage]
        if raeume:
            nutzt_vorgaenger = vorlage == 'vorgaenger'
            prot = Abnahmeprotokoll.objects.create(
                vertrag=ausziehend if typ == 'beides' else v,
                typ=('auszug' if typ == 'beides' else typ), datum=datum,
                vorgaenger=vorgaenger if nutzt_vorgaenger else None,
                folge_vertrag=einziehend if typ == 'beides' else None,
                verwalter_name=(request.user.get_full_name() or request.user.username))
            _vorort_positionen_anlegen(prot, raeume, vorgaenger if nutzt_vorgaenger else None)
            from core.services.abnahme_schluessel import schluessel_anlegen
            schluessel_anlegen(prot, vorgaenger if nutzt_vorgaenger else None)
            return redirect(f'/neu/abnahme/{prot.id}/vorort/')
        messages.error(request, gettext('Mindestens ein Raum ist nötig.'))
    else:
        raeume = vorlagen[vorlage]

    entwurf = Abnahmeprotokoll.objects.filter(vertrag__in=[v, *( [ausziehend] if ausziehend else [] )],
                                              abgeschlossen=False, positionen__isnull=False) \
        .distinct().order_by('-id').first()
    return render(request, 'fw/abnahme_vorort_neu.html', {
        **_global_filter(request), 'nav': 'vertraege', 'v': v,
        'typ': typ, 'datum': datum.isoformat(), 'vorlage': vorlage, 'raeume': raeume,
        'vorlagen': vorlagen, 'katalog': _vorort_raumkatalog(v.einheit, vorlagen),
        'entwurf': entwurf, 'vorgaenger': vorgaenger,
        'paar': paar, 'ausziehend': ausziehend, 'einziehend': einziehend,
        'partner': (einziehend if ausziehend.id == v.id else ausziehend) if paar else None,
        'andere': andere_vertraege(v),
    })


def _grundlage_texte():
    """Wie der Mieteranteil eines Schadens zustande kommt — je stabiler
    Grundlage aus core/services/zeitwert.py ein Satz für die Anzeige. Dieselben
    Sätze wie auf der Protokollseite: Vor Ort soll sichtbar sein, was dort
    später steht, besonders der volle Betrag ohne Lebensdauer."""
    from core.services import zeitwert as zw
    return {
        zw.ZEITWERT: gettext('Mieteranteil nach Lebensdauer (Zeitwert)'),
        zw.OHNE_LEBENSDAUER: gettext('Voller Betrag: Alter/Lebensdauer fehlt'),
        zw.VORSATZ: gettext('Absichtlich: kein Abzug'),
        zw.ABGESCHRIEBEN: gettext('Lebensdauer abgelaufen: kein Mieteranteil'),
        zw.OHNE_BETRAG: gettext('Noch kein Betrag: Kostenschätzung eingeben'),
        zw.KEIN_MIETERSCHADEN: gettext('Kein Mieterschaden'),
    }


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_vorort(request, pk):
    """Die Abnahme vor Ort: ein Raum pro Seite, am Ende der Abschluss.

    Auch ein Protokoll aus dem klassischen Formular (ohne Bauteile) schliesst
    hier ab: Es hat keine Räume, der Abschluss ist dann der erste Schritt."""
    from rentals.models import Abnahmeprotokoll
    basis = _global_filter(request)
    from django.shortcuts import redirect
    from rentals.models import AbnahmePosition
    from core.services import abnahme_abschluss as ab
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    if prot.abgeschlossen:
        return redirect(f'/neu/abnahme/{prot.id}/')
    positionen = list(prot.positionen.select_related('vorgaenger_position__protokoll__vertrag__mieter',
                                                     'mangel__ausstattung'))
    gruppen = {}
    for pos in positionen:
        gruppen.setdefault(pos.raum, []).append(pos)
    raeume = [{'nr': nr, 'name': name, 'positionen': ps,
               'offen': sum(1 for p in ps if not p.zustand),
               'fertig': all(p.zustand for p in ps)}
              for nr, (name, ps) in enumerate(gruppen.items())]
    try:
        schritt = int(request.GET.get('r', 0))
    except ValueError:
        schritt = 0
    schritt = max(0, min(schritt, len(raeume)))        # len(raeume) = Abschluss
    aktuell = raeume[schritt] if schritt < len(raeume) else None
    abschluss = {}
    if aktuell is None:
        abschluss = {
            'unbewertet': [p for p in positionen if not p.zustand],
            'ohne_lebensdauer': ab.ohne_lebensdauer(prot),
            'allgemein_zustaende': Abnahmeprotokoll._meta.get_field('allgemein_zustand').choices,
            # Das klassische Formular hat den Allgemeinzustand schon gefragt; vor
            # Ort stand er bisher still auf dem Modell-Standard «gut» — hier
            # deshalb ohne Vorbelegung, damit er bewusst gewählt wird.
            'allgemein_vorbelegt': (prot.allgemein_zustand if not positionen else ''),
        }
    return render(request, 'fw/abnahme_vorort.html', {
        **basis, 'nav': 'vertraege', 'p': prot, 'v': prot.vertrag,
        'raeume': raeume, 'schritt': schritt, 'raum': aktuell,
        'letzter': len(raeume), 'offen_total': sum(r['offen'] for r in raeume),
        'vorbestand_offen_total': sum(1 for p in positionen if p.vorbestand_offen),
        'schluessel': list(prot.schluessel.all()),
        'vorgaenger': prot.vorgaenger,
        'zustaende': [(z, dict(AbnahmePosition.ZUSTAND)[z]) for z in VORORT_ZUSTAENDE],
        'grundlage_texte': (_grundlage_texte() if aktuell is not None else {}),
        'vorher': schritt - 1 if schritt > 0 else None,
        'nachher': schritt + 1 if schritt < len(raeume) else None,
        **abschluss,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_abnahme_position_speichern(request, pk):
    """Speichert eine Änderung an einem Bauteil (Ampel, Kommentar, Foto,
    Kosten, Absicht) und hält den zugehörigen Mangel im Einklang. Antwort: JSON.
    Nur die Felder, die im Aufruf stehen, werden angefasst."""
    from rentals.models import Abnahmeprotokoll, AbnahmePosition
    prot = get_object_or_404(Abnahmeprotokoll, id=pk)
    pos = get_object_or_404(AbnahmePosition, id=request.POST.get('position') or 0, protokoll=prot)
    if prot.abgeschlossen:
        return JsonResponse({'ok': False, 'fehler': 'abgeschlossen'}, status=409)
    P = request.POST
    if 'zustand' in P:
        if P['zustand'] not in ('',) + VORORT_ZUSTAENDE:
            return JsonResponse({'ok': False, 'fehler': 'zustand'}, status=400)
        pos.zustand = P['zustand']
    if 'kommentar' in P:
        pos.kommentar = P['kommentar'].strip()[:2000]
    if 'kosten' in P:
        try:
            pos.kostenschaetzung = Decimal(_num(P['kosten'])) if P['kosten'].strip() else None
        except Exception:
            return JsonResponse({'ok': False, 'fehler': 'kosten'}, status=400)
    if 'bezeichnung' in P:
        name = ' '.join(P['bezeichnung'].split())[:120]
        if not name:
            return JsonResponse({'ok': False, 'fehler': 'bezeichnung'}, status=400)
        pos.bezeichnung = name
    if 'vorsatz' in P:
        pos.vorsaetzlich = P['vorsatz'] == '1'
    if 'vorbestand' in P:
        if P['vorbestand'] not in ('', 'mieter', 'vorbestehend'):
            return JsonResponse({'ok': False, 'fehler': 'vorbestand'}, status=400)
        pos.vorbestand_entscheid = P['vorbestand']
    if request.FILES.get('foto'):
        pos.foto = request.FILES['foto']
    if pos.zustand != 'uebermaessig':
        pos.vorbestand_entscheid = ''      # ohne Beanstandung gibt es nichts zu entscheiden
    pos.save()                 # zuerst: erst dabei bekommt ein neues Foto seinen Ablagepfad
    pos.mangel_abgleichen()
    pos.save()
    return JsonResponse({
        'ok': True, 'zustand': pos.zustand, 'bezeichnung': pos.bezeichnung,
        'foto': pos.foto.url if pos.foto else '',
        'mieteranteil': (str(pos.mangel.mieteranteil) if pos.mangel_id and pos.mangel.mieteranteil is not None else ''),
        'grundlage': (pos.mangel.zeitwert_grundlage if pos.mangel_id else ''),
        'offen': prot.positionen.filter(zustand='').count(),
        'vorbestand_warnung': pos.vorbestand_warnung,
        'vorbestand_entscheid': pos.vorbestand_entscheid,
        'vorbestand_offen': sum(1 for p in prot.positionen.select_related('vorgaenger_position', 'protokoll')
                                if p.vorbestand_offen),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_abnahme_vorort_abschliessen(request, pk):
    """Schliesst die Abnahme ab: Zählerstände, Schlüssel, Allgemeinzustand,
    neue Adresse, Anwesenheit und Unterschriften. Danach ist das Protokoll
    nicht mehr änderbar.

    Die Felder werden zuerst in den Entwurf übernommen — scheitert der
    Abschluss an einer Regel (`abschluss_pruefen`), steht beim zweiten Versuch
    alles wieder da. Nur die Unterschriften nicht: Sie gelten dem Stand, der
    tatsächlich abgeschlossen wird, und werden erst dann gespeichert."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.auth import log_aktion
    from core.services import abnahme_abschluss as ab
    from core.services.abnahme_schluessel import unterschrift_pruefen
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    if prot.abgeschlossen:
        return redirect(f'/neu/abnahme/{prot.id}/')
    zurueck = redirect(f'/neu/abnahme/{prot.id}/vorort/?r={_vorort_abschluss_schritt(prot)}')
    P = request.POST
    ab.abschlussfelder_uebernehmen(prot, P)
    prot.save()
    # Vorbestehende Mängel müssen entschieden sein, bevor sie dem Mieter belastet
    # werden: Was schon beim Einzug beanstandet war, ist kein Mieterschaden.
    offen = sum(1 for p in prot.positionen.select_related('vorgaenger_position', 'protokoll')
                if p.vorbestand_offen)
    if offen:
        messages.error(request, gettext(
            '%(count)s Bauteil(e) waren schon im Vorgänger-Protokoll beanstandet: bitte entscheiden, '
            'ob sie dem Mieter belastet werden.') % {'count': offen})
        return zurueck
    # Unterschriften prüfen: Eine ungültige Eingabe schliesst nichts ab.
    bilder = {}
    for feld in ('unterschrift_mieter_bild', 'unterschrift_verwalter_bild'):
        eingabe = P.get(feld, '')
        if not eingabe:
            continue
        roh = unterschrift_pruefen(eingabe)
        if roh is None:
            messages.error(request, gettext('Die Unterschrift konnte nicht gelesen werden. Bitte erneut unterschreiben.'))
            return zurueck
        bilder[feld] = roh
    if not prot.mieter_anwesend:
        # Abwesend: Eine Unterschrift «des Mieters» kann es nicht geben.
        bilder.pop('unterschrift_mieter_bild', None)
    fehler = ab.abschluss_pruefen(prot, P, bilder)
    if fehler:
        for f in fehler:
            messages.error(request, f)
        return zurueck
    from django.core.files.base import ContentFile
    for feld, roh in bilder.items():
        getattr(prot, feld).save(f'{feld.replace("_bild", "")}.png', ContentFile(roh), save=False)
    if not prot.unterschrift_verwalter:
        prot.unterschrift_verwalter = prot.verwalter_name
    prot.abgeschlossen = True
    prot.save()
    v = prot.vertrag
    bestaetigt = []
    if P.get('unbewertet_ok') == '1' and ab.unbewertet(prot):
        bestaetigt.append('unbewertete Bauteile')
    if P.get('ohne_lebensdauer_ok') == '1' and ab.ohne_lebensdauer(prot):
        bestaetigt.append('voller Betrag ohne Lebensdauer')
    log_aktion(request, "Wohnungsabnahme abgeschlossen", str(v.mieter),
               f"{auf_deutsch(prot.get_typ_display)} {prot.datum}"
               + (f" · bestätigt: {', '.join(bestaetigt)}" if bestaetigt else ''), ziel=v)
    ohne_zuordnung = ab.abschluss_folgen(prot, user=request.user)
    if ohne_zuordnung is None:
        messages.warning(request, gettext('Die Schlüssel konnten nicht gebucht werden. Bitte über die '
                                          'Schliessanlage der Liegenschaft nachtragen.'))
    elif ohne_zuordnung:
        messages.warning(request, gettext('Nicht im Schlüsselregister, deshalb nicht gebucht: %(liste)s')
                         % {'liste': ', '.join(ohne_zuordnung)})
    # Modul 5: Regel «Abnahme abgeschlossen» — Begleitdokument; das Protokoll
    # selbst entsteht wie bisher beim PDF-Abruf.
    from core.services.dokument_regeln import dokument_fuer_ereignis
    dokument_fuer_ereignis('abnahme_abgeschlossen', organisation=v.organisation, vertrag=v)
    messages.success(request, '✅ ' + gettext('Abnahmeprotokoll erfasst (%(count)s Mängel).') % {'count': prot.maengel.count()})
    if prot.typ == 'auszug' and ab.ruege_noetig(prot):
        hinweis = gettext('Mängelrüge bis %(frist)s versenden (Art. 267a OR).') % {
            'frist': ab.ruege_frist(prot.datum).strftime('%d.%m.%Y')}
        if not prot.mieter_anwesend:
            hinweis += ' ' + gettext('Der Mieter war abwesend: eingeschrieben senden.')
        messages.warning(request, '⚠️ ' + hinweis)
    if prot.folge_vertrag_id and not prot.nachfolger.exists():
        from core.services.abnahme_vorgaenger import einzug_vorbereiten
        einzug = einzug_vorbereiten(prot)
        messages.info(request, gettext(
            'Einzugsprotokoll für den Nachmieter vorbereitet: bitte prüfen und abschliessen.'))
        return redirect(f'/neu/abnahme/{einzug.id}/vorort/?r={_vorort_abschluss_schritt(einzug)}')
    return redirect(f'/neu/abnahme/{prot.id}/')


_SERVICE_WORKER = """\
// Abnahme vor Ort: Seiten und Schriften vorhalten, damit ein Raum ohne Empfang
// offen bleibt. Nur die Vor-Ort-Seiten und /static/ — nichts sonst.
const CACHE = 'abnahme-vor-ort-v1';
const MAX_ALTER = 24 * 3600 * 1000;       // Seiten mit Mieterdaten bleiben höchstens einen Tag
const SEITE = /^\\/neu\\/abnahme\\/\\d+\\/vorort\\/$/;
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

async function aufraeumen(cache) {
  for (const anfrage of await cache.keys()) {
    const antwort = await cache.match(anfrage);
    const datum = antwort && Date.parse(antwort.headers.get('date') || '');
    if (!datum || Date.now() - datum > MAX_ALTER) await cache.delete(anfrage);
  }
}
async function netzZuerst(anfrage) {
  const cache = await caches.open(CACHE);
  try {
    const antwort = await fetch(anfrage);
    if (antwort.ok && !antwort.redirected) { cache.put(anfrage, antwort.clone()); aufraeumen(cache); }
    return antwort;
  } catch (fehler) {
    const treffer = await cache.match(anfrage);
    if (treffer) return treffer;
    throw fehler;
  }
}
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== self.location.origin) return;
  if (SEITE.test(u.pathname) || u.pathname.startsWith('/static/')) e.respondWith(netzZuerst(r));
});
self.addEventListener('message', e => {
  const seiten = (e.data && e.data.vorladen) || [];
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    for (const s of seiten) {
      if (!SEITE.test(new URL(s, self.location.origin).pathname)) continue;
      try { const a = await fetch(s, { credentials: 'same-origin' }); if (a.ok && !a.redirected) await cache.put(s, a); } catch (x) {}
    }
  })());
});
"""


def abnahme_service_worker(request):
    """Service Worker der Vor-Ort-Abnahme (Scope /neu/abnahme/). Enthält nichts
    Mandantenspezifisches und braucht deshalb keine Anmeldung."""
    from django.http import HttpResponse
    r = HttpResponse(_SERVICE_WORKER, content_type='text/javascript; charset=utf-8')
    r['Cache-Control'] = 'no-cache'
    return r

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_texte(request):
    """Einstellungsseite: Wortlaut der Schlussbestimmungen im Abnahmeprotokoll.

    Gespeichert wird nur, was vom Standard abweicht; ein leeres Feld oder der
    Standardtext selbst stellt den Standard wieder her."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from core.auth import hat_rolle, log_aktion
    from core.services.abnahme_texte import ABSAETZE, MAX_LAENGE, eigene_texte
    from rentals.models import AbnahmeText
    basis = _global_filter(request)
    organisation = getattr(request, 'organisation', None)

    if request.method == 'POST':
        if organisation is None or not hat_rolle(request.user, SCHREIB_ROLLEN):
            messages.error(request, gettext('Keine Berechtigung zum Bearbeiten.'))
            return redirect('/neu/abnahme-texte/')
        zu_lang = []
        geaendert = 0
        for schluessel, (titel, standard) in ABSAETZE.items():
            text = ' '.join((request.POST.get(f'text_{schluessel}') or '').split())
            if len(text) > MAX_LAENGE:
                zu_lang.append(gettext(titel))
                continue
            vorher = eigene_texte(organisation).get(schluessel)
            if not text or text == ' '.join(standard.split()):
                if vorher is not None:
                    AbnahmeText.objects.filter(organisation=organisation, schluessel=schluessel).delete()
                    geaendert += 1
            elif text != vorher:
                AbnahmeText.objects.update_or_create(organisation=organisation, schluessel=schluessel,
                                                     defaults={'text': text})
                geaendert += 1
        if zu_lang:
            messages.error(request, gettext('Zu lang (höchstens %(n)s Zeichen): %(titel)s') % {
                'n': MAX_LAENGE, 'titel': ', '.join(zu_lang)})
        elif geaendert:
            log_aktion(request, 'Abnahme-Texte bearbeitet')
            messages.success(request, gettext('Gespeichert'))
        return redirect('/neu/abnahme-texte/')

    eigene = eigene_texte(organisation)
    absaetze = [{'schluessel': k, 'titel': titel, 'text': eigene.get(k) or standard,
                 'eigen': k in eigene} for k, (titel, standard) in ABSAETZE.items()]
    return render(request, 'fw/abnahme_texte.html', {**basis, 'nav': 'einstellungen', 'absaetze': absaetze})
