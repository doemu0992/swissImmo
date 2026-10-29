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
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.auth import (BETREIBUNGS_ROLLEN, SCHREIB_ROLLEN, TICKET_SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN,
                       TEAM_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich)

from ._basis import _global_filter

DATUM = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def _werte(form):
    """Feldwerte als Strings für Formulare mit ausgeschriebenen Eingabefeldern.

    Nach einem Fehler steht dort, was eingetippt wurde (`form.data`); beim ersten
    Aufruf der Anfangswert bzw. der Wert der Instanz. Daten kommen als ISO-Text
    zurück: `<input type=date>` verträgt kein anderes Format, und die
    Lokalisierung der Vorlage würde es in «05.10.2026» wandeln.
    """
    def text(roh):
        if roh is None:
            return ''
        return roh.isoformat() if hasattr(roh, 'isoformat') else str(roh)

    werte = {}
    for name in form.fields:
        if form.is_bound:
            werte[name] = form.data.get(name, '')
        elif name in form.initial:
            werte[name] = text(form.initial[name])
        else:
            werte[name] = text(getattr(getattr(form, 'instance', None), name, None))
    return werte


def _seite(request, form, *, titel, hinweis='', zurueck, zurueck_text, senden, nav, extra=None, status=200,
           vorlage='fw/phase2_form.html'):
    """`nav` ist Pflicht: Ohne Schlüssel leuchtet im Menüband kein Bereich (DESIGN-04)."""
    ctx = {**_global_filter(request), 'form': form, 'werte': _werte(form), 'titel': titel, 'hinweis': hinweis,
           'zurueck': zurueck, 'zurueck_text': zurueck_text, 'senden': senden, 'nav': nav, **(extra or {})}
    return render(request, vorlage, ctx, status=status)


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
                  senden=gettext('Zuweisen'), nav='schadensfaelle', status=400 if request.method == 'POST' else 200,
                  vorlage='fw/ticket_zuweisen.html')


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
                  senden=gettext('Speichern'), nav='nebenkosten',
                  status=400 if request.method == 'POST' else 200, vorlage='fw/nk_zustellung.html')


# ---------------------------------------------------------------- Betreibung

class BetreibungForm(forms.ModelForm):
    """Stand und Daten einer Betreibung nachführen (Bearbeiten).

    WARNUNG STATT FEHLER. Was nach Gesetz in Ausnahmefällen zulässig sein kann,
    blockiert das Speichern nicht, sondern steht nach dem Speichern als Warnung
    da (`warnungen`). Beispiel Rechtsvorschlag nach mehr als zehn Tagen: Er kann
    rechtzeitig sein — Fristende an einem Samstag, Sonntag oder Feiertag
    (Art. 31 Abs. 3 SchKG), Betreibungsferien und Rechtsstillstand (Art. 56,
    63 SchKG) oder ein nachträglicher Rechtsvorschlag (Art. 77 SchKG). Ob das
    zutrifft, weiss das Betreibungsamt, nicht diese Anwendung. Ein Fehler am
    Feld hätte die Verwaltung gezwungen, ein falsches Datum einzutragen.
    """

    class Meta:
        from finance.models import Betreibung
        model = Betreibung
        fields = ['status', 'betreibungsamt', 'betreibungsnummer', 'forderung', 'zinssatz', 'zins_ab',
                  'forderungsgrund', 'kosten',
                  'begehren_am', 'zahlungsbefehl_am', 'rechtsvorschlag_am', 'rechtsoeffnung_beantragt_am',
                  'rechtsoeffnung_am', 'rechtsoeffnung_art', 'fortsetzung_am', 'pfaendung_am',
                  'verlustschein_am', 'bemerkung']
        widgets = {k: DATUM for k in ('begehren_am', 'zahlungsbefehl_am', 'rechtsvorschlag_am',
                                      'rechtsoeffnung_beantragt_am', 'rechtsoeffnung_am', 'fortsetzung_am',
                                      'pfaendung_am', 'verlustschein_am', 'zins_ab')}
        widgets['bemerkung'] = forms.Textarea(attrs={'rows': 3})
        widgets['forderungsgrund'] = forms.Textarea(attrs={'rows': 3})

    #: Stand → Datumsfeld, das dafür belegt sein muss.
    BRAUCHT = {'zahlungsbefehl': 'zahlungsbefehl_am', 'rechtsvorschlag': 'rechtsvorschlag_am',
               'rechtsoeffnung_beantragt': 'rechtsoeffnung_beantragt_am',
               'rechtsoeffnung': 'rechtsoeffnung_am', 'fortsetzung': 'fortsetzung_am',
               'pfaendung': 'pfaendung_am', 'verlustschein': 'verlustschein_am'}
    #: Reihenfolge der Daten — jedes darf nicht vor seinem Vorgänger liegen.
    ABFOLGE = ['begehren_am', 'zahlungsbefehl_am', 'rechtsvorschlag_am', 'rechtsoeffnung_beantragt_am',
               'rechtsoeffnung_am', 'fortsetzung_am', 'pfaendung_am', 'verlustschein_am']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: Hinweise, die das Speichern nicht verhindern (siehe Klassenkommentar).
        self.warnungen = []

    def clean_forderung(self):
        f = self.cleaned_data['forderung']
        if f is None or f <= 0:
            raise forms.ValidationError(gettext('Die Forderung muss grösser als 0 sein.'))
        return f

    def clean_zinssatz(self):
        z = self.cleaned_data.get('zinssatz')
        if z is not None and not (Decimal('0') <= z <= Decimal('100')):
            raise forms.ValidationError(gettext('Der Zinssatz muss zwischen 0 und 100 % liegen.'))
        return z

    def clean(self):
        data = super().clean()
        heute = timezone.localdate()
        status = data.get('status')
        pflicht = self.BRAUCHT.get(status)
        if pflicht and pflicht in self.fields and not data.get(pflicht):
            self.add_error(pflicht, gettext('Für den Stand «%(s)s» ist dieses Datum nötig.')
                           % {'s': dict(self.fields['status'].choices).get(status, status)})
        vorher = None
        for feld in self.ABFOLGE:
            if feld not in self.fields:
                continue
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
            self.warnungen.append(gettext(
                'Rechtsvorschlag mehr als 10 Tage nach Zustellung des Zahlungsbefehls (Art. 74 SchKG). '
                'Gespeichert — bitte beim Betreibungsamt klären, ob er gilt: Er kann rechtzeitig sein '
                '(z. B. Fristende an einem Wochenende oder Feiertag, Betreibungsferien oder Rechtsstillstand, '
                'Art. 31, 56, 63 SchKG, oder nachträglicher Rechtsvorschlag, Art. 77 SchKG).'))
        if data.get('rechtsoeffnung_beantragt_am') and not rv:
            self.warnungen.append(gettext(
                'Rechtsöffnungsgesuch ohne erfassten Rechtsvorschlag — eine Rechtsöffnung braucht es nur, '
                'wenn Rechtsvorschlag erhoben wurde.'))
        fs = data.get('fortsetzung_am')
        if fs and zb and not self.errors:
            from finance.models import Betreibung
            probe = Betreibung(zahlungsbefehl_am=zb, rechtsvorschlag_am=rv,
                               rechtsoeffnung_beantragt_am=data.get('rechtsoeffnung_beantragt_am'),
                               rechtsoeffnung_am=data.get('rechtsoeffnung_am'))
            frueh, spaet = probe.fortsetzung_frist
            if frueh is None:
                self.warnungen.append(gettext(
                    'Fortsetzungsbegehren erfasst, obwohl der Rechtsvorschlag noch nicht durch einen '
                    'Rechtsöffnungsentscheid beseitigt ist (Art. 88 Abs. 1 SchKG).'))
            elif fs < frueh:
                self.warnungen.append(gettext(
                    'Fortsetzungsbegehren vor dem frühesten Termin (%(d)s, Art. 88 Abs. 1 SchKG).')
                    % {'d': frueh.strftime('%d.%m.%Y')})
            elif spaet and fs > spaet:
                self.warnungen.append(gettext(
                    'Fortsetzungsbegehren nach Ablauf der Jahresfrist (%(d)s, Art. 88 Abs. 2 SchKG).')
                    % {'d': spaet.strftime('%d.%m.%Y')})
        return data


class BetreibungNeuForm(BetreibungForm):
    """Der Assistent «Betreibung einleiten»: Forderungen, Gläubiger/Zins/Grund, Prüfen.

    Angelegt wird immer im Stand «Begehren». Den weiteren Stand führt die
    Verwaltung auf der Betreibung nach (`BetreibungForm`) — ein Assistent, der
    zugleich alle späteren Stände abfragte, wäre keiner mehr.

    `weitere_rechnungen` sind die zusätzlichen Monatsmieten DESSELBEN Vertrags; die Auswahl
    kommt aus `betreibung.betreibbare_forderungen`. Eine fremde oder bereits
    betriebene ID ist darin nicht enthalten und wird als ungültige Wahl abgelehnt.
    Bleibt die Forderung leer, gilt die Summe der offenen Beträge.
    """

    class Meta(BetreibungForm.Meta):
        fields = ['betreibungsamt', 'betreibungsnummer', 'forderung', 'zinssatz', 'zins_ab',
                  'forderungsgrund', 'begehren_am', 'bemerkung']

    weitere_rechnungen = forms.ModelMultipleChoiceField(queryset=None, required=False,
                                             widget=forms.CheckboxSelectMultiple,
                                             label=_('Weitere Forderungen'))

    def __init__(self, *args, haupt, auswahl, **kwargs):
        super().__init__(*args, **kwargs)
        from finance.models import DebitorenRechnung
        self.haupt = haupt
        self.auswahl = [r for r in auswahl if r.pk != haupt.pk]
        self.fields['weitere_rechnungen'].queryset = DebitorenRechnung.objects.filter(pk__in=[r.pk for r in self.auswahl])
        self.fields['forderung'].required = False
        # Leer heisst: der gesetzliche Satz (Modell-Vorgabe, Art. 104 OR). Wer keinen
        # Zins verlangt, trägt 0 ein.
        self.fields['zinssatz'].required = False

    def clean_forderung(self):
        f = self.cleaned_data.get('forderung')
        if f is not None and f <= 0:
            raise forms.ValidationError(gettext('Die Forderung muss grösser als 0 sein.'))
        return f

    def clean_zinssatz(self):
        z = super().clean_zinssatz()
        if z is None:
            from finance.models import Betreibung
            z = Betreibung._meta.get_field('zinssatz').default
        return z

    def gewaehlte(self):
        """Hauptforderung und gewählte weitere, älteste zuerst — mit vorgeladenen Zahlungen."""
        geladen = {r.pk: r for r in self.auswahl}
        weitere = [geladen.get(r.pk, r) for r in (self.cleaned_data.get('weitere_rechnungen') or [])]
        return [self.haupt] + sorted(weitere, key=lambda r: (r.faellig_am or r.datum, r.pk))

    def clean(self):
        data = super().clean()
        if 'weitere_rechnungen' in self.errors:
            return data
        if data.get('forderung') is None and 'forderung' not in self.errors:
            data['forderung'] = sum((r.offener_betrag for r in self.gewaehlte()), Decimal('0.00'))
        return data


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_betreibungen(request):
    """Alle Betreibungen der Organisation, offene zuerst."""
    from finance.models import Betreibung
    basis = _global_filter(request)
    qs = Betreibung.objects.select_related('debitoren_rechnung__vertrag__mieter')
    abgeschlossen = Betreibung.ABGESCHLOSSEN
    rows = list(qs)
    rows.sort(key=lambda b: (b.status in abgeschlossen, -b.begehren_am.toordinal()))
    return render(request, 'fw/betreibungen.html', {
        **basis, 'nav': 'mahnwesen', 'rows': rows, 'abgeschlossen': abgeschlossen,
        'summe_offen': sum((b.forderung for b in rows if b.status not in abgeschlossen), Decimal('0.00')),
    })


class _EntwurfBetreibung:
    """Was `betreibung.glaeubiger` von einer Betreibung braucht — vor dem Speichern."""

    def __init__(self, rechnung, organisation):
        self.vertrag = rechnung.vertrag
        self.debitoren_rechnung = rechnung
        self.organisation = organisation


def _gewaehlt_ids(form):
    """IDs der angekreuzten weiteren Forderungen — nach einem Fehler, was gesendet wurde."""
    if not form.is_bound:
        return []
    return [int(x) for x in form.data.getlist('weitere_rechnungen') if str(x).isdigit()]


@rolle_erforderlich(*BETREIBUNGS_ROLLEN)
def fw_betreibung_neu(request, pk):
    """Betreibung einleiten — Assistent ab einer offenen Debitorenrechnung (pk = Rechnung).

    Die Rechnung aus der Adresse ist die Hauptforderung; weitere offene, fällige
    Mieten desselben Vertrags lassen sich dazunehmen. Forderungen, die schon in
    einer offenen Betreibung stehen, sind nicht wählbar — zweimal dieselbe Miete
    zu betreiben hiesse zwei Zahlungsbefehle für eine Schuld."""
    from core.services import betreibung as bdienst
    from core.tenancy import organisation_der_anfrage
    from finance.models import DebitorenRechnung
    r = get_object_or_404(DebitorenRechnung.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft__eigentuemer', 'liegenschaft'), pk=pk)
    if r.status in ('bezahlt', 'storniert'):
        messages.error(request, gettext('Für eine bezahlte oder stornierte Rechnung kann keine Betreibung eingeleitet werden.'))
        return redirect('/neu/mahnwesen/')
    betrieben = bdienst.rechnung_ids_in_offener_betreibung()
    if r.pk in betrieben:
        messages.error(request, gettext('Diese Forderung steht bereits in einer offenen Betreibung.'))
        return redirect('/neu/betreibungen/')
    if r.vertrag_id:
        auswahl = [x for x in bdienst.betreibbare_forderungen(r.vertrag) if x.pk not in betrieben]
    else:
        auswahl = [r] if r.offener_betrag > 0 else []
    haupt = next((x for x in auswahl if x.pk == r.pk), None)
    if haupt is None:
        messages.error(request, gettext('Betrieben werden kann nur eine offene, fällige Hauptforderung '
                                        '(keine Mahngebühr, kein Zins, nichts noch nicht Fälliges).'))
        return redirect('/neu/mahnwesen/')
    form = BetreibungNeuForm(request.POST or None, haupt=haupt, auswahl=auswahl, initial={
        'forderung': haupt.offener_betrag, 'begehren_am': timezone.localdate(), 'zinssatz': Decimal('5.00'),
        'zins_ab': bdienst.zins_ab_vorschlag([haupt]),
        'forderungsgrund': bdienst.forderungsgrund_vorschlag([haupt], r.vertrag),
        # Ausdrücklich leer: `_werte` liest sonst die M2M der noch ungespeicherten
        # Betreibung, und Django verweigert das ohne Primärschlüssel.
        'weitere_rechnungen': []})
    if request.method == 'POST' and form.is_valid():
        gewaehlt = form.gewaehlte()
        b = form.save(commit=False)
        b.debitoren_rechnung, b.vertrag, b.erstellt_von = haupt, haupt.vertrag, request.user
        b.status = 'begehren'
        if not b.forderungsgrund.strip():
            b.forderungsgrund = bdienst.forderungsgrund_vorschlag(gewaehlt, haupt.vertrag)
        b.save()
        b.weitere_rechnungen.set(gewaehlt[1:])
        bdienst.nach_speichern(b, user=request.user)
        log_aktion(request, 'Betreibung eingeleitet', str(haupt.vertrag.mieter if haupt.vertrag_id else haupt.titel),
                   f'CHF {b.forderung} · {len(gewaehlt)} Forderung(en)', ziel=haupt.vertrag)
        messages.success(request, gettext('Betreibung erfasst. Das Datenblatt für das Betreibungsbegehren '
                                          'steht als PDF bereit.'))
        return redirect(f'/neu/betreibungen/{b.id}/')
    gl, vertreter = bdienst.glaeubiger(_EntwurfBetreibung(haupt, organisation_der_anfrage(request)))
    return render(request, 'fw/betreibung_neu.html', {
        **_global_filter(request), 'form': form, 'werte': _werte(form), 'r': haupt,
        'auswahl': form.auswahl, 'gewaehlt_ids': _gewaehlt_ids(form),
        'glaeubiger': gl, 'vertreter': vertreter, 'titel': gettext('Betreibung einleiten'),
        'nav': 'mahnwesen',
    }, status=400 if request.method == 'POST' else 200)


@rolle_erforderlich(*BETREIBUNGS_ROLLEN)
def fw_betreibung_bearbeiten(request, pk):
    """Stand und Daten einer Betreibung nachführen.

    Der Wechsel auf «Verlustschein» schreibt die offenen Forderungen ab (3805) —
    das dürfen nur Verwaltungsrollen, wie das Abschreiben im OP-Buch
    (`fw_debitor_abschreiben`)."""
    from core.auth import hat_rolle
    from core.services import betreibung as bdienst
    from finance.models import Betreibung
    b = get_object_or_404(Betreibung.objects.select_related(
        'debitoren_rechnung', 'vertrag__mieter', 'vertrag__einheit__liegenschaft', 'kosten_rechnung'), pk=pk)
    alter_status = b.status
    kann_verwalten = hat_rolle(request.user, VERWALTUNGS_ROLLEN)
    form = BetreibungForm(request.POST or None, instance=b)
    if request.method == 'POST' and form.is_valid():
        if (form.cleaned_data.get('status') == 'verlustschein' and alter_status != 'verlustschein'
                and not kann_verwalten):
            form.add_error('status', gettext('Der Verlustschein schreibt die offenen Forderungen ab (Konto 3805) — '
                                             'das darf nur die Verwaltung (Verwalter oder Inhaber).'))
        else:
            b = form.save()
            ergebnis = bdienst.nach_speichern(b, alter_status=alter_status, user=request.user)
            log_aktion(request, 'Betreibung bearbeitet', f'Betreibung #{b.id}', b.get_status_display(),
                       ziel=b.vertrag)
            messages.success(request, gettext('Betreibung gespeichert.'))
            for w in form.warnungen:
                messages.warning(request, w)
            if ergebnis:
                n, summe, ausgelassen = ergebnis
                if n:
                    messages.success(request, gettext('Verlustschein: %(n)s Forderung(en) über CHF %(s)s als '
                                                      'Debitorenverlust abgeschrieben (Konto 3805).')
                                     % {'n': n, 's': f'{summe:.2f}'})
                if ausgelassen:
                    messages.warning(request, gettext('%(n)s Forderung(en) liegen in einer gesperrten '
                                                      'Buchungsperiode und wurden nicht abgeschrieben.')
                                     % {'n': ausgelassen})
            return redirect(f'/neu/betreibungen/{b.id}/')
    if request.method == 'POST':
        # Nach einem Fehler gilt der gespeicherte Stand, nicht der halb geänderte
        # aus der Eingabe — die Knöpfe unten (PDF, Kosten) wirken auf ihn.
        b.refresh_from_db()
    extra = {'b': b, 'rechnungen': b.rechnungen(), 'kann_verwalten': kann_verwalten}
    if b.rechtsvorschlag_frist_bis:
        extra['fristen'] = {'rv': b.rechtsvorschlag_frist_bis, 'fortsetzung': b.fortsetzung_frist}
    return _seite(request, form, titel=gettext('Betreibung bearbeiten'),
                  hinweis=f'{b.debitoren_rechnung.titel}', zurueck='/neu/betreibungen/',
                  zurueck_text=gettext('Betreibungen'), senden=gettext('Speichern'), nav='mahnwesen', extra=extra,
                  status=400 if request.method == 'POST' else 200, vorlage='fw/betreibung_form.html')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_betreibung_pdf(request, pk):
    """Datenblatt für das Betreibungsbegehren (Vorlage, nicht das amtliche Formular).

    GET ist die VORSCHAU und schreibt nichts. Erst POST («Datenblatt erstellen»)
    legt das Blatt in der Vertragsakte ab — dort überschreibt derselbe Titel das
    frühere Blatt derselben Betreibung, statt Kopien zu stapeln. Das Blatt ist
    intern und bleibt für den Mieter unsichtbar (ROUTE-01)."""
    from django.http import HttpResponse

    from core.services.ablage import ablegen
    from core.services.inkasso_briefe import betreibungsbegehren_pdf
    from finance.models import Betreibung
    b = get_object_or_404(Betreibung.objects.select_related(
        'debitoren_rechnung__liegenschaft__eigentuemer', 'vertrag__mieter',
        'vertrag__einheit__liegenschaft__eigentuemer', 'organisation'), pk=pk)
    pdf = betreibungsbegehren_pdf(b)
    if request.method == 'POST':
        # Das Blatt in der Akte ablegen ist Teil des Betreibungsverfahrens: nur
        # die Verwaltung (SICH-11). Die Vorschau (GET) bleibt der Schreibrolle.
        if not hat_rolle(request.user, BETREIBUNGS_ROLLEN):
            raise PermissionDenied('Das Betreibungsbegehren legt nur die Verwaltung ab.')
        if b.vertrag_id:
            ablegen(pdf, f"Betreibungsbegehren (Daten) {b.betreibungsnummer or '#' + str(b.pk)}",
                    kategorie='korrespondenz', vertrag=b.vertrag, dedup=True,
                    dateiname=f"Betreibungsbegehren_{b.pk}.pdf", im_portal_sichtbar=False)
        log_aktion(request, 'Betreibungsbegehren (Daten) erstellt', f'Betreibung #{b.id}', f'CHF {b.forderung}',
                   ziel=b.vertrag)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Betreibungsbegehren_{b.pk}.pdf"'
    return resp


@rolle_erforderlich(*BETREIBUNGS_ROLLEN)
def fw_betreibung_kosten(request, pk):
    """«Kosten dem Mieter belasten» — Betreibungskosten (Art. 68 SchKG) als Forderung.

    Dieselbe Rolle wie das Erfassen einer Mahngebühr (`fw_mahnung_erfassen`)."""
    from core.services import betreibung as bdienst
    from finance.models import Betreibung
    b = get_object_or_404(Betreibung.objects.all(), pk=pk)
    if request.method != 'POST':
        return redirect(f'/neu/betreibungen/{b.id}/')
    try:
        k = bdienst.kosten_belasten(b, user=request.user)
    except (bdienst.BetreibungsFehler, PermissionError) as exc:
        # PermissionError: gesperrte Buchungsperiode (`buche`).
        messages.error(request, str(exc))
        return redirect(f'/neu/betreibungen/{b.id}/')
    log_aktion(request, 'Betreibungskosten belastet', f'Betreibung #{b.id}', f'CHF {k.betrag}', ziel=b.vertrag)
    messages.success(request, gettext('Betreibungskosten von CHF %(b)s dem Mieter belastet (Art. 68 SchKG).')
                     % {'b': f'{k.betrag:.2f}'})
    return redirect(f'/neu/betreibungen/{b.id}/')


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
        # Ausserhalb des f-Strings: `makemessages` liest Texte darin nicht.
        allgemein = gettext('allgemein')
        self.fields['zaehler'].label_from_instance = lambda z: (
            f"{z.typ} {z.zaehler_nummer}" + (f" · {z.einheit.bezeichnung}" if z.einheit_id else f" · {allgemein}"))

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
                  senden=gettext('Speichern'), nav='liegenschaften', extra={'weiter_knopf': True},
                  status=400 if request.method == 'POST' else 200)
