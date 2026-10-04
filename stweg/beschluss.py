"""Auswertung der Stimmen und Feststellung des Beschlusses.

Das System RECHNET einen Vorschlag (`auswerten`). Welche Mehrheit ein Geschäft
braucht, ist Sache von Gesetz und Reglement und wird je Traktandum von der
Verwaltung gewählt (`Traktandum.mehrheitsart`); hier steht keine Rechtsnorm.
FESTGESTELLT wird das Ergebnis von einer Person (`feststellen`) — die
Versammlungsleitung kann vom Vorschlag abweichen (Berichtigungen,
Wiederholung der Abstimmung). Das Protokoll hält die Zahlen zum Zeitpunkt der
Feststellung fest.

ZÄHLWEISE
  · Kopf  = ein Stockwerkeigentümer (mehrere Einheiten derselben Person zählen
    einmal). Einheiten ohne zugeordneten Eigentümer zählen je als eigener Kopf.
  · Quote = Wertquote der Einheit.
  · Es zählen nur Einheiten, die anwesend oder vertreten sind.
  · Enthaltungen zählen nicht als Stimme (weder Ja noch Nein).
  · Stimmt derselbe Eigentümer mit seinen Einheiten widersprüchlich (Ja und
    Nein), ist das ein Erfassungsfehler: Feststellung wird verweigert.
"""
from django.utils.translation import gettext
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from stweg.models import Anwesenheit, Stimme, StimmeEreignis, Traktandum
from stweg.validierung import stimm_einheiten


class BeschlussFehler(ValueError):
    pass


def _kopf(einheit):
    return f"e{einheit.stockwerkeigentuemer_id}" if einheit.stockwerkeigentuemer_id else f"u{einheit.pk}"


def vertretene_einheiten(versammlung):
    ids = set(Anwesenheit.objects.filter(
        versammlung=versammlung, art__in=(Anwesenheit.ANWESEND, Anwesenheit.VERTRETEN)
    ).values_list('einheit_id', flat=True))
    return [e for e in stimm_einheiten(versammlung.liegenschaft) if e.pk in ids]


def praesenz(versammlung):
    """Vertretene Köpfe und Wertquoten gegenüber dem Total — Information, KEIN
    Urteil über die Beschlussfähigkeit (die richtet sich nach Reglement)."""
    alle = list(stimm_einheiten(versammlung.liegenschaft))
    da = vertretene_einheiten(versammlung)
    return {
        'koepfe': len({_kopf(e) for e in da}), 'koepfe_total': len({_kopf(e) for e in alle}),
        'quoten': sum((e.wertquote for e in da), Decimal('0')),
        'quoten_total': Decimal(versammlung.liegenschaft.wertquote_total),
    }


def zaehlen(einheiten, stimmen, mehrheitsart, total_quoten, anwesende_koepfe=None):
    """Zählt Stimmen und schlägt ein Ergebnis vor — gemeinsam für Versammlung und
    Zirkularbeschluss.

    `einheiten`: ALLE Einheiten der Gemeinschaft; `stimmen`: {einheit: wert} der
    Einheiten, die abgestimmt haben (bei der Versammlung nur die vertretenen);
    `anwesende_koepfe`: Köpfe der anwesenden oder vertretenen Eigentümer, auch wenn sie nicht
    abgestimmt haben (nur für «doppelt_anwesende»; beim Zirkularbeschluss gibt es keine Anwesenheit)."""
    vertreten = {e.pk: e for e in einheiten if e.pk in stimmen}
    quoten = {Stimme.JA: Decimal('0'), Stimme.NEIN: Decimal('0'), Stimme.ENTHALTUNG: Decimal('0')}
    je_kopf = {}
    for eid, wert in stimmen.items():
        if eid not in vertreten:
            continue
        quoten[wert] += vertreten[eid].wertquote
        je_kopf.setdefault(_kopf(vertreten[eid]), set()).add(wert)

    koepfe = {Stimme.JA: 0, Stimme.NEIN: 0, Stimme.ENTHALTUNG: 0}
    widerspruch = []
    for kopf, werte in je_kopf.items():
        echte = werte - {Stimme.ENTHALTUNG}
        if len(echte) > 1:
            widerspruch.append(kopf)
        elif echte:
            koepfe[next(iter(echte))] += 1
        else:
            koepfe[Stimme.ENTHALTUNG] += 1

    total_koepfe = len({_kopf(e) for e in einheiten})
    total_quoten = Decimal(total_quoten)
    ja_k, nein_k = koepfe[Stimme.JA], koepfe[Stimme.NEIN]
    ja_q, nein_q = quoten[Stimme.JA], quoten[Stimme.NEIN]

    if mehrheitsart == 'kenntnisnahme':
        angenommen = None
    elif mehrheitsart == 'einfach_koepfe':
        angenommen = ja_k > nein_k
    elif mehrheitsart == 'einfach_quoten':
        angenommen = ja_q > nein_q
    elif mehrheitsart == 'doppelt':
        angenommen = ja_k > nein_k and ja_q > nein_q
    elif mehrheitsart == 'doppelt_aller':
        angenommen = ja_k * 2 > total_koepfe and ja_q * 2 > total_quoten
    elif mehrheitsart == 'doppelt_anwesende':
        if anwesende_koepfe is None:
            raise BeschlussFehler(gettext('«Mehrheit der Anwesenden» braucht eine Versammlung mit Anwesenheit.'))
        angenommen = ja_k * 2 > anwesende_koepfe and ja_q * 2 > total_quoten
    elif mehrheitsart == 'einstimmig':
        angenommen = ja_k == total_koepfe
    else:
        raise BeschlussFehler(gettext('Unbekannte Mehrheitsart «%(mehrheitsart)s».') % {'mehrheitsart': mehrheitsart})

    vorschlag = (Traktandum.KENNTNIS if angenommen is None
                 else Traktandum.ANGENOMMEN if angenommen else Traktandum.ABGELEHNT)
    return {
        'ja_koepfe': ja_k, 'nein_koepfe': nein_k, 'enthaltung_koepfe': koepfe[Stimme.ENTHALTUNG],
        'ja_quoten': ja_q, 'nein_quoten': nein_q, 'enthaltung_quoten': quoten[Stimme.ENTHALTUNG],
        'total_koepfe': total_koepfe, 'total_quoten': total_quoten,
        'vorschlag': vorschlag, 'widerspruch': widerspruch,
    }


def auswerten(traktandum):
    """Zählt die Stimmen eines Traktandums und schlägt ein Ergebnis vor. Ändert nichts."""
    v = traktandum.versammlung
    vertreten = {e.pk for e in vertretene_einheiten(v)}
    stimmen = {s.einheit_id: s.wert for s in Stimme.objects.filter(traktandum=traktandum)
               if s.einheit_id in vertreten}
    anwesende = len({_kopf(e) for e in vertretene_einheiten(v)})
    return zaehlen(list(stimm_einheiten(v.liegenschaft)), stimmen, traktandum.mehrheitsart,
                   v.liegenschaft.wertquote_total, anwesende_koepfe=anwesende)


@transaction.atomic
def feststellen(traktandum, ergebnis, *, beschlusstext=None, user=None, trotzdem=False):
    """Hält das Ergebnis fest (Zahlen als Momentaufnahme) und legt bei einem
    angenommenen Beschluss mit Vollzugsaufgabe eine Pendenz an."""
    if ergebnis not in dict(Traktandum.ERGEBNIS_CHOICES) or ergebnis == Traktandum.OFFEN:
        raise BeschlussFehler(gettext('Ungültiges Ergebnis «%(ergebnis)s».') % {'ergebnis': ergebnis})
    v = traktandum.versammlung
    if v.status == v.ENTWURF:
        raise BeschlussFehler(gettext('Die Versammlung wurde noch nicht einberufen.'))
    z = auswerten(traktandum)
    if z['widerspruch'] and ergebnis in (Traktandum.ANGENOMMEN, Traktandum.ABGELEHNT):
        raise BeschlussFehler(gettext('Widersprüchliche Stimmen desselben Eigentümers — bitte zuerst korrigieren.'))
    # Beschlussfähigkeit: nur, wenn die Gemeinschaft ein Quorum eingetragen hat (`stweg.vorgaben`);
    # das System kennt keinen Wert von sich aus. Die Verwaltung kann trotzdem feststellen — das steht dann im Protokoll.
    traktandum.ohne_beschlussfaehigkeit = False
    if ergebnis in (Traktandum.ANGENOMMEN, Traktandum.ABGELEHNT):
        from stweg import vorgaben
        bf = vorgaben.beschlussfaehigkeit(v)
        if bf is not None and not bf['beschlussfaehig']:
            if not trotzdem:
                raise BeschlussFehler(gettext('Nicht beschlussfähig nach den Vorgaben der Gemeinschaft: %(gruende)s')
                                      % {'gruende': ' '.join(bf['gruende'])})
            traktandum.ohne_beschlussfaehigkeit = True

    for feld in ('ja_koepfe', 'nein_koepfe', 'enthaltung_koepfe',
                 'ja_quoten', 'nein_quoten', 'enthaltung_quoten'):
        setattr(traktandum, feld, z[feld])
    traktandum.ergebnis = ergebnis
    if beschlusstext is not None:
        traktandum.beschlusstext = beschlusstext
    traktandum.festgestellt_am = timezone.now()
    traktandum.save()

    if traktandum.budget_id:
        from stweg import budget as bd
        if ergebnis == Traktandum.ANGENOMMEN:
            try:
                bd.budget_genehmigen(traktandum.budget, traktandum=traktandum)
            except bd.BudgetFehler as e:
                raise BeschlussFehler(gettext('Das Budget kann nicht genehmigt werden: %(e)s') % {'e': e})
        elif ergebnis == Traktandum.ABGELEHNT and traktandum.budget.status == traktandum.budget.VORGELEGT:
            bd.budget_ablehnen(traktandum.budget)

    if ergebnis == Traktandum.ANGENOMMEN and traktandum.vollzug_aufgabe:
        from stweg.aufgaben import vollzug_pendenz
        vollzug_pendenz(traktandum, user=user)
    return traktandum


def anwesenheit_setzen(versammlung, einheit, art, vertreter=''):
    if einheit.liegenschaft_id != versammlung.liegenschaft_id:
        raise BeschlussFehler(gettext('Die Einheit gehört nicht zu dieser Gemeinschaft.'))
    obj, _ = Anwesenheit.objects.update_or_create(
        versammlung=versammlung, einheit=einheit,
        defaults={'art': art, 'vertreter': vertreter if art == Anwesenheit.VERTRETEN else ''})
    return obj


def stimme_abgeben(traktandum, einheit, wert, *, kanal='verwaltung', eigentuemer=None):
    """Erfasst oder ändert die Stimme einer Einheit. Nach der Feststellung des Ergebnisses ist
    sie gesperrt (das Protokoll hielte sonst Zahlen fest, die nicht mehr stimmen). Jede Abgabe
    steht zusätzlich im Ereignisprotokoll `StimmeEreignis`."""
    if wert not in dict(Stimme.WERT_CHOICES):
        raise BeschlussFehler(gettext('Ungültige Stimme «%(wert)s».') % {'wert': wert})
    if traktandum.ergebnis != Traktandum.OFFEN:
        raise BeschlussFehler(gettext('Das Ergebnis dieses Traktandums ist bereits festgestellt — die Stimmen sind gesperrt.'))
    if traktandum.mehrheitsart == 'kenntnisnahme':
        raise BeschlussFehler(gettext('Zur Kenntnisnahme wird nicht abgestimmt.'))
    if einheit.pk not in {e.pk for e in vertretene_einheiten(traktandum.versammlung)}:
        raise BeschlussFehler(gettext('Diese Einheit ist nicht anwesend oder vertreten — sie hat kein Stimmrecht.'))
    with transaction.atomic():
        alt = Stimme.objects.filter(traktandum=traktandum, einheit=einheit).first()
        obj, _ = Stimme.objects.update_or_create(
            traktandum=traktandum, einheit=einheit,
            defaults={'wert': wert, 'kanal': kanal, 'abgegeben_am': timezone.now()})
        StimmeEreignis.objects.create(traktandum=traktandum, einheit=einheit, wert=wert,
                                      vorher=alt.wert if alt else '', kanal=kanal, eigentuemer=eigentuemer)
    return obj


def stimme_loeschen(traktandum, einheit, *, kanal='verwaltung'):
    """Nimmt eine erfasste Stimme zurück (Erfassungsfehler). Gesperrt nach der Feststellung;
    das Ereignisprotokoll hält den Widerruf mit leerem Wert fest."""
    if traktandum.ergebnis != Traktandum.OFFEN:
        raise BeschlussFehler(gettext('Das Ergebnis dieses Traktandums ist bereits festgestellt — die Stimmen sind gesperrt.'))
    with transaction.atomic():
        alt = Stimme.objects.filter(traktandum=traktandum, einheit=einheit).first()
        if alt is None:
            return
        alt.delete()
        StimmeEreignis.objects.create(traktandum=traktandum, einheit=einheit, wert='', vorher=alt.wert,
                                      kanal=kanal)
