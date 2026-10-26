"""Leerstands-Cockpit und Team & Auslastung (UI-Audit 26.10.2026).

Geprüft wird, was die Seiten behaupten: Leer ist, was die Objektliste leer
nennt; ein Nachmieter nimmt die Einheit aus der Arbeitsliste; der Ausfall
rechnet mit dem Netto-Mietzins; ohne Mietzins ist der nächste Schritt «Mietzins
festlegen». Im Team zählt jede Person ihre eigenen Tickets und Fälle, Überfälliges
doppelt, und was niemandem gehört, steht getrennt. «Team» ist der Verwaltung
vorbehalten und erscheint für andere nicht in der Navigation.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation


class _Basis(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.verwalter = _team_user('Verwalter')
        self.c = Client()
        self.c.force_login(self.verwalter)
        self.heute = timezone.localdate()

    def neue_einheit(self, name, miete='1800', typ='whg', **kw):
        from portfolio.models import Einheit
        return Einheit.objects.create(liegenschaft=self.lg, bezeichnung=name, typ=typ,
                                      nettomiete_aktuell=Decimal(miete), **kw)

    def neuer_vertrag(self, einheit, beginn, ende=None, status='aktiv'):
        from rentals.models import Mietvertrag
        return Mietvertrag.objects.create(mieter=self.mieter, einheit=einheit, beginn=beginn, ende=ende,
                                          netto_mietzins=einheit.nettomiete_aktuell or Decimal('0'),
                                          nebenkosten=Decimal('0'), status=status)


class LeerstandCockpitTests(_Basis):
    def test_leer_bald_frei_und_versorgt_werden_richtig_eingeordnet(self):
        from faelle.leerstand_cockpit import cockpit
        from portfolio.models import Einheit
        lang = self.neue_einheit('Lange leer', '2000')
        self.neuer_vertrag(lang, date(2020, 1, 1), self.heute - timedelta(days=120), status='archiviert')
        frisch = self.neue_einheit('Frisch leer', '1000')
        self.neuer_vertrag(frisch, date(2020, 1, 1), self.heute - timedelta(days=10), status='archiviert')
        bald = self.neue_einheit('Wird frei', '1500')
        self.neuer_vertrag(bald, date(2020, 1, 1), self.heute + timedelta(days=40), status='gekuendigt')
        versorgt = self.neue_einheit('Mit Nachmieter', '1700')
        self.neuer_vertrag(versorgt, self.heute + timedelta(days=20), status='aktiv')
        c = cockpit(Einheit.objects.all(), self.heute)
        namen = {z['e'].bezeichnung: z for z in c['zeilen']}
        self.assertEqual(set(namen), {'Lange leer', 'Frisch leer', 'Wird frei'})
        self.assertEqual([z['e'].bezeichnung for z in c['versorgt']], ['Mit Nachmieter'])
        self.assertEqual(namen['Lange leer']['stufe'], 'crit')
        self.assertEqual(namen['Frisch leer']['stufe'], 'warn')
        self.assertEqual(namen['Wird frei']['zustand'], 'bald')
        self.assertEqual(namen['Wird frei']['tage_bis_frei'], 41)
        # Der lange Leerstand steht oben
        self.assertEqual(c['zeilen'][0]['e'].bezeichnung, 'Lange leer')
        self.assertEqual(c['n_leer'], 2)
        self.assertEqual(c['ausfall_monat'], Decimal('3000'))
        self.assertEqual(c['ausfall_bald'], Decimal('1500'))
        # 120 Tage × 2000 / 30
        self.assertEqual(namen['Lange leer']['ausfall_bisher'], Decimal('8000'))
        # Die vermietete Wohnung aus dem Grundbestand zählt nicht
        self.assertNotIn('3.5 Zi', namen)

    def test_ohne_mietzins_ist_der_naechste_schritt_der_preis(self):
        from faelle.leerstand_cockpit import cockpit
        from portfolio.models import Einheit
        self.neue_einheit('Ohne Preis', miete='0')
        z = cockpit(Einheit.objects.filter(bezeichnung='Ohne Preis'), self.heute)['zeilen'][0]
        self.assertEqual(z['schritt']['text'], 'Mietzins festlegen')
        self.assertEqual(z['stufe'], 'crit')
        self.assertIsNone(z['tage'])   # noch nie vermietet

    def test_zusage_fuehrt_zum_vertrag(self):
        from faelle.leerstand_cockpit import cockpit
        from mietprozess.models import Mietbewerbung
        from portfolio.models import Einheit
        e = self.neue_einheit('Mit Zusage', '1600', zur_ausschreibung=True)
        Mietbewerbung.objects.create(einheit=e, status='zugesagt', vorname='Lea', nachname='Frei', email='l@example.ch',
                                     geburtsdatum=date(1990, 1, 1), mobilnummer='079', beruf='x', einkommen_jahr='80000')
        z = cockpit(Einheit.objects.filter(pk=e.pk), self.heute)['zeilen'][0]
        self.assertEqual(z['schritt']['url'], f'/neu/vertraege/neu/?einheit={e.id}')
        self.assertEqual(z['bewerbungen'], 1)

    def test_seite_filter_und_export(self):
        self.neue_einheit('Leer A', '1000')
        self.neue_einheit('PP 1', '120', typ='pp')
        r = self.c.get('/neu/leerstand/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Leer A')
        self.assertContains(r, 'PP 1')
        r = self.c.get('/neu/leerstand/?typ=wohnen')
        self.assertContains(r, 'Leer A')
        self.assertNotContains(r, 'PP 1')
        csv = self.c.get('/neu/leerstand/?export=csv').content.decode('utf-8-sig')
        self.assertIn('Leer A', csv)
        self.assertIn('Mietzins', csv.splitlines()[0])

    def test_lesezugriff_sieht_die_seite(self):
        c = Client()
        c.force_login(_team_user('Lesezugriff'))
        self.assertEqual(c.get('/neu/leerstand/').status_code, 200)


class TeamAuslastungTests(_Basis):
    def setUp(self):
        super().setUp()
        self.sb = _team_user('Sachbearbeiter')
        self.sb.first_name, self.sb.last_name = 'Sara', 'Beck'
        self.sb.save()

    def ticket(self, wer=None, faellig=None, status='neu', alter=0):
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.create(liegenschaft=self.lg, titel='T', beschreibung='x', status=status,
                                          zugewiesen_an=wer, faellig_bis=faellig)
        if alter:
            SchadenMeldung.objects.filter(pk=t.pk).update(erstellt_am=timezone.now() - timedelta(days=alter))
        return t

    def test_last_je_person_und_niemand(self):
        from faelle.models import Fall, Fallart
        from faelle.team_auslastung import auslastung
        self.ticket(self.sb)
        self.ticket(self.sb, faellig=self.heute - timedelta(days=2))   # überfällig
        self.ticket(self.verwalter)
        self.ticket(None)                                                 # niemand
        self.ticket(self.sb, status='erledigt')                           # zählt nicht
        art = Fallart.objects.create(schluessel='test', bezeichnung='Test')
        Fall.objects.create(fallart=art, betreff='F1', zustaendig=self.sb)
        a = auslastung(self.org, self.heute)
        z = {r['u'].pk: r for r in a['zeilen']}
        self.assertEqual(z[self.sb.pk]['tickets'], 2)
        self.assertEqual(z[self.sb.pk]['tickets_ueber'], 1)
        self.assertEqual(z[self.sb.pk]['faelle'], 1)
        self.assertEqual(z[self.sb.pk]['last'], 2 + 1 + 1)   # Überfälliges doppelt
        self.assertEqual(z[self.sb.pk]['stufe'], 'crit')
        self.assertEqual(z[self.verwalter.pk]['tickets'], 1)
        self.assertEqual(a['zeilen'][0]['u'].pk, self.sb.pk)      # die Höchstlast oben
        self.assertEqual(z[self.sb.pk]['anteil'], 100)
        self.assertEqual(a['niemand']['tickets'], 1)
        self.assertEqual(a['offen_tickets'], 4)

    def test_alter_der_offenen_tickets(self):
        from faelle.team_auslastung import auslastung
        self.ticket(alter=2)
        self.ticket(alter=20)
        self.ticket(alter=120)
        stufen = {s['label']: s['n'] for s in auslastung(self.org, self.heute)['alter']}
        self.assertEqual(stufen, {'0–7': 1, '8–30': 1, '31–90': 0, '> 90': 1})

    def test_abwesenheit_wird_gezeigt(self):
        from faelle.termin_models import Abwesenheit
        from faelle.team_auslastung import auslastung
        Abwesenheit.objects.create(benutzer=self.sb, von=self.heute, bis=self.heute + timedelta(days=3),
                                   grund=Abwesenheit.FERIEN, vertreten_durch=self.verwalter)
        a = auslastung(self.org, self.heute)
        z = {r['u'].pk: r for r in a['zeilen']}
        self.assertIsNotNone(z[self.sb.pk]['abwesend'])
        self.assertIsNone(z[self.verwalter.pk]['abwesend'])
        self.assertEqual(a['abwesend_n'], 1)

    def test_seite_nur_fuer_die_verwaltung_und_nur_dort_im_menue(self):
        self.ticket(self.sb)
        r = self.c.get('/neu/team/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sara Beck')
        c = Client()
        c.force_login(self.sb)
        self.assertEqual(c.get('/neu/team/').status_code, 403)
        # Der Reiter «Team & Auslastung» erscheint für den Sachbearbeiter nicht
        berichte = c.get('/neu/berichte/').content.decode()
        self.assertNotIn('href="/neu/team/', berichte)
        self.assertIn('href="/neu/team/', self.c.get('/neu/berichte/').content.decode())

    def test_filter_niemand_in_der_ticketliste(self):
        self.ticket(None)
        t2 = self.ticket(self.sb)
        t2.titel = 'Zugeteiltes Ticket'
        t2.save()
        r = self.c.get('/neu/schaeden/?zustaendig=niemand&sicht=alle')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Zugeteiltes Ticket')
