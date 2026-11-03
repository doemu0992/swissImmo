"""Der persönliche Gruss in allen Mails («Guten Tag Herr Muster»), 3.11.2026.

Vorher grüsste ein Mieter-Mail mit «Guten Tag Mieter» (kein Name bekannt), mit «Guten Tag» allein
oder mit dem vollen Namen. Jetzt gilt eine Regel (`core.services.anrede`): Herr/Frau + Nachname,
sonst Vorname Nachname, bei einer Firma die Kontaktperson bzw. die Firma, sonst «Guten Tag» —
nie ein Platzhalterwort.

Gegenproben (je Klasse; Fehler einbauen, Test wird rot, zurückbauen):
- `anrede._gruss`: den Zweig `anrede == 'Herr'` auf `'Frau'` stellen -> `HelferTests.test_herr`,
  `TicketMailTests.test_erledigt_*` rot;
- `ticket_workflow.melder_gruss`: den letzten `return` (Mieter der Einheit) durch
  `mail_gruss(sprache=sprache)` ersetzen -> `test_intern_erfasst_nimmt_den_mieter_der_einheit` rot;
- `ticket_workflow._ALTE_ANREDE` auf ein nie passendes Muster stellen ->
  `test_gespeicherte_vorlage_gruesst_persoenlich` rot;
- `ticket_kontext`: `'melder_name'` wieder mit Rückfall `'Mieter'` in den Gruss einsetzen -> `test_nie_mieter` rot;
- `eigentuemer_gruss`: den `anrede`-Zweig entfernen -> `EigentuemerTests` rot;
- `stweg/anfragen.py`: `eigentuemer_gruss_html(eig)` durch `eig.firma_oder_name` ersetzen -> `test_stweg_anfrage` rot;
- `tickets/services.py`: `melder_anrede=...` entfernen -> `test_aushang_speichert_anrede_und_gruesst` rot.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.utils.html import strip_tags

from core.services.anrede import (benutzer_gruss, eigentuemer_gruss, handwerker_gruss, mail_gruss,
                                  mieter_gruss)

from ._helfer import _basis_objekte, _team_user
from .test_mailwege_schaden import _text, sofort
from .test_ticket_workflow import _handwerker, _ticket


def _klar(m):
    """Der Mailtext ohne Markup, Zeilenumbrüche als solche: so liest ihn der Empfänger."""
    return strip_tags(m.body.replace('<br>', '\n').replace('</p>', '\n\n')).strip()


class HelferTests(SimpleTestCase):

    def test_herr(self):
        self.assertEqual(mail_gruss('Herr', 'Hans', 'Muster'), 'Guten Tag Herr Muster')

    def test_frau(self):
        self.assertEqual(mail_gruss('Frau', 'Eva', 'Muster'), 'Guten Tag Frau Muster')

    def test_ohne_anrede_voller_name(self):
        self.assertEqual(mail_gruss('', 'Eva', 'Muster'), 'Guten Tag Eva Muster')
        self.assertEqual(mail_gruss('Familie', 'Eva', 'Muster'), 'Guten Tag Eva Muster')

    def test_nur_nachname_ohne_anrede(self):
        self.assertEqual(mail_gruss('', '', 'Muster'), 'Guten Tag Muster')

    def test_firma(self):
        self.assertEqual(mail_gruss(firma='Bau AG'), 'Guten Tag Bau AG')

    def test_firma_mit_kontaktperson(self):
        self.assertEqual(mail_gruss(firma='Bau AG', kontaktperson='Anna Meier'), 'Guten Tag Anna Meier')
        self.assertEqual(mail_gruss('Frau', firma='Bau AG', kontaktperson='Anna Meier'), 'Guten Tag Frau Meier')

    def test_nichts_bekannt(self):
        self.assertEqual(mail_gruss(), 'Guten Tag')
        self.assertEqual(mail_gruss('Herr', '', ''), 'Guten Tag')

    def test_sprachen(self):
        self.assertEqual(mail_gruss('Herr', 'Hans', 'Muster', sprache='fr'), 'Bonjour Monsieur Muster')
        self.assertEqual(mail_gruss('Frau', 'Eva', 'Muster', sprache='fr'), 'Bonjour Madame Muster')
        self.assertEqual(mail_gruss('Herr', 'Hans', 'Muster', sprache='it'), 'Buongiorno Signor Muster')
        self.assertEqual(mail_gruss('Frau', 'Eva', 'Muster', sprache='it'), 'Buongiorno Signora Muster')
        self.assertEqual(mail_gruss('Herr', 'Hans', 'Muster', sprache='en'), 'Hello Mr Muster')
        self.assertEqual(mail_gruss('Frau', 'Eva', 'Muster', sprache='en'), 'Hello Ms Muster')
        for sprache, erwartet in (('fr', 'Bonjour'), ('it', 'Buongiorno'), ('en', 'Hello')):
            self.assertEqual(mail_gruss(sprache=sprache), erwartet)
        self.assertEqual(mail_gruss('', 'Eva', 'Muster', sprache='fr'), 'Bonjour Eva Muster')

    def test_mieter_firma_ignoriert_die_vorgabe_anrede(self):
        """`Mieter.anrede` steht bei jeder Firma auf der Vorgabe «Herr» — sie sagt nichts über die Kontaktperson."""
        firma = SimpleNamespace(typ='firma', firmen_name='Treuhand AG', kontaktperson='', anrede='Herr',
                                vorname='', nachname='')
        self.assertEqual(mieter_gruss(firma), 'Guten Tag Treuhand AG')
        firma.kontaktperson = 'Beat Frei'
        self.assertEqual(mieter_gruss(firma), 'Guten Tag Beat Frei')

    def test_benutzer_und_handwerker(self):
        self.assertEqual(benutzer_gruss(SimpleNamespace(first_name='Rita', last_name='Roth')),
                         'Guten Tag Rita Roth')
        self.assertEqual(benutzer_gruss(SimpleNamespace(first_name='', last_name='')), 'Guten Tag')
        self.assertEqual(handwerker_gruss(SimpleNamespace(firma='Sanitär AG', kontaktperson=None)),
                         'Guten Tag Sanitär AG')


class _Basis(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        mail.outbox.clear()


class TicketMailTests(_Basis):
    """Mails an den Melder: Mieter am Ticket, Name aus der Meldung, Mieter der Einheit, niemand."""

    def _erledigt(self, t):
        from tickets.workflow import wechsle_status
        wechsle_status(t, 'in_bearbeitung')
        mail.outbox.clear()
        wechsle_status(t, 'wartet_auf_rechnung')
        wechsle_status(t, 'erledigt', melder_informieren=True, ohne_rechnung=True)
        return [m for m in mail.outbox if m.to == [t.email_melder or t.gemeldet_von.email]]

    def _gruss_zeile(self, t):
        mails = self._erledigt(t)
        self.assertEqual(len(mails), 1)
        return _klar(mails[0]).split('\n')[0].strip()

    def test_erledigt_herr(self):
        t = _ticket()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Herr Muster')

    def test_erledigt_frau(self):
        t = _ticket()
        t.gemeldet_von.anrede = 'Frau'
        t.gemeldet_von.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Frau Muster')

    def test_erledigt_unbekannte_anrede(self):
        t = _ticket()
        t.gemeldet_von.anrede = ''
        t.gemeldet_von.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Hans Muster')

    def test_erledigt_franzoesisch(self):
        t = _ticket()
        t.gemeldet_von.sprache = 'fr'
        t.gemeldet_von.save()
        self.assertEqual(self._gruss_zeile(t), 'Bonjour Monsieur Muster')

    def test_erledigt_firma(self):
        t = _ticket()
        m = t.gemeldet_von
        m.typ, m.firmen_name, m.kontaktperson = 'firma', 'Treuhand AG', ''
        m.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Treuhand AG')
        m.kontaktperson = 'Beat Frei'
        m.save()
        mail.outbox.clear()
        t.status = 'neu'
        t.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Beat Frei')

    def test_meldung_ohne_mieter_nimmt_name_und_anrede_der_meldung(self):
        t = _ticket()
        t.gemeldet_von = None
        t.melder_anrede, t.melder_vorname, t.melder_nachname = 'Frau', 'Eva', 'Test'
        t.email_melder = 'eva@example.ch'
        t.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Frau Test')

    def test_meldung_ohne_anrede_nimmt_vorname_nachname(self):
        t = _ticket()
        t.gemeldet_von = None
        t.melder_vorname, t.melder_nachname = 'Eva', 'Test'
        t.email_melder = 'eva@example.ch'
        t.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Eva Test')

    def test_intern_erfasst_nimmt_den_mieter_der_einheit(self):
        t = _ticket()
        t.gemeldet_von = None          # intern erfasst: kein Melder-Name, kein verknüpfter Mieter
        t.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Herr Muster')

    def test_fremde_adresse_bekommt_nicht_den_namen_des_mieters(self):
        """Meldet ein Nachbar (andere Adresse), wäre der Name des Mieters der Einheit falsch."""
        t = _ticket()
        t.gemeldet_von = None
        t.email_melder = 'nachbar@example.ch'
        t.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag')

    def test_nie_mieter(self):
        """Weder Mieter noch Name noch Einheit: «Guten Tag» allein, nie «Guten Tag Mieter»."""
        t = _ticket()
        t.gemeldet_von = None
        t.betroffene_einheit = None
        t.email_melder = 'jemand@example.ch'
        t.save()
        mails = self._erledigt(t)
        text = _klar(mails[0])
        self.assertNotIn('Guten Tag Mieter', text)
        self.assertEqual(text.split('\n')[0].strip(), 'Guten Tag')

    def test_gespeicherte_vorlage_gruesst_persoenlich(self):
        """Eine vom Nutzer gespeicherte Vorlage mit «Guten Tag {melder_name}» bleibt unverändert in der
        Datenbank, die Mail grüsst aber mit Anrede."""
        from crm.models import Vorlage
        v = Vorlage.objects.create(name='Eigene', kategorie='ticket_erledigt', betreff='Fertig #{ticket_id}',
                                   inhalt='Guten Tag {melder_name}\n\nIhr Schaden „{schaden}“ ist behoben.')
        t = _ticket()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag Herr Muster')
        v.refresh_from_db()
        self.assertEqual(v.inhalt, 'Guten Tag {melder_name}\n\nIhr Schaden „{schaden}“ ist behoben.')

    def test_gespeicherte_vorlage_ohne_namen_sagt_nicht_mieter(self):
        from crm.models import Vorlage
        Vorlage.objects.create(name='Eigene', kategorie='ticket_erledigt', betreff='Fertig',
                               inhalt='Guten Tag {melder_name}\n\nFertig.')
        t = _ticket()
        t.gemeldet_von = None
        t.betroffene_einheit = None
        t.email_melder = 'jemand@example.ch'
        t.save()
        self.assertEqual(self._gruss_zeile(t), 'Guten Tag')

    def test_eigene_vorlage_mit_melder_name_mitten_im_satz_bleibt(self):
        """Nur die Grusszeile wird ersetzt: `{melder_name}` im Satz behält seinen Wert."""
        from core.services.ticket_workflow import vorlage_text
        from crm.models import Vorlage
        Vorlage.objects.create(name='Eigene', kategorie='ticket_erledigt', betreff='x',
                               inhalt='Guten Tag {melder_name}\n\nDer Mieter {melder_name} wurde informiert.')
        _betreff, inhalt = vorlage_text('ticket_erledigt', _ticket())
        self.assertIn('Guten Tag Herr Muster\n', inhalt)
        self.assertIn('Der Mieter Hans Muster wurde', inhalt)


class HandwerkerMailTests(_Basis):

    def test_auftrag_gruesst_die_firma(self):
        from tickets.workflow import auftrag_vergeben
        auftrag_vergeben(_ticket(), _handwerker())
        hw = [m for m in mail.outbox if m.to == ['hw@example.ch']][0]
        self.assertIn('Guten Tag Sanitär AG', _text(hw))

    def test_auftrag_gruesst_die_kontaktperson(self):
        from tickets.workflow import auftrag_vergeben
        auftrag_vergeben(_ticket(), _handwerker(kontaktperson='Peter Pfister'))
        hw = [m for m in mail.outbox if m.to == ['hw@example.ch']][0]
        self.assertIn('Guten Tag Peter Pfister', _text(hw))
        self.assertNotIn('Sehr geehrte Damen und Herren', _text(hw))

    def test_termin_mail_je_empfaenger(self):
        """Dieselbe Vorlage `ticket_termin_abgesagt` geht an Mieter UND Handwerker: jeder wird mit seinem Namen gegrüsst."""
        from tickets.workflow import handwerker_zuweisen, termin_absagen, termin_festlegen
        a = handwerker_zuweisen(_ticket(), _handwerker())
        termin_festlegen(a, datetime(2026, 11, 20, 8, 30))
        mail.outbox.clear()
        termin_absagen(a)
        an = {m.to[0]: _text(m) for m in mail.outbox}
        self.assertIn('Guten Tag Herr Muster', an['hans@example.ch'])
        self.assertIn('Guten Tag Sanitär AG', an['hw@example.ch'])

    def test_freigabe_entscheid_an_handwerker(self):
        from tickets.workflow import freigabe_entscheid_melden, handwerker_zuweisen
        a = handwerker_zuweisen(_ticket(), _handwerker(kontaktperson='Peter Pfister'))
        mail.outbox.clear()
        freigabe_entscheid_melden(a, True)
        hw = [m for m in mail.outbox if m.to == ['hw@example.ch']][0]
        self.assertTrue(_klar(hw).startswith('Guten Tag Peter Pfister'))


class EigentuemerTests(_Basis):

    def setUp(self):
        super().setUp()
        from crm.models import Eigentuemer
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.eig = Eigentuemer.objects.create(firma_oder_name='Robert Keller', email='keller@example.ch')
        self.lg.eigentuemer = self.eig
        self.lg.save()

    def test_ohne_anrede_wie_bisher(self):
        self.assertEqual(eigentuemer_gruss(self.eig), 'Guten Tag Robert Keller')
        self.eig.kontaktperson = 'Anna Meier'
        self.assertEqual(eigentuemer_gruss(self.eig), 'Guten Tag Anna Meier')

    def test_mit_anrede(self):
        self.eig.anrede = 'Herr'
        self.assertEqual(eigentuemer_gruss(self.eig), 'Guten Tag Herr Keller')
        self.eig.kontaktperson = 'Anna Meier'
        self.eig.anrede = 'Frau'
        self.assertEqual(eigentuemer_gruss(self.eig), 'Guten Tag Frau Meier')
        self.assertEqual(eigentuemer_gruss(self.eig, 'fr'), 'Bonjour Madame Meier')

    def test_freigabebitte_gruesst_persoenlich(self):
        from tickets.workflow import eigentuemer_um_freigabe_bitten, handwerker_zuweisen
        self.eig.anrede = 'Herr'
        self.eig.save()
        t = _ticket()
        t.liegenschaft = self.lg
        t.save()
        a = handwerker_zuweisen(t, _handwerker())
        mail.outbox.clear()
        eigentuemer_um_freigabe_bitten(a)
        m = [x for x in mail.outbox if x.to == ['keller@example.ch']][0]
        self.assertTrue(_klar(m).startswith('Guten Tag Herr Keller'))

    def test_freigabebitte_franzoesisch(self):
        from tickets.workflow import eigentuemer_um_freigabe_bitten, handwerker_zuweisen
        self.eig.anrede, self.eig.sprache = 'Frau', 'fr'
        self.eig.save()
        t = _ticket()
        t.liegenschaft = self.lg
        t.save()
        a = handwerker_zuweisen(t, _handwerker())
        mail.outbox.clear()
        eigentuemer_um_freigabe_bitten(a)
        m = [x for x in mail.outbox if x.to == ['keller@example.ch']][0]
        self.assertTrue(_klar(m).startswith('Bonjour Madame Keller'))

    def test_formular_speichert_nur_herr_oder_frau(self):
        c = Client()
        c.force_login(_team_user())
        daten = {'firma_oder_name': 'Robert Keller', 'anrede': 'Frau'}
        c.post(f'/neu/mandate/{self.eig.pk}/bearbeiten/', daten)
        self.eig.refresh_from_db()
        self.assertEqual(self.eig.anrede, 'Frau')
        c.post(f'/neu/mandate/{self.eig.pk}/bearbeiten/', {**daten, 'anrede': '<b>x</b>'})
        self.eig.refresh_from_db()
        self.assertEqual(self.eig.anrede, '')

    def test_report_mail(self):
        from crm.models import Eigentuemer
        _team_user()
        Eigentuemer.objects.all().update(anrede='Frau', firma_oder_name='Dora Dupont', email='d@example.ch')
        with mock.patch('core.services.portfolio_report.generate_portfolio_report_fuer', return_value=b'%PDF'), \
                mock.patch('core.services.steuerauszug.generate_steuerauszug_pdf', return_value=b'%PDF'), \
                mock.patch('core.utils.email_service.send_report_mail', return_value=True) as senden:
            call_command('send_eigentuemer_reports', '--jahr', '2025', stdout=mock.MagicMock(),
                         stderr=mock.MagicMock())
        self.assertIn('Guten Tag Frau Dupont', senden.call_args.args[2])

    def test_stweg_anfrage(self):
        from portfolio.models import Liegenschaft
        from stweg.anfragen import anfrage_erfassen, beantworten
        self.eig.anrede = 'Herr'
        self.eig.save()
        # Ohne `save()`: Eine STWEG verlangt Wertquoten, die dieser Test nicht braucht.
        Liegenschaft.objects.filter(pk=self.lg.pk).update(typ=Liegenschaft.TYP_STWEG)
        self.lg.refresh_from_db()
        a = anfrage_erfassen(self.lg, 'Frage zur Heizung', eigentuemer=self.eig)
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True) as senden:
            beantworten(a, 'Wir kümmern uns.')
        self.assertIn('Guten Tag Herr Keller', senden.call_args.args[2])


class MieterMailTests(_Basis):

    def test_zahlungserinnerung(self):
        from core.utils.email_service import send_payment_reminder
        from datetime import date
        from decimal import Decimal
        lg, e, m, v = _basis_objekte()
        m.anrede = 'Frau'
        m.save()
        with sofort():
            send_payment_reminder(v, date(2026, 10, 1), Decimal('100.00'))
        self.assertIn('Guten Tag Frau Muster,', _text(mail.outbox[0]))

    def test_nk_begleittext(self):
        from core.services.nk_versand import mail_text
        text = mail_text({'verwaltung': None, 'saldo': 0, 'objekt': 'x'}, '2025',
                         mieter_gruss(SimpleNamespace(typ='person', anrede='Herr', vorname='Hans',
                                                      nachname='Muster', firmen_name='', kontaktperson='')))
        self.assertTrue(text.startswith('<p>Guten Tag Herr Muster</p>'))
        # ohne Angabe wie bisher
        self.assertTrue(mail_text({'verwaltung': None, 'saldo': 0}, '2025').startswith('<p>Guten Tag</p>'))

    def test_aushang_speichert_anrede_und_gruesst(self):
        lg, e, m, v = _basis_objekte()
        with sofort():
            Client().post(f'/report/{lg.id}/', {
                'titel': 'Heizung kalt', 'beschreibung': 'Seit gestern', 'anrede': 'Frau', 'vorname': 'Eva',
                'nachname': 'Test', 'email': 'eva@example.ch', 'telefon': '079 123 45 67'})
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.get(email_melder='eva@example.ch')
        self.assertEqual((t.melder_anrede, t.melder_vorname, t.melder_nachname), ('Frau', 'Eva', 'Test'))
        an_melder = [m for m in mail.outbox if m.to == ['eva@example.ch']][0]
        self.assertIn('Guten Tag Frau Test', _text(an_melder))

    def test_aushang_firma_ist_keine_anrede(self):
        lg, e, m, v = _basis_objekte()
        with sofort():
            Client().post(f'/report/{lg.id}/', {
                'titel': 'Heizung kalt', 'beschreibung': 'Seit gestern', 'anrede': 'Firma', 'vorname': 'Eva',
                'nachname': 'Test', 'email': 'eva@example.ch', 'telefon': '079 123 45 67'})
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.get(email_melder='eva@example.ch')
        self.assertEqual(t.melder_anrede, '')
        an_melder = [m for m in mail.outbox if m.to == ['eva@example.ch']][0]
        self.assertIn('Guten Tag Eva Test', _text(an_melder))

    def test_bewerber_zusage(self):
        from mietprozess.models import Mietbewerbung as Bewerbung
        from core.views.fw.mietprozess import _bewerber_mail
        from crm.models import Vorlage
        lg, e, m, v = _basis_objekte()
        Vorlage.objects.filter(kategorie__startswith='bewerber').delete()      # sonst gilt der Text der Vorlage
        b = Bewerbung(vorname='Eva', nachname='Test', einheit=e)
        for entscheid in ('zusage', 'absage'):
            _betreff, body = _bewerber_mail(b, entscheid)
            self.assertTrue(body.startswith('Guten Tag Eva Test\n'), entscheid)


