"""Ablauf einer amtlichen Mietzinsanpassung: Entwurf → versandt → wirksam / angefochten.

WARUM ES DIESEN DIENST GIBT (Befund C, 26.10.2026)

Bis hierher buchte schon die PDF-Vorschau. Ein Klick auf «Formular als PDF»
legte die Anpassung, die Sollmietzins-Zeile am Objekt und die Pendenz zur
Anfechtungsfrist an — und jeder geänderte Betrag eine weitere, weil die
Idempotenz am Betrag hing. Wer drei Varianten durchrechnete, hatte drei
Erhöhungen gebucht. Die Anfechtungsfrist lief ab dem Tag der Vorschau statt ab
dem Zugang beim Mieter.

Jetzt gilt:

* Ein **Entwurf** bucht nichts. Je Vertrag gibt es höchstens einen offenen; wer
  weiterrechnet, ändert ihn, statt einen zweiten anzulegen.
* Erst der **Versand** bucht: Status, Sollmietzins ab `wirksam_ab`, die
  Anfechtungs-Pendenz ab Zugang + 30 Tage (Art. 270b OR) und die Basisdaten
  des Vertrags (Kostensteigerung ausgeglichen bis, letzte Indexanpassung,
  bezifferter Vorbehalt).
* **Wirksam** und **angefochten** halten den weiteren Verlauf fest. Was bei
  einer Anfechtung bis zum Entscheid verrechnet wird, entscheidet dieser
  Dienst NICHT — die Buchung bleibt, und eine Pendenz verlangt die Prüfung nach
  dem Ausgang des Verfahrens.

Die Views (`core/views/fw/mietzins.py`) erzeugen das PDF und rufen diese
Funktionen; die Fachentscheide stehen hier, an einer Stelle.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

#: Art. 270b OR: Anfechtung innert 30 Tagen nach Empfang. Gleicher Wert wie in
#: der bisherigen Pendenz in `fw_mietzins_anpassung` und im Gesetzesregister.
ANFECHTUNG_TAGE = 30


def quelle_anfechtung(anp):
    """Stabiler Schlüssel der Anfechtungs-Pendenz — macht sie idempotent."""
    return f'270b:{anp.pk}'


def offener_entwurf(vertrag):
    """Der offene Entwurf dieses Vertrags (der jüngste), oder None."""
    from rentals.models import MietzinsAnpassung
    return (MietzinsAnpassung.objects
            .filter(vertrag=vertrag, status=MietzinsAnpassung.STATUS_ENTWURF)
            .order_by('-id').first())


def entwurf_speichern(vertrag, werte, entwurf=None):
    """Legt den Entwurf an oder schreibt ihn fort. Bucht nichts.

    `entwurf` — ein bestehender Entwurf DIESES Vertrags (vom Aufrufer über
    `objects` gefunden, also mandantengeprüft). Ohne ihn wird der offene
    Entwurf des Vertrags fortgeschrieben; erst wenn keiner da ist, entsteht
    ein neuer. So bleibt es bei einem Entwurf je Vertrag.
    """
    from rentals.models import MietzinsAnpassung
    anp = entwurf if entwurf is not None else offener_entwurf(vertrag)
    if anp is None:
        anp = MietzinsAnpassung(vertrag=vertrag, status=MietzinsAnpassung.STATUS_ENTWURF)
    elif anp.vertrag_id != vertrag.pk or anp.status != MietzinsAnpassung.STATUS_ENTWURF:
        raise ValueError(gettext('Nur ein Entwurf dieses Vertrags lässt sich bearbeiten.'))
    # Eine schon versandte Anpassung auf denselben Termin: ein zweiter Klick auf
    # «Als versandt erfassen» oder ein zweiter Massenlauf. Ohne diese Sperre
    # entstünde eine zweite gebuchte Anpassung — und beide teilten sich die
    # Sollmietzins-Zeile am Objekt (sie hängt an Einheit + Datum).
    termin = werte.get('wirksam_ab', anp.wirksam_ab)
    if termin and MietzinsAnpassung.objects.filter(
            vertrag=vertrag, wirksam_ab=termin,
            status__in=MietzinsAnpassung.GEBUCHT).exclude(pk=anp.pk).exists():
        raise ValueError(gettext('Für den %(datum)s ist bereits eine Anpassung versandt.') % {
            'datum': termin.strftime('%d.%m.%Y')})
    for feld, wert in werte.items():
        setattr(anp, feld, wert)
    anp.save()
    return anp


def ist_erhoehung(anp):
    """Netto höher — oder das Nebenkosten-Akonto (E1, NK-Wizard): Auch die Erhöhung des Akontos
    ist eine einseitige Vertragsänderung zulasten des Mieters, mit derselben Frist und Anfechtung."""
    if (anp.neuer_netto_mietzins or Decimal('0')) > (anp.alter_netto_mietzins or Decimal('0')):
        return True
    neu, alt = getattr(anp, 'neue_nebenkosten', None), getattr(anp, 'alte_nebenkosten', None)
    return neu is not None and alt is not None and neu > alt


def fristfehler(anp, versand_am, zugang_am=None):
    """Meldung, wenn der Termin bei diesem Versand/Zugang zu früh ist — sonst ''.

    Art. 269d OR: Die Erhöhung muss mindestens zehn Tage vor Beginn der
    Kündigungsfrist ZUGEHEN. Gerechnet über `naechster_anpassungstermin` —
    dieselbe Rechnung wie im Formular, mit dem bestätigten Zugang, wenn er
    bekannt ist, sonst mit dem Zustellpuffer. Nur für Erhöhungen: Eine Senkung
    darf früher wirken.
    """
    from rentals.services import naechster_anpassungstermin
    if not ist_erhoehung(anp):
        return ''
    frueh = naechster_anpassungstermin(anp.vertrag, versand_am, zugang_am=zugang_am)
    if anp.wirksam_ab < frueh:
        return gettext('Wirksamkeitsdatum zu früh: Bei diesem Versand kann die Erhöhung frühestens '
                       'auf %(datum)s wirksam werden (Kündigungsfrist + 10 Tage ab Zugang, '
                       'Art. 269d OR).') % {'datum': frueh.strftime('%d.%m.%Y')}
    return ''


@transaction.atomic
def versand_erfassen(anp, versand_am, zugang_am=None, benutzer=None):
    """Der Übergang Entwurf → versandt. Bucht. Wirft `ValueError` mit Klartext.

    Was beim Versand geschieht, in dieser Reihenfolge:
      1. Prüfung der 269d-Frist mit dem tatsächlichen Versand/Zugang;
      2. Status, Versand- und Zugangsdatum → `save()` führt die Sollmietzins-
         Zeile am Objekt (nur gebuchte Anpassungen tragen eine);
      3. Anfechtungs-Pendenz bei einer Erhöhung: Zugang (bestätigt, sonst
         vermutet) + 30 Tage;
      4. Basisdaten am Vertrag (Befund I).
    """
    from rentals.models import MietzinsAnpassung
    if anp.status != MietzinsAnpassung.STATUS_ENTWURF:
        raise ValueError(gettext('Nur ein Entwurf kann als versandt erfasst werden.'))
    heute = timezone.localdate()
    if versand_am is None:
        raise ValueError(gettext('Bitte das Versanddatum angeben.'))
    if versand_am > heute or (zugang_am and zugang_am > heute):
        raise ValueError(gettext('Versand- und Zugangsdatum können nicht in der Zukunft liegen.'))
    if zugang_am and zugang_am < versand_am:
        raise ValueError(gettext('Der Zugang kann nicht vor dem Versand liegen.'))
    fehler = fristfehler(anp, versand_am, zugang_am)
    if fehler:
        raise ValueError(fehler)

    anp.status = MietzinsAnpassung.STATUS_VERSANDT
    anp.versand_am = versand_am
    anp.zugang_am = zugang_am
    anp.save()

    v = anp.vertrag
    if ist_erhoehung(anp):
        _anfechtungs_pendenz(anp, benutzer)
    _vertragsbasis_fortschreiben(v, anp)
    return anp


def _anfechtungs_pendenz(anp, benutzer=None):
    from core.models import Pendenz
    v = anp.vertrag
    zugang = anp.zugang_vermutet()
    frist = zugang + timedelta(days=ANFECHTUNG_TAGE)
    vermutet = '' if anp.zugang_am else ' (Zugang vermutet: Versand + Zustellpuffer)'
    werte = dict(
        titel=f"Anfechtungsfrist Mietzinserhöhung läuft ab – {v.mieter.display_name}",
        beschreibung=(f"Erhöhung auf CHF {anp.neuer_netto_mietzins} (wirksam {anp.wirksam_ab:%d.%m.%Y}). "
                      f"Zugang {zugang:%d.%m.%Y}{vermutet}. Der Mieter kann sie innert "
                      f"{ANFECHTUNG_TAGE} Tagen ab Empfang des amtlichen Formulars bei der "
                      "Schlichtungsbehörde anfechten (Art. 270b OR)."),
        kategorie='frist', faellig_am=frist, vertrag=v,
        liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
    )
    p = Pendenz.objects.filter(vertrag=v, quelle=quelle_anfechtung(anp)).first()
    if p is None:
        Pendenz.objects.create(quelle=quelle_anfechtung(anp), erstellt_von=benutzer, **werte)
    else:
        for feld, wert in werte.items():
            setattr(p, feld, wert)
        p.save()


def zugang_nachtragen(anp, zugang_am):
    """Bestätigter Zugang nach dem Versand: die Anfechtungsfrist folgt ihm."""
    if zugang_am > timezone.localdate():
        raise ValueError(gettext('Das Zugangsdatum kann nicht in der Zukunft liegen.'))
    if anp.versand_am and zugang_am < anp.versand_am:
        raise ValueError(gettext('Der Zugang kann nicht vor dem Versand liegen.'))
    anp.zugang_am = zugang_am
    anp.save(update_fields=['zugang_am'])
    if ist_erhoehung(anp):
        _anfechtungs_pendenz(anp)


def _vertragsbasis_fortschreiben(v, anp):
    """Befund I: Die Basisdaten am Vertrag folgen der versandten Anpassung.

    * «Kostensteigerung ausgeglichen bis» — nur wenn diese Anpassung eine
      Kostensteigerung geltend macht. Sonst rechnete die nächste Anpassung die
      Pauschale wieder ab Vertragsbeginn und verlangte sie ein zweites Mal.
      Ohne geltend gemachten Anteil bleibt das Datum stehen: Ob ein nicht
      verlangter Anteil verfällt, ist eine Rechtsfrage, die hier niemand
      entscheidet.
    * «Letzte Indexanpassung» bei Indexmiete — der Beginn des Mindestintervalls.
    * Der bezifferte Vorbehalt wird zur Mietzinsreserve des Vertrags.

    Referenzzins und LIK werden NICHT in `basis_*` geschrieben: Die Basis des
    Vertragsbeginns bleibt stehen, die jeweils geltende liefert
    `Mietvertrag.effektive_basis()` aus der jüngsten gebuchten Anpassung.
    """
    felder = []
    if anp.kosten_ausgeglichen_bis and (anp.kosten_prozent or Decimal('0')) > 0:
        v.kostensteigerung_datum = anp.kosten_ausgeglichen_bis
        felder.append('kostensteigerung_datum')
    if v.mietzins_modell == 'index':
        v.index_letzte_anpassung = anp.wirksam_ab
        felder.append('index_letzte_anpassung')
    if anp.vorbehalt_betrag is not None or anp.vorbehalt_prozent is not None:
        v.mietzinsreserve_betrag = anp.vorbehalt_betrag
        v.mietzinsreserve_prozent = anp.vorbehalt_prozent
        felder += ['mietzinsreserve_betrag', 'mietzinsreserve_prozent']
    if felder:
        v.save(update_fields=felder)


ERLAUBTE_UEBERGAENGE = {
    'versandt': ('wirksam', 'angefochten'),
    'angefochten': ('wirksam',),
}


@transaction.atomic
def status_setzen(anp, neu, benutzer=None):
    """versandt → wirksam / angefochten, angefochten → wirksam. `ValueError` sonst."""
    from core.models import Pendenz
    if neu not in ERLAUBTE_UEBERGAENGE.get(anp.status, ()):
        raise ValueError(gettext('Dieser Statuswechsel ist nicht möglich.'))
    anp.status = neu
    anp.save(update_fields=['status'])
    v = anp.vertrag
    if neu == 'angefochten':
        Pendenz.objects.get_or_create(
            vertrag=v, quelle=f'270b-verfahren:{anp.pk}',
            defaults=dict(
                titel=f"Mietzinsanpassung angefochten – {v.mieter.display_name}",
                beschreibung=(f"Der Mieter hat die Anpassung auf CHF {anp.neuer_netto_mietzins} "
                              f"(wirksam {anp.wirksam_ab:%d.%m.%Y}) angefochten. Ausgang des "
                              "Schlichtungsverfahrens abwarten und die Sollstellung danach prüfen — "
                              "die Buchung des Versands bleibt bis dahin unverändert."),
                kategorie='frist', faellig_am=timezone.localdate() + timedelta(days=ANFECHTUNG_TAGE),
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                erstellt_von=benutzer))
    if neu == 'wirksam':
        # Einzeln speichern statt `.update()`: Pendenz.save() trägt Folgen
        # (Fall, Protokoll), die ein Massen-Update überginge.
        for p in Pendenz.objects.filter(vertrag=v, erledigt=False, quelle__in=[
                quelle_anfechtung(anp), f'270b-verfahren:{anp.pk}']):
            p.erledigt = True
            p.erledigt_am = timezone.localdate()
            p.save(update_fields=['erledigt', 'erledigt_am'])
    return anp
