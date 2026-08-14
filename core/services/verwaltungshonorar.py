"""Verwaltungshonorar: Honorarsatz (%) × Mieterträge je Liegenschaft eines
Eigentümer für ein Geschäftsjahr. Gebucht wird Soll 4500 (Verwaltungshonorar,
Aufwand der Liegenschaft) / Haben Bank — das mindert das Eigentümer-Ergebnis
und die auszuzahlende Liquidität; die Bilanz bleibt ausgeglichen.

Buchhalterisch aus Eigentümersicht: das Honorar ist ein Aufwand der Liegenschaft.
Die Ertragsseite der Verwaltungsgesellschaft liegt ausserhalb dieser Bücher."""
from datetime import date
from decimal import Decimal


def _beleg_text(jahr, lg):
    return f"Verwaltungshonorar {jahr} — {lg.strasse}"


def honorar_vorschau(eigentuemer, jahr):
    """Berechnet je Liegenschaft das Honorar (ohne zu buchen) und ob es für das
    Jahr bereits verbucht ist. Gibt (zeilen, total, prozent) zurück."""
    from finance.models import Buchung, Buchungskonto
    from portfolio.models import Liegenschaft
    from django.db.models import Sum

    prozent = eigentuemer.honorar_prozent or Decimal('0.00')
    von, bis = date(jahr, 1, 1), date(jahr, 12, 31)
    # 3090 (Mietzinserlass/Rabatt, Ertragsminderung der Option-B-Bruttobuchung) mit
    # einbeziehen: dort ist (Haben−Soll) negativ und mindert den Ertrag → das Honorar
    # wird auf der tatsächlich vereinnahmten Miete berechnet, nicht auf der vollen
    # Referenzmiete inkl. erlassener Anteile.
    ertrag_konten = list(Buchungskonto.objects.filter(nummer__in=['3000', '3010', '3090']))

    # Abschlussbuchungen ausklammern: sie saldieren 3000/3010 per 31.12. gegen
    # 2970. Ohne den Ausschluss wäre die Honorarbasis nach dem Jahresabschluss
    # null und das Honorar verschwände (Audit).
    from core.services.jahresabschluss import abschluss_buchungen_q

    zeilen = []
    total = Decimal('0.00')
    for lg in Liegenschaft.objects.filter(eigentuemer=eigentuemer).order_by('strasse'):
        bqs = (Buchung.objects.filter(liegenschaft=lg, datum__gte=von, datum__lte=bis)
               .exclude(abschluss_buchungen_q()))
        mietertrag = Decimal('0.00')
        for k in ertrag_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            mietertrag += (h - s)
        # Basis nie negativ: Bei überwiegend erlassenen Perioden (Sanierung,
        # Leerstand mit Erlass) hätte die Zeile sonst «x % von −200» gezeigt und
        # ein negatives Honorar ausgewiesen (Audit).
        mietertrag = max(mietertrag, Decimal('0.00'))
        honorar = (mietertrag * prozent / Decimal('100')).quantize(Decimal('0.01'))
        # storniert_am mitprüfen: sonst sieht der Wächter das stornierte
        # ORIGINAL weiter und das Honorar liesse sich nach einer Korrektur
        # (falscher Satz) nie wieder buchen.
        bereits = Buchung.objects.filter(liegenschaft=lg, beleg_text=_beleg_text(jahr, lg),
                                         ist_storno=False,
                                         storniert_am__isnull=True).exists()
        zeilen.append({'lg': lg, 'mietertrag': mietertrag, 'honorar': honorar, 'gebucht': bereits})
        # Nur zählen, was auch gebucht wird (buche_honorar überspringt <= 0).
        # Sonst zeigte der Bestätigungsdialog eine andere Summe als die Buchung —
        # eine Liegenschaft mit negativem Ertrag (Erlassjahr) zog das Total nach
        # unten, ohne je gebucht zu werden (Audit).
        if not bereits and honorar > 0:
            total += honorar
    return zeilen, total, prozent


def buche_honorar(eigentuemer, jahr, *, gegen_nummer='2850', user=None):
    """Bucht das Verwaltungshonorar je Liegenschaft (idempotent — bereits für das
    Jahr gebuchte Liegenschaften werden übersprungen). Gibt (anzahl, summe) zurück.

    Gegenkonto ist das Eigentümer-Kontokorrent 2850 (Verbindlichkeit), NICHT die
    Bank: Zum Buchungszeitpunkt (31.12.) fliesst kein Geld — die frühere Buchung
    `4500 an 1020` liess den Banksaldo vom realen Kontoauszug abweichen
    (Audit-Befund W3). Die effektive Zahlung wird separat über das Kontokorrent
    ausgebucht."""
    from finance.booking import buche, konto

    zeilen, _total, _prozent = honorar_vorschau(eigentuemer, jahr)
    gegen = konto(gegen_nummer)
    anzahl = 0
    summe = Decimal('0.00')
    for z in zeilen:
        if z['gebucht'] or z['honorar'] <= 0:
            continue
        buche('4500', gegen, z['honorar'], _beleg_text(jahr, z['lg']),
              datum=date(jahr, 12, 31), liegenschaft=z['lg'], user=user)
        anzahl += 1
        summe += z['honorar']
    return anzahl, summe
