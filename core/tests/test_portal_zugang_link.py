"""Portal-Zugänge: ein Link zum Festlegen des Passworts statt eines Passworts in der Mail (Audit 1.4).

Vorher erzeugte die Verwaltung ein Passwort und schickte es im Klartext; bei fehlender Adresse stand es in der
Meldung am Bildschirm. Jetzt legt die Person es über einen einmaligen, befristeten Link selbst fest.

Gegenprobe (15.11.2026): `create_user(..., password='irgendwas')` wieder eingesetzt -> Test «kein brauchbares
Passwort» rot.
"""
import re

from django.contrib.messages import get_messages
from django.core import mail
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user

LINK = re.compile(r'https?://[^\s"<>]+/passwort/neu/[^\s"<>]+/[^\s"<>]+/')


def _html(nachricht):
    return next((inhalt for inhalt, art in getattr(nachricht, 'alternatives', []) if art == 'text/html'),
                nachricht.body)


class PortalZugangLinkTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _anlegen(self):
        return self.c.post(f'/neu/personen/{self.m.id}/portal-zugang/', {'aktion': 'erstellen'})

    def test_die_mail_traegt_einen_link_und_kein_passwort(self):
        self._anlegen()
        inhalt = _html(mail.outbox[0]) + mail.outbox[0].body
        self.assertRegex(inhalt, LINK)
        self.assertNotIn('Passwort:', inhalt)
        self.m.refresh_from_db()
        self.assertIn(self.m.benutzer.username, inhalt)

    def test_das_neue_konto_hat_kein_brauchbares_passwort(self):
        self._anlegen()
        self.m.refresh_from_db()
        self.assertFalse(self.m.benutzer.has_usable_password())

    def test_ueber_den_link_setzt_die_person_ihr_passwort_und_kann_sich_anmelden(self):
        self._anlegen()
        link = LINK.search(_html(mail.outbox[0])).group(0)
        pfad = '/' + link.split('/', 3)[3]
        gast = Client()
        erste = gast.get(pfad, follow=True)                       # Django leitet auf die Formularadresse um
        self.assertEqual(erste.status_code, 200)
        antwort = gast.post(erste.redirect_chain[-1][0], {'new_password1': 'Sehr-Langes-Geheimnis-2026',
                                                          'new_password2': 'Sehr-Langes-Geheimnis-2026'})
        self.assertEqual(antwort.status_code, 302)
        self.m.refresh_from_db()
        self.assertTrue(self.m.benutzer.check_password('Sehr-Langes-Geheimnis-2026'))
        self.assertNotEqual(gast.get(pfad, follow=True).content, erste.content)      # der Link gilt nur einmal

    def test_ohne_adresse_zeigt_die_meldung_den_link_nicht_ein_passwort(self):
        self.m.email = ''
        self.m.save()
        antwort = self._anlegen()
        meldungen = ' '.join(str(x) for x in get_messages(antwort.wsgi_request))
        self.assertRegex(meldungen, LINK)
        self.assertNotIn('Passwort:', meldungen)
        self.assertEqual(mail.outbox, [])

    def test_erneutes_senden_laesst_ein_bestehendes_passwort_stehen(self):
        self._anlegen()
        self.m.refresh_from_db()
        u = self.m.benutzer
        u.set_password('Bestehendes-Geheimnis-2026')
        u.save()
        self._anlegen()
        u.refresh_from_db()
        self.assertTrue(u.check_password('Bestehendes-Geheimnis-2026'))
        self.assertEqual(len(mail.outbox), 2)

    def test_eigentuemer_bekommt_ebenfalls_einen_link(self):
        from crm.models import Eigentuemer
        eig = Eigentuemer.objects.first() or Eigentuemer.objects.create(firma_oder_name='Eig AG')
        eig.email = 'eig@example.ch'
        eig.save()
        self.c.post(f'/neu/mandate/{eig.pk}/portal-zugang/')
        nachricht = [x for x in mail.outbox if x.to == ['eig@example.ch']][0]
        self.assertRegex(_html(nachricht), LINK)
        eig.refresh_from_db()
        self.assertFalse(eig.benutzer.has_usable_password())
