# core/views/eigentuemer_portal.py
"""Eigentümerportal v2: mehrseitig, lesend, nur eigene Liegenschaften.

Jede Seite hier hängt an `@eigentuemer_seite`: angemeldet, mit Eigentümerverknüpfung,
`never_cache`. Was sichtbar ist, entscheidet `core.services.eigentuemer_portal` über
die Menge des Eigentümers (Mandantentrennung UND Eigentümerbezug); eine fremde ID
ergibt 404, nie 403.

Die Übersicht (`/portal/`) und die Reparaturfreigabe bleiben in `core/views/portal.py`.
"""
import os
from functools import wraps

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache

from core.services import eigentuemer_portal as dienst
from core.utils.parameter import jahr_streng
from core.zeit import datum_heute


def eigentuemer_seite(view):
    """Angemeldet + Eigentümerverknüpfung; reicht den `Eigentuemer` als zweites Argument.

    Ohne Verknüpfung (Team-Konto, Mieter-Konto, unverknüpftes Konto) geht es zur
    Portal-Startseite zurück, die den Fall erklärt bzw. ins Team weiterleitet."""
    @wraps(view)
    @never_cache
    @login_required
    def gehuellt(request, *args, **kwargs):
        eigentuemer = getattr(request.user, 'eigentuemer_profil', None)
        if eigentuemer is None:
            return redirect('portal')
        return view(request, eigentuemer, *args, **kwargs)
    return gehuellt


def _kontext(eigentuemer, **extra):
    """Gemeinsamer Kontext: Mandatsende erscheint auf jeder Seite als Hinweis."""
    return {'eigentuemer': eigentuemer, 'mandat_ende': dienst.mandat_status(eigentuemer),
            'hat_stweg': eigentuemer.stweg_einheiten.exists(), **extra}


@eigentuemer_seite
def portal_liegenschaften(request, eigentuemer):
    karten = dienst.liegenschaften_karten(eigentuemer)
    return render(request, 'core/eig_liegenschaften.html', _kontext(
        eigentuemer, karten=karten,
        aktive=[k for k in karten if k['archiviert'] is None],
        archivierte=[k for k in karten if k['archiviert'] is not None]))


@eigentuemer_seite
def portal_liegenschaft(request, eigentuemer, pk):
    daten = dienst.belegung(eigentuemer, pk)
    if daten is None:
        raise Http404
    dokumente = [d for d in dienst.sichtbare_dokumente(eigentuemer)
                 if (d.liegenschaft_id or d.einheit.liegenschaft_id) == pk][:10]
    return render(request, 'core/eig_liegenschaft.html', _kontext(eigentuemer, dokumente=dokumente, **daten))


@eigentuemer_seite
def portal_abrechnungen(request, eigentuemer):
    ergebnis = dienst.ergebnis_je_jahr(eigentuemer)
    jahre = []
    for jahr in dienst.jahre_mit_daten(eigentuemer, ergebnis):
        _zeilen, totals, _von, _bis = dienst.abrechnung_jahr(eigentuemer, jahr, ergebnis)
        jahre.append({'jahr': jahr, 'totals': totals, 'laufend': jahr == datum_heute().year,
                      'leer': jahr not in ergebnis})
    return render(request, 'core/eig_abrechnungen.html', _kontext(
        eigentuemer, jahre=jahre, konto=dienst.konto_stand(eigentuemer, ergebnis),
        auszahlungen=dienst.auszahlungen(eigentuemer), offene=dienst.offene_posten(eigentuemer),
        steuerjahr=datum_heute().year - 1))


@eigentuemer_seite
def portal_abrechnung_pdf(request, eigentuemer):
    """Eigentümerabrechnung (Mandatsabrechnung) eines Jahres (`?jahr=`) als PDF — nur die eigenen Liegenschaften."""
    try:
        jahr = jahr_streng(request.GET.get('jahr'))
    except ValueError:
        raise Http404
    if jahr > datum_heute().year:
        raise Http404
    from core.services.mandat_abrechnung import generate_mandat_abrechnung_pdf
    zeilen, totals, von, bis = dienst.abrechnung_jahr(eigentuemer, jahr)
    pdf = generate_mandat_abrechnung_pdf(eigentuemer, jahr, zeilen, totals, von, bis, eigentuemer.organisation)
    antwort = HttpResponse(pdf, content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="Eigentuemerabrechnung_{jahr}.pdf"'
    return antwort


@eigentuemer_seite
def portal_dokumente(request, eigentuemer):
    gruppen = {}
    for d in dienst.sichtbare_dokumente(eigentuemer):
        lg = d.liegenschaft or d.einheit.liegenschaft
        gruppen.setdefault(lg, []).append(d)
    return render(request, 'core/eig_dokumente.html', _kontext(
        eigentuemer, gruppen=[{'lg': lg, 'dokumente': docs} for lg, docs in gruppen.items()],
        anzahl=sum(len(v) for v in gruppen.values())))


@eigentuemer_seite
def portal_mitteilungen(request, eigentuemer):
    """Anfragen an die Verwaltung: Formular und Verlauf. Die Anfrage landet als Pendenz."""
    eingabe = {'liegenschaft': '', 'art': 'frage', 'betreff': '', 'text': ''}
    fehler = ''
    if request.method == 'POST':
        eingabe = {k: (request.POST.get(k) or '') for k in eingabe}
        try:
            dienst.anfrage_senden(eigentuemer, request.user, liegenschaft_pk=eingabe['liegenschaft'],
                                  art=eingabe['art'], betreff=eingabe['betreff'], text=eingabe['text'])
        except dienst.AnfrageFehler as e:
            fehler = str(e)
        else:
            messages.success(request, gettext('Ihre Anfrage wurde an die Verwaltung übermittelt.'))
            return redirect('portal_mitteilungen')
    lgs = list(dienst.eigene_liegenschaften(eigentuemer).exclude(status='archiviert'))
    if not eingabe['liegenschaft'] and len(lgs) == 1:
        eingabe['liegenschaft'] = str(lgs[0].pk)
    return render(request, 'core/eig_mitteilungen.html', _kontext(
        eigentuemer, liegenschaften=lgs, arten=dienst.ANFRAGE_ARTEN, eingabe=eingabe, fehler=fehler,
        anfragen=dienst.meine_anfragen(eigentuemer), verwaltung=eigentuemer.organisation,
        betreff_max=dienst.BETREFF_MAX, text_max=dienst.TEXT_MAX))


@eigentuemer_seite
def portal_profil(request, eigentuemer):
    """Angaben ansehen, Korrespondenzsprache wählen, Passwort ändern."""
    from crm.models import Eigentuemer
    sprachen = Eigentuemer._meta.get_field('sprache').choices
    passwort = PasswordChangeForm(request.user)
    if request.method == 'POST':
        if request.POST.get('aktion') == 'sprache':
            wahl = request.POST.get('sprache')
            if wahl in dict(sprachen):
                eigentuemer.sprache = wahl
                eigentuemer.save(update_fields=['sprache'])
                messages.success(request, gettext('Korrespondenzsprache gespeichert.'))
                return redirect('portal_profil')
            messages.error(request, gettext('Bitte eine der angebotenen Sprachen wählen.'))
        elif request.POST.get('aktion') == 'passwort':
            passwort = PasswordChangeForm(request.user, request.POST)
            if passwort.is_valid():
                benutzer = passwort.save()
                update_session_auth_hash(request, benutzer)
                messages.success(request, gettext('Passwort geändert.'))
                return redirect('portal_profil')
    return render(request, 'core/eig_profil.html', _kontext(
        eigentuemer, sprachen=sprachen, passwort=passwort))


@never_cache
@login_required
def portal_dokument_herunterladen(request, pk):
    """Download eines freigegebenen Dokuments der eigenen Liegenschaften."""
    eigentuemer = getattr(request.user, 'eigentuemer_profil', None)
    if eigentuemer is None:
        raise Http404
    dok = dienst.sichtbare_dokumente(eigentuemer).filter(pk=pk).first()
    if dok is None:
        raise Http404
    try:
        datei = dok.datei.open('rb')
    except Exception:
        raise Http404
    antwort = HttpResponse(datei.read(), content_type='application/octet-stream')
    antwort['Content-Disposition'] = f'attachment; filename="{os.path.basename(dok.datei.name)}"'
    return antwort
