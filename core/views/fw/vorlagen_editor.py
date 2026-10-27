# core/views/fw/vorlagen_editor.py
#
# Modul 5 (27.10.2026): Editor, Live-Vorschau, Probe-PDF und Regeln der
# Dokumenten-Automatisierung unter Einstellungen › Vorlagen, dazu der Verlauf
# der Dokumentfassungen. Die Liste und das Speichern der Vorlage stehen
# weiter in `profil.py` (`fw_vorlagen`, `fw_vorlage_form`); hier liegen die
# Helfer, die beide brauchen, und die neuen Endpunkte.

import logging
from datetime import date

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, rolle_erforderlich
from core.tenancy import organisation_der_anfrage

from ._basis import _global_filter

logger = logging.getLogger(__name__)

#: Ein Vorschlag, wenn eine Vorlage aus einer Regelkachel heraus entsteht.
#: Nur Anschreiben, kein Rechtstext — die Verwaltung passt ihn an.
MUSTERTEXT = {
    'vertrag_erstellt': _('{mieter.anrede}\n\nbeiliegend erhalten Sie Ihren Mietvertrag für '
                          '{objekt.bezeichnung}, {objekt.adresse}. Mietbeginn ist der {vertrag.beginn}.\n\n'
                          'Freundliche Grüsse'),
    'bewerber_zugesagt': _('{mieter.anrede}\n\ngerne bieten wir Ihnen die Wohnung an der {objekt.adresse} '
                           'ab {vertrag.beginn} an. Der Nettomietzins beträgt CHF {vertrag.mietzins_netto}, '
                           'die Nebenkosten CHF {vertrag.nebenkosten}.\n\nFreundliche Grüsse\n'
                           '{verwaltung.sachbearbeiter}'),
    'kuendigung_erfasst': _('{mieter.anrede}\n\ndie Kündigung des Mietverhältnisses für {objekt.bezeichnung}, '
                            '{objekt.adresse} ist bei uns erfasst. Wir melden uns für die Wohnungsabnahme.\n\n'
                            'Freundliche Grüsse'),
    'mza_versandt': _('{mieter.anrede}\n\nSie erhalten das amtliche Formular zur Anpassung Ihres Mietzinses '
                      'für {objekt.bezeichnung}. Bei Fragen erreichen Sie uns unter {verwaltung.telefon}.\n\n'
                      'Freundliche Grüsse'),
    'nk_versandt': _('{mieter.anrede}\n\nSie erhalten die Nebenkostenabrechnung für {objekt.bezeichnung}. '
                     'Bei Fragen erreichen Sie uns unter {verwaltung.telefon}.\n\nFreundliche Grüsse'),
    'abnahme_abgeschlossen': _('{mieter.anrede}\n\ndie Wohnungsabnahme für {objekt.bezeichnung}, '
                               '{objekt.adresse} ist abgeschlossen. Vielen Dank für die Übergabe.\n\n'
                               'Freundliche Grüsse'),
}

FELDER = ('name', 'kategorie', 'betreff', 'inhalt', 'format', 'sprache', 'ereignis', 'gueltig_ab', 'aktiv')


def _gueltig(wert, choices):
    return wert in {c for c, _l in choices}


def formular_lesen(P, vl):
    """(werte, fehler) aus dem POST. Fehlt ein Feld ganz, gilt der bisherige Wert.

    «Fehlt» und «leer» sind zweierlei: Ältere Formulare und Tests schicken
    nur Name, Kategorie, Betreff und Inhalt. Ein fehlendes Häkchen hiesse
    dort sonst «ausgeschaltet» — darum trägt der Editor `aktiv_feld` mit.
    """
    from crm.models import Vorlage
    from core.services.platzhalter import unbekannte
    fehler = []

    def alt(feld, standard):
        return getattr(vl, feld, standard) if vl is not None else standard

    werte = {
        'name': (P.get('name') or '').strip(),
        'kategorie': P.get('kategorie', alt('kategorie', 'brief')),
        'betreff': (P.get('betreff') or '').strip(),
        'inhalt': P.get('inhalt', ''),
        'format': P.get('format', alt('format', 'text')),
        'sprache': P.get('sprache', alt('sprache', 'de')),
        'ereignis': P.get('ereignis', alt('ereignis', '')),
        'gueltig_ab': alt('gueltig_ab', None),
        'aktiv': ('aktiv' in P) if 'aktiv_feld' in P else alt('aktiv', True),
    }
    if 'gueltig_ab' in P:
        roh = (P.get('gueltig_ab') or '').strip()
        try:
            werte['gueltig_ab'] = date.fromisoformat(roh) if roh else None
        except ValueError:
            fehler.append(gettext('«Gültig ab» ist kein Datum.'))
            werte['gueltig_ab'] = None
    if not werte['name']:
        fehler.append(gettext('Bezeichnung ist erforderlich.'))
    if not _gueltig(werte['kategorie'], Vorlage.KATEGORIE_CHOICES):
        fehler.append(gettext('Unbekannte Kategorie.'))
    if not _gueltig(werte['format'], Vorlage.FORMAT_CHOICES):
        fehler.append(gettext('Unbekanntes Format.'))
    if not _gueltig(werte['sprache'], Vorlage.SPRACHE_CHOICES):
        fehler.append(gettext('Unbekannte Sprache.'))
    if werte['ereignis'] and not _gueltig(werte['ereignis'], Vorlage.EREIGNIS_CHOICES):
        fehler.append(gettext('Unbekanntes Ereignis.'))
    falsch = unbekannte(werte['betreff'] + '\n' + werte['inhalt'])
    if falsch:
        fehler.append(gettext('Unbekannte Platzhalter: %(liste)s. Erlaubt sind die Platzhalter in der Liste '
                              'neben dem Text.') % {'liste': ', '.join(falsch)})
    return werte, fehler


def formular_vorbelegung(G, vl):
    """Werte für ein frisch geöffnetes Formular.

    `?ereignis=…` (aus einer Regelkachel) legt einen Mustertext vor;
    `?von=<pk>&sprache=fr` übernimmt eine bestehende Vorlage als Grundlage
    einer weiteren Sprachfassung.
    """
    from crm.models import Vorlage
    if vl is not None:
        return {f: getattr(vl, f) for f in FELDER}
    werte = {'name': '', 'kategorie': 'brief', 'betreff': '', 'inhalt': '', 'format': 'text',
             'sprache': 'de', 'ereignis': '', 'gueltig_ab': None, 'aktiv': True}
    von = (G.get('von') or '').strip()
    if von.isdigit():
        quelle = Vorlage.objects.filter(pk=int(von)).first()       # eigene oder System
        if quelle is not None:
            werte.update({f: getattr(quelle, f) for f in FELDER})
            werte['gueltig_ab'] = None
    ereignis = (G.get('ereignis') or '').strip()
    if not von and _gueltig(ereignis, Vorlage.EREIGNIS_CHOICES):
        werte.update({'ereignis': ereignis, 'kategorie': 'dokument',
                      'name': str(dict(Vorlage.EREIGNIS_CHOICES)[ereignis]),
                      'inhalt': str(MUSTERTEXT.get(ereignis, ''))})
    sprache = (G.get('sprache') or '').strip()
    if _gueltig(sprache, Vorlage.SPRACHE_CHOICES):
        werte['sprache'] = sprache
    return werte


def formular_kontext(request, vl, werte):
    """Alles, was `fw/vorlage_form.html` braucht — für GET und für den Fehlerfall."""
    from crm.models import Vorlage
    from mietprozess.models import Mietbewerbung
    from rentals.models import Mietvertrag
    from core.services.platzhalter import ALIASE, gruppiert
    from .profil import PLATZHALTER_HILFE

    fassungen = []
    if vl is not None:
        geschwister = (Vorlage.objects.filter(name=vl.name, ereignis=vl.ereignis)
                       .exclude(pk=vl.pk).order_by('sprache', '-version'))
        vorhanden = {}
        for g in geschwister:
            if g.organisation_id == vl.organisation_id:
                vorhanden.setdefault(g.sprache, g)
        for code, label in Vorlage.SPRACHE_CHOICES:
            if code == vl.sprache:
                continue
            ziel = vorhanden.get(code)
            fassungen.append({'code': code, 'label': label,
                              'url': (f'/neu/vorlagen/{ziel.pk}/bearbeiten/' if ziel
                                      else f'/neu/vorlagen/neu/?von={vl.pk}&sprache={code}'),
                              'vorhanden': ziel is not None})
    return {
        'vl': vl, 'ist_neu': vl is None, 'werte': werte,
        'ist_system': vl is not None and vl.organisation_id is None,
        'version': (vl.version if vl is not None else 1),
        'kategorien': Vorlage.KATEGORIE_CHOICES, 'formate': Vorlage.FORMAT_CHOICES,
        'sprachen': Vorlage.SPRACHE_CHOICES, 'ereignisse': Vorlage.EREIGNIS_CHOICES,
        'gruppen': gruppiert(),
        'alte_platzhalter': [(c, b) for c, b in PLATZHALTER_HILFE if c.strip('{}') in ALIASE],
        'fassungen': fassungen,
        'vorschau_vertraege': list(Mietvertrag.objects.select_related('mieter', 'einheit')
                                   .order_by('-id')[:30]),
        'vorschau_bewerbungen': list(Mietbewerbung.objects.select_related('einheit')
                                     .order_by('-id')[:20]),
    }


def _quelle(request):
    """Der Datensatz der Vorschau — aus der EIGENEN Verwaltung, sonst 404.

    `v:<id>` ein Vertrag, `b:<id>` eine Bewerbung, leer = Beispielwerte. Der
    Mandantenfilter steckt im Manager (`Mietvertrag.objects`); eine fremde
    ID findet er nicht.
    """
    from mietprozess.models import Mietbewerbung
    from rentals.models import Mietvertrag
    roh = (request.POST.get('quelle') or '').strip()
    if not roh:
        return {}
    art, _sep, nr = roh.partition(':')
    if not nr.isdigit():
        raise Http404
    if art == 'v':
        return {'vertrag': get_object_or_404(
            Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=int(nr))}
    if art == 'b':
        return {'bewerbung': get_object_or_404(
            Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=int(nr))}
    raise Http404


def _vorschau_daten(request):
    """(org, entwurf, kontext, mit_daten) aus dem Editorformular."""
    from crm.models import Vorlage
    from core.services.platzhalter import beispiel_kontext, kontext_fuer
    org = organisation_der_anfrage(request)
    P = request.POST
    entwurf = Vorlage(betreff=(P.get('betreff') or '').strip(), inhalt=P.get('inhalt', ''),
                      format=P.get('format') if _gueltig(P.get('format'), Vorlage.FORMAT_CHOICES) else 'text',
                      sprache=P.get('sprache') if _gueltig(P.get('sprache'), Vorlage.SPRACHE_CHOICES) else 'de')
    quelle = _quelle(request)
    if quelle:
        kontext = kontext_fuer(organisation=org, sprache=entwurf.sprache, **quelle)
    else:
        kontext = {**beispiel_kontext(), **kontext_fuer(organisation=org, sprache=entwurf.sprache)}
    return org, entwurf, kontext, bool(quelle)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_vorlage_vorschau(request):
    """Live-Vorschau als HTML-Ausschnitt: der Text mit einem echten Vertrag
    (oder einer Bewerbung) der eigenen Verwaltung, sonst mit Beispielwerten."""
    from core.services.dokumentsprache import in_sprache
    from core.services.platzhalter import unbekannte
    from core.services.vorlagen_pdf import dokument_kontext
    org, entwurf, kontext, mit_daten = _vorschau_daten(request)
    ctx = dokument_kontext(betreff=entwurf.betreff, inhalt=entwurf.inhalt, format=entwurf.format,
                           sprache=entwurf.sprache, kontext=kontext, organisation=org)
    with in_sprache(entwurf.sprache):
        return render(request, 'fw/_vorlage_vorschau.html', {
            **ctx, 'mit_daten': mit_daten,
            'unbekannte': unbekannte(entwurf.betreff + '\n' + entwurf.inhalt)})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_vorlage_probe_pdf(request):
    """Das PDF, wie die Regel es ablegen würde — nur angezeigt, nicht abgelegt."""
    from core.services.vorlagen_pdf import vorlage_pdf
    org, entwurf, kontext, _mit_daten = _vorschau_daten(request)
    try:
        pdf = vorlage_pdf(entwurf, kontext, org)
    except Exception:
        logger.exception('Probe-PDF nicht erzeugt (Organisation %s)', org.pk)
        return HttpResponse(gettext('Das Probe-PDF liess sich nicht erzeugen.'), status=500)
    antwort = HttpResponse(pdf, content_type='application/pdf')
    antwort['Content-Disposition'] = 'inline; filename="Probe.pdf"'
    return antwort


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_regel_umschalten(request):
    """Schaltet die Regel eines Ereignisses für die EIGENE Verwaltung an oder aus.

    Eigene Vorlagen zum Ereignis: alle aus, oder — wenn alle aus sind — alle
    an. Nur eine Systemvorlage: Es entsteht eine eigene, ausgeschaltete
    Kopie; die Systemvorlage bleibt für alle anderen, wie sie ist.
    """
    from crm.models import Vorlage
    from core.auth import log_aktion
    from core.services.dokument_regeln import aktive_vorlage
    if request.method != 'POST':
        return redirect('/neu/vorlagen/')
    ereignis = (request.POST.get('ereignis') or '').strip()
    if not _gueltig(ereignis, Vorlage.EREIGNIS_CHOICES):
        raise Http404
    org = organisation_der_anfrage(request)
    label = dict(Vorlage.EREIGNIS_CHOICES)[ereignis]
    eigene = Vorlage.objects.filter(organisation=org, ereignis=ereignis)
    if eigene.exists():
        an = not eigene.filter(aktiv=True).exists()
        eigene.update(aktiv=an)
    else:
        system = aktive_vorlage(ereignis, organisation=org)
        if system is None:
            messages.info(request, gettext('Für dieses Ereignis gibt es noch keine Vorlage.'))
            return redirect('/neu/vorlagen/')
        Vorlage.objects.create(
            organisation=org, name=system.name, kategorie=system.kategorie, betreff=system.betreff,
            inhalt=system.inhalt, format=system.format, sprache=system.sprache, ereignis=ereignis,
            version=(system.version or 1) + 1, aktiv=False)
        an = False
    from core.services.dokumentsprache import auf_deutsch
    log_aktion(request, "Dokumentregel " + ("eingeschaltet" if an else "ausgeschaltet"), auf_deutsch(label), '')
    messages.success(request, (gettext('Regel «%(e)s» ist eingeschaltet.') if an
                               else gettext('Regel «%(e)s» ist ausgeschaltet.')) % {'e': label})
    return redirect('/neu/vorlagen/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_rentals_dokument_verlauf(request, pk):
    """Detailansicht eines abgelegten Dokuments mit allen Fassungen."""
    from rentals.models import Dokument
    d = get_object_or_404(Dokument.objects.select_related('vertrag__mieter', 'vorlage'), id=pk)
    return render(request, 'fw/dokument_verlauf.html', {
        **_global_filter(request), 'nav': 'dokumente', 'd': d, 'fassungen': d.verlauf()})
