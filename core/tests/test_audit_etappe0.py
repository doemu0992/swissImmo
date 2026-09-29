"""Etappe 0 aus docs/AUDIT-SAAS-NIVEAU.md: Korrektheit vor Gestaltung.

Hält fest, dass Seitenaufrufe (GET) nichts mehr auslösen, was eine Erklärung,
einen Versand oder einen Import bedeutet, und dass die korrigierten Einstiege
wirklich wirken.
"""
from datetime import date
from decimal import Decimal

from django.core import mail
from django.test import TestCase, Client

from ._helfer import _team_user, _basis_objekte


class GetOhneNebenwirkung(TestCase):
    """Ein Link-Prefetch, ein Crawler oder ein Klick aufs falsche Lesezeichen
    darf keine Mahnung verschicken, keinen Vertrag an DocuSeal geben und keinen
    Import starten."""

    def setUp(self):
        _lg, _e, self.m, self.v = _basis_objekte()
        self.m.email = 'mieter@example.ch'
        self.m.save()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_mahnung_per_mail_nicht_ueber_get(self):
        r = self.c.get(f'/vertrag/{self.v.id}/mahnung/mail/')
        self.assertEqual(r.status_code, 405)
        self.assertEqual(len(mail.outbox), 0)

    def test_docuseal_versand_nicht_ueber_get(self):
        r = self.c.get(f'/vertrag/{self.v.id}/senden/')
        self.assertEqual(r.status_code, 405)

    def test_marktdaten_import_nicht_ueber_get(self):
        r = self.c.get('/admin/update-marktdaten/')
        self.assertEqual(r.status_code, 405)

    def test_ruege_267a_nicht_ueber_get(self):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel, Dokument
        from core.models import Pendenz
        prot = Abnahmeprotokoll.objects.create(vertrag=self.v, typ='auszug', datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung='Kochfeld gesprungen',
                                     verursacher='mieter', kostenschaetzung=Decimal('400'))
        pendenz = Pendenz.objects.create(titel='Mängelrüge Art. 267a versenden', vertrag=self.v,
                                         kategorie='frist')
        r = self.c.get(f'/neu/abnahme/{prot.id}/ruege-267a/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'/neu/abnahme/{prot.id}/')
        self.assertFalse(Dokument.objects.filter(
            vertrag=self.v, bezeichnung__startswith='Mängelrüge Art. 267a').exists())
        pendenz.refresh_from_db()
        self.assertFalse(pendenz.erledigt)


class Einstiege(TestCase):

    def test_loeschbegehren_ist_ein_formular(self):
        """Der Link schickte per GET an eine reine POST-Ansicht und tat nichts."""
        _lg, _e, m, _v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/personen/{m.id}/').content.decode()
        self.assertNotIn(f'<a href="/neu/personen/{m.id}/dsg-loeschen/"', body)
        # Menü UND Fusszeile tragen je ein POST-Formular.
        self.assertEqual(body.count(f'action="/neu/personen/{m.id}/dsg-loeschen/"'), 2)

    def test_fall_brotkrume_heisst_wie_die_navigation(self):
        with open('core/templates/fw/fall_detail.html', encoding='utf-8') as f:
            vorlage = f.read()
        self.assertIn('<a href="/neu/">{% trans "Heute" %}</a>', vorlage)
        self.assertNotIn('{% trans "Arbeit" %}', vorlage)


class Fehlerseiten(TestCase):
    """Wer aus dem Portal auf eine tote Adresse trifft, gehört zurück ins
    Portal, nicht vor die Anmeldung des Teams."""

    def _ziel(self, pfad):
        r = Client().get(pfad)
        self.assertEqual(r.status_code, 404)
        return r.content.decode()

    def test_mieterportal(self):
        self.assertIn('href="/mieter/"', self._ziel('/mieter/gibt-es-nicht/'))

    def test_eigentuemerportal(self):
        self.assertIn('href="/portal/"', self._ziel('/portal/gibt-es-nicht/'))

    def test_team(self):
        body = self._ziel('/neu/gibt-es-nicht/')
        self.assertIn('href="/neu/"', body)
        self.assertNotIn('href="/mieter/"', body)

    def test_favicon_in_markenfarbe(self):
        for name in ('403', '404', '500'):
            with open(f'core/templates/{name}.html', encoding='utf-8') as f:
                vorlage = f.read()
            self.assertNotIn('4f46e5', vorlage, name)
            self.assertIn('0f6f6a', vorlage, name)
