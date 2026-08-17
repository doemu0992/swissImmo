"""Regressionstest: KPI-Summen der optimierten View gegen eine unabhaengige
Python-Referenzrechnung (die alte Logik), inkl. Teilzahlungen und Storni."""
from decimal import Decimal
from datetime import date
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
import core.tests_perf as _P
from core.tests_perf import _seed


class VerifyDebitoren(TestCase):
    def test_kpis_identisch_zur_referenz(self):
        from finance.models import DebitorenRechnung, Zahlungseingang
        _P.PERF_SKALA, _P.EINHEITEN_PRO_LG, _P.MONATE = 2, 4, 6
        _seed()
        u = User.objects.create_user(username='v', password='x')
        u.groups.add(Group.objects.get_or_create(name='Verwalter')[0])
        _mitgliedschaft(u)

        # Realistische Vielfalt erzeugen: Teilzahlungen, Vollzahlung, Storno,
        # stornierte Zahlung (darf NICHT zaehlen), ueberfaellig und zukuenftig.
        offene = list(DebitorenRechnung.objects.filter(status='offen')[:40])
        for i, r in enumerate(offene):
            if i % 4 == 0:
                Zahlungseingang.objects.create(debitoren_rechnung=r, vertrag=r.vertrag,
                                               betrag=Decimal('700'), status='verbucht',
                                               erstellt_von=u)
                r.status = 'teilbezahlt'; r.save()
            elif i % 4 == 1:
                Zahlungseingang.objects.create(debitoren_rechnung=r, vertrag=r.vertrag,
                                               betrag=Decimal('500'), status='storniert',
                                               erstellt_von=u)
            elif i % 4 == 2:
                r.status = 'storniert'; r.save()
            elif i % 4 == 3:
                r.faellig_am = None; r.datum = date(2099, 1, 1); r.save()

        # --- Referenz: exakt die alte Python-Logik -------------------------
        heute = __import__('django.utils.timezone', fromlist=['x']).localdate()
        ref_betrag = Decimal('0.00'); ref_offen = Decimal('0.00')
        ref_n_offen = 0; ref_n_ueber = 0
        qs = (DebitorenRechnung.objects
              .select_related('vertrag__einheit__liegenschaft__eigentuemer', 'liegenschaft__eigentuemer')
              .prefetch_related('zahlungseingaenge'))
        for r in qs:
            offen = r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')
            faellig = r.faellig_am or r.datum
            if r.status != 'storniert':
                ref_betrag += (r.betrag or Decimal('0.00'))
            if r.status in ('offen', 'teilbezahlt'):
                ref_offen += offen
                ref_n_offen += 1
                if faellig < heute:
                    ref_n_ueber += 1

        c = Client(); c.force_login(u)
        ctx = c.get('/neu/debitoren/', secure=True).context
        print(f"\n{'Kennzahl':<22}{'Referenz':>16}{'View':>16}")
        for name, ref, got in [
            ('total_betrag', ref_betrag, ctx['total_betrag']),
            ('total_offen', ref_offen, ctx['total_offen']),
            ('anzahl_offen', ref_n_offen, ctx['anzahl_offen']),
            ('anzahl_ueberfaellig', ref_n_ueber, ctx['anzahl_ueberfaellig']),
            ('rows_gesamt', qs.count(), ctx['rows_gesamt']),
        ]:
            print(f'{name:<22}{str(ref):>16}{str(got):>16}')
            self.assertEqual(Decimal(str(ref)), Decimal(str(got)), name)

    def test_reihenfolge_und_seiten_vollstaendig(self):
        """Jede Rechnung erscheint genau einmal ueber alle Seiten, offene zuerst."""
        from finance.models import DebitorenRechnung
        _P.PERF_SKALA, _P.EINHEITEN_PRO_LG, _P.MONATE = 2, 4, 6
        _seed()
        u = User.objects.create_user(username='v2', password='x')
        u.groups.add(Group.objects.get_or_create(name='Verwalter')[0])
        _mitgliedschaft(u)
        c = Client(); c.force_login(u)
        gesamt = DebitorenRechnung.objects.count()
        gesehen, reihenfolge = [], []
        for s in range(1, (gesamt // 50) + 2):
            # Ueber `page` iterieren, nicht ueber `rows`: das Template macht es
            # genauso ({% for row in page %}). Ein Paginator, dessen object_list
            # nicht die echten Zeilen traegt, faellt nur hier auf.
            seite_obj = c.get(f'/neu/debitoren/?seite={s}', secure=True).context['page']
            for row in seite_obj:
                gesehen.append(row['r'].id)
                reihenfolge.append(row['r'].status in ('offen', 'teilbezahlt'))
        self.assertEqual(len(gesehen), gesamt, 'Positionen gehen verloren oder doppeln')
        self.assertEqual(len(set(gesehen)), gesamt, 'Doppelte Positionen ueber die Seiten')
        # offene Posten bilden einen zusammenhaengenden Block am Anfang
        self.assertEqual(reihenfolge, sorted(reihenfolge, reverse=True),
                         'Offene Posten stehen nicht geschlossen zuoberst')
        print(f'\n{gesamt} Positionen ueber {len(range(1, (gesamt//50)+2))} Seiten: '
              f'vollstaendig, ueberschneidungsfrei, offene zuoberst.')
