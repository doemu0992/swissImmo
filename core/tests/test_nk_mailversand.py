"""NK-Abrechnung per E-Mail an die Mieter.

Geprüft wird, was ein Mensch merken würde: Wer bekommt eine Mail mit PDF, wann gilt die
Abrechnung als zugestellt (Einsprachefrist), und was passiert, wenn eine Adresse fehlt oder
der Versand scheitert — dann darf die Zustellung NICHT als erfolgt festgehalten werden.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone

from core.tests._helfer import (Einheit, Liegenschaft, Mieter, Mietvertrag, _seed_konten, _team_user,
                                _test_organisation)


class _Basis(TestCase):
    def setUp(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        _seed_konten()
        self.org = _test_organisation()
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Mailweg 1', plz='8000', ort='Zürich',
                                              versicherungswert=Decimal('1'))
        self.mieter = []
        for i, adresse in enumerate(('a@example.ch', 'b@example.ch')):
            e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung=f'W{i}', typ='whg', flaeche_m2=Decimal('50'))
            m = Mieter.objects.create(typ='person', vorname='Vor', nachname=f'Nach{i}', email=adresse,
                                      strasse='x', plz='8000', ort='Zürich')
            Mietvertrag.objects.create(mieter=m, einheit=e, beginn=date(2024, 1, 1), status='aktiv',
                                       netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'))
            self.mieter.append(m)
        self.p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025', abgeschlossen=True,
                                                   start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        NebenkostenBeleg.objects.create(periode=self.p, kategorie='hauswart', text='Hauswart',
                                        betrag=Decimal('1000.00'), verteilschluessel='m2')
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))
        self.url = f'/neu/nebenkosten/{self.p.id}/mail/'
        mail.outbox = []


class Versand(_Basis):
    def test_jeder_mieter_bekommt_seine_abrechnung_als_pdf(self):
        self.c.post(self.url)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['a@example.ch', 'b@example.ch'])
        for m in mail.outbox:
            self.assertEqual(len(m.attachments), 1)
            name, inhalt, typ = m.attachments[0]
            self.assertEqual(typ, 'application/pdf')
            self.assertTrue(inhalt.startswith(b'%PDF'))
            self.assertIn('Nebenkostenabrechnung', m.subject)

    def test_vollstaendiger_versand_haelt_die_zustellung_und_die_frist_fest(self):
        self.c.post(self.url)
        self.p.refresh_from_db()
        self.assertEqual(self.p.versendet_am, timezone.localdate())
        self.assertEqual(self.p.versand_kanal, 'email')
        self.assertIsNotNone(self.p.einsprache_bis)

    def test_abrechnung_landet_in_der_akte_und_im_kommunikationsjournal(self):
        from crm.models import Kommunikation
        self.c.post(self.url)
        self.assertEqual(Kommunikation.objects.filter(typ='email', betreff__icontains='Nebenkostenabrechnung').count(), 2)

    def test_antwortadresse_ist_das_postfach_der_verwaltung(self):
        from core.models import Postfach
        Postfach.objects.create(organisation=self.org, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True,
                                benutzer='antwort@verwaltung.ch', server='imap.example.ch')
        self.c.post(self.url)
        self.assertEqual({tuple(m.reply_to) for m in mail.outbox}, {('antwort@verwaltung.ch',)})


class Luecken(_Basis):
    def test_mieter_ohne_adresse_verhindert_die_zustellungsmarke_und_wird_genannt(self):
        self.mieter[1].email = ''
        self.mieter[1].save()
        antwort = self.c.post(self.url, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.versendet_am)
        meldungen = ' | '.join(str(m) for m in antwort.context['messages'])
        self.assertIn('Nach1', meldungen)
        self.assertIn('Keine E-Mail-Adresse', meldungen)

    def test_gescheiterter_versand_wird_nicht_als_zugestellt_festgehalten(self):
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=False):
            antwort = self.c.post(self.url, follow=True)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.versendet_am)
        self.assertIn('Versand fehlgeschlagen', ' | '.join(str(m) for m in antwort.context['messages']))

    def test_unverbuchte_periode_wird_nicht_versendet(self):
        self.p.abgeschlossen = False
        self.p.save()
        self.c.post(self.url)
        self.assertEqual(len(mail.outbox), 0)

    def test_zweiter_versand_braucht_eine_bestaetigung(self):
        self.c.post(self.url)
        mail.outbox = []
        self.c.post(self.url)
        self.assertEqual(len(mail.outbox), 0)
        self.c.post(self.url, {'nochmals': '1'})
        self.assertEqual(len(mail.outbox), 2)


class Zugriff(_Basis):
    def test_sachbearbeiter_und_lesezugriff_duerfen_nicht_versenden(self):
        for rolle in ('Sachbearbeiter', 'Lesezugriff'):
            c = Client()
            c.force_login(_team_user(rolle))
            c.post(self.url)
        self.assertEqual(len(mail.outbox), 0)

    def test_fremde_periode_ergibt_404_und_keine_mail(self):
        from crm.models import Organisation
        from core.tenancy import organisation_kontext
        from finance.models import AbrechnungsPeriode
        fremd = Organisation.objects.create(firma='Fremde Verwaltung AG')
        with organisation_kontext(fremd):
            lg = Liegenschaft.objects.create(organisation=fremd, strasse='Fremdweg 3', plz='3000', ort='Bern',
                                             versicherungswert=Decimal('1'))
            p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung='Fremd', abgeschlossen=True,
                                                  start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        self.assertEqual(self.c.post(f'/neu/nebenkosten/{p.id}/mail/').status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    def test_get_loest_keinen_versand_aus(self):
        self.c.get(self.url)
        self.assertEqual(len(mail.outbox), 0)
