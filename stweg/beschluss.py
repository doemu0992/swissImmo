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
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from stweg.models import Anwesenheit, Stimme, Traktandum


class BeschlussFehler(ValueError):
    pass


def _kopf(einheit):
    return f"e{einheit.stockwerkeigentuemer_id}" if einheit.stockwerkeigentuemer_id else f"u{einheit.pk}"


def vertretene_einheiten(versammlung):
    ids = set(Anwesenheit.objects.filter(
        versammlung=versammlung, art__in=(Anwesenheit.ANWESEND, Anwesenheit.VERTRETEN)
    ).values_list('einheit_id', flat=True))
    return [e for e in versammlung.liegenschaft.einheiten.all() if e.pk in ids]


def praesenz(versammlung):
    """Vertretene Köpfe und Wertquoten gegenüber dem Total — Information, KEIN
    Urteil über die Beschlussfähigkeit (die richtet sich nach Reglement)."""
    alle = list(versammlung.liegenschaft.einheiten.all())
    da = vertretene_einheiten(versammlung)
    return {
        'koepfe': len({_kopf(e) for e in da}), 'koepfe_total': len({_kopf(e) for e in alle}),
        'quoten': sum((e.wertquote for e in da), Decimal('0')),
        'quoten_total': Decimal(versammlung.liegenschaft.wertquote_total),
    }


def auswerten(traktandum):
    """Zählt die Stimmen und schlägt ein Ergebnis vor. Ändert nichts."""
    v = traktandum.versammlung
    lg = v.liegenschaft
    alle = list(lg.einheiten.all())
    vertreten = {e.pk: e for e in vertretene_einheiten(v)}
    stimmen = {s.einheit_id: s.wert for s in Stimme.objects.filter(traktandum=traktandum)
               if s.einheit_id in vertreten}

    quoten = {Stimme.JA: Decimal('0'), Stimme.NEIN: Decimal('0'), Stimme.ENTHALTUNG: Decimal('0')}
    je_kopf = {}
    for eid, wert in stimmen.items():
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

    total_koepfe = len({_kopf(e) for e in alle})
    total_quoten = Decimal(lg.wertquote_total)
    ja_k, nein_k = koepfe[Stimme.JA], koepfe[Stimme.NEIN]
    ja_q, nein_q = quoten[Stimme.JA], quoten[Stimme.NEIN]

    art = traktandum.mehrheitsart
    if art == 'kenntnisnahme':
        angenommen = None
    elif art == 'einfach_koepfe':
        angenommen = ja_k > nein_k
    elif art == 'einfach_quoten':
        angenommen = ja_q > nein_q
    elif art == 'doppelt':
        angenommen = ja_k > nein_k and ja_q > nein_q
    elif art == 'doppelt_aller':
        angenommen = ja_k * 2 > total_koepfe and ja_q * 2 > total_quoten
    elif art == 'einstimmig':
        angenommen = ja_k == total_koepfe
    else:
        raise BeschlussFehler(f'Unbekannte Mehrheitsart «{art}».')

    vorschlag = (Traktandum.KENNTNIS if angenommen is None
                 else Traktandum.ANGENOMMEN if angenommen else Traktandum.ABGELEHNT)
    return {
        'ja_koepfe': ja_k, 'nein_koepfe': nein_k, 'enthaltung_koepfe': koepfe[Stimme.ENTHALTUNG],
        'ja_quoten': ja_q, 'nein_quoten': nein_q, 'enthaltung_quoten': quoten[Stimme.ENTHALTUNG],
        'total_koepfe': total_koepfe, 'total_quoten': total_quoten,
        'vorschlag': vorschlag, 'widerspruch': widerspruch,
    }


@transaction.atomic
def feststellen(traktandum, ergebnis, *, beschlusstext=None, user=None):
    """Hält das Ergebnis fest (Zahlen als Momentaufnahme) und legt bei einem
    angenommenen Beschluss mit Vollzugsaufgabe eine Pendenz an."""
    if ergebnis not in dict(Traktandum.ERGEBNIS_CHOICES) or ergebnis == Traktandum.OFFEN:
        raise BeschlussFehler(f'Ungültiges Ergebnis «{ergebnis}».')
    v = traktandum.versammlung
    if v.status == v.ENTWURF:
        raise BeschlussFehler('Die Versammlung wurde noch nicht einberufen.')
    z = auswerten(traktandum)
    if z['widerspruch'] and ergebnis in (Traktandum.ANGENOMMEN, Traktandum.ABGELEHNT):
        raise BeschlussFehler('Widersprüchliche Stimmen desselben Eigentümers — bitte zuerst korrigieren.')

    for feld in ('ja_koepfe', 'nein_koepfe', 'enthaltung_koepfe',
                 'ja_quoten', 'nein_quoten', 'enthaltung_quoten'):
        setattr(traktandum, feld, z[feld])
    traktandum.ergebnis = ergebnis
    if beschlusstext is not None:
        traktandum.beschlusstext = beschlusstext
    traktandum.festgestellt_am = timezone.now()
    traktandum.save()

    if ergebnis == Traktandum.ANGENOMMEN and traktandum.vollzug_aufgabe:
        from stweg.aufgaben import vollzug_pendenz
        vollzug_pendenz(traktandum, user=user)
    return traktandum


def anwesenheit_setzen(versammlung, einheit, art, vertreter=''):
    if einheit.liegenschaft_id != versammlung.liegenschaft_id:
        raise BeschlussFehler('Die Einheit gehört nicht zu dieser Gemeinschaft.')
    obj, _ = Anwesenheit.objects.update_or_create(
        versammlung=versammlung, einheit=einheit,
        defaults={'art': art, 'vertreter': vertreter if art == Anwesenheit.VERTRETEN else ''})
    return obj


def stimme_abgeben(traktandum, einheit, wert):
    if wert not in dict(Stimme.WERT_CHOICES):
        raise BeschlussFehler(f'Ungültige Stimme «{wert}».')
    if einheit.pk not in {e.pk for e in vertretene_einheiten(traktandum.versammlung)}:
        raise BeschlussFehler('Diese Einheit ist nicht anwesend oder vertreten — sie hat kein Stimmrecht.')
    obj, _ = Stimme.objects.update_or_create(traktandum=traktandum, einheit=einheit,
                                             defaults={'wert': wert})
    return obj
