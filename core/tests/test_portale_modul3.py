"""Modul 3 — Portale für Mieter und Handwerker (27.10.2026).

HANDWERKERPORTAL: ein geheimer Link je Auftrag, kein Konto (Entscheid E6).
Die Tests rufen den Link OHNE Anmeldung und OHNE Mandantenkontext auf — wie
`test_anonyme_einstiegspunkte.py`: Ein gesetzter Kontext würde eine Welt
prüfen, in der der Handwerker angemeldet ist. Kontext gibt es nur beim
Anlegen der Daten, jeweils in einem eigenen `organisation_kontext`-Block.

MIETERPORTAL: kleinere Startseite, Meldeformular mit Kategorie/Zutritt/
Erreichbarkeit, Tickets der Einheit während der Mietdauer, Termin und Zutritt
im Detail, und die Nachricht des Mieters über den Workflow statt am Statusfeld
vorbei.
"""
import hashlib
import os
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def _pdf(name='beleg.pdf', inhalt=PDF):
    return SimpleUploadedFile(name, inhalt, content_type='application/pdf')


class _MedienWurzel(TestCase):
    """Eigener, temporärer MEDIA_ROOT je Klasse (wie test_medien_isolation)."""

    @classmethod
    def setUpClass(cls):
        cls._wurzel = tempfile.mkdtemp(prefix='swissimmo-modul3-')
        cls._override = override_settings(MEDIA_ROOT=cls._wurzel)
        cls._override.enable()
        cls.addClassCleanup(shutil.rmtree, cls._wurzel, ignore_errors=True)
        cls.addClassCleanup(cls._override.disable)
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.assertTrue(settings.MEDIA_ROOT.startswith(self._wurzel))
        cache.clear()          # Rate-Limit und Protokoll-Drossel je Test frisch


def _auftrag(fx, titel='Wasserhahn tropft', status='in_bearbeitung', tel='079 111 22 33'):
    from tickets.models import HandwerkerAuftrag, SchadenMeldung
    with organisation_kontext(fx.organisation):
        t = SchadenMeldung.objects.create(
            liegenschaft=fx.liegenschaft, betroffene_einheit=fx.einheit, titel=titel,
            beschreibung=f'Tropft in der Küche.\n\n--- KONTAKT ---\nName: Frau Melder\n'
                         f'Tel: {tel}\nEmail: melder@example.ch\nErreichbar: 08:00 - 10:00\n',
            status=status, tel_melder=tel, zutritt='passpartout',
            # Die Fixture-Liegenschaft ist eine STWEG: ohne Deklaration sperrt
            # `kostentraeger_pruefen` den Abschluss (wie beim Fixture-Schaden).
            bauteil='kueche_sanitaer', kostentraeger='sonderrecht')
        # Der Auftragstext aus der Vorlage `ticket_handwerker` nennt Name und
        # Telefon des Melders — nach dem Abschluss darf er nicht mehr erscheinen.
        a = HandwerkerAuftrag.objects.create(ticket=t, handwerker=fx.handwerker,
                                             bemerkung=f'Bitte Frau Melder anrufen ({tel}).')
    return a


def _link(fx, auftrag):
    from tickets.handwerker_zugang import link_erzeugen
    with organisation_kontext(fx.organisation):
        return link_erzeugen(auftrag)


def _neu(auftrag):
    from tickets.models import HandwerkerAuftrag
    return HandwerkerAuftrag.alle_organisationen.select_related('ticket').get(pk=auftrag.pk)


def _abschliessen(fx, auftrag):
    """Ticket regulär erledigen: Rechnung verknüpfen, Abschluss über den Workflow."""
    from finance.models import KreditorenRechnung
    from tickets.workflow import rechnung_verknuepfen
    with organisation_kontext(fx.organisation):
        kr = KreditorenRechnung.objects.create(
            lieferant='Sanitär', betrag=Decimal('300'), liegenschaft=fx.liegenschaft, status='neu')
        rechnung_verknuepfen(_neu(auftrag), kr, abschliessen=True)
    return _neu(auftrag)


class HandwerkerBasis(_MedienWurzel):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        super().setUp()
        self.client = Client(raise_request_exception=False)
        self.auftrag = _auftrag(self.a)
        self.token = _link(self.a, self.auftrag)
        self.url = f'/auftrag/{self.token}/'


class HandwerkerLinkTests(HandwerkerBasis):
    """Gültig, falsch, fremd, abgelaufen, widerrufen — und nur der Hash."""

    def test_gueltiger_link_zeigt_den_auftrag_mit_schutzkoepfen(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Wasserhahn tropft')
        self.assertContains(r, 'A-Weg 7')                 # Adresse
        self.assertContains(r, '079 111 22 33')           # Telefon, solange offen
        self.assertContains(r, 'Passpartout')             # Zutritt
        self.assertEqual(r['X-Robots-Tag'], 'noindex, nofollow')
        # same-origin, nicht no-referrer: Sonst sendet der Browser bei den
        # eigenen Formularen `Origin: null` und CSRF lehnt ab (403).
        self.assertEqual(r['Referrer-Policy'], 'same-origin')
        self.assertIn('no-store', r['Cache-Control'])

    def test_falscher_und_kaputter_token_ergeben_404(self):
        import secrets
        self.assertEqual(self.client.get(f'/auftrag/{secrets.token_urlsafe(32)}/').status_code, 404)
        self.assertEqual(self.client.get('/auftrag/kurz/').status_code, 404)
        # Der Hash selbst ist kein Schlüssel: Wer die Tabelle liest, kommt nicht hinein.
        self.assertEqual(self.client.get(f'/auftrag/{_neu(self.auftrag).token_hash}/').status_code, 404)

    def test_fremder_token_zeigt_nur_den_fremden_auftrag(self):
        auftrag_b = _auftrag(self.b, titel='Heizung B kalt')
        token_b = _link(self.b, auftrag_b)
        r = self.client.get(f'/auftrag/{token_b}/')
        self.assertContains(r, 'Heizung B kalt')
        self.assertNotContains(r, 'Wasserhahn tropft')
        self.assertNotContains(r, 'A-Weg')

    def test_widerrufen_ergibt_404(self):
        from tickets.handwerker_zugang import link_widerrufen
        with organisation_kontext(self.a.organisation):
            self.assertTrue(link_widerrufen(_neu(self.auftrag)))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_abgelaufen_ergibt_404(self):
        from tickets.models import HandwerkerAuftrag
        a = _abschliessen(self.a, self.auftrag)
        self.assertEqual(self.client.get(self.url).status_code, 200)    # lesend
        HandwerkerAuftrag.alle_organisationen.filter(pk=a.pk).update(
            token_gueltig_bis=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_abgeschlossen_ohne_frist_ist_abgelaufen(self):
        """Fail-closed: Schliesst ein Weg den Auftrag, ohne die Frist zu setzen,
        ist der Link tot statt ewig offen."""
        from tickets.models import HandwerkerAuftrag
        HandwerkerAuftrag.alle_organisationen.filter(pk=self.auftrag.pk).update(
            status='erledigt', token_gueltig_bis=None)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_in_der_datenbank_steht_nur_der_hash(self):
        from django.forms.models import model_to_dict
        a = _neu(self.auftrag)
        self.assertEqual(a.token_hash, hashlib.sha256(self.token.encode()).hexdigest())
        self.assertNotEqual(a.token_hash, self.token)
        werte = ' '.join(str(v) for v in model_to_dict(a).values())
        werte += ' ' + ' '.join(str(getattr(a, f)) for f in ('token_hash', 'token_gueltig_bis',
                                                             'token_widerrufen_am'))
        self.assertNotIn(self.token, werte)
        self.assertEqual(len(self.token), 43)            # token_urlsafe(32)

    def test_neuer_link_ersetzt_den_alten(self):
        neu = _link(self.a, _neu(self.auftrag))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(f'/auftrag/{neu}/').status_code, 200)

    def test_fehlversuche_sperren_auch_den_gueltigen_link(self):
        import secrets
        from core.views.handwerker_portal import FEHLVERSUCHE
        for _ in range(FEHLVERSUCHE):
            self.client.get(f'/auftrag/{secrets.token_urlsafe(32)}/')
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_rate_limit_antwortet_429(self):
        with patch('core.views.handwerker_portal.ANFRAGEN', 2):
            self.client.get(self.url)
            self.client.get(self.url)
            self.assertEqual(self.client.get(self.url).status_code, 429)

    def test_oeffnen_steht_im_aktivitaetslog_der_richtigen_verwaltung(self):
        from core.models import AktivitaetsLog
        self.client.get(self.url)
        self.client.get(self.url)          # gedrosselt: ein Eintrag je Stunde
        eintraege = AktivitaetsLog.alle_organisationen.filter(aktion='Handwerker-Link geöffnet')
        self.assertEqual(eintraege.count(), 1)
        self.assertEqual(eintraege.first().organisation_id, self.a.organisation.pk)
        self.assertNotIn(self.token, eintraege.first().details)


class HandwerkerKeinZweiterAuftragTests(HandwerkerBasis):
    """Derselbe Token öffnet keinen anderen Auftrag derselben Verwaltung."""

    def setUp(self):
        super().setUp()
        from tickets.models import SchadenFoto
        self.zweiter = _auftrag(self.a, titel='Storen klemmen', tel='079 999 88 77')
        with organisation_kontext(self.a.organisation):
            self.foto_zweiter = SchadenFoto.objects.create(
                schaden=self.zweiter.ticket,
                bild=SimpleUploadedFile('storen.jpg', b'\xff\xd8\xff\xe0JFIF', content_type='image/jpeg'))

    def test_seite_zeigt_nichts_vom_zweiten_auftrag(self):
        r = self.client.get(self.url)
        self.assertNotContains(r, 'Storen klemmen')
        self.assertNotContains(r, '079 999 88 77')

    def test_foto_des_zweiten_auftrags_ist_nicht_adressierbar(self):
        r = self.client.get(f'/auftrag/{self.token}/foto/{self.foto_zweiter.pk}/')
        self.assertEqual(r.status_code, 404)
        # Gegenstück: über den eigenen Link geht dasselbe Foto.
        token2 = _link(self.a, self.zweiter)
        self.assertEqual(self.client.get(f'/auftrag/{token2}/foto/{self.foto_zweiter.pk}/').status_code, 200)

    def test_aktion_wirkt_nur_auf_den_eigenen_auftrag(self):
        from tickets.models import TicketNachricht
        self.client.post(self.url, {'aktion': 'nachricht', 'text': 'Komme morgen.'})
        self.assertTrue(TicketNachricht.alle_organisationen.filter(
            ticket=self.auftrag.ticket, nachricht='Komme morgen.').exists())
        self.assertFalse(TicketNachricht.alle_organisationen.filter(
            ticket=self.zweiter.ticket, nachricht='Komme morgen.').exists())


class HandwerkerLesendTests(HandwerkerBasis):
    """Nach dem Abschluss: lesen ja, handeln nein, Telefon und PDF weg."""

    def setUp(self):
        super().setUp()
        self.abgeschlossen = _abschliessen(self.a, self.auftrag)

    def test_frist_ist_30_tage_nach_abschluss(self):
        bis = self.abgeschlossen.token_gueltig_bis
        self.assertIsNotNone(bis)
        self.assertAlmostEqual((bis - timezone.now()).total_seconds(),
                               timedelta(days=30).total_seconds(), delta=120)

    def test_lesend_ohne_telefon_und_ohne_pdf(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-zustand="lesend"')
        self.assertNotContains(r, '079 111 22 33')          # weder im Feld …
        self.assertNotContains(r, 'melder@example.ch')       # … noch im Kontaktblock
        self.assertNotContains(r, 'data-karte="offerte"')
        self.assertEqual(self.client.get(f'/auftrag/{self.token}/pdf/').status_code, 404)

    def test_aktionen_werden_abgewiesen(self):
        from tickets.models import TicketNachricht
        vorher = TicketNachricht.alle_organisationen.filter(ticket=self.auftrag.ticket).count()
        r = self.client.post(self.url, {'aktion': 'nachricht', 'text': 'Noch etwas'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TicketNachricht.alle_organisationen.filter(
            ticket=self.auftrag.ticket).count(), vorher)
        self.assertEqual(_neu(self.auftrag).ticket.status, 'erledigt')

    def test_storno_macht_den_link_ebenfalls_lesend(self):
        from tickets.workflow import auftrag_stornieren
        a2 = _auftrag(self.a, titel='Storno-Fall')
        t2 = _link(self.a, a2)
        with organisation_kontext(self.a.organisation):
            auftrag_stornieren(_neu(a2))
        self.assertIsNotNone(_neu(a2).token_gueltig_bis)
        r = self.client.get(f'/auftrag/{t2}/')
        self.assertContains(r, 'data-zustand="lesend"')


class HandwerkerAktionenTests(HandwerkerBasis):
    """Offerte, Rechnung, Meldungen, Termin — über die bestehenden Wege."""

    def test_offerte_ueber_der_schwelle_fordert_die_freigabe_an(self):
        from tickets.workflow import REPARATUR_FREIGABE_SCHWELLE
        r = self.client.post(self.url, {'aktion': 'offerte', 'betrag': '1500.00', 'datei': _pdf('offerte.pdf')})
        self.assertEqual(r.status_code, 302)
        a = _neu(self.auftrag)
        self.assertEqual(a.kosten_geschaetzt, Decimal('1500.00'))
        self.assertGreaterEqual(a.kosten_geschaetzt, REPARATUR_FREIGABE_SCHWELLE)
        self.assertEqual(a.freigabe_status, 'ausstehend')
        # Eigentümer A bekommt die Anfrage per Mail (derselbe Text wie im fw-Weg).
        self.assertTrue(any('eig-a@example.ch' in m.to for m in mail.outbox))

    def test_offerte_unter_der_schwelle_braucht_keine_freigabe(self):
        self.client.post(self.url, {'aktion': 'offerte', 'betrag': '400', 'datei': _pdf('offerte.pdf')})
        a = _neu(self.auftrag)
        self.assertEqual(a.kosten_geschaetzt, Decimal('400.00'))
        self.assertEqual(a.freigabe_status, 'nicht_noetig')

    def test_offerte_liegt_unter_der_organisation(self):
        from tickets.models import TicketNachricht
        self.client.post(self.url, {'aktion': 'offerte', 'betrag': '400', 'datei': _pdf('offerte.pdf')})
        n = TicketNachricht.alle_organisationen.filter(ticket=self.auftrag.ticket).exclude(datei='').get()
        self.assertTrue(n.datei.name.startswith(f'organisation/{self.a.organisation.pk}/ticket_anhang/'),
                        n.datei.name)

    def test_rechnung_erzeugt_kreditoren_entwurf_unter_der_organisation(self):
        from finance.models import KreditorenRechnung
        r = self.client.post(self.url, {'aktion': 'rechnung', 'betrag': "1'240.50", 'datei': _pdf('rechnung.pdf')})
        self.assertEqual(r.status_code, 302)
        kr = KreditorenRechnung.alle_organisationen.get(handwerker=self.a.handwerker)
        self.assertEqual(kr.status, 'neu')
        self.assertEqual(kr.betrag, Decimal('1240.50'))
        self.assertEqual(kr.organisation_id, self.a.organisation.pk)
        self.assertTrue(kr.beleg_scan.name.startswith(
            f'organisation/{self.a.organisation.pk}/kreditoren_belege/'), kr.beleg_scan.name)
        a = _neu(self.auftrag)
        self.assertEqual(a.kreditoren_rechnung_id, kr.pk)       # verknüpft wie fw_auftrag_rechnung
        self.assertNotEqual(a.ticket.status, 'erledigt')        # abgeschlossen wird intern

    def test_zweite_rechnung_wird_abgelehnt(self):
        from finance.models import KreditorenRechnung
        self.client.post(self.url, {'aktion': 'rechnung', 'betrag': '100', 'datei': _pdf()})
        self.client.post(self.url, {'aktion': 'rechnung', 'betrag': '100', 'datei': _pdf()})
        self.assertEqual(KreditorenRechnung.alle_organisationen.filter(handwerker=self.a.handwerker).count(), 1)

    def test_falscher_dateityp_wird_abgelehnt(self):
        from finance.models import KreditorenRechnung
        for name, inhalt in (('rechnung.html', b'<script>alert(1)</script>'),
                             ('rechnung.pdf', b'<html>kein pdf</html>'),
                             ('rechnung.exe', b'MZ\x90\x00')):
            with self.subTest(datei=name):
                self.client.post(self.url, {'aktion': 'rechnung', 'betrag': '100',
                                            'datei': SimpleUploadedFile(name, inhalt)})
        self.assertFalse(KreditorenRechnung.alle_organisationen.filter(handwerker=self.a.handwerker).exists())
        self.assertIsNone(_neu(self.auftrag).kreditoren_rechnung_id)

    def test_zu_grosse_datei_wird_abgelehnt(self):
        from core.utils.uploads import MAX_DOKUMENT_BYTES
        gross = SimpleUploadedFile('offerte.pdf', PDF + b'0' * (MAX_DOKUMENT_BYTES + 1))
        self.client.post(self.url, {'aktion': 'offerte', 'betrag': '400', 'datei': gross})
        self.assertIsNone(_neu(self.auftrag).kosten_geschaetzt)

    def test_erledigt_melden_geht_ueber_den_workflow(self):
        self.client.post(self.url, {'aktion': 'erledigt'})
        self.assertEqual(_neu(self.auftrag).ticket.status, 'wartet_auf_rechnung')

    def test_nicht_erlaubter_uebergang_laesst_den_status_und_hinterlaesst_hinweis(self):
        from tickets.models import SchadenMeldung, TicketNachricht
        SchadenMeldung.alle_organisationen.filter(pk=self.auftrag.ticket_id).update(status='neu')
        self.client.post(self.url, {'aktion': 'erledigt'})
        self.assertEqual(_neu(self.auftrag).ticket.status, 'neu')
        self.assertTrue(TicketNachricht.alle_organisationen.filter(
            ticket_id=self.auftrag.ticket_id, typ='system', nachricht__contains='bitte prüfen').exists())

    def test_termin_setzen_und_bestaetigen(self):
        wann = (timezone.localtime() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
        self.client.post(self.url, {'aktion': 'termin', 'termin': wann.strftime('%Y-%m-%dT%H:%M')})
        a = _neu(self.auftrag)
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(timezone.localtime(a.termin_am).hour, 9)
        self.assertEqual(a.ticket.status, 'warte_auf_handwerker')    # termin_festlegen
        self.client.post(self.url, {'aktion': 'termin_bestaetigen'})
        from tickets.models import TicketNachricht
        self.assertTrue(TicketNachricht.alle_organisationen.filter(
            ticket=a.ticket, nachricht__contains='bestätigt den Termin').exists())

    def test_termin_in_der_vergangenheit_wird_abgelehnt(self):
        gestern = timezone.localtime() - timedelta(days=1)
        self.client.post(self.url, {'aktion': 'termin', 'termin': gestern.strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(_neu(self.auftrag).termin_status, 'offen')

    def test_nachricht_ist_handwerker_mail_vom_handwerker(self):
        from tickets.models import TicketNachricht
        self.client.post(self.url, {'aktion': 'nachricht', 'text': 'Ersatzteil bestellt.'})
        n = TicketNachricht.alle_organisationen.get(nachricht='Ersatzteil bestellt.')
        self.assertEqual(n.typ, 'handwerker_mail')
        self.assertTrue(n.is_intern)
        self.assertFalse(n.is_von_verwaltung)
        self.assertEqual(n.empfaenger_handwerker_id, self.a.handwerker.pk)
        self.assertFalse(_neu(self.auftrag).ticket.gelesen)


class AuftragsMailTests(_MedienWurzel):
    """Der Link geht in der bestehenden Auftrags-Mail mit — nur dort im Klartext."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_mail_enthaelt_den_link_und_die_db_nur_den_hash(self):
        import re
        from tickets.models import TicketNachricht
        from tickets.workflow import arbeitsauftrag_senden
        with organisation_kontext(self.a.organisation):
            self.a.handwerker.email = 'hw-a@example.ch'
            self.a.handwerker.save()
        a = _auftrag(self.a)
        with organisation_kontext(self.a.organisation):
            _pdf_bytes, versendet = arbeitsauftrag_senden(_neu(a))
        self.assertTrue(versendet)
        body = mail.outbox[-1].body
        treffer = re.search(r'/auftrag/([A-Za-z0-9_-]{43})/', body)
        self.assertIsNotNone(treffer, body)
        token = treffer.group(1)
        self.assertEqual(_neu(a).token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertFalse(TicketNachricht.alle_organisationen.filter(nachricht__contains=token).exists())
        self.assertEqual(Client().get(f'/auftrag/{token}/').status_code, 200)


class LinkVerwaltungTests(_MedienWurzel):
    """Reiter «Handwerker»: widerrufen und neu erzeugen, nur im eigenen Bestand."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        super().setUp()
        self.c = Client(raise_request_exception=False)
        self.c.force_login(self.a.benutzer)

    def test_neu_erzeugen_zeigt_den_link_einmal(self):
        import re
        r = self.c.post(f'/neu/auftrag/{self.a.auftrag.pk}/link/', {'aktion': 'neu'})
        self.assertEqual(r.status_code, 200)
        token = re.search(r'/auftrag/([A-Za-z0-9_-]{43})/', r.content.decode()).group(1)
        self.assertEqual(Client().get(f'/auftrag/{token}/').status_code, 200)
        # Der Reiter zeigt den Zustand, aber nie den Klartext.
        detail = self.c.get(f'/neu/schaeden/{self.a.schaden.pk}/?tab=handwerker')
        self.assertContains(detail, 'data-link-status="aktiv"')
        self.assertNotContains(detail, token)

    def test_widerrufen(self):
        token = _link(self.a, self.a.auftrag)
        self.c.post(f'/neu/auftrag/{self.a.auftrag.pk}/link/', {'aktion': 'widerrufen'})
        self.assertEqual(Client().get(f'/auftrag/{token}/').status_code, 404)

    def test_fremder_auftrag_404_und_unveraendert(self):
        token_b = _link(self.b, self.b.auftrag)
        for aktion in ('neu', 'widerrufen'):
            with self.subTest(aktion=aktion):
                r = self.c.post(f'/neu/auftrag/{self.b.auftrag.pk}/link/', {'aktion': aktion})
                self.assertEqual(r.status_code, 404)
        self.assertEqual(Client().get(f'/auftrag/{token_b}/').status_code, 200)

    def test_lesende_rolle_darf_nicht(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from crm.models import Mitgliedschaft
        u = get_user_model().objects.create_user(username='lesend_m3', password='x')
        u.groups.add(Group.objects.get_or_create(name='Lesend')[0])
        with organisation_kontext(self.a.organisation):
            Mitgliedschaft.objects.create(benutzer=u, organisation=self.a.organisation,
                                          rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        c = Client(raise_request_exception=False)
        c.force_login(u)
        r = c.post(f'/neu/auftrag/{self.a.auftrag.pk}/link/', {'aktion': 'neu'})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(_neu(self.a.auftrag).token_hash)


class AblagepfadeTests(_MedienWurzel):
    """Neue Uploads unter organisation/<id>/, alte bleiben geschützt."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _anlegen(self, rel):
        pfad = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, 'wb') as fh:
            fh.write(PDF)

    def test_neue_pfade_tragen_die_organisation(self):
        from finance.models import KreditorenRechnung
        from tickets.models import TicketNachricht
        with organisation_kontext(self.a.organisation):
            n = TicketNachricht(ticket=self.a.schaden, absender_name='x', nachricht='x')
            n.datei = _pdf('anhang.pdf')
            n.save()
            kr = KreditorenRechnung(lieferant='x', betrag=Decimal('1'), liegenschaft=self.a.liegenschaft)
            kr.beleg_scan = _pdf('beleg.pdf')
            kr.save()
        org = self.a.organisation.pk
        self.assertTrue(n.datei.name.startswith(f'organisation/{org}/ticket_anhang/'), n.datei.name)
        self.assertTrue(kr.beleg_scan.name.startswith(f'organisation/{org}/kreditoren_belege/'),
                        kr.beleg_scan.name)

    def test_beide_pfadformen_bleiben_geschuetzt_und_pruefen_die_organisation(self):
        from finance.models import KreditorenRechnung
        from tickets.models import TicketNachricht
        org_b = self.b.organisation.pk
        alt_anhang, alt_beleg = 'ticket_anhang/alt-b.pdf', 'kreditoren_belege/alt-b.pdf'
        neu_anhang = f'organisation/{org_b}/ticket_anhang/2026-10-27/neu-b.pdf'
        neu_beleg = f'organisation/{org_b}/kreditoren_belege/2026-10-27/neu-b.pdf'
        for rel in (alt_anhang, alt_beleg, neu_anhang, neu_beleg):
            self._anlegen(rel)
        # Die alten Pfade gehören B laut Datenbank (kein Präfix, keine Verschiebung).
        with organisation_kontext(self.b.organisation):
            TicketNachricht.objects.create(ticket=self.b.schaden, absender_name='x', nachricht='x',
                                           datei=alt_anhang)
            KreditorenRechnung.objects.create(lieferant='x', betrag=Decimal('1'),
                                              liegenschaft=self.b.liegenschaft, beleg_scan=alt_beleg)
        team_a, team_b = Client(), Client()
        team_a.force_login(self.a.benutzer)
        team_b.force_login(self.b.benutzer)
        for rel in (alt_anhang, alt_beleg, neu_anhang, neu_beleg):
            with self.subTest(pfad=rel):
                self.assertEqual(Client().get('/media/' + rel).status_code, 404, 'anonym')
                self.assertEqual(team_a.get('/media/' + rel).status_code, 404, 'fremde Verwaltung')
                self.assertEqual(team_b.get('/media/' + rel).status_code, 200, 'eigene Verwaltung')


# ===========================================================================
# Mieterportal
# ===========================================================================

class MieterBasis(_MedienWurzel):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        User = get_user_model()
        for fx in (cls.a, cls.b):
            u = User.objects.create_user(username=f'mieter_m3_{fx.kuerzel.lower()}', password='x')
            with organisation_kontext(fx.organisation):
                fx.mieter.benutzer = u
                fx.mieter.save()
            fx.mieter_login = u

    def setUp(self):
        super().setUp()
        self.c = Client(raise_request_exception=False)
        self.c.force_login(self.a.mieter_login)

    def _ticket(self, fx, titel, einheit=None, gemeldet_von=None, erstellt=None, **extra):
        from tickets.models import SchadenMeldung
        with organisation_kontext(fx.organisation):
            t = SchadenMeldung.objects.create(
                liegenschaft=fx.liegenschaft, betroffene_einheit=einheit, gemeldet_von=gemeldet_von,
                titel=titel, beschreibung=extra.pop('beschreibung', 'Beschreibung'), **extra)
        if erstellt:
            SchadenMeldung.alle_organisationen.filter(pk=t.pk).update(erstellt_am=erstellt)
        return t


class MieterStartTests(MieterBasis):

    def test_startseite_zeigt_die_fuenf_kacheln(self):
        r = self.c.get('/mieter/')
        self.assertEqual(r.status_code, 200)
        for k in ('melden', 'meldungen', 'dokumente', 'rechnungen', 'schluessel'):
            self.assertContains(r, f'data-kachel="{k}"')
        self.assertContains(r, 'fw-kachel akzent b-l" data-kachel="melden"')
        self.assertContains(r, 'Ihr Mietobjekt')
        self.assertContains(r, 'S-A-01')                  # offene Schlüsselausgabe des Fixtures

    def test_zurueckgegebener_schluessel_fehlt_und_leerer_zustand(self):
        from portfolio.models import SchluesselAusgabe
        SchluesselAusgabe.alle_organisationen.filter(mieter=self.a.mieter).update(rueckgabe_am=date.today())
        r = self.c.get('/mieter/')
        self.assertNotContains(r, 'S-A-01')
        self.assertContains(r, 'Keine Schlüssel erfasst.')

    def test_meldungen_kachel_zaehlt_offene_und_nennt_den_termin(self):
        from tickets.models import HandwerkerAuftrag
        t = self._ticket(self.a, 'Lavabo verstopft', einheit=self.a.einheit, status='in_bearbeitung')
        self._ticket(self.a, 'Erledigtes', einheit=self.a.einheit, status='erledigt')
        wann = timezone.now() + timedelta(days=3)
        with organisation_kontext(self.a.organisation):
            HandwerkerAuftrag.objects.create(ticket=t, handwerker=self.a.handwerker,
                                             termin_am=wann, termin_status='vereinbart')
        r = self.c.get('/mieter/')
        inhalt = r.content.decode()
        kachel = inhalt[inhalt.index('data-kachel="meldungen"'):inhalt.index('data-kachel="dokumente"')]
        # Fixture-Schaden (neu) + «Lavabo verstopft» = 2 offen; «Erledigtes» zählt nicht.
        self.assertIn('>2<small>', kachel)
        self.assertIn(timezone.localtime(wann).strftime('%d.%m.'), kachel)

    def test_uebrige_seiten_bleiben_erreichbar(self):
        for pfad in ('/mieter/rechnungen/', '/mieter/dokumente/', '/mieter/tickets/', '/mieter/konto/',
                     '/mieter/kuendigung/', '/mieter/daten/', '/mieter/schaden/neu/'):
            with self.subTest(pfad=pfad):
                self.assertEqual(self.c.get(pfad).status_code, 200)


class MieterTicketSichtTests(MieterBasis):

    def test_telefonisch_erfasstes_ticket_der_einheit_ist_sichtbar(self):
        t = self._ticket(self.a, 'Telefonisch: Rollladen', einheit=self.a.einheit,
                         beschreibung='Rollladen klemmt.\n\n--- KONTAKT ---\nName: Nachbar Muster\n'
                                      'Tel: 044 123 45 67\nEmail: nachbar@example.ch\n')
        self.assertContains(self.c.get('/mieter/tickets/'), 'Telefonisch: Rollladen')
        r = self.c.get(f'/mieter/ticket/{t.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Rollladen klemmt.')
        self.assertNotContains(r, '044 123 45 67')           # Kontakt eines anderen Melders
        self.assertNotContains(r, 'nachbar@example.ch')

    def test_ticket_vor_dem_mietbeginn_bleibt_verborgen(self):
        t = self._ticket(self.a, 'Vom Vormieter', einheit=self.a.einheit,
                         erstellt=timezone.make_aware(timezone.datetime(2023, 6, 1, 10, 0)))
        self.assertNotContains(self.c.get('/mieter/tickets/'), 'Vom Vormieter')
        self.assertEqual(self.c.get(f'/mieter/ticket/{t.pk}/').status_code, 404)

    def test_ticket_nach_dem_vertragsende_bleibt_verborgen(self):
        from rentals.models import Mietvertrag
        Mietvertrag.alle_organisationen.filter(pk=self.a.vertrag.pk).update(
            ende=date.today() - timedelta(days=10))
        t = self._ticket(self.a, 'Vom Nachmieter', einheit=self.a.einheit)
        self.assertEqual(self.c.get(f'/mieter/ticket/{t.pk}/').status_code, 404)

    def test_fremdes_ticket_ergibt_404(self):
        fremd_b = self._ticket(self.b, 'Fremd B', einheit=self.b.einheit)
        andere_einheit = self._ticket(self.a, 'Treppenhaus A', einheit=None)
        for t in (fremd_b, andere_einheit):
            with self.subTest(ticket=t.titel):
                self.assertEqual(self.c.get(f'/mieter/ticket/{t.pk}/').status_code, 404)
                r = self.c.post(f'/mieter/ticket/{t.pk}/nachricht/', {'text': 'hallo'})
                self.assertEqual(r.status_code, 404)
        liste = self.c.get('/mieter/tickets/').content.decode()
        self.assertNotIn('Fremd B', liste)
        self.assertNotIn('Treppenhaus A', liste)

    def test_interne_notizen_und_handwerker_mails_bleiben_verborgen(self):
        from tickets.models import TicketNachricht
        t = self._ticket(self.a, 'Mit Verlauf', einheit=self.a.einheit, gemeldet_von=self.a.mieter)
        with organisation_kontext(self.a.organisation):
            TicketNachricht.objects.create(ticket=t, absender_name='Team', nachricht='INTERN GEHEIM',
                                           is_intern=True)
            TicketNachricht.objects.create(ticket=t, absender_name='HW', typ='handwerker_mail',
                                           nachricht='HANDWERKER INTERN')
            TicketNachricht.objects.create(ticket=t, absender_name='Verwaltung', typ='antwort_senden',
                                           nachricht='Wir kümmern uns.', is_von_verwaltung=True)
        r = self.c.get(f'/mieter/ticket/{t.pk}/')
        self.assertNotContains(r, 'INTERN GEHEIM')
        self.assertNotContains(r, 'HANDWERKER INTERN')
        self.assertContains(r, 'Wir kümmern uns.')

    def test_detail_zeigt_termin_und_zutritt(self):
        from tickets.models import HandwerkerAuftrag
        t = self._ticket(self.a, 'Mit Termin', einheit=self.a.einheit, zutritt='passpartout')
        wann = timezone.now() + timedelta(days=2)
        with organisation_kontext(self.a.organisation):
            HandwerkerAuftrag.objects.create(ticket=t, handwerker=self.a.handwerker,
                                             termin_am=wann, termin_status='vereinbart')
        r = self.c.get(f'/mieter/ticket/{t.pk}/')
        self.assertContains(r, 'Sanitaer A GmbH kommt am')
        self.assertContains(r, timezone.localtime(wann).strftime('%d.%m.%Y, %H:%M'))
        self.assertContains(r, 'Passpartout')


class MieterMeldungTests(MieterBasis):

    def test_meldung_speichert_kategorie_zutritt_und_erreichbarkeit(self):
        from tickets.models import SchadenMeldung
        r = self.c.post('/mieter/schaden/', {
            'vertrag_id': self.a.vertrag.pk, 'titel': 'Herd defekt', 'beschreibung': 'Platte bleibt kalt',
            'kategorie': 'Allgemeine Anfrage', 'zutritt': 'passpartout',
            'erreichbarkeit': ['14:00 - 16:00', '08:00 - 10:00', 'erfunden']})
        self.assertEqual(r.status_code, 302)
        t = SchadenMeldung.alle_organisationen.get(titel='Herd defekt')
        self.assertEqual(t.kategorie, 'Allgemeine Anfrage')
        self.assertEqual(t.zutritt, 'passpartout')
        self.assertIn('Erreichbar: 08:00 - 10:00, 14:00 - 16:00', t.beschreibung)
        self.assertNotIn('erfunden', t.beschreibung)

    def test_unbekannte_werte_fallen_auf_die_vorgabe_zurueck(self):
        from tickets.models import SchadenMeldung
        self.c.post('/mieter/schaden/', {
            'vertrag_id': self.a.vertrag.pk, 'titel': 'Fenster', 'beschreibung': 'zieht',
            'kategorie': '<b>frei</b>', 'zutritt': 'tuer_offen'})
        t = SchadenMeldung.alle_organisationen.get(titel='Fenster')
        self.assertEqual(t.kategorie, 'Schadensmeldung')
        self.assertEqual(t.zutritt, 'telefon')

    def test_formular_bietet_die_werte_aus_dem_bestand_an(self):
        from tickets.meldung import ZEITFENSTER
        from tickets.models import SchadenMeldung
        r = self.c.get('/mieter/schaden/neu/')
        for wert, _ in SchadenMeldung.ZUTRITT_CHOICES:
            self.assertContains(r, f'name="zutritt" value="{wert}"')
        for fenster in ZEITFENSTER:
            self.assertContains(r, f'name="erreichbarkeit" value="{fenster}"')
        self.assertContains(r, '<option value="Schlüsselbestellung">')


class MieterNachrichtWorkflowTests(MieterBasis):
    """Die Nachricht des Mieters nutzt den erlaubten Übergang — nicht das Feld."""

    def _erledigtes_ticket(self):
        t = self._ticket(self.a, 'Erledigt', einheit=self.a.einheit, gemeldet_von=self.a.mieter)
        from tickets.models import SchadenMeldung
        SchadenMeldung.alle_organisationen.filter(pk=t.pk).update(status='erledigt')
        return t

    def test_erledigtes_ticket_wird_ueber_den_workflow_geoeffnet(self):
        from tickets.models import SchadenMeldung, TicketNachricht
        t = self._erledigtes_ticket()
        with patch('tickets.workflow.wechsle_status', wraps=__import__(
                'tickets.workflow', fromlist=['x']).wechsle_status) as wechsel:
            self.c.post(f'/mieter/ticket/{t.pk}/nachricht/', {'text': 'Tropft wieder.'})
        self.assertTrue(wechsel.called)
        self.assertEqual(SchadenMeldung.alle_organisationen.get(pk=t.pk).status, 'in_bearbeitung')
        self.assertTrue(TicketNachricht.alle_organisationen.filter(
            ticket=t, typ='system', nachricht__contains='wieder geöffnet').exists())

    def test_ohne_erlaubten_uebergang_bleibt_der_status_und_es_gibt_einen_hinweis(self):
        from tickets.models import SchadenMeldung, TicketNachricht
        from tickets import workflow
        t = self._erledigtes_ticket()
        with patch.dict(workflow.UEBERGAENGE, {'erledigt': set()}):
            self.c.post(f'/mieter/ticket/{t.pk}/nachricht/', {'text': 'Noch eine Frage.'})
        self.assertEqual(SchadenMeldung.alle_organisationen.get(pk=t.pk).status, 'erledigt')
        self.assertTrue(TicketNachricht.alle_organisationen.filter(
            ticket=t, typ='system', is_intern=True, nachricht__contains='Status bleibt').exists())
        self.assertTrue(TicketNachricht.alle_organisationen.filter(
            ticket=t, nachricht='Noch eine Frage.').exists())

    def test_antwort_auf_warte_auf_mieter_geht_zurueck_an_die_verwaltung(self):
        from tickets.models import SchadenMeldung
        t = self._ticket(self.a, 'Rückfrage', einheit=self.a.einheit, gemeldet_von=self.a.mieter,
                         status='warte_auf_mieter')
        self.c.post(f'/mieter/ticket/{t.pk}/nachricht/', {'text': 'Montag passt.'})
        self.assertEqual(SchadenMeldung.alle_organisationen.get(pk=t.pk).status, 'in_bearbeitung')


class KontaktblockTests(TestCase):

    def test_kontaktblock_fehlt_erreichbarkeit_und_geraet_bleiben(self):
        from tickets.meldung import ohne_kontaktblock
        text = ('Kühlschrank kühlt nicht\n\n--- KONTAKT ---\nName: Frau X\nTel: 079 1\n'
                'Email: x@example.ch\nErreichbar: 08:00 - 10:00\n\n--- GERÄT ---\nMarke: V-Zug\n')
        aus = ohne_kontaktblock(text)
        self.assertIn('Kühlschrank kühlt nicht', aus)
        self.assertIn('Erreichbar: 08:00 - 10:00', aus)
        self.assertIn('Marke: V-Zug', aus)
        for weg in ('Frau X', '079 1', 'x@example.ch'):
            self.assertNotIn(weg, aus)
        self.assertEqual(ohne_kontaktblock('ohne Block'), 'ohne Block')

