"""Rundschreiben per E-Mail: sofort wie bisher, im Hintergrund nur bei vielen Empfängern UND aktivem Läufer."""
from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from core.models import Auftrag
from core.services import auftraege, rundschreiben
from crm.models import Kommunikation, Mieter
from faelle.test_monatsabschluss import _Basis

SENDEN = 'core.utils.email_service.send_ticket_email'


class RundschreibenTests(_Basis):
    def setUp(self):
        super().setUp()
        cache.delete(auftraege.PULS_SCHLUESSEL)
        self.addCleanup(cache.delete, auftraege.PULS_SCHLUESSEL)
        self.mieter.email = 'eins@example.ch'
        self.mieter.save()
        self.zwei = Mieter.objects.create(typ='person', vorname='Zora', nachname='Zwei', email='zwei@example.ch')
        self.ohne = Mieter.objects.create(typ='person', vorname='Otto', nachname='Ohne', email='')
        self.ids = [self.mieter.pk, self.zwei.pk, self.ohne.pk]

    def _post(self):
        return self.c.post('/neu/kommunikation/senden/', {
            'betreff': 'Wasser abgestellt', 'text': 'Am Montag von 8 bis 10 Uhr.', 'empfaenger_id': self.ids},
            follow=True)

    def test_wenige_empfaenger_gehen_sofort_hinaus(self):
        auftraege.puls_melden()
        with mock.patch(SENDEN, return_value=True) as senden:
            self._post()
        self.assertEqual(senden.call_count, 2)                 # der Mieter ohne Adresse wird übergangen
        self.assertEqual(Auftrag.objects.count(), 0)

    @override_settings(RUNDSCHREIBEN_SCHWELLE_HINTERGRUND=1)
    def test_viele_empfaenger_ohne_laeufer_werden_trotzdem_zum_auftrag(self):
        with mock.patch(SENDEN, return_value=True) as senden, \
                self.assertLogs('core.services.auftraege', level='ERROR'):
            self._post()
        self.assertEqual(senden.call_count, 0)
        self.assertEqual(Auftrag.objects.count(), 1)

    @override_settings(RUNDSCHREIBEN_SCHWELLE_HINTERGRUND=1)
    def test_viele_empfaenger_mit_laeufer_werden_zum_auftrag(self):
        auftraege.puls_melden()
        with mock.patch(SENDEN, return_value=True) as senden:
            antwort = self._post()
            self.assertEqual(senden.call_count, 0)             # noch nichts versandt
            self.assertContains(antwort, 'im Hintergrund versandt')
            self.assertEqual(auftraege.abarbeiten(), 1)
        self.assertEqual(senden.call_count, 2)
        auftrag = Auftrag.objects.get()
        self.assertEqual(auftrag.zustand, Auftrag.ZUSTAND_FERTIG, auftrag.fehler)
        self.assertEqual(sorted(auftrag.parameter['erledigt']), sorted([self.mieter.pk, self.zwei.pk]))
        self.assertIn('2 von 3', auftrag.ergebnis)
        self.assertEqual(Kommunikation.objects.filter(betreff='Wasser abgestellt').count(), 2)

    def test_ein_neustart_nach_absturz_sendet_keine_mail_doppelt(self):
        """Der erste Lauf stirbt nach der ersten Mail; der zweite sendet nur noch die zweite."""
        auftrag = auftraege.anlegen('rundschreiben', {
            'betreff': 'B', 'text': 'T', 'empfaenger': self.ids, 'erledigt': []}, organisation=self.org)
        gesendet = []

        def erst_gut_dann_absturz(adresse, *_a, **_k):
            if gesendet:
                raise SystemExit('Läufer beendet')              # simuliert den Absturz mitten im Lauf
            gesendet.append(adresse)
            return True
        with mock.patch(SENDEN, side_effect=erst_gut_dann_absturz):
            with self.assertRaises(SystemExit):
                auftraege.abarbeiten()
        auftrag = Auftrag.alle_organisationen.get(pk=auftrag.pk)
        self.assertEqual(len(auftrag.parameter['erledigt']), 1)
        # Wiederanlauf: der Auftrag wartet erneut (wie nach `_abgestuerzte_wieder_einreihen`).
        Auftrag.alle_organisationen.filter(pk=auftrag.pk).update(zustand=Auftrag.ZUSTAND_WARTET)
        with mock.patch(SENDEN, return_value=True) as senden:
            auftraege.abarbeiten()
        self.assertEqual(senden.call_count, 1)                 # nur noch die zweite Adresse
        self.assertNotEqual(senden.call_args[0][0], gesendet[0])
        self.assertEqual(Auftrag.alle_organisationen.get(pk=auftrag.pk).zustand, Auftrag.ZUSTAND_FERTIG)

    def test_eine_fremde_mieter_id_wird_uebergangen(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        fremd_org = Organisation.objects.create(firma='Fremd AG')
        with organisation_kontext(fremd_org):
            fremd = Mieter.objects.create(typ='person', vorname='F', nachname='Fremd', email='fremd@example.ch')
        with organisation_kontext(self.org), mock.patch(SENDEN, return_value=True) as senden:
            self.assertEqual(rundschreiben.versenden('B', 'T', [fremd.pk, self.zwei.pk]), 1)
        self.assertEqual(senden.call_args[0][0], 'zwei@example.ch')
