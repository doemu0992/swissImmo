# core/views/fw/phase2_formulare.py
#
# Oberflächen für die Basis-Strukturen aus dem Phase-1-Audit (docs/AUDIT-FEATURES.md):
# interne Ticket-Zuweisung mit SLA-Frist, Zustellung der Nebenkostenabrechnung
# (Einsprachefrist), Betreibung des Mietzinses und Zählerstände für die HKVO.
#
# Jedes Formular ist ein Django-Form: Ein Validierungsfehler erscheint am Feld
# (`fw/_feldfehler.html`), die Eingabe bleibt stehen, und die Seite wird bei
# Fehlern NICHT umgeleitet. Erst ein gültiges POST speichert und leitet weiter.

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.auth import (SCHREIB_ROLLEN, TICKET_SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN,
                       TEAM_ROLLEN, log_aktion, rolle_erforderlich)

from ._basis import _global_filter

DATUM = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def _seite(request, form, *, titel, hinweis='', zurueck, zurueck_text, senden, extra=None, status=200):
    ctx = {**_global_filter(request), 'form': form, 'titel': titel, 'hinweis': hinweis,
           'zurueck': zurueck, 'zurueck_text': zurueck_text, 'senden': senden, **(extra or {})}
    return render(request, 'fw/phase2_form.html', ctx, status=status)


# ---------------------------------------------------------------- Ticket zuweisen

class TicketZuweisungForm(forms.Form):
    zugewiesen_an = forms.ModelChoiceField(
        queryset=None, required=False, label=_('Zuständig (intern)'), empty_label=_('— niemand —'))
    faellig_bis = forms.DateField(required=False, widget=DATUM, label=_('Erledigen bis (SLA)'))

    def __init__(self, *args, organisation, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        self.fields['zugewiesen_an'].queryset = (
            get_user_model().objects.filter(
                mitgliedschaften__organisation=organisation,
                mitgliedschaften__rolle__in=[r for r in TICKET_SCHREIB_ROLLEN],
                is_active=True).distinct().order_by('last_name', 'username'))
        self.fields['zugewiesen_an'].label_from_instance = lambda u: u.get_full_name() or u.username

    def clean_faellig_bis(self):
        d = self.cleaned_data.get('faellig_bis')
        if d and d < timezone.localdate() - timedelta(days=1):
            raise forms.ValidationError(gettext('Die Frist liegt in der Vergangenheit.'))
        return d


# Bewusst NUR die Schreibrollen, nicht TICKET_SCHREIB_ROLLEN: Der Hauswart darf den
# Status eines Tickets ändern, aber nicht bestimmen, wer es bearbeitet
# (`core/tests/test_rbac.py`: Hauswart bekommt ausser Schäden-Status überall 403).
@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_zuweisen(request, pk):
    """Ticket einem internen Bearbeiter zuweisen und die Zielzeit setzen."""
    from tickets.models import SchadenMeldung, TicketNachricht
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft'), pk=pk)
    org = t.organisation
    form = TicketZuweisungForm(request.POST or None, organisation=org,
                               initial={'zugewiesen_an': t.zugewiesen_an_id, 'faellig_bis': t.faellig_bis})
    if request.method == 'POST' and form.is_valid():
        neu = form.cleaned_data['zugewiesen_an']
        t.zugewiesen_an = neu
        t.faellig_bis = form.cleaned_data['faellig_bis']
        t.save(update_fields=['zugewiesen_an', 'faellig_bis', 'aktualisiert_am'])
        name = (neu.get_full_name() or neu.username) if neu else gettext('niemand')
        TicketNachricht.objects.create(ticket=t, absender_name='System', typ='system', is_intern=True,
                                       nachricht=gettext('Zuständig: %(name)s.') % {'name': name})
        log_aktion(request, 'Ticket zugewiesen', f'Ticket #{t.id}', name)
        messages.success(request, gettext('Ticket zugewiesen: %(name)s.') % {'name': name})
        return redirect(f'/neu/schaeden/{t.id}/')
    return _seite(request, form, titel=gettext('Ticket zuweisen'),
                  hinweis=t.titel, zurueck=f'/neu/schaeden/{t.id}/', zurueck_text=gettext('Ticket'),
                  senden=gettext('Zuweisen'), status=400 if request.method == 'POST' else 200)


# ---------------------------------------------------------------- NK-Zustellung

class NkZustellungForm(forms.Form):
    versendet_am = forms.DateField(widget=DATUM, label=_('Zugestellt am'))
    versand_kanal = forms.ChoiceField(label=_('Zustellung'), choices=[
        ('email', _('E-Mail')), ('brief', _('Brief')), ('portal', _('Mieterportal'))])

    def __init__(self, *args, periode, **kwargs):
        super().__init__(*args, **kwargs)
        self.periode = periode

    def clean_versendet_am(self):
        d = self.cleaned_data['versendet_am']
        if d > timezone.localdate():
            raise forms.ValidationError(gettext('Das Zustelldatum liegt in der Zukunft.'))
        if d < self.periode.ende_datum:
            raise forms.ValidationError(gettext('Die Abrechnung kann nicht vor Ende der Abrechnungsperiode zugestellt werden.'))
        return d

    def clean(self):
        data = super().clean()
        if not self.periode.abgeschlossen:
            raise forms.ValidationError(gettext('Die Abrechnung ist noch nicht verbucht — erst verbuchen, dann zustellen.'))
        return data


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_nebenkosten_zustellung(request, pk):
    """Zustelldatum der Nebenkostenabrechnung festhalten (Beginn der Einsprachefrist)."""
    from finance.models import AbrechnungsPeriode
    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), pk=pk)
    form = NkZustellungForm(request.POST or None, periode=p,
                            initial={'versendet_am': p.versendet_am or timezone.localdate(),
                                     'versand_kanal': p.versand_kanal or 'brief'})
    if request.method == 'POST' and form.is_valid():
        p.versendet_am = form.cleaned_data['versendet_am']
        p.versand_kanal = form.cleaned_data['versand_kanal']
        p.save(update_fields=['versendet_am', 'versand_kanal'])
        log_aktion(request, 'Abrechnung zugestellt', p.bezeichnung, f'{p.versendet_am:%d.%m.%Y}')
        messages.success(request, gettext('Zustellung erfasst. Einsprachefrist bis %(d)s.')
                         % {'d': p.einsprache_bis.strftime('%d.%m.%Y')})
        return redirect(f'/neu/nebenkosten/{p.id}/')
    return _seite(request, form, titel=gettext('Abrechnung zugestellt'),
                  hinweis=gettext('Mit dem Zustelldatum beginnt die Prüf- und Einsprachefrist (%(n)s Tage).')
                  % {'n': p.EINSPRACHE_TAGE},
                  zurueck=f'/neu/nebenkosten/{p.id}/', zurueck_text=p.bezeichnung,
                  senden=gettext('Speichern'), status=400 if request.method == 'POST' else 200)


# ---------------------------------------------------------------- Betreibung

class BetreibungForm(forms.ModelForm):
    class Meta:
        from finance.models import Betreibung
        model = Betreibung
        fields = ['status', 'betreibungsamt', 'betreibungsnummer', 'forderung', 'kosten',
                  'begehren_am', 'zahlungsbefehl_am', 'rechtsvorschlag_am', 'rechtsoeffnung_am',
                  'fortsetzung_am', 'verlustschein_am', 'bemerkung']
        widgets = {k: DATUM for k in ('begehren_am', 'zahlungsbefehl_am', 'rechtsvorschlag_am',
                                      'rechtsoeffnung_am', 'fortsetzung_am', 'verlustschein_am')}
        widgets['bemerkung'] = forms.Textarea(attrs={'rows': 3})

    #: Stand → Datumsfeld, das dafür belegt sein muss.
    BRAUCHT = {'zahlungsbefehl': 'zahlungsbefehl_am', 'rechtsvorschlag': 'rechtsvorschlag_am',
               'rechtsoeffnung': 'rechtsoeffnung_am', 'fortsetzung': 'fortsetzung_am',
               'verlustschein': 'verlustschein_am'}
    #: Reihenfolge der Daten — jedes darf nicht vor seinem Vorgänger liegen.
    ABFOLGE = ['begehren_am', 'zahlungsbefehl_am', 'rechtsvorschlag_am', 'rechtsoeffnung_am',
               'fortsetzung_am', 'verlustschein_am']

    def clean_forderung(self):
        f = self.cleaned_data['forderung']
        if f is None or f <= 0:
            raise forms.ValidationError(gettext('Die Forderung muss grösser als 0 sein.'))
        return f

    def clean(self):
        data = super().clean()
        heute = timezone.localdate()
        status = data.get('status')
        pflicht = self.BRAUCHT.get(status)
        if pflicht and not data.get(pflicht):
            self.add_error(pflicht, gettext('Für den Stand «%(s)s» ist dieses Datum nötig.')
                           % {'s': dict(self.fields['status'].choices).get(status, status)})
        vorher = None
        for feld in self.ABFOLGE:
            d = data.get(feld)
            if d and d > heute and feld != 'begehren_am':
                self.add_error(feld, gettext('Das Datum liegt in der Zukunft.'))
            elif d and vorher and d < vorher[1]:
                self.add_error(feld, gettext('Das Datum liegt vor «%(f)s».')
                               % {'f': self.fields[vorher[0]].label})
            if d:
                vorher = (feld, d)
        zb, rv = data.get('zahlungsbefehl_am'), data.get('rechtsvorschlag_am')
        if zb and rv and rv > zb + timedelta(days=10):
            self.add_error('rechtsvorschlag_am', gettext(
                'Rechtsvorschlag nach Ablauf der 10-Tage-Frist (Art. 74 SchKG) — bitte prüfen.'))
        return data


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_betreibungen(request):
    """Alle Betreibungen der Organisation, offene zuerst."""
    from finance.models import Betreibung
    basis = _global_filter(request)
    qs = Betreibung.objects.select_related('debitoren_rechnung__vertrag__mieter')
    abgeschlossen = ('bezahlt', 'verlustschein', 'zurueckgezogen')
    rows = list(qs)
    rows.sort(key=lambda b: (b.status in abgeschlossen, -b.begehren_am.toordinal()))
    return render(request, 'fw/betreibungen.html', {
        **basis, 'rows': rows, 'abgeschlossen': abgeschlossen,
        'summe_offen': sum((b.forderung for b in rows if b.status not in abgeschlossen), Decimal('0.00')),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_betreibung_neu(request, pk):
    """Betreibung für eine offene Debitorenrechnung einleiten (pk = Rechnung)."""
    from finance.models import Betreibung, DebitorenRechnung
    r = get_object_or_404(DebitorenRechnung.objects.select_related('vertrag__mieter'), pk=pk)
    if r.status in ('bezahlt', 'storniert'):
        messages.error(request, gettext('Für eine bezahlte oder stornierte Rechnung kann keine Betreibung eingeleitet werden.'))
        return redirect('/neu/mahnwesen/')
    offen = r.offener_betrag or r.betrag
    form = BetreibungForm(request.POST or None, initial={
        'forderung': offen, 'begehren_am': timezone.localdate(), 'status': 'begehren'})
    if request.method == 'POST' and form.is_valid():
        b = form.save(commit=False)
        b.debitoren_rechnung, b.vertrag, b.erstellt_von = r, r.vertrag, request.user
        b.save()
        log_aktion(request, 'Betreibung eingeleitet', str(r.vertrag.mieter if r.vertrag_id else r.titel), f'CHF {b.forderung}')
        messages.success(request, gettext('Betreibung erfasst.'))
        return redirect('/neu/betreibungen/')
    return _seite(request, form, titel=gettext('Betreibung einleiten'),
                  hinweis=f'{r.titel} · CHF {offen}', zurueck='/neu/mahnwesen/',
                  zurueck_text=gettext('Mahnwesen'), senden=gettext('Betreibung erfassen'),
                  status=400 if request.method == 'POST' else 200)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_betreibung_bearbeiten(request, pk):
    """Stand und Daten einer Betreibung nachführen."""
    from finance.models import Betreibung
    b = get_object_or_404(Betreibung.objects.select_related('debitoren_rechnung'), pk=pk)
    form = BetreibungForm(request.POST or None, instance=b)
    if request.method == 'POST' and form.is_valid():
        b = form.save()
        log_aktion(request, 'Betreibung bearbeitet', f'Betreibung #{b.id}', b.get_status_display())
        messages.success(request, gettext('Betreibung gespeichert.'))
        return redirect('/neu/betreibungen/')
    extra = {}
    if b.rechtsvorschlag_frist_bis:
        extra['fristen'] = {'rv': b.rechtsvorschlag_frist_bis, 'fortsetzung': b.fortsetzung_frist}
    return _seite(request, form, titel=gettext('Betreibung bearbeiten'),
                  hinweis=f'{b.debitoren_rechnung.titel}', zurueck='/neu/betreibungen/',
                  zurueck_text=gettext('Betreibungen'), senden=gettext('Speichern'), extra=extra,
                  status=400 if request.method == 'POST' else 200)


# ---------------------------------------------------------------- Zählerstand

class ZaehlerstandForm(forms.Form):
    zaehler = forms.ModelChoiceField(queryset=None, label=_('Zähler'))
    datum = forms.DateField(widget=DATUM, label=_('Ablesedatum'))
    wert = forms.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0'),
                              label=_('Zählerstand'), localize=False)

    def __init__(self, *args, liegenschaft, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q
        from portfolio.models import Zaehler
        self.fields['zaehler'].queryset = Zaehler.objects.filter(
            Q(liegenschaft=liegenschaft) | Q(einheit__liegenschaft=liegenschaft)
        ).select_related('einheit').order_by('typ', 'zaehler_nummer')
        self.fields['zaehler'].label_from_instance = lambda z: (
            f"{z.typ} {z.zaehler_nummer}" + (f" · {z.einheit.bezeichnung}" if z.einheit_id else f" · {gettext('allgemein')}"))

    def clean_datum(self):
        d = self.cleaned_data['datum']
        if d > timezone.localdate():
            raise forms.ValidationError(gettext('Das Ablesedatum liegt in der Zukunft.'))
        return d

    def clean(self):
        data = super().clean()
        z, d, w = data.get('zaehler'), data.get('datum'), data.get('wert')
        if z and d and w is not None:
            # Ein Zählerstand darf zwischen zwei bekannten Ständen nicht sinken —
            # sonst entsteht ein negativer Verbrauch (billing ignoriert ihn still).
            from portfolio.models import ZaehlerStand
            davor = ZaehlerStand.objects.filter(zaehler=z, datum__lte=d).order_by('-datum', '-id').first()
            danach = ZaehlerStand.objects.filter(zaehler=z, datum__gt=d).order_by('datum', 'id').first()
            if davor and w < davor.wert:
                self.add_error('wert', gettext('Der Stand liegt unter dem Stand vom %(d)s (%(w)s).')
                               % {'d': davor.datum.strftime('%d.%m.%Y'), 'w': davor.wert})
            elif danach and w > danach.wert:
                self.add_error('wert', gettext('Der Stand liegt über dem späteren Stand vom %(d)s (%(w)s).')
                               % {'d': danach.datum.strftime('%d.%m.%Y'), 'w': danach.wert})
        return data


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehlerstand_neu(request, pk):
    """Zählerstand erfassen (pk = Liegenschaft). Grundlage der HKVO-Verbrauchsverteilung."""
    from portfolio.models import Liegenschaft, ZaehlerStand
    lg = get_object_or_404(Liegenschaft, pk=pk)
    form = ZaehlerstandForm(request.POST or None, liegenschaft=lg,
                            initial={'datum': timezone.localdate(), 'zaehler': request.GET.get('zaehler')})
    if request.method == 'POST' and form.is_valid():
        z, d, w = form.cleaned_data['zaehler'], form.cleaned_data['datum'], form.cleaned_data['wert']
        ZaehlerStand.objects.create(zaehler=z, datum=d, wert=w)
        letzter = z.staende.order_by('-datum', '-id').first()
        if letzter:
            z.aktueller_stand = letzter.wert
            z.save(update_fields=['aktueller_stand'])
        log_aktion(request, 'Zählerstand erfasst', f'{z.typ} {z.zaehler_nummer}', str(w))
        messages.success(request, gettext('Zählerstand erfasst.'))
        if request.POST.get('weiter'):
            return redirect(f'/neu/liegenschaften/{lg.id}/zaehlerstand/?zaehler={z.id}')
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    return _seite(request, form, titel=gettext('Zählerstand erfassen'), hinweis=str(lg),
                  zurueck=f'/neu/liegenschaften/{lg.id}/', zurueck_text=str(lg),
                  senden=gettext('Speichern'), extra={'weiter_knopf': True},
                  status=400 if request.method == 'POST' else 200)
