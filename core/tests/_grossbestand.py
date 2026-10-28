"""Grosser Bestand für Skalierungstests (Etappe 2, SICH-09).

Ein Test auf die Abfragezahl ist nur etwas wert, wenn der Bestand gross genug
ist, dass eine Abfrage je Zeile auffällt. Der Bestand hier wächst über
`liegenschaften` × `einheiten_je`: je Einheit ein Mieter, ein aktiver Vertrag,
eine überfällige Miete (mit Teilzahlung) und, bei jeder zweiten, eine
erfasste Mahnung. Die Zahlen sind klein genug für einen Testlauf; die Aussage
des Tests ist nicht «schnell», sondern «die Abfragezahl hängt nicht von der
Zeilenzahl ab».
"""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone


def grossbestand_anlegen(organisation, liegenschaften, einheiten_je, ab=0):
    """Legt den Bestand IM Kontext der Organisation an. `ab` verschiebt die
    Nummern, damit zwei Aufrufe sich nicht in die Quere kommen."""
    from core.tenancy import organisation_kontext
    from crm.models import Eigentuemer, Mieter
    from finance.models import DebitorenRechnung, Mahnung, Zahlungseingang
    from portfolio.models import Einheit, Liegenschaft
    from mietprozess.models import Mietbewerbung
    from portfolio.models import Dokument as LgDokument
    from rentals.models import Mietvertrag
    from tickets.models import SchadenMeldung

    heute = timezone.localdate()
    with organisation_kontext(organisation):
        for li in range(ab, ab + liegenschaften):
            eig = Eigentuemer.objects.create(firma_oder_name=f'Eigentuemer {li}')
            lg = Liegenschaft.objects.create(
                strasse=f'Bestandsweg {li}', plz='8000', ort='Zürich', eigentuemer=eig,
                organisation=organisation, verkehrswert=Decimal('2000000'))
            for ei in range(einheiten_je):
                nr = li * 1000 + ei
                einheit = Einheit.objects.create(
                    liegenschaft=lg, bezeichnung=f'Whg {nr}', typ='whg',
                    nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
                mieter = Mieter.objects.create(
                    typ='person', vorname='Mieter', nachname=f'Nr{nr}',
                    email=f'm{nr}@example.ch')
                vertrag = Mietvertrag.objects.create(
                    mieter=mieter, einheit=einheit, beginn=date(2024, 1, 1),
                    netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'), status='aktiv')
                tage = 10 + (nr % 5) * 25          # verteilt über mehrere Mahnstufen
                rechnung = DebitorenRechnung.objects.create(
                    vertrag=vertrag, liegenschaft=lg, einheit=einheit, titel=f'Miete {nr}',
                    betrag=Decimal('1700'), datum=heute - timedelta(days=tage),
                    faellig_am=heute - timedelta(days=tage), status='offen')
                Zahlungseingang.objects.create(
                    vertrag=vertrag, betrag=Decimal('100'), datum_eingang=heute,
                    buchungs_monat=heute.replace(day=1), debitoren_rechnung=rechnung)
                # Eine bezahlte Vorrechnung, eine Meldung, ein Dokument, eine Bewerbung:
                # alles, was eine Seite je Einheit nachladen könnte.
                bezahlt = DebitorenRechnung.objects.create(
                    vertrag=vertrag, titel=f'Vormiete {nr}', betrag=Decimal('1700'),
                    datum=heute - timedelta(days=60), faellig_am=heute - timedelta(days=60),
                    status='bezahlt')
                Zahlungseingang.objects.create(
                    vertrag=vertrag, betrag=Decimal('1700'), datum_eingang=heute - timedelta(days=50),
                    buchungs_monat=heute.replace(day=1), debitoren_rechnung=bezahlt)
                if nr % 2 == 0:
                    SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=einheit,
                                                  titel=f'Schaden {nr}', beschreibung='x')
                LgDokument.objects.create(liegenschaft=lg, titel=f'Dok {nr}', datei='dok/x.pdf')
                Mietbewerbung.objects.create(einheit=einheit, vorname='B', nachname=f'W{nr}',
                                             geburtsdatum=date(1990, 1, 1), mobilnummer='079',
                                             email='b@example.ch', beruf='x', einkommen_jahr='90000')
                if nr % 2 == 0:
                    Mahnung.objects.create(debitoren_rechnung=rechnung, vertrag=vertrag,
                                           stufe=1, betrag_offen=Decimal('1600'))
