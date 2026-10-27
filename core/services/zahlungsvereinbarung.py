"""Zahlungsvereinbarung mit Ratenplan.

Vorher gab es nur das Häkchen `Mieter.mahnsperre`: Es sperrte das Mahnen, ohne
Betrag, Raten oder Ende — und niemand bemerkte, wenn die Vereinbarung gebrochen
wurde (Stresstest 30.09.2026). Jetzt:

· `anlegen` erfasst den gedeckten Rückstand, verteilt ihn auf gleich hohe Raten
  (die letzte trägt den Rest) und legt je Rate eine Pendenz an.
· `pruefen` (täglich und nach jeder Zahlung) stellt fest, ob erfüllt oder gebrochen.
  Gebrochen: Die bezahlte Summe liegt unter der Soll-Summe der Raten, die vor
  `TOLERANZ_TAGE` Tagen fällig waren. Dann laufen die gedeckten Forderungen wieder
  im Mahnlauf, und eine Pendenz verlangt die Fortsetzung des Mahnprozesses.

WAS GESPERRT IST (seit 26.10.2026)

Solange eine Vereinbarung `aktiv` ist, nimmt der Mahnlauf genau die Forderungen
aus, die sie deckt: die Rechnungen des Vertrags, die bis `gedeckt_bis` fällig
waren, und die daraus abgeleiteten Mahngebühren und Zinsen (`stammrechnung`).
Eine neue Monatsmiete während des Ratenplans ist NICHT gedeckt und wird normal
gemahnt — der Mieter zahlt Raten auf den alten Rückstand, nicht auf die laufende
Miete. Früher setzte `anlegen` dafür `Mieter.mahnsperre` und sperrte damit den
ganzen Mieter; das Häkchen ist seither wieder ein reiner Handschalter
(Datenmigration finance 0048). Zentral entschieden wird in
`ist_durch_vereinbarung_gesperrt` bzw. `gesperrte_rechnung_ids`; Mahnlauf und
Mahnwesen fragen nur dort.

Eine Vereinbarung hemmt eine laufende 257d-Frist nicht (siehe Modellkommentar).
"""
import calendar
from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.utils import timezone

TOLERANZ_TAGE = 5


def _plus_monate(d, monate):
    j, m = divmod(d.month - 1 + monate, 12)
    j, m = d.year + j, m + 1
    return date(j, m, min(d.day, calendar.monthrange(j, m)[1]))


def raten_plan(v):
    """[(nr, faellig, betrag)] — gleich hohe Raten, die letzte trägt den Rest."""
    n = v.anzahl_raten
    basis = (v.betrag_total / n).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    plan = []
    for i in range(n):
        betrag = basis if i < n - 1 else v.betrag_total - basis * (n - 1)
        plan.append((i + 1, _plus_monate(v.erste_rate, i * v.intervall_monate), betrag))
    return plan


def rueckstand(v):
    """Noch offener Betrag der gedeckten Forderungen."""
    from core.services.zahlungsverzug import faelliger_rueckstand
    return faelliger_rueckstand(v.vertrag, stichtag=v.gedeckt_bis)


def bezahlt(v):
    return max(v.betrag_total - rueckstand(v), Decimal('0.00'))


def soll_bis(v, stichtag):
    return sum((b for _, f, b in raten_plan(v) if f <= stichtag), Decimal('0.00'))


def anlegen(vertrag, anzahl_raten, erste_rate, intervall_monate=1, user=None, notiz=''):
    """Legt die Vereinbarung an. Wirft ValueError bei unzulässigen Angaben."""
    from core.models import Pendenz
    from finance.models import Zahlungsvereinbarung

    heute = timezone.localdate()
    if not 2 <= anzahl_raten <= 36:
        raise ValueError('Die Zahl der Raten muss zwischen 2 und 36 liegen.')
    if intervall_monate not in (1, 2, 3):
        raise ValueError('Der Abstand der Raten muss 1, 2 oder 3 Monate betragen.')
    if erste_rate < heute:
        raise ValueError('Die erste Rate darf nicht in der Vergangenheit liegen.')
    if vertrag.zahlungsvereinbarungen.filter(status='aktiv').exists():
        raise ValueError('Für diesen Vertrag läuft bereits eine Zahlungsvereinbarung.')
    from core.services.zahlungsverzug import faelliger_rueckstand
    total = faelliger_rueckstand(vertrag, stichtag=heute)
    if total <= 0:
        raise ValueError('Es gibt keinen fälligen Rückstand, der vereinbart werden könnte.')
    if total < anzahl_raten * Decimal('0.05'):
        raise ValueError('Der Rückstand ist für diese Zahl Raten zu klein.')

    v = Zahlungsvereinbarung.objects.create(
        vertrag=vertrag, betrag_total=total, gedeckt_bis=heute, anzahl_raten=anzahl_raten,
        erste_rate=erste_rate, intervall_monate=intervall_monate, notiz=notiz[:255],
        erstellt_von=user)
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    for nr, faellig, betrag in raten_plan(v):
        Pendenz.objects.create(
            titel=f'Rate {nr}/{anzahl_raten} CHF {betrag:.2f} – {vertrag.mieter.display_name}',
            beschreibung=f'Zahlungsvereinbarung #{v.pk}: Rate {nr} von {anzahl_raten}.',
            kategorie='finanzen', faellig_am=faellig, vertrag=vertrag, liegenschaft=lg,
            quelle=f'auto:rate:{v.pk}:{nr}', erstellt_von=user)
    return v


def _gedeckt_q(vereinbarungen):
    """Q-Ausdruck über die Hauptforderungen, die diese Vereinbarungen decken.

    Massgebend ist das Fälligkeitsdatum, ohne eines das Rechnungsdatum — wie in
    `zahlungsverzug.faelliger_rueckstand`, mit dem der Rückstand berechnet wurde."""
    from django.db.models import Q
    q = Q(pk__in=[])
    for v in vereinbarungen:
        q |= (Q(vertrag_id=v.vertrag_id, stammrechnung__isnull=True)
              & (Q(faellig_am__lte=v.gedeckt_bis)
                 | Q(faellig_am__isnull=True, datum__lte=v.gedeckt_bis)))
    return q


def gesperrte_rechnung_ids():
    """IDs aller Forderungen, die eine AKTIVE Vereinbarung deckt (siehe Modulkopf).

    Für Listen und den Mahnlauf: drei Abfragen, egal wie viele Rechnungen
    geprüft werden. Läuft über `objects` — also im Kontext der Organisation."""
    from finance.models import DebitorenRechnung, Zahlungsvereinbarung
    aktive = list(Zahlungsvereinbarung.objects.filter(status='aktiv')
                  .only('vertrag_id', 'gedeckt_bis'))
    if not aktive:
        return set()
    haupt = set(DebitorenRechnung.objects.filter(_gedeckt_q(aktive)).values_list('pk', flat=True))
    if not haupt:
        return set()
    abgeleitet = set(DebitorenRechnung.objects.filter(stammrechnung_id__in=haupt)
                     .values_list('pk', flat=True))
    return haupt | abgeleitet


def ist_durch_vereinbarung_gesperrt(rechnung):
    """Ist diese Forderung durch eine aktive Zahlungsvereinbarung vom Mahnen ausgenommen?

    Eine abgeleitete Forderung (Mahngebühr, Zins) teilt das Schicksal ihrer
    Stammrechnung."""
    haupt = rechnung
    if rechnung.stammrechnung_id:
        haupt = rechnung.stammrechnung
    if not haupt.vertrag_id:
        return False
    faellig = haupt.faellig_am or haupt.datum
    if not faellig:
        return False
    return haupt.vertrag.zahlungsvereinbarungen.filter(status='aktiv', gedeckt_bis__gte=faellig).exists()


def gedeckte_forderungen(v):
    """[(Rechnung, offen bei Abschluss)] — die Forderungen, die der Rückstand umfasst.

    Für das Schreiben mit Schuldanerkennung: Es nennt die Forderungen, wie sie am
    Tag des Abschlusses offen waren, damit die Summe dem anerkannten Betrag
    (`betrag_total`) entspricht — auch wenn danach schon Raten eingegangen sind.
    Gezählt werden verbuchte Zahlungen mit Eingang bis `gedeckt_bis`."""
    zeilen = []
    for r in (v.vertrag.debitoren_rechnungen
              .filter(_gedeckt_q([v]))
              .exclude(status='storniert')
              .prefetch_related('zahlungseingaenge')
              .order_by('faellig_am', 'datum', 'id')):
        bezahlt_bis = sum((z.betrag or Decimal('0.00')) for z in r.zahlungseingaenge.all()
                          if z.status == 'verbucht' and z.datum_eingang and z.datum_eingang <= v.gedeckt_bis)
        offen = max(Decimal('0.00'), r.betrag - bezahlt_bis)
        if offen > 0:
            zeilen.append((r, offen))
    return zeilen


def _raten_pendenzen(v, erledigen_bis_nr=None, alle=False):
    """Raten-Pendenzen der Vereinbarung erledigen (bezahlte, oder alle)."""
    from core.models import Pendenz
    heute = timezone.localdate()
    for p in Pendenz.objects.filter(quelle__startswith=f'auto:rate:{v.pk}:', erledigt=False):
        nr = int(p.quelle.rsplit(':', 1)[-1])
        if alle or (erledigen_bis_nr is not None and nr <= erledigen_bis_nr):
            p.erledigt = True
            p.erledigt_am = heute
            p.save(update_fields=['erledigt', 'erledigt_am'])


def pruefen(v, stichtag=None, bruch=True):
    """Bewertet EINE aktive Vereinbarung. Gibt den neuen Status zurück.

    `bruch=False` (nach einer Zahlung): nur Erfüllung und gedeckte Raten, kein Urteil
    «gebrochen» — wer gerade nachzahlt, hat die Vereinbarung nicht gebrochen."""
    from core.models import Pendenz
    if v.status != 'aktiv':
        return v.status
    stichtag = stichtag or timezone.localdate()
    offen = rueckstand(v)
    lg = v.vertrag.einheit.liegenschaft if v.vertrag.einheit_id else None
    if offen <= 0:
        v.status = 'erfuellt'
        v.save(update_fields=['status'])
        _raten_pendenzen(v, alle=True)
        return v.status
    gezahlt = v.betrag_total - offen
    # Raten, die durch die Zahlungen bereits gedeckt sind, sind erledigt.
    kum, gedeckt_nr = Decimal('0.00'), 0
    for nr, _f, b in raten_plan(v):
        kum += b
        if gezahlt >= kum:
            gedeckt_nr = nr
    _raten_pendenzen(v, erledigen_bis_nr=gedeckt_nr)
    from datetime import timedelta
    if bruch and gezahlt < soll_bis(v, stichtag - timedelta(days=TOLERANZ_TAGE)):
        v.status = 'gebrochen'
        v.save(update_fields=['status'])
        _raten_pendenzen(v, alle=True)
        Pendenz.objects.get_or_create(
            quelle=f'auto:ratenbruch:{v.pk}',
            defaults={
                'titel': f'Zahlungsvereinbarung gebrochen – {v.vertrag.mieter.display_name}',
                'beschreibung': (f'Bezahlt CHF {gezahlt:.2f} von CHF {soll_bis(v, stichtag - timedelta(days=TOLERANZ_TAGE)):.2f} '
                                 f'fälligen Raten. Die gedeckten Forderungen laufen wieder im Mahnlauf; '
                                 f'der Mahnprozess geht weiter (Mahnwesen, ggf. Fristansetzung nach '
                                 f'Art. 257d OR).'),
                'kategorie': 'finanzen', 'faellig_am': stichtag, 'vertrag': v.vertrag,
                'liegenschaft': lg})
    return v.status


def pruefen_vertrag(vertrag):
    n = 0
    for v in vertrag.zahlungsvereinbarungen.filter(status='aktiv'):
        pruefen(v, bruch=False)
        n += 1
    return n


def pruefen_alle():
    """Täglicher Lauf im Kontext einer Organisation."""
    from finance.models import Zahlungsvereinbarung
    return sum(1 for v in Zahlungsvereinbarung.objects.filter(status='aktiv')
               .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
               if pruefen(v))


def abbrechen(v):
    if v.status == 'aktiv':
        v.status = 'abgebrochen'
        v.save(update_fields=['status'])
        _raten_pendenzen(v, alle=True)
