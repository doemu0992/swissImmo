"""Go-Live-Härtetest, Schritt 1: der komplette Lebenszyklus über alle Module.

Eigentümer → Liegenschaft mit zwei Wohnungen → Vertrag (Wohnung A) → Kaution →
erste Mietzinsrechnung → Schadenmeldung mit Handwerker → ausserterminliche
Kündigung → Abnahme → Kautionsauflösung mit Reparaturabzug → Archivierung.

Der Test fährt über die echten Routen (Client, eingeloggter Verwalter), nicht
über Service-Funktionen: Ein Datenstrom, der nur im Service hält und in der
View bricht, soll hier auffallen.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _team_user, _test_organisation


class LebenszyklusTests(TestCase):

    def setUp(self):
        from finance.booking import ensure_kontenplan
        self.org = _test_organisation()
        ensure_kontenplan(self.org)
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))
        self.heute = date.today()

    def _post(self, url, daten=None, **kw):
        return self.c.post(url, daten or {}, secure=True, **kw)

    def test_vom_eigentuemer_bis_zur_archivierung(self):
        from crm.models import Eigentuemer, Handwerker
        from finance.models import Buchung, DebitorenRechnung
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Abnahmeprotokoll, Kuendigung, Mietvertrag
        from tickets.models import HandwerkerAuftrag, SchadenMeldung

        # 1. Eigentümer, Liegenschaft, zwei Wohnungen ------------------------
        eig = Eigentuemer.objects.create(firma_oder_name='Eva Eigner', email='eva@example.ch')
        lg = Liegenschaft.objects.create(
            strasse='Lebensweg 7', plz='8000', ort='Zürich', eigentuemer=eig,
            organisation=self.org, versicherungswert=Decimal('2000000'))
        a = Einheit.objects.create(liegenschaft=lg, bezeichnung='Wohnung A', typ='whg',
                                   nettomiete_aktuell=Decimal('1800'), nebenkosten_aktuell=Decimal('250'))
        b = Einheit.objects.create(liegenschaft=lg, bezeichnung='Wohnung B', typ='whg',
                                   nettomiete_aktuell=Decimal('1600'), nebenkosten_aktuell=Decimal('220'))
        self.assertEqual(lg.einheiten.count(), 2)

        # 2. Vermietung von A: Vertrag über den Assistenten ------------------
        beginn = self.heute.replace(day=1)
        r = self._post('/neu/vertraege/neu/speichern/', {
            'einheit_id': a.id, 'mieter_typ': 'person', 'anrede': 'Herr',
            'vorname': 'Max', 'nachname': 'Mieter', 'm_email': 'max@example.ch',
            'm_strasse': 'Alt 1', 'm_plz': '8001', 'm_ort': 'Zürich',
            'beginn': beginn.isoformat(), 'netto_mietzins': '1800', 'nebenkosten': '250',
            'kautions_betrag': '5400',
        })
        self.assertIn(r.status_code, (200, 302), r.content[:300])
        v = Mietvertrag.objects.get(einheit=a)
        self.assertEqual(v.mieter.nachname, 'Mieter')
        self.assertEqual(v.kautions_betrag, Decimal('5400'))
        r = self._post(f'/neu/vertraege/{v.id}/status/', {'status': 'aktiv'})
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

        # Vertragsdokument (PDF) lässt sich erzeugen
        r = self.c.get(f'/vertrag/{v.id}/pdf/', secure=True)
        self.assertEqual(r.status_code, 200, r.content[:300])

        # Kaution: Einzahlung auf Sperrkonto, bilanziert
        r = self._post(f'/neu/vertraege/{v.id}/kaution/', {
            'aktion': 'einzahlung', 'einbezahlt_am': self.heute.isoformat(),
            'kautions_konto': 'CH9300762011623852957'})
        v.refresh_from_db()
        self.assertIsNotNone(v.kautions_einbezahlt_am)
        self.assertTrue(Buchung.objects.filter(beleg_text__icontains='Kaution').exists(),
                        'Kautionseinzahlung erzeugt keine Buchung.')

        # 3. Erste Mietzinsrechnung (Sollstellung) ---------------------------
        r = self._post('/neu/sollstellung/starten/', {
            'jahr': self.heute.year, 'monat': self.heute.month})
        self.assertIn(r.status_code, (200, 302))
        rechnungen = DebitorenRechnung.objects.filter(vertrag=v)
        self.assertTrue(rechnungen.exists(), 'Sollstellung erzeugt keine Rechnung.')
        rechnung = rechnungen.first()
        self.assertEqual(rechnung.betrag, Decimal('2050.00'))
        self.assertEqual(rechnung.liegenschaft_id, lg.id)
        self.assertTrue(rechnung.buchungen.exists(), 'Rechnung ohne Hauptbuch-Buchung.')

        # 4. Mangel: Wasserschaden → Ticket → Handwerker ---------------------
        hw = Handwerker.objects.create(firma='Sanitär Flink AG', email='flink@example.ch', branche='sanitaer')
        r = self._post('/neu/schaeden/neu/', {
            'titel': 'Wasserschaden Bad', 'beschreibung': 'Leitung tropft',
            'liegenschaft_id': lg.id, 'einheit_id': a.id, 'kategorie': 'wasser',
            'melder_vorname': 'Max', 'melder_nachname': 'Mieter', 'prioritaet': 'hoch'})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.objects.get(titel='Wasserschaden Bad')
        self.assertEqual(t.betroffene_einheit_id, a.id)
        r = self._post(f'/neu/schaeden/{t.id}/auftrag/', {
            'handwerker_id': hw.id, 'auftragstext': 'Leitung im Bad reparieren'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(HandwerkerAuftrag.objects.filter(ticket=t, handwerker=hw).exists())

        # 5. Ausserterminliche Kündigung durch den Mieter --------------------
        auszug = self.heute + timedelta(days=45)
        r = self._post(f'/neu/vertraege/{v.id}/kuendigen/', {
            'absender': 'mieter', 'eingang_datum': self.heute.isoformat(), 'bestaetigen': 'on',
            'ausserordentlich': 'on', 'ausserordentlich_grund': 'Versetzung',
            'gewuenschtes_ende': auszug.isoformat()})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt', 'Vertrag nicht auf «gekündigt» gesetzt.')
        self.assertTrue(Kuendigung.objects.filter(vertrag=v).exists())

        # Abnahme mit Mangel (Reparaturkosten 800)
        r = self._post(f'/neu/vertraege/{v.id}/abnahme/neu/', {
            'typ': 'auszug', 'datum': auszug.isoformat(), 'mieter_anwesend': 'on',
            'allgemein_zustand': 'gut', 'abgeschlossen': 'on',
            'm_raum': ['Bad'], 'm_beschreibung': ['Wasserschaden Fliesen'],
            'm_verursacher': ['mieter'], 'm_kosten': ['800'], 'm_ausstattung': [''], 'm_neuwert': ['']})
        self.assertEqual(r.status_code, 302, r.content[:300])
        prot = Abnahmeprotokoll.objects.get(vertrag=v)
        self.assertEqual(prot.maengel.count(), 1)

        # Schlussabrechnung: Kaution 5400 − Reparatur 800
        r = self._post(f'/neu/vertraege/{v.id}/schlussabrechnung/', {
            'aktion': 'buchen', 'auszug_datum': auszug.isoformat(), 'kaution_verrechnen': 'on',
            'pos_text': ['Reparatur Bad'], 'pos_betrag': ['800'], 'pos_richtung': ['zulasten'],
            'pos_mwst': ['0']})
        self.assertIn(r.status_code, (200, 302), r.content[:300])
        nach = Buchung.objects.filter(beleg_text__contains=f'[V{v.pk}]')
        self.assertTrue(nach.exists(), 'Schlussabrechnung hat nichts gebucht.')
        # Kautionskonto 2010 muss auf null stehen; Rückzahlung = 5400 − 2050 − 800
        from django.db.models import Sum
        haben = Buchung.objects.filter(haben_konto__nummer='2010').aggregate(s=Sum('betrag'))['s'] or 0
        soll = Buchung.objects.filter(soll_konto__nummer='2010').aggregate(s=Sum('betrag'))['s'] or 0
        self.assertEqual(haben - soll, 0, 'Kautionsverbindlichkeit (2010) nicht ausgeglichen.')
        self.assertTrue(Buchung.objects.filter(soll_konto__nummer='2010', haben_konto__nummer='1020',
                                               betrag=Decimal('2550.00')).exists())

        # Archivierung
        r = self._post(f'/neu/vertraege/{v.id}/status/', {'status': 'archiviert'})
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')
        self.assertFalse(v.aktiv)

        # Datenströme: alles hängt noch am Vertrag / an der Liegenschaft
        t.refresh_from_db()
        self.assertEqual(t.liegenschaft_id, lg.id)
        rechnung.refresh_from_db()
        self.assertEqual(rechnung.vertrag_id, v.id)
        # Detailseiten laden ohne Fehler
        for url in (f'/neu/vertraege/{v.id}/', f'/neu/personen/{v.mieter_id}/',
                    f'/neu/liegenschaften/{lg.id}/', f'/neu/schaeden/{t.id}/',
                    f'/neu/abnahme/{prot.id}/', f'/neu/objekte/{a.id}/', f'/neu/objekte/{b.id}/'):
            self.assertEqual(self.c.get(url, secure=True).status_code, 200, url)
