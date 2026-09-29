"""Auswahlwerte der Modelle: Anzeige übersetzt, gespeichert der Code.

- Jede Beschriftung einer Auswahl ist übersetzbar (lazy) — ausser den
  bewusst deutschen: Rollennamen (Produktbegriffe), Aufenthaltsbewilligungen,
  Mietzinsmodell mit Art.-Verweis, Zustellart der Kündigung, Regelarten
  (Rechtsbegriffe) und Abo-Stufen (Produktnamen), GEAK-Klassen (Buchstaben).
- Gespeicherter Text bleibt deutsch, auch bei französischer Oberfläche:
  interne Ticketnachricht und Protokoll beim Statuswechsel eines Schadens.

Gegenproben:
- in rentals/models.py bei `('aktiv', _('Aktiv'))` das `_( … )` entfernen —
  `test_jede_auswahl_ist_uebersetzbar` wird rot (neue unübersetzte Stelle);
- in core/views/fw/schaeden.py `auf_deutsch(t.get_status_display)` in der
  Ticketnachricht durch `t.get_status_display()` ersetzen —
  `test_statuswechsel_speichert_deutsch` wird rot.
"""
from django.apps import apps
from django.test import Client, SimpleTestCase, TestCase
from django.utils import translation
from django.utils.functional import Promise

from core.services.dokumentsprache import auf_deutsch
from core.tests._helfer import _basis_objekte, _team_user

APPS = ('crm', 'portfolio', 'rentals', 'finance', 'tickets', 'faelle', 'mietprozess', 'core')

#: (App, Modell, Feld), deren Beschriftung bewusst deutsch bleibt.
BEWUSST_DEUTSCH = {
    ('crm', 'Mitgliedschaft', 'rolle'),
    ('crm', 'Organisation', 'abo_plan'),
    ('crm', 'Mieter', 'aufenthaltsbewilligung'),
    ('rentals', 'Mietvertrag', 'mietzins_modell'),
    ('rentals', 'Kuendigung', 'zustellung'),
    ('faelle', 'Regel', 'art'),
    ('portfolio', 'Liegenschaft', 'geak_klasse'),
    ('portfolio', 'Liegenschaft', 'geak_klasse_gesamt'),
}


def _unuebersetzt():
    funde = set()
    for modell in apps.get_models():
        if modell._meta.app_label not in APPS:
            continue
        for feld in modell._meta.fields:
            # «—» (leer) braucht keine Übersetzung.
            if feld.choices and any(not isinstance(l, Promise) and l.strip('—- ')
                                    for _w, l in feld.flatchoices):
                funde.add((modell._meta.app_label, modell.__name__, feld.name))
    return funde


class AuswahlTests(SimpleTestCase):

    def test_jede_auswahl_ist_uebersetzbar(self):
        self.assertEqual(_unuebersetzt() - BEWUSST_DEUTSCH, set())

    def test_die_ausnahmen_gibt_es_noch(self):
        """Eine veraltete Ausnahme verdeckte eine künftige Lücke."""
        self.assertEqual(BEWUSST_DEUTSCH - _unuebersetzt(), set())

    def test_anzeige_folgt_der_sprache_gespeichert_bleibt_der_code(self):
        from rentals.models import Mietvertrag
        v = Mietvertrag(status='aktiv')
        with translation.override('fr'):
            self.assertEqual(v.get_status_display(), 'Actif')
            # Kontext «Auswahl»: gleicher deutscher Text, anderer Sinn
            from faelle.termin_models import Termin
            self.assertEqual(Termin(status='abgesagt').get_status_display(), 'Annulé')
        self.assertEqual(v.status, 'aktiv')

    def test_rollennamen_bleiben_deutsch(self):
        from crm.models import Mitgliedschaft
        with translation.override('fr'):
            self.assertEqual(Mitgliedschaft(rolle=Mitgliedschaft.ROLLE_VERWALTER).get_rolle_display(), 'Verwalter')

    def test_auf_deutsch(self):
        from rentals.models import Mietvertrag
        with translation.override('fr'):
            self.assertEqual(auf_deutsch(Mietvertrag(status='aktiv').get_status_display), 'Aktiv')
            self.assertEqual(translation.get_language(), 'fr')


class GespeicherterTextTests(TestCase):

    def test_statuswechsel_speichert_deutsch(self):
        from core.models import AktivitaetsLog
        from tickets.models import SchadenMeldung, TicketNachricht
        lg, e, _m, _v = _basis_objekte()
        t = SchadenMeldung.objects.create(liegenschaft=lg, betroffene_einheit=e, titel='Leck', beschreibung='x')
        c = Client()
        c.force_login(_team_user())
        c.cookies['django_language'] = 'fr'
        c.post(f'/neu/schaeden/{t.id}/status/', {'status': 'in_bearbeitung'})
        notiz = TicketNachricht.objects.filter(ticket=t, typ='system').latest('id').nachricht
        self.assertEqual(notiz, 'Status geändert: In Bearbeitung.')
        eintrag = AktivitaetsLog.objects.filter(aktion='Ticket-Status geändert').latest('id')
        self.assertIn('In Bearbeitung', str(eintrag.details))
