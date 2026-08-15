"""Gemeinsame Grundlage aller Testmodule in core/tests/.

Bis Etappe 1 war das der Kopfbereich von core/tests.py — 51 Zeilen vor
222 Testklassen. Die Klassen liegen jetzt nach Fachgebiet in eigenen
Modulen; was sie alle brauchen, steht hier.

Unveraendert uebernommen.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client, RequestFactory
from django.contrib import admin
from unittest import skipUnless

try:                      # noqa: SIM105 — bewusst als Schalter, nicht als Import
    import zxingcpp as _zxingcpp     # noqa: F401
    ZXING_DA = True
except ImportError:
    ZXING_DA = False

# Warum ein Schalter und kein harter Import (P0.8): `zxing-cpp` steht zwar in
# requirements.txt, ist aber ein Wheel mit nativem Code — in einer Umgebung
# ohne vollstaendigen Install fehlt es. finance/utils.py faengt das korrekt ab
# und faellt still auf die Textsuche zurueck. Die beiden QR-Tests schlugen dann
# mit `methode == 'leer'` statt `'qr'` fehl und sahen wie ein FACHFEHLER aus,
# obwohl nur ein Paket fehlte. Unter `--parallel` verdeckte zusaetzlich ein
# Pickle-Fehler des Prozesspools die Meldung ganz.
from django.contrib.auth.models import User, Group

from crm.models import Mieter, Eigentuemer, Verwaltung
from portfolio.models import Liegenschaft, Einheit, Wartungsfrist
from rentals.models import Mietvertrag


def _team_user(rolle='Verwaltung'):
    grp, _ = Group.objects.get_or_create(name=rolle)
    u = User.objects.create_user(username=f'team_{rolle}', password='x')
    u.groups.add(grp)
    return u


def _basis_objekte():
    lg = Liegenschaft.objects.create(strasse='Teststrasse 1', plz='8000', ort='Zürich',
                                     versicherungswert=Decimal('1000000'))
    e = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi', typ='wohnung',
                               nettomiete_aktuell=Decimal('1500'), nebenkosten_aktuell=Decimal('200'))
    m = Mieter.objects.create(typ='person', vorname='Hans', nachname='Muster',
                              email='hans@example.ch', strasse='Seeweg 3', plz='8000', ort='Zürich')
    v = Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                                   netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                                   status='aktiv', kautions_betrag=Decimal('4500'))
    return lg, e, m, v


# Vier weitere Helfer, die in der alten core/tests.py NICHT im Kopfbereich
# standen, sondern auf Modulebene MITTEN zwischen den Klassen — und die
# trotzdem quer durch die Datei benutzt wurden (_seed_konten an 23 Stellen).
# Beim Herausloesen der Klassenkoerper fielen sie zuerst durch; Ruffs F821
# hat sie gemeldet. Unveraendert uebernommen.

def _seed_konten():
    from finance.models import Buchungskonto
    for nr, bez, typ in [('1020', 'Bank', 'bilanz'), ('1100', 'Debitoren', 'bilanz'),
                         ('3000', 'Mietertrag', 'ertrag'), ('3020', 'NK-Akonto', 'ertrag')]:
        Buchungskonto.objects.get_or_create(nummer=nr, defaults={'bezeichnung': bez, 'typ': typ})


_P3_CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.04">
 <BkToCstmrStmt><Stmt>
  <Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>
  <FrToDt><FrDtTm>2024-03-01T00:00:00</FrDtTm><ToDtTm>2024-03-31T00:00:00</ToDtTm></FrToDt>
  <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1000.00</Amt>
       <CdtDbtInd>CRDT</CdtDbtInd></Bal>
  <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1450.00</Amt>
       <CdtDbtInd>CRDT</CdtDbtInd></Bal>
  <Ntry>
   <Amt Ccy="CHF">800.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <BookgDt><Dt>2024-03-05</Dt></BookgDt><ValDt><Dt>2024-03-04</Dt></ValDt>
   <NtryDtls><TxDtls>
     <Refs><AcctSvcrRef>P3-CRDT-1</AcctSvcrRef></Refs>
     <RltdPties><Dbtr><Nm>Hans Muster</Nm></Dbtr></RltdPties>
     <RmtInf><Ustrd>Miete Maerz</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
  <Ntry>
   <Amt Ccy="CHF">350.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2024-03-07</Dt></BookgDt><ValDt><Dt>2024-03-06</Dt></ValDt>
   <NtryDtls><TxDtls>
     <Refs><AcctSvcrRef>P3-DBIT-1</AcctSvcrRef></Refs>
     <RltdPties><Cdtr><Nm>Hauswartung AG</Nm></Cdtr></RltdPties>
     <RmtInf><Ustrd>Hauswartung Februar</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
 </Stmt></BkToCstmrStmt>
</Document>"""


def _sig_bytes():
    """Kleines PNG als Ersatz für einen echten Unterschriften-Scan."""
    import io as _io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 120), "white")
    d = ImageDraw.Draw(img)
    d.line([(20, 90), (90, 30), (150, 95), (220, 35), (300, 80), (370, 45)],
           fill="black", width=6)
    b = _io.BytesIO(); img.save(b, format="PNG")
    return b.getvalue()


def _heute():
    from django.utils import timezone
    return timezone.localdate()
