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

from ._basis import _global_filter, _num, _parse_adresse
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
        prot = Abnahmeprotokoll.objects.create(
            vertrag=v, typ=P.get('typ', 'auszug'), datum=datum,
            mieter_anwesend=P.get('mieter_anwesend') == 'on',
            verwalter_name=P.get('verwalter_name', '').strip(),
            allgemein_zustand=P.get('allgemein_zustand', 'gut'),
            schluessel_anzahl=int(P.get('schluessel_anzahl')) if (P.get('schluessel_anzahl') or '').isdigit() else None,
            zaehler_strom=P.get('zaehler_strom', '').strip(),
            zaehler_wasser=P.get('zaehler_wasser', '').strip(),
            zaehler_gas=P.get('zaehler_gas', '').strip(),
            neue_adresse=P.get('neue_adresse', '').strip(),
            bemerkungen=P.get('bemerkungen', '').strip(),
            unterschrift_mieter=P.get('unterschrift_mieter', '').strip(),
            unterschrift_verwalter=P.get('unterschrift_verwalter', '').strip(),
            abgeschlossen=P.get('abgeschlossen') == 'on',
        )
        # Mängel-Zeilen (parallele Listen). Fotos werden in Reihenfolge zugeordnet
        # (leere Datei-Inputs liefert der Browser nicht mit).
        raeume = P.getlist('m_raum')
        beschr = P.getlist('m_beschreibung')
        verurs = P.getlist('m_verursacher')
        kosten = P.getlist('m_kosten')
        assets = P.getlist('m_ausstattung')
        neuwerte = P.getlist('m_neuwert')
        vorsatz = P.getlist('m_vorsatz')  # Auswahlfeld '' / '1' (Checkbox liesse die Listen auseinanderlaufen)
        fotos = list(request.FILES.getlist('m_foto'))
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
            mangel = AbnahmeMangel(
                protokoll=prot,
                raum=(raeume[i] if i < len(raeume) else '').strip(),
                beschreibung=b,
                verursacher=(verurs[i] if i < len(verurs) else 'abnutzung'),
                kostenschaetzung=_dec(kosten[i] if i < len(kosten) else ''),
                ausstattung=element,
                neuwert=nw,
                vorsaetzlich=(vorsatz[i] if i < len(vorsatz) else '') == '1',
                foto=(fotos.pop(0) if fotos else None),
            )
            # Mieteranteil nach Lebensdauertabelle berechnen und einfrieren
            mangel.mieteranteil = mangel.berechne_mieteranteil(stichtag=datum)
            mangel.save()
        # Passende Auszugs-Pendenzen automatisch abhaken
        if prot.typ == 'auszug':
            from core.services.automation import erledige_pendenzen_fuer
            kw = ['Wohnungsabnahme', 'Abnahmetermin']
            if prot.zaehler_strom or prot.zaehler_wasser or prot.zaehler_gas:
                kw.append('Zählerstände')
            if prot.schluessel_anzahl is not None:
                kw.append('Schlüssel')
            # Ohne dem Mieter zugeordnete Mängel gibt es nichts zu rügen — die
            # 267a-Frist-Pendenz ist dann gegenstandslos. Mit Mieter-Mängeln
            # bleibt sie offen, bis die Rüge (fw_abnahme_ruege_267a) erzeugt ist.
            if not prot.maengel.filter(verursacher='mieter').exists():
                kw.append('Mängelrüge Art. 267a')
            erledige_pendenzen_fuer(v, kw, user=request.user)
            # Neue Wohnadresse ab Auszugsdatum als datierte Adress-Zeile hinterlegen
            # (Wegzug-Adresse) — für Haupt- und Mitmieter. Wird zum Stichtag zur
            # effektiven Zustelladresse (Nachsendung an die neue Adresse).
            neue_adr = (prot.neue_adresse or '').strip()
            if neue_adr:
                from crm.models import MieterAdresse
                strasse, plz, ort = _parse_adresse(neue_adr)
                for person in (v.mieter, v.mitmieter):
                    if not person:
                        continue
                    MieterAdresse.objects.get_or_create(
                        mieter=person, art='wohn', gueltig_ab=datum,
                        defaults=dict(strasse=strasse, plz=plz, ort=ort,
                                      quelle=f'auszug:{prot.id}',
                                      notiz='Wegzug gemäss Abnahmeprotokoll'))
                    person.sync_effektive_adresse()
        log_aktion(request, "Wohnungsabnahme erfasst", str(v.mieter), f"{auf_deutsch(prot.get_typ_display)} {datum}", ziel=v)
        if P.get('embed'):
            typ_txt = prot.get_typ_display()
            return render(request, 'fw/_modal_done.html', {'msg': f"{typ_txt} erfasst ({prot.maengel.count()} Mängel)"})
        messages.success(request, '✅ ' + gettext('Abnahmeprotokoll erfasst (%(count)s Mängel).') % {'count': prot.maengel.count()})
        # Mieterschaden ohne Alter/Lebensdauer: wird mit dem vollen Betrag belastet,
        # das ist angreifbar (Beweislast des Vermieters) — sichtbar machen statt still rechnen.
        from core.services.zeitwert import OHNE_LEBENSDAUER
        ohne = sum(1 for m in prot.maengel.select_related('ausstattung')
                   if m.zeitwert_grundlage == OHNE_LEBENSDAUER)
        if ohne:
            messages.warning(request, '⚠️ ' + gettext(
                '%(count)s Mieterschaden ohne Alter oder Lebensdauer des Bauteils: voller Betrag '
                'belastet. Bitte Einbaudatum und Lebensdauer im Raumbuch prüfen.') % {'count': ohne})
        return redirect(f'/neu/abnahme/{prot.id}/')

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
    basis = _global_filter(request)
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    return render(request, 'fw/abnahme_detail.html', {
        **basis, 'nav': 'vertraege', 'p': prot, 'v': prot.vertrag,
        'maengel': prot.maengel.select_related('ausstattung'),
        'positionen': prot.positionen.select_related('vorgaenger_position__protokoll'),
        'schluessel': prot.schluessel.all(),
        'hat_mieter_maengel': any(m.verursacher == 'mieter' for m in prot.maengel.all()),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_ruege_267a(request, pk):
    """Sofortige Mängelrüge nach Rückgabe (Art. 267a OR) aus dem Auszugs-
    Abnahmeprotokoll: rügt alle dem Mieter zugeordneten Mängel schriftlich —
    muss SOFORT nach der Abnahme versendet werden, sonst verwirken die
    Ersatzansprüche. Legt das PDF ab und hakt die Checklisten-Pendenz ab."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from crm.models import Organisation
    from core.services.mietprozess_briefe import rueckgabe_maengelruege_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    # Nur POST: Die Rüge ist eine Erklärung, sie hakt die Checklisten-Pendenz ab
    # und wird protokolliert. Ein blosser Seitenaufruf darf das nicht auslösen.
    if request.method != 'POST':
        return redirect(f'/neu/abnahme/{prot.id}/')
    v = prot.vertrag
    maengel = [{'raum': m.raum, 'beschreibung': m.beschreibung,
                'betrag': (m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung)}
               for m in prot.maengel.all() if m.verursacher == 'mieter']
    if not maengel:
        messages.info(request, gettext('Keine dem Mieter zugeordneten Mängel im Protokoll — keine Rüge nötig.'))
        return redirect(f'/neu/abnahme/{prot.id}/')
    pdf = rueckgabe_maengelruege_pdf(v, maengel, verwaltung=v.organisation,
                                     abnahme_datum=prot.datum)
    ablegen(pdf, f"Mängelrüge Art. 267a {prot.datum:%d.%m.%Y}",
            kategorie='vertrag', vertrag=v, dedup=True)
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(v, ['Mängelrüge Art. 267a'], user=request.user)
    log_aktion(request, "Mängelrüge Art. 267a erstellt", str(v.mieter),
               f"{len(maengel)} Mängel", ziel=v)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Maengelruege_267a_{v.mieter.nachname}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_loeschen(request, pk):
    """Abnahmeprotokoll löschen (inkl. Mängel-Positionen)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag'), id=pk)
    vid = prot.vertrag_id
    if request.method == 'POST':
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
    from core.services.abnahme_vorgaenger import vorgaenger_fuer, aus_und_einzug_paar
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    standard_typ = 'auszug' if v.status in ('gekuendigt', 'archiviert') else 'einzug'
    P = request.POST if request.method == 'POST' else request.GET
    paar = aus_und_einzug_paar(v)                     # (ausziehender, einziehender) oder None
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
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_vorort(request, pk):
    """Die Abnahme vor Ort: ein Raum pro Seite, am Ende der Abschluss."""
    from rentals.models import Abnahmeprotokoll
    basis = _global_filter(request)
    from django.shortcuts import redirect
    from rentals.models import AbnahmePosition
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    if prot.abgeschlossen:
        return redirect(f'/neu/abnahme/{prot.id}/')
    positionen = list(prot.positionen.select_related('vorgaenger_position__protokoll__vertrag__mieter'))
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
    return render(request, 'fw/abnahme_vorort.html', {
        **basis, 'nav': 'vertraege', 'p': prot, 'v': prot.vertrag,
        'raeume': raeume, 'schritt': schritt, 'raum': aktuell,
        'letzter': len(raeume), 'offen_total': sum(r['offen'] for r in raeume),
        'vorbestand_offen_total': sum(1 for p in positionen if p.vorbestand_offen),
        'schluessel': list(prot.schluessel.all()),
        'vorgaenger': prot.vorgaenger,
        'zustaende': [(z, dict(AbnahmePosition.ZUSTAND)[z]) for z in VORORT_ZUSTAENDE],
        'vorher': schritt - 1 if schritt > 0 else None,
        'nachher': schritt + 1 if schritt < len(raeume) else None,
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
    """Schliesst die Abnahme vor Ort ab: Zählerstände, Schlüssel, Namen der
    Unterzeichnenden. Danach ist das Protokoll nicht mehr änderbar."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    if prot.abgeschlossen:
        return redirect(f'/neu/abnahme/{prot.id}/')
    # Vorbestehende Mängel müssen entschieden sein, bevor sie dem Mieter belastet
    # werden: Was schon beim Einzug beanstandet war, ist kein Mieterschaden.
    offen = sum(1 for p in prot.positionen.select_related('vorgaenger_position', 'protokoll')
                if p.vorbestand_offen)
    if offen:
        messages.error(request, gettext(
            '%(count)s Bauteil(e) waren schon im Vorgänger-Protokoll beanstandet: bitte entscheiden, '
            'ob sie dem Mieter belastet werden.') % {'count': offen})
        return redirect(f'/neu/abnahme/{prot.id}/vorort/?r={_vorort_abschluss_schritt(prot)}')
    P = request.POST
    from core.services.abnahme_schluessel import schluessel_speichern, unterschrift_speichern
    # Unterschriften zuerst prüfen: Eine ungültige Eingabe schliesst nichts ab.
    for feld in ('unterschrift_mieter_bild', 'unterschrift_verwalter_bild'):
        eingabe = P.get(feld, '')
        if eingabe and not unterschrift_speichern(prot, feld, eingabe):
            messages.error(request, gettext('Die Unterschrift konnte nicht gelesen werden. Bitte erneut unterschreiben.'))
            return redirect(f'/neu/abnahme/{prot.id}/vorort/?r={_vorort_abschluss_schritt(prot)}')
    prot.mieter_anwesend = P.get('mieter_anwesend') == 'on'
    prot.zaehler_strom = P.get('zaehler_strom', '').strip()[:40]
    prot.zaehler_wasser = P.get('zaehler_wasser', '').strip()[:40]
    prot.zaehler_gas = P.get('zaehler_gas', '').strip()[:40]
    if 's_bezeichnung' in P:
        schluessel_speichern(prot, P)          # setzt schluessel_anzahl aus der Summe der gezählten
    else:
        prot.schluessel_anzahl = int(P['schluessel_anzahl']) if P.get('schluessel_anzahl', '').isdigit() else None
    prot.bemerkungen = P.get('bemerkungen', '').strip()
    prot.unterschrift_mieter = P.get('unterschrift_mieter', '').strip()[:120]
    prot.unterschrift_verwalter = P.get('unterschrift_verwalter', '').strip()[:120]
    prot.abgeschlossen = True
    prot.save()
    v = prot.vertrag
    log_aktion(request, "Wohnungsabnahme erfasst", str(v.mieter),
               f"{auf_deutsch(prot.get_typ_display)} {prot.datum} (vor Ort)", ziel=v)
    if prot.typ == 'auszug':
        from core.services.automation import erledige_pendenzen_fuer
        kw = ['Wohnungsabnahme', 'Abnahmetermin']
        if prot.zaehler_strom or prot.zaehler_wasser or prot.zaehler_gas:
            kw.append('Zählerstände')
        if prot.schluessel_anzahl is not None:
            kw.append('Schlüssel')
        # Wie in fw_abnahme_neu: ohne Mieter-Mängel ist die 267a-Pendenz gegenstandslos.
        if not prot.maengel.filter(verursacher='mieter').exists():
            kw.append('Mängelrüge Art. 267a')
        erledige_pendenzen_fuer(v, kw, user=request.user)
    messages.success(request, '✅ ' + gettext('Abnahmeprotokoll erfasst (%(count)s Mängel).') % {'count': prot.maengel.count()})
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
