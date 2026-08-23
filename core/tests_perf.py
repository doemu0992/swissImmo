"""Performance-Harness: misst Query-Zahl und Laufzeit der /neu/-Seiten.

Kein Korrektheits-Test — ein Messwerkzeug. N+1-Probleme werden erst bei
Volumen sichtbar: mit einer Handvoll Datensätze sieht jede Seite schnell aus.
Deshalb seedet das Harness ein realistisches Portfolio und meldet pro Route
Queries + Dauer, sortiert nach Queries.

Aufruf:
    python manage.py test core.tests_perf -v0

Die Seitengrösse steuert PERF_SKALA (Liegenschaften). Standard 12 LG × 12
Einheiten = 144 Objekte/Verträge, 12 Monate Sollstellung.
"""
import os
import time
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from django.contrib.auth.models import Group

User = get_user_model()

def _mitgliedschaft(benutzer, rolle='Verwalter'):
    """Rolle je Organisation (Etappe 4.3).

    Diese drei Perf-Module bauen ihren Benutzer selbst, statt `_team_user` aus
    `core/tests/_helfer.py` zu nehmen. Seit `hat_rolle()` die Mitgliedschaft
    liest, reicht die Django-Gruppe nicht mehr — ohne diese Zeilen antwortet
    jede gemessene View mit 403, und die Messung misst die Fehlerseite.
    """
    from crm.models import Mitgliedschaft, Organisation
    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        organisation = Organisation.objects.create(
            firma='Perf AG', strasse='Perfstrasse 1', plz='8000', ort='Zürich')
    # `alle_organisationen`: Die Mitgliedschaft wird angelegt, BEVOR ein
    # Mandantenkontext existiert — sie ist ja gerade das, woraus die
    # Middleware ihn später ableitet. Über `objects` wäre das ein Henne-Ei
    # und seit Etappe 6.2 ein OrganisationsFehler.
    Mitgliedschaft.alle_organisationen.get_or_create(
        benutzer=benutzer, organisation=organisation, defaults={'rolle': rolle})
    # Kontext fuer die Abfragen des Tests selbst setzen — dieselbe Rolle, die
    # `_helfer._test_organisation()` fuer die uebrigen Tests spielt. In den
    # gemessenen Views setzt ihn die Middleware je Anfrage; was der Test
    # DANEBEN abfragt (`DebitorenRechnung.objects.count()` als Referenzwert)
    # laeuft ohne Anfrage und braucht ihn hier.
    #
    # NICHT als allgemeine Bequemlichkeit verstehen: Genau dieser beilaeufig
    # gesetzte Kontext hat am 17.08.2026 acht kaputte Scheduler-Befehle
    # verdeckt. Wer einen Management-Command testet, benutzt `MandantenFixture`
    # und setzt NICHTS.
    from core.tenancy import setze_organisation
    setze_organisation(organisation)
    return organisation

from django.test import Client, TestCase
from unittest import skipUnless
from django.test.utils import CaptureQueriesContext
from django.db import connection

from portfolio.models import Liegenschaft, Einheit
from crm.models import Mieter
from rentals.models import Mietvertrag

PERF_SKALA = 12          # Liegenschaften
EINHEITEN_PRO_LG = 12    # Objekte je Liegenschaft
MONATE = 12              # Monate Sollstellung

# Parameterlose GET-Seiten der /neu/-Oberfläche (Listen + Cockpits).
ROUTEN = [
    '/neu/', '/neu/pendenzen/', '/neu/fristen/',
    '/neu/liegenschaften/', '/neu/objekte/', '/neu/mieterspiegel/',
    '/neu/personen/', '/neu/vertraege/', '/neu/mieterwechsel/',
    '/neu/vermarktung/', '/neu/bewerbungen/',
    '/neu/finanzen/', '/neu/debitoren/', '/neu/mieterkonten/',
    '/neu/mahnwesen/', '/neu/mahnwesen/aging/', '/neu/sollstellung/',
    '/neu/kautionen/', '/neu/kreditoren/', '/neu/zahllauf/',
    '/neu/bankabgleich/', '/neu/bankkonten/', '/neu/buchhaltung/',
    '/neu/kontenplan/', '/neu/nebenkosten/', '/neu/anlagen/',
    '/neu/schaeden/', '/neu/ersatzplanung/', '/neu/dienstleister/',
    '/neu/berichte/', '/neu/auswertung/', '/neu/dokumente/',
]


def _seed():
    """Realistisches Portfolio: LG → Einheiten → Mieter → Verträge → Rechnungen.

    MANDANTENKONTEXT UND `bulk_create` — zwei Dinge, die hier zusammenkommen:

    Seit Etappe 6.2 wirft `Model.objects` ohne Kontext, und ein Test hat
    keinen, solange er ihn nicht setzt. Und `bulk_create` umgeht `save()`,
    also auch die Stelle, die die Organisation aus dem Kontext einträgt — sie
    muss darum an JEDEM Objekt von Hand stehen. Fehlt eines von beidem,
    scheitert das Seeding, und das Messwerkzeug misst nichts.
    """
    from finance.models import Buchungskonto, DebitorenRechnung

    from core.tenancy import organisation_kontext
    from crm.models import Organisation

    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        organisation = Organisation.objects.create(
            firma='Perf AG', strasse='Perfstrasse 1', plz='8000', ort='Zürich')
    with organisation_kontext(organisation):
        return _seed_im_kontext(organisation)


def _seed_im_kontext(organisation):
    from finance.models import Buchungskonto, DebitorenRechnung
    for nr, bez, typ in [('1020', 'Bank', 'bilanz'), ('1100', 'Debitoren', 'bilanz'),
                         ('1190', 'Durchlauf', 'bilanz'), ('2030', 'Guthaben Mieter', 'bilanz'),
                         ('3000', 'Mietertrag', 'ertrag'), ('3020', 'NK-Akonto', 'ertrag')]:
        Buchungskonto.objects.get_or_create(nummer=nr, defaults={'bezeichnung': bez, 'typ': typ})

    lgs = [Liegenschaft(strasse=f'Teststrasse {i}', plz='4500', ort='Solothurn',
                        versicherungswert=Decimal('2450000'), organisation=organisation)
           for i in range(1, PERF_SKALA + 1)]
    Liegenschaft.objects.bulk_create(lgs)
    lgs = list(Liegenschaft.objects.all())

    einheiten, mieter = [], []
    for lg in lgs:
        for j in range(1, EINHEITEN_PRO_LG + 1):
            einheiten.append(Einheit(liegenschaft=lg, bezeichnung=f'Whg {j}', typ='whg',
                                     nettomiete_aktuell=Decimal('1500'),
                                     nebenkosten_aktuell=Decimal('200'),
                                     organisation=organisation))
    Einheit.objects.bulk_create(einheiten)
    einheiten = list(Einheit.objects.all())

    for k in range(len(einheiten)):
        mieter.append(Mieter(typ='person', vorname=f'Vorname{k}', nachname=f'Nachname{k}',
                             email=f'm{k}@example.ch', strasse='Seeweg 3',
                             plz='4500', ort='Solothurn', organisation=organisation))
    Mieter.objects.bulk_create(mieter)
    mieter = list(Mieter.objects.all())

    vertraege = [Mietvertrag(mieter=m, einheit=e, beginn=date(2024, 1, 1),
                             netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'),
                             status='aktiv', kautions_betrag=Decimal('4500'),
                             organisation=organisation)
                 for e, m in zip(einheiten, mieter)]
    Mietvertrag.objects.bulk_create(vertraege)
    vertraege = list(Mietvertrag.objects.all())

    # Sollstellung über MONATE Monate — der Datenberg, an dem Debitoren,
    # Mahnwesen und Mieterkonten tatsächlich rechnen.
    rechnungen = []
    for v in vertraege:
        for mo in range(MONATE):
            jahr, monat = 2024 + mo // 12, mo % 12 + 1     # trägt über Jahresgrenzen
            rechnungen.append(DebitorenRechnung(
                vertrag=v, titel=f'Miete & NK {monat:02d}/{jahr}', betrag=Decimal('1700'),
                datum=date(jahr, monat, 1), faellig_am=date(jahr, monat, 1),
                status='bezahlt' if mo < MONATE - 2 else 'offen',
                organisation=organisation))
    DebitorenRechnung.objects.bulk_create(rechnungen, batch_size=500)
    return lgs, einheiten, vertraege


@skipUnless(os.environ.get("PERF"), "Messwerkzeug — mit PERF=1 starten")
class PerfHarness(TestCase):
    """Misst jede Route einmal und druckt einen sortierten Bericht."""

    def test_profil_neu_seiten(self):
        lgs, einheiten, vertraege = _seed()
        from finance.models import DebitorenRechnung
        grp, _ = Group.objects.get_or_create(name='Verwalter')
        u = User.objects.create_user(username='perf', password='x')
        u.groups.add(grp)
        _mitgliedschaft(u)
        c = Client()
        c.force_login(u)

        print(f"\n{'='*74}")
        print(f"PERF-PROFIL — {len(lgs)} Liegenschaften · {len(einheiten)} Objekte · "
              f"{len(vertraege)} Verträge · {DebitorenRechnung.objects.count()} Rechnungen")
        print(f"{'='*74}")

        ergebnisse = []
        for route in ROUTEN:
            try:
                with CaptureQueriesContext(connection) as ctx:
                    t0 = time.perf_counter()
                    resp = c.get(route, secure=True)
                    dauer = (time.perf_counter() - t0) * 1000
                n = len(ctx.captured_queries)
                # Doppelte SQL zählen: die Signatur von N+1.
                sqls = [q['sql'] for q in ctx.captured_queries]
                haeufigste = max(((sqls.count(s), s) for s in set(sqls)), default=(0, ''))
                ergebnisse.append((n, dauer, route, resp.status_code, haeufigste))
            except Exception as exc:                      # noqa: BLE001 — Messlauf
                ergebnisse.append((-1, 0.0, route, f'ERR {type(exc).__name__}: {exc}'[:60],
                                   (0, '')))

        ergebnisse.sort(reverse=True)
        print(f"\n{'Queries':>8} {'ms':>8}  {'Code':>5}  Route")
        print('-' * 74)
        for n, dauer, route, code, _h in ergebnisse:
            flag = '  ⚠' if n >= 60 else ''
            print(f'{n:>8} {dauer:>8.0f}  {str(code):>5}  {route}{flag}')

        print(f"\n{'-'*74}\nTOP-WIEDERHOLUNGEN (N+1-Signatur: dieselbe SQL vielfach)\n{'-'*74}")
        for n, _d, route, _c, (anzahl, sql) in ergebnisse[:10]:
            if anzahl >= 5:
                print(f'\n{route}  —  {anzahl}× dieselbe Abfrage (von {n})')
                print(f'   {sql[:150]}')
