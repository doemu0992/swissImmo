"""Direktkanal Mieter <-> Handwerker (Chat + Mail, gleichwertig und synchron) und Terminabstimmung.

Anlass (3.11.2026): Ein Mieter antwortete auf die Terminmail «Termin passt nicht, können Sie am 05.11. um
17:00?». Die Antwort landete nur im Verlauf der Verwaltung, der Handwerker erfuhr nichts, der Termin blieb
«vereinbart». Jetzt stimmen Mieter und Handwerker sich direkt ab; die Verwaltung liest mit und wird nur
informiert, wenn der Termin steht oder abgesagt wird.

Jede Klasse nennt ihre GEGENPROBE im Docstring (Code temporär ändern -> der Test wird rot).
"""
import re
from datetime import timedelta
from email.message import EmailMessage
from unittest import mock

from django.core import mail, signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.tenancy import organisation_kontext

from ._helfer import _team_user, _test_organisation
from ._isolation import MandantenFixture
from .test_ticket_workflow import MAIL, _handwerker, _ticket

MIETER = 'hans@example.ch'            # `_basis_objekte`
HANDWERKER = 'hw@example.ch'          # `_handwerker`
VERWALTUNG = 'verwaltung@example.ch'


def _auftrag_einfach():
    """Ticket (Melder Hans Muster) + Auftrag an «Sanitär AG»; die Verwaltung hat eine Mailadresse."""
    from tickets.workflow import handwerker_zuweisen
    _test_organisation(email=VERWALTUNG)
    t = _ticket()
    a = handwerker_zuweisen(t, _handwerker())
    mail.outbox.clear()
    return t, a


def _an(adresse):
    return [m for m in mail.outbox if adresse in m.to]


def _text(m):
    return m.body + ''.join(a[0] for a in getattr(m, 'alternatives', []))


def _kopf(m):
    """Die Kopfzeilen einer ausgehenden Mail, wie sie ein Empfangsserver als Mapping sähe."""
    return dict(m.extra_headers)


def _zeit(tage=2, stunde=9):
    return (timezone.localtime() + timedelta(days=tage)).replace(hour=stunde, minute=0, second=0, microsecond=0)


@MAIL
class ChatNachMailTests(TestCase):
    """Chat -> Mail: Wer im Chat schreibt, dessen Gegenseite bekommt dieselbe Nachricht per Mail.

    Gegenprobe: in `direktkanal.schreiben` den Aufruf `zustellung_pruefen` auskommentieren -> die
    Mail-Tests sind rot. Gegenprobe Isolation von Adressen: in `_mail_senden` `absender_name=...` entfernen
    -> `test_absender_nennt_nie_die_adresse_der_gegenseite` rot.
    """

    def test_mieter_schreibt_handwerker_bekommt_mail_mit_link_und_marke(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Termin passt nicht, geht der 05.11. um 17:00?')
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, [HANDWERKER])
        self.assertIn(f'[A{a.pk}]', m.subject)
        self.assertIn(f'Ticket #{t.pk}', m.subject)
        self.assertIn('Termin passt nicht', _text(m))
        self.assertIn('/direkt/', _text(m))                  # Link zum Chat
        self.assertIn('Muster via', m.from_email)            # «<Name> via immoswiss», nicht die Firma der Verwaltung
        self.assertNotIn('Testverwaltung', m.from_email)
        n = a.direktnachrichten.get()
        self.assertEqual((n.typ, n.seite, n.is_intern, n.gelesen), ('direkt', 'mieter', True, True))
        self.assertIsNotNone(n.zugestellt_am)

    def test_handwerker_schreibt_mieter_bekommt_mail(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'handwerker', 'Dienstag 5.11., 17:00 ginge bei mir.')
        self.assertEqual([m.to for m in mail.outbox], [[MIETER]])
        self.assertIn('Dienstag 5.11.', _text(mail.outbox[0]))
        self.assertIn(f'[A{a.pk}]', mail.outbox[0].subject)

    def test_verwaltung_schreibt_beide_seiten_bekommen_die_mail(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'verwaltung', 'Bitte bis Freitag klären.', name='Frau Meier')
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted([HANDWERKER, MIETER]))
        n = a.direktnachrichten.get()
        self.assertTrue(n.is_von_verwaltung)
        self.assertEqual(n.seite, 'verwaltung')

    def test_absender_bekommt_seine_nachricht_nicht_zurueck(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Hallo')
        direktkanal.schreiben(a, 'handwerker', 'Hallo zurück')
        self.assertEqual(len(_an(HANDWERKER)), 1)
        self.assertEqual(len(_an(MIETER)), 1)
        self.assertNotIn('Hallo zurück', _text(_an(HANDWERKER)[0]))

    def test_absender_nennt_nie_die_adresse_der_gegenseite(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Hallo')
        direktkanal.schreiben(a, 'handwerker', 'Hallo zurück')
        for m in mail.outbox:
            roh = m.message().as_string() + _text(m)
            self.assertNotIn(MIETER if m.to == [HANDWERKER] else HANDWERKER, roh)

    def test_schleifenschutz_kopfzeilen_an_der_weiterleitung(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Hallo')
        kopf = _kopf(mail.outbox[0])
        self.assertEqual(kopf.get('X-Immoswiss-Bridge'), '1')
        self.assertEqual(kopf.get('Auto-Submitted'), 'auto-generated')

    def test_die_verwaltung_wird_durch_den_chat_nicht_benachrichtigt(self):
        """Mitleser: Verlauf ja, Mail und Ungelesen-Badge nein."""
        from tickets import direktkanal
        from tickets.models import TicketNachricht
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Hallo')
        direktkanal.schreiben(a, 'handwerker', 'Hallo zurück')
        self.assertEqual(_an(VERWALTUNG), [])
        self.assertFalse(TicketNachricht.objects.filter(gelesen=False, typ='direkt').exists())

    def test_leer_zu_lang_und_unbekannte_seite(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        for text in ('', '   '):
            with self.assertRaises(ValidationError):
                direktkanal.schreiben(a, 'mieter', text)
        with self.assertRaises(ValidationError):
            direktkanal.schreiben(a, 'mieter', 'x' * (direktkanal.MAX_LAENGE + 1))
        with self.assertRaises(ValidationError):
            direktkanal.schreiben(a, 'eigentuemer', 'hallo')
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_geschlossener_auftrag_nimmt_nichts_mehr_an(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        a.status = 'erledigt'
        a.save()
        with self.assertRaises(ValidationError):
            direktkanal.schreiben(a, 'mieter', 'Noch was')
        self.assertEqual(a.direktnachrichten.count(), 0)

    def test_gegenseite_ohne_adresse_nachricht_bleibt_im_chat_kein_fehler(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        a.handwerker.email = ''
        a.handwerker.save()
        direktkanal.schreiben(a, 'mieter', 'Hallo')
        self.assertEqual(mail.outbox, [])
        self.assertEqual(a.direktnachrichten.count(), 1)


@MAIL
class BuendelungTests(TestCase):
    """Mehrere Chat-Nachrichten kurz hintereinander fluten die Gegenseite nicht.

    Die erste geht sofort, weitere innerhalb von `BUENDELUNG` (1 Minute) warten und gehen gesammelt in EINER
    Mail hinaus (`fetch_replies` ruft `ausstehende_zustellen` jede Minute).

    Gegenprobe: `BUENDELUNG = timedelta(0)` -> `test_fuenf_nachrichten_ergeben_zwei_mails` rot.
    """

    def test_fuenf_nachrichten_ergeben_zwei_mails(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        t0 = timezone.now()
        direktkanal.schreiben(a, 'mieter', 'Erste Nachricht', jetzt=t0)
        for i, text in enumerate(('Zweite', 'Dritte', 'Vierte', 'Fuenfte'), start=1):
            direktkanal.schreiben(a, 'mieter', f'{text} Nachricht', jetzt=t0 + timedelta(seconds=10 * i))
        self.assertEqual(len(mail.outbox), 1)                        # nur die erste ist hinaus
        self.assertEqual(a.direktnachrichten.filter(zugestellt_am__isnull=True).count(), 4)
        self.assertEqual(direktkanal.ausstehende_zustellen(jetzt=t0 + timedelta(seconds=50)), 0)
        self.assertEqual(len(mail.outbox), 1)                        # Fenster noch offen
        self.assertEqual(direktkanal.ausstehende_zustellen(jetzt=t0 + timedelta(minutes=2)), 1)
        self.assertEqual(len(mail.outbox), 2)
        sammel = _text(mail.outbox[1])
        for wort in ('Zweite', 'Dritte', 'Vierte', 'Fuenfte'):
            self.assertIn(f'{wort} Nachricht', sammel)
        self.assertNotIn('Erste Nachricht', sammel)                  # nie doppelt zugestellt
        self.assertEqual(direktkanal.ausstehende_zustellen(jetzt=t0 + timedelta(minutes=30)), 0)
        self.assertEqual(len(mail.outbox), 2)

    def test_nach_dem_fenster_geht_die_naechste_nachricht_sofort_samt_wartenden(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        t0 = timezone.now()
        direktkanal.schreiben(a, 'handwerker', 'Eins', jetzt=t0)
        direktkanal.schreiben(a, 'handwerker', 'Zwei', jetzt=t0 + timedelta(seconds=30))
        direktkanal.schreiben(a, 'handwerker', 'Drei', jetzt=t0 + timedelta(minutes=10))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('Zwei', _text(mail.outbox[1]))
        self.assertIn('Drei', _text(mail.outbox[1]))

    def test_die_seiten_buendeln_unabhaengig(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        t0 = timezone.now()
        direktkanal.schreiben(a, 'mieter', 'M1', jetzt=t0)
        direktkanal.schreiben(a, 'handwerker', 'H1', jetzt=t0 + timedelta(seconds=10))
        self.assertEqual(len(mail.outbox), 2)                        # beide ersten gehen sofort


@MAIL
class MailNachChatTests(TestCase):
    """Mail -> Chat -> Mail an die Gegenseite (`antwort_zuordnen` mit Auftragsmarke).

    Gegenprobe: in `workflow.antwort_zuordnen` den Aufruf `direktkanal.aus_mail` auskommentieren -> rot.
    """

    def test_mieter_antwort_landet_im_chat_und_beim_handwerker(self):
        """Der Fall aus dem Anlass: «Termin passt nicht, können Sie am 05.11. um 17:00?»."""
        from tickets.models import TicketNachricht
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        seite = antwort_zuordnen(t, 'Hans Muster <Hans@Example.ch>',
                                 'Termin passt nicht, können Sie am 05.11. um 17:00?', auftrag_id=a.pk)
        self.assertEqual(seite, 'direkt_mieter')
        n = a.direktnachrichten.get()
        self.assertEqual((n.seite, n.typ), ('mieter', 'direkt'))
        self.assertIn('05.11. um 17:00', n.nachricht)
        self.assertFalse(TicketNachricht.objects.filter(typ='mail_antwort').exists())   # nicht nur im Verlauf
        self.assertEqual([m.to for m in mail.outbox], [[HANDWERKER]])
        self.assertIn('05.11. um 17:00', _text(mail.outbox[0]))
        self.assertEqual(_an(VERWALTUNG), [])

    def test_handwerker_antwort_geht_an_den_mieter(self):
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        seite = antwort_zuordnen(t, 'Sanitär AG <hw@example.ch>', 'Ja, 17:00 passt.', auftrag_id=a.pk)
        self.assertEqual(seite, 'direkt_handwerker')
        self.assertEqual([m.to for m in mail.outbox], [[MIETER]])
        self.assertEqual(a.direktnachrichten.get().seite, 'handwerker')

    def test_unbekannter_absender_bleibt_im_verlauf_und_wird_nicht_weitergeleitet(self):
        from tickets.models import TicketNachricht
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        seite = antwort_zuordnen(t, 'Fremder <fremder@example.org>', 'Hallo?', auftrag_id=a.pk)
        self.assertEqual(seite, 'melder')                      # wie bisher
        self.assertTrue(TicketNachricht.objects.filter(typ='mail_antwort', nachricht='Hallo?').exists())
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_ohne_auftragsmarke_gilt_der_bisherige_weg(self):
        from tickets.models import TicketNachricht
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        seite = antwort_zuordnen(t, 'hans@example.ch', 'Frage an die Verwaltung')
        self.assertEqual(seite, 'melder')
        self.assertTrue(TicketNachricht.objects.filter(typ='mail_antwort').exists())
        self.assertEqual(mail.outbox, [])

    def test_automatische_mails_werden_nicht_weitergeleitet(self):
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        faelle = [
            ('hans@example.ch', {'Auto-Submitted': 'auto-replied'}),
            ('hans@example.ch', {'X-Autoreply': 'yes'}),
            ('hans@example.ch', {'Precedence': 'bulk'}),
            ('MAILER-DAEMON@example.ch', {}),
            ('hw@example.ch', {'X-Immoswiss-Bridge': '1'}),
            ('hw@example.ch', {'Return-Path': '<>'}),
        ]
        for absender, kopf in faelle:
            with self.subTest(absender=absender, kopf=kopf):
                antwort_zuordnen(t, absender, 'Ich bin bis Montag abwesend.', auftrag_id=a.pk, kopf=kopf)
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_eigene_absenderadresse_wird_nicht_weitergeleitet(self):
        from django.conf import settings
        from tickets.workflow import antwort_zuordnen
        from email.utils import parseaddr
        t, a = _auftrag_einfach()
        # Die Adresse des Handwerkers ist (versehentlich/Weiterleitungsregel) die Absenderadresse der Plattform:
        # eine Mail von ihr ist unser eigenes Echo und wird nicht noch einmal weitergeleitet.
        a.handwerker.email = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        a.handwerker.save()
        antwort_zuordnen(t, settings.DEFAULT_FROM_EMAIL, 'Echo', auftrag_id=a.pk)
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_marke_eines_fremden_tickets_wird_nicht_beachtet(self):
        from tickets.workflow import antwort_zuordnen, handwerker_zuweisen
        t, a = _auftrag_einfach()
        t2 = _ticket()
        a2 = handwerker_zuweisen(t2, _handwerker())
        mail.outbox.clear()
        antwort_zuordnen(t, 'hans@example.ch', 'Frage', auftrag_id=a2.pk)     # Marke gehört zu t2
        self.assertEqual(a2.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_kreislauf_die_weitergeleitete_mail_loest_keine_zweite_aus(self):
        """Die Mail an den Handwerker kommt (z. B. über eine Weiterleitungsregel) zurück: Schluss."""
        from tickets import direktkanal
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Hallo')
        gesendet = mail.outbox[0]
        mail.outbox.clear()
        antwort_zuordnen(t, 'hw@example.ch', _text(gesendet), auftrag_id=a.pk, kopf=_kopf(gesendet))
        self.assertEqual(a.direktnachrichten.count(), 1)
        self.assertEqual(mail.outbox, [])

    def test_geschlossener_auftrag_geht_den_alten_weg(self):
        from tickets.models import TicketNachricht
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        a.status = 'storniert'
        a.save()
        antwort_zuordnen(t, 'hans@example.ch', 'Zu spät', auftrag_id=a.pk)
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertTrue(TicketNachricht.objects.filter(typ='mail_antwort').exists())

    def test_abrufbefehl_liest_die_marke_aus_dem_betreff(self):
        from core.management.commands.fetch_replies import Command
        t, a = _auftrag_einfach()
        m = EmailMessage()
        m['Subject'] = f'Re: Termin für Ihre Reparatur (Ticket #{t.pk}) [A{a.pk}]'
        m['From'] = 'Hans Muster <hans@example.ch>'
        m.set_content('Geht auch der 05.11. um 17:00?\n\nAm 01.11.2026 schrieb Verwaltung via immoswiss schrieb am: alt')
        Command().verarbeite_mail(m.as_bytes())
        n = a.direktnachrichten.get()
        self.assertEqual(n.nachricht, 'Geht auch der 05.11. um 17:00?')
        self.assertEqual([x.to for x in mail.outbox], [[HANDWERKER]])

    def test_abrufbefehl_ignoriert_eine_abwesenheitsnotiz(self):
        from core.management.commands.fetch_replies import Command
        t, a = _auftrag_einfach()
        m = EmailMessage()
        m['Subject'] = f'Automatische Antwort: Termin (Ticket #{t.pk}) [A{a.pk}]'
        m['From'] = 'hans@example.ch'
        m['Auto-Submitted'] = 'auto-replied'
        m.set_content('Ich bin im Urlaub.')
        Command().verarbeite_mail(m.as_bytes())
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_webhook_mit_marke_legt_chat_an(self):
        import json
        t, a = _auftrag_einfach()
        with override_settings(BREVO_WEBHOOK_SECRET='geheim'):
            r = Client().post(
                reverse('brevo_inbound_webhook'), data=json.dumps({
                    'Subject': f'Re: Termin (Ticket #{t.pk}) [A{a.pk}]', 'From': 'hans@example.ch',
                    'RawTextBody': 'Gern am Donnerstag.'}),
                content_type='application/json', HTTP_X_WEBHOOK_SECRET='geheim')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(a.direktnachrichten.get().nachricht, 'Gern am Donnerstag.')
        self.assertEqual([x.to for x in mail.outbox], [[HANDWERKER]])


@MAIL
class TerminabstimmungTests(TestCase):
    """Vorschlag -> Bestätigung -> vereinbart (+ Kalendereintrag, Verwaltung informiert).

    Gegenprobe: in `termin_abstimmung.bestaetigen` den Aufruf `termin_festlegen` entfernen -> rot;
    `_termin_steht_melden` entfernen -> `test_bestaetigung_setzt_termin...` (Verwaltungsmail) rot.
    """

    def _ics(self, m):
        return [a for a in m.attachments if a[0] == 'Termin.ics']

    def test_vorschlag_setzt_noch_keinen_termin_und_informiert_nur_die_gegenseite(self):
        from tickets import termin_abstimmung
        t, a = _auftrag_einfach()
        wann = _zeit()
        self.assertTrue(termin_abstimmung.vorschlagen(a, 'handwerker', wann, 'ab 8 Uhr'))
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vorgeschlagen')
        self.assertIsNone(a.termin_am)
        self.assertEqual(a.termin_vorschlag_von, 'handwerker')
        self.assertEqual(a.termin_vorschlag_hinweis, 'ab 8 Uhr')
        self.assertEqual([m.to for m in mail.outbox], [[MIETER]])
        m = mail.outbox[0]
        self.assertEqual(self._ics(m), [])                          # noch kein Kalendereintrag
        self.assertIn('/direkt/', _text(m))                         # signierter Link
        self.assertIn(f'[A{a.pk}]', m.subject)
        self.assertEqual(_an(VERWALTUNG), [])
        self.assertTrue(a.direktnachrichten.filter(nachricht__startswith='Terminvorschlag').exists())

    def test_bestaetigung_setzt_termin_ics_an_beide_und_informiert_die_verwaltung(self):
        from tickets import termin_abstimmung
        t, a = _auftrag_einfach()
        wann = _zeit()
        termin_abstimmung.vorschlagen(a, 'handwerker', wann)
        mail.outbox.clear()
        termin_abstimmung.bestaetigen(a, 'mieter')
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(a.termin_am, wann.astimezone(a.termin_am.tzinfo))
        self.assertIsNone(a.termin_vorschlag_am)
        self.assertEqual(a.termin_vorschlag_von, '')
        t.refresh_from_db()
        self.assertEqual(t.status, 'warte_auf_handwerker')
        for adresse in (MIETER, HANDWERKER):
            mails = _an(adresse)
            self.assertEqual(len(mails), 1, adresse)
            ics = self._ics(mails[0])
            self.assertEqual(len(ics), 1)
            self.assertIn('METHOD:PUBLISH', ics[0][1])
            self.assertNotIn('dann verschieben wir', _text(mails[0]))
        v = _an(VERWALTUNG)
        self.assertEqual(len(v), 1)
        self.assertIn('Termin steht', v[0].subject)
        self.assertIn('Sanitär AG', v[0].body)
        self.assertIn('Hans Muster', v[0].body)
        self.assertIn(wann.strftime('%d.%m.%Y, %H:%M'), v[0].body)
        self.assertNotIn('Ticket #', v[0].subject)                  # sonst würde die Antwort ins Ticket sortiert
        self.assertTrue(t.nachrichten.filter(typ='system', nachricht__contains='Termin direkt abgestimmt').exists())

    def test_mieter_schlaegt_vor_handwerker_bestaetigt(self):
        from tickets import termin_abstimmung
        t, a = _auftrag_einfach()
        termin_abstimmung.vorschlagen(a, 'mieter', _zeit())
        self.assertEqual([m.to for m in mail.outbox], [[HANDWERKER]])
        mail.outbox.clear()
        termin_abstimmung.bestaetigen(a, 'handwerker')
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(len(_an(VERWALTUNG)), 1)

    def test_den_eigenen_vorschlag_kann_man_nicht_selbst_bestaetigen(self):
        from tickets import termin_abstimmung
        t, a = _auftrag_einfach()
        termin_abstimmung.vorschlagen(a, 'handwerker', _zeit())
        mail.outbox.clear()
        with self.assertRaises(ValidationError):
            termin_abstimmung.bestaetigen(a, 'handwerker')
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vorgeschlagen')
        self.assertEqual(mail.outbox, [])

    def test_gegenvorschlag_ersetzt_den_vorschlag_und_alte_bestaetigung_ist_veraltet(self):
        from tickets import direkt_aktionen, termin_abstimmung
        t, a = _auftrag_einfach()
        termin_abstimmung.vorschlagen(a, 'handwerker', _zeit(2, 9))
        alt = direkt_aktionen.kennung(a)
        termin_abstimmung.vorschlagen(a, 'mieter', _zeit(3, 17), 'nach der Arbeit')
        a.refresh_from_db()
        self.assertEqual((a.termin_status, a.termin_vorschlag_von), ('vorgeschlagen', 'mieter'))
        self.assertEqual(timezone.localtime(a.termin_vorschlag_am).hour, 17)
        with self.assertRaises(ValidationError):                    # Mieter-Mail-Link vom ersten Vorschlag
            termin_abstimmung.bestaetigen(a, 'handwerker', kennung=alt)
        termin_abstimmung.bestaetigen(a, 'handwerker', kennung=direkt_aktionen.kennung(a))
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(timezone.localtime(a.termin_am).hour, 17)

    def test_verschiebung_eines_vereinbarten_termins_sagt_den_alten_ab_und_informiert_die_verwaltung(self):
        from tickets import termin_abstimmung
        from tickets.workflow import termin_festlegen
        t, a = _auftrag_einfach()
        termin_festlegen(a, _zeit(2, 9))
        mail.outbox.clear()
        termin_abstimmung.vorschlagen(a, 'mieter', _zeit(3, 17))
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vorgeschlagen')
        for adresse in (MIETER, HANDWERKER):
            absagen = [m for m in _an(adresse) if self._ics(m) and 'METHOD:CANCEL' in self._ics(m)[0][1]]
            self.assertEqual(len(absagen), 1, adresse)
        v = _an(VERWALTUNG)
        self.assertEqual(len(v), 1)
        self.assertIn('verschoben', v[0].subject)

    def test_absage_durch_den_mieter_storniert_ics_und_informiert_die_verwaltung(self):
        from tickets import termin_abstimmung
        from tickets.workflow import termin_festlegen
        t, a = _auftrag_einfach()
        termin_festlegen(a, _zeit())
        mail.outbox.clear()
        termin_abstimmung.absagen_durch(a, 'mieter', 'Bin verreist')
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'abgesagt')
        cancels = [m for m in mail.outbox if self._ics(m) and 'METHOD:CANCEL' in self._ics(m)[0][1]]
        self.assertEqual(sorted(m.to[0] for m in cancels), sorted([MIETER, HANDWERKER]))
        v = _an(VERWALTUNG)
        self.assertEqual(len(v), 1)
        self.assertIn('abgesagt', v[0].subject)
        self.assertIn('Bin verreist', v[0].body)

    def test_absage_ohne_vereinbarten_termin_ist_ein_fehler(self):
        from tickets import termin_abstimmung
        t, a = _auftrag_einfach()
        with self.assertRaises(ValidationError):
            termin_abstimmung.absagen_durch(a, 'mieter')

    def test_vergangenheit_zu_weit_und_langer_hinweis(self):
        from tickets import termin_abstimmung
        t, a = _auftrag_einfach()
        with self.assertRaises(ValidationError):
            termin_abstimmung.vorschlagen(a, 'mieter', timezone.now() - timedelta(hours=1))
        with self.assertRaises(ValidationError):
            termin_abstimmung.vorschlagen(a, 'mieter', timezone.now() + timedelta(days=400))
        with self.assertRaises(ValidationError):
            termin_abstimmung.vorschlagen(a, 'mieter', _zeit(), 'x' * 301)
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'offen')

    def test_eine_mail_antwort_setzt_nie_einen_termin(self):
        """Kein Text-Parsing: «05.11. um 17:00» in einer Antwort ist eine Chat-Nachricht, sonst nichts."""
        from tickets.workflow import antwort_zuordnen
        t, a = _auftrag_einfach()
        antwort_zuordnen(t, 'hans@example.ch', 'Termin passt nicht, können Sie am 05.11. um 17:00?',
                         auftrag_id=a.pk)
        a.refresh_from_db()
        self.assertEqual((a.termin_status, a.termin_am, a.termin_vorschlag_am), ('offen', None, None))

    def test_verwaltung_setzt_weiterhin_direkt_und_der_mailtext_verspricht_keine_verschiebung(self):
        from tickets.workflow import termin_festlegen
        t, a = _auftrag_einfach()
        termin_festlegen(a, _zeit())
        a.refresh_from_db()
        self.assertEqual(a.termin_status, 'vereinbart')
        mieter_mail = _an(MIETER)[0]
        hw_mail = _an(HANDWERKER)[0]
        for m in (mieter_mail, hw_mail):
            self.assertNotIn('verschieben wir', _text(m))
        self.assertIn('Mieterportal', _text(mieter_mail))
        self.assertIn('direkt auf diese Mail', _text(mieter_mail))
        self.assertIn('antworten Sie direkt auf diese Mail', _text(hw_mail))
        self.assertIn(f'[A{a.pk}]', mieter_mail.subject)            # die Antwort darauf wird Chat
        self.assertEqual(_an(VERWALTUNG), [])                       # die Verwaltung hat ihn selbst gesetzt

    def test_festlegen_durch_die_verwaltung_raeumt_einen_offenen_vorschlag_ab(self):
        from tickets import termin_abstimmung
        from tickets.workflow import termin_festlegen
        t, a = _auftrag_einfach()
        termin_abstimmung.vorschlagen(a, 'mieter', _zeit(5))
        termin_festlegen(a, _zeit(2))
        a.refresh_from_db()
        self.assertEqual((a.termin_status, a.termin_vorschlag_am, a.termin_vorschlag_von),
                         ('vereinbart', None, ''))

    def test_standardtexte_in_allen_sprachen_ohne_dann_verschieben_wir(self):
        from django.utils import translation
        from core.services.ticket_workflow import DEFAULT_VORLAGEN
        for sprache in ('de', 'fr', 'it', 'en'):
            with self.subTest(sprache=sprache), translation.override(sprache):
                for kat in ('ticket_termin', 'ticket_termin_handwerker'):
                    text = translation.gettext(DEFAULT_VORLAGEN[kat]['inhalt'])
                    self.assertNotIn('verschieben wir', text)
                    self.assertNotIn('dann verschieben', text)
                if sprache != 'de':
                    self.assertNotEqual(translation.gettext(DEFAULT_VORLAGEN['ticket_termin']['inhalt']),
                                        DEFAULT_VORLAGEN['ticket_termin']['inhalt'])


@MAIL
class VerwaltungDirektTests(TestCase):
    """Die Verwaltung als Mitleser: sieht den Chat, darf schreiben (markiert), Rollen und Mandantengrenze.

    Gegenprobe: `@rolle_erforderlich` an `fw_auftrag_direkt` entfernen -> `test_ohne_anmeldung...` rot;
    `HandwerkerAuftrag.objects` -> `.alle_organisationen` -> `test_fremder_auftrag_ist_404` rot.
    """

    def test_ohne_anmeldung_und_ohne_rolle_kein_zugriff(self):
        t, a = _auftrag_einfach()
        r = Client().post(f'/neu/auftrag/{a.pk}/direkt/', {'text': 'hallo'})
        self.assertIn(r.status_code, (301, 302, 403))
        self.assertEqual(a.direktnachrichten.count(), 0)
        c = Client()
        c.force_login(_team_user('Hauswart'))
        r = c.post(f'/neu/auftrag/{a.pk}/direkt/', {'text': 'hallo'})
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(a.direktnachrichten.count(), 0)

    def test_verwaltung_schreibt_beide_sehen_es_markiert(self):
        t, a = _auftrag_einfach()
        c = Client()
        c.force_login(_team_user())
        r = c.post(f'/neu/auftrag/{a.pk}/direkt/', {'text': 'Bitte bis Freitag klären.'})
        self.assertEqual(r.status_code, 302)
        n = a.direktnachrichten.get()
        self.assertEqual((n.seite, n.is_von_verwaltung), ('verwaltung', True))
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted([MIETER, HANDWERKER]))

    def test_fremder_auftrag_ist_404(self):
        t, a = _auftrag_einfach()
        fremd = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(fremd.organisation):
            fremder = fremd.auftrag
        mail.outbox.clear()
        c = Client()
        c.force_login(_team_user())
        r = c.post(f'/neu/auftrag/{fremder.pk}/direkt/', {'text': 'hallo'})
        self.assertEqual(r.status_code, 404)
        with organisation_kontext(fremd.organisation):
            self.assertEqual(fremder.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_schadenakte_zeigt_den_direktverlauf_und_den_offenen_vorschlag(self):
        from tickets import direktkanal, termin_abstimmung
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'mieter', 'Passt der Donnerstag?')
        termin_abstimmung.vorschlagen(a, 'handwerker', _zeit())
        c = Client()
        c.force_login(_team_user())
        r = c.get(f'/neu/schaeden/{t.pk}/')
        self.assertContains(r, 'Passt der Donnerstag?')
        self.assertContains(r, 'Direkt zwischen Mieter und Handwerker')
        self.assertContains(r, 'data-zustand="vorgeschlagen"')
        self.assertContains(r, f'/neu/auftrag/{a.pk}/direkt/')


class _PortalBasis(TestCase):
    """Zwei Mandanten; je ein Ticket mit Auftrag, der Melder ist der Mieter der Fixture."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        User = get_user_model()
        for fx in (cls.a, cls.b):
            u = User.objects.create_user(username=f'mieter_dk_{fx.kuerzel.lower()}', password='x')
            with organisation_kontext(fx.organisation):
                fx.mieter.benutzer = u
                fx.mieter.save()
                fx.handwerker.email = f'hw-{fx.kuerzel.lower()}@example.ch'
                fx.handwerker.save()
                fx.organisation.email = f'verwaltung-{fx.kuerzel.lower()}@example.ch'
                fx.organisation.save()
                fx.dk_ticket = SchadenMeldung.objects.create(
                    liegenschaft=fx.liegenschaft, betroffene_einheit=fx.einheit, gemeldet_von=fx.mieter,
                    titel=f'Hahn {fx.kuerzel}', beschreibung='tropft', status='in_bearbeitung',
                    bauteil='kueche_sanitaer', kostentraeger='sonderrecht')
                fx.dk_auftrag = HandwerkerAuftrag.objects.create(ticket=fx.dk_ticket, handwerker=fx.handwerker)
            fx.mieter_login = u

    def setUp(self):
        super().setUp()
        cache.clear()
        mail.outbox.clear()
        self.c = Client(raise_request_exception=False)
        self.c.force_login(self.a.mieter_login)

    def _chat(self, fx, auftrag=None):
        from tickets import direktkanal
        auftrag = auftrag or fx.dk_auftrag
        with organisation_kontext(fx.organisation):
            return [n.nachricht for n in direktkanal.verlauf(auftrag)]


@MAIL
class MieterportalDirektTests(_PortalBasis):
    """Mieterportal: Chat und Termin je Auftrag, nur für den Melder des Tickets.

    Gegenprobe: in `mieter_ticket_direkt` `.filter(gemeldet_von=mieter)` entfernen -> `test_nicht_melder...`
    rot; `_mieter_tickets(mieter)` durch `SchadenMeldung.alle_organisationen` ersetzen -> die
    Isolationstests sind rot.
    """

    def url(self, fx=None, auftrag=None):
        fx = fx or self.a
        auftrag = auftrag or fx.dk_auftrag
        return f'/mieter/ticket/{auftrag.ticket_id}/direkt/{auftrag.pk}/'

    def test_mieter_schreibt_im_portal_handwerker_bekommt_mail_verwaltung_nicht(self):
        r = self.c.post(self.url(), {'aktion': 'direkt', 'text': 'Passt der 05.11. um 17:00?'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._chat(self.a), ['Passt der 05.11. um 17:00?'])
        self.assertEqual([m.to for m in mail.outbox], [['hw-a@example.ch']])
        self.assertEqual(_an('verwaltung-a@example.ch'), [])

    def test_detailseite_zeigt_chat_und_formulare_nur_dem_melder(self):
        self.c.post(self.url(), {'aktion': 'direkt', 'text': 'Sichtbarer Chat-Text'})
        r = self.c.get(f'/mieter/ticket/{self.a.dk_ticket.pk}/')
        self.assertContains(r, 'Sichtbarer Chat-Text')
        self.assertContains(r, 'data-karte="direkt"')
        self.assertContains(r, 'name="aktion" value="direkt"')
        self.assertContains(r, 'csrfmiddlewaretoken')

    def test_chat_erscheint_nicht_im_allgemeinen_verlauf_mit_der_verwaltung(self):
        """Der Verlauf «mit der Verwaltung» bleibt, was er war: Direktnachrichten sind intern markiert."""
        self.c.post(self.url(), {'aktion': 'direkt', 'text': 'Nur im Chat'})
        r = self.c.get(f'/mieter/ticket/{self.a.dk_ticket.pk}/')
        self.assertEqual(r.content.decode().count('Nur im Chat'), 1)

    def test_handwerker_antwort_erscheint_im_portal_des_mieters(self):
        from tickets import direktkanal
        with organisation_kontext(self.a.organisation):
            direktkanal.schreiben(self.a.dk_auftrag, 'handwerker', 'Ich komme um 17:00.')
        r = self.c.get(f'/mieter/ticket/{self.a.dk_ticket.pk}/')
        self.assertContains(r, 'Ich komme um 17:00.')

    def test_csrf_wird_geprueft(self):
        c = Client(enforce_csrf_checks=True, raise_request_exception=False)
        c.force_login(self.a.mieter_login)
        r = c.post(self.url(), {'aktion': 'direkt', 'text': 'ohne Token'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._chat(self.a), [])

    def test_get_aendert_nichts_und_zu_langer_text_wird_abgelehnt(self):
        self.assertEqual(self.c.get(self.url()).status_code, 302)
        self.c.post(self.url(), {'aktion': 'direkt', 'text': 'x' * 2001})
        self.c.post(self.url(), {'aktion': 'direkt', 'text': '   '})
        self.c.post(self.url(), {'aktion': 'quatsch', 'text': 'hallo'})
        self.assertEqual(self._chat(self.a), [])
        self.assertEqual(mail.outbox, [])

    def test_fremdes_ticket_ist_404_nichts_wird_geschrieben(self):
        """Mieter A zielt auf Ticket und Auftrag von Mandant B."""
        r = self.c.post(self.url(self.b), {'aktion': 'direkt', 'text': 'Einbruch'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._chat(self.b), [])
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self.c.get(f'/mieter/ticket/{self.b.dk_ticket.pk}/').status_code, 404)

    def test_eigenes_ticket_mit_fremdem_auftrag_ist_404(self):
        r = self.c.post(f'/mieter/ticket/{self.a.dk_ticket.pk}/direkt/{self.b.dk_auftrag.pk}/',
                        {'aktion': 'direkt', 'text': 'Einbruch'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._chat(self.b), [])

    def test_fremder_mieter_im_selben_mandanten_ist_404(self):
        """Ein zweiter Mieter derselben Verwaltung sieht das Ticket nicht und schreibt nicht hinein."""
        from django.contrib.auth import get_user_model
        from crm.models import Mieter
        with organisation_kontext(self.a.organisation):
            m2 = Mieter.objects.create(typ='person', anrede='Frau', vorname='Zweite', nachname='Mieterin',
                                       email='zweite@example.ch', strasse='x 1', plz='8000', ort='Zürich')
            u2 = get_user_model().objects.create_user(username='mieter_dk_zwei', password='x')
            m2.benutzer = u2
            m2.save()
        c2 = Client(raise_request_exception=False)
        c2.force_login(u2)
        r = c2.post(self.url(), {'aktion': 'direkt', 'text': 'Ich bin gar nicht der Melder'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._chat(self.a), [])

    def test_nicht_melder_der_einheit_darf_nicht_schreiben(self):
        """Das Ticket ist über die Einheit sichtbar (Mitbewohner/intern erfasst), der Chat bleibt dem Melder."""
        from tickets.models import SchadenMeldung
        with organisation_kontext(self.a.organisation):
            SchadenMeldung.objects.filter(pk=self.a.dk_ticket.pk).update(gemeldet_von=None)
        r = self.c.post(self.url(), {'aktion': 'direkt', 'text': 'Ich wohne hier auch'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._chat(self.a), [])
        self.assertNotContains(self.c.get(f'/mieter/ticket/{self.a.dk_ticket.pk}/'), 'data-karte="direkt"')

    def test_ohne_anmeldung_kein_zugriff(self):
        r = Client().post(self.url(), {'aktion': 'direkt', 'text': 'anonym'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])
        self.assertEqual(self._chat(self.a), [])

    def test_mieter_schlaegt_termin_vor(self):
        wann = _zeit(3, 17)
        r = self.c.post(self.url(), {'aktion': 'termin_vorschlagen', 'termin': wann.strftime('%Y-%m-%dT%H:%M'),
                                     'hinweis': 'nach der Arbeit'})
        self.assertEqual(r.status_code, 302)
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual((a.termin_status, a.termin_vorschlag_von), ('vorgeschlagen', 'mieter'))
        self.assertEqual([m.to for m in mail.outbox], [['hw-a@example.ch']])

    def test_mieter_bestaetigt_vorschlag_des_handwerkers_termin_steht(self):
        from tickets import direkt_aktionen, termin_abstimmung
        with organisation_kontext(self.a.organisation):
            termin_abstimmung.vorschlagen(self.a.dk_auftrag, 'handwerker', _zeit())
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
            kennung = direkt_aktionen.kennung(a)
        mail.outbox.clear()
        r = self.c.get(f'/mieter/ticket/{self.a.dk_ticket.pk}/')
        self.assertContains(r, 'value="vorschlag_bestaetigen"')
        self.c.post(self.url(), {'aktion': 'vorschlag_bestaetigen', 'kennung': kennung})
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(len(_an('verwaltung-a@example.ch')), 1)
        self.assertEqual(len(_an('hw-a@example.ch')), 1)
        self.assertEqual(len(_an(self.a.mieter.email)), 1)

    def test_mieter_kann_den_eigenen_vorschlag_nicht_bestaetigen(self):
        from tickets import direkt_aktionen, termin_abstimmung
        with organisation_kontext(self.a.organisation):
            termin_abstimmung.vorschlagen(self.a.dk_auftrag, 'mieter', _zeit())
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
            kennung = direkt_aktionen.kennung(a)
        self.c.post(self.url(), {'aktion': 'vorschlag_bestaetigen', 'kennung': kennung})
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual(a.termin_status, 'vorgeschlagen')


@MAIL
class HandwerkerseiteDirektTests(_PortalBasis):
    """Auftragsseite des Handwerkers (Token): Chat, Termin, nur der eigene Auftrag.

    Gegenprobe: in `handwerker_auftrag` den Block `if aktion in direkt_aktionen.AKTIONEN` auf `'termin'`
    zurückbauen (`termin_festlegen`) -> `test_vorschlag_statt_festlegen` rot; `direktkanal.verlauf` ohne
    `auftrag=auftrag` -> `test_nur_der_eigene_chat` rot.
    """

    def setUp(self):
        super().setUp()
        from tickets.handwerker_zugang import link_erzeugen
        with organisation_kontext(self.a.organisation):
            self.token = link_erzeugen(self.a.dk_auftrag)
        self.hc = Client(raise_request_exception=False)
        self.url = f'/auftrag/{self.token}/'

    def test_handwerker_schreibt_mieter_bekommt_mail(self):
        r = self.hc.post(self.url, {'aktion': 'direkt', 'text': 'Donnerstag 17:00 passt.'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._chat(self.a), ['Donnerstag 17:00 passt.'])
        self.assertEqual([m.to for m in mail.outbox], [[self.a.mieter.email]])
        self.assertEqual(_an('verwaltung-a@example.ch'), [])
        self.assertContains(self.hc.get(self.url), 'Donnerstag 17:00 passt.')

    def test_nur_der_eigene_chat(self):
        """Zwei Aufträge am selben Ticket: der Token des einen zeigt den Chat des anderen nicht."""
        from tickets import direktkanal
        from tickets.models import HandwerkerAuftrag
        from crm.models import Handwerker
        with organisation_kontext(self.a.organisation):
            hw2 = Handwerker.objects.create(firma='Elektro AG', email='elektro@example.ch')
            a2 = HandwerkerAuftrag.objects.create(ticket=self.a.dk_ticket, handwerker=hw2)
            direktkanal.schreiben(a2, 'mieter', 'GEHEIM-FUER-ELEKTRO')
        self.hc.post(self.url, {'aktion': 'direkt', 'text': 'Eigener Chat'})
        r = self.hc.get(self.url)
        self.assertContains(r, 'Eigener Chat')
        self.assertNotContains(r, 'GEHEIM-FUER-ELEKTRO')

    def test_fremder_oder_falscher_token_ist_404(self):
        for token in ('x' * 43, self.token[:-1] + ('a' if self.token[-1] != 'a' else 'b')):
            r = self.hc.post(f'/auftrag/{token}/', {'aktion': 'direkt', 'text': 'rein'})
            self.assertEqual(r.status_code, 404)
        self.assertEqual(self._chat(self.a), [])

    def test_csrf_wird_geprueft(self):
        c = Client(enforce_csrf_checks=True, raise_request_exception=False)
        r = c.post(self.url, {'aktion': 'direkt', 'text': 'ohne Token'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._chat(self.a), [])

    def test_vorschlag_statt_festlegen(self):
        wann = _zeit()
        self.hc.post(self.url, {'aktion': 'termin', 'termin': wann.strftime('%Y-%m-%dT%H:%M')})
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual((a.termin_status, a.termin_am), ('vorgeschlagen', None))
        self.assertEqual([m.to for m in mail.outbox], [[self.a.mieter.email]])

    def test_abgeschlossener_auftrag_ist_nur_lesbar(self):
        with organisation_kontext(self.a.organisation):
            type(self.a.dk_auftrag).objects.filter(pk=self.a.dk_auftrag.pk).update(
                status='erledigt', token_gueltig_bis=timezone.now() + timedelta(days=10))   # lesend, wie nach dem Abschluss
        r = self.hc.post(self.url, {'aktion': 'direkt', 'text': 'zu spät'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._chat(self.a), [])


@MAIL
class SignierterLinkTests(_PortalBasis):
    """Der Link aus der Mail: Bestätigen/Gegenvorschlag/Chat ohne Anmeldung.

    Gegenprobe: in `direkt_link` die POST-Prüfung durch eine Aktion im GET ersetzen -> `test_get_aendert_nichts`
    rot; `max_age` aus `auftrag_aus_link` entfernen -> `test_abgelaufener_link` rot; die Seitenprüfung in
    `bestaetigen` (`eigener_vorschlag`) entfernen -> `test_link_der_vorschlagenden_seite...` rot.
    """

    def _link(self, seite, auftrag=None):
        from tickets import direktkanal
        return reverse('direkt_link', args=[direktkanal.link_token(auftrag or self.a.dk_auftrag, seite)])

    def test_mail_enthaelt_einen_funktionierenden_link_und_get_aendert_nichts(self):
        from tickets import termin_abstimmung
        with organisation_kontext(self.a.organisation):
            termin_abstimmung.vorschlagen(self.a.dk_auftrag, 'handwerker', _zeit())
        # Der Link trägt einen Sekunden-Zeitstempel: ein zweiter, danach erzeugter Link kann sich über eine
        # Sekundengrenze hinweg unterscheiden (CI-Fehler). Darum den Link aus der Mail nehmen und nur
        # den Inhalt (vor dem Zeitstempel) mit dem erwarteten vergleichen.
        erwartet = self._link('mieter')
        treffer = re.search(r'/direkt/[^/\'"<>\s]+/', _text(mail.outbox[0]))
        self.assertIsNotNone(treffer, 'Die Mail enthält keinen Direktlink')
        url = treffer.group(0)
        self.assertEqual(url.split(':')[0], erwartet.split(':')[0])
        r = Client().get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'value="vorschlag_bestaetigen"')
        self.assertEqual(r['X-Robots-Tag'], 'noindex, nofollow')
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual(a.termin_status, 'vorgeschlagen')            # GET bestätigt nichts

    def test_bestaetigen_per_link_ohne_login_ist_voll_wirksam(self):
        from tickets import direkt_aktionen, termin_abstimmung
        with organisation_kontext(self.a.organisation):
            termin_abstimmung.vorschlagen(self.a.dk_auftrag, 'handwerker', _zeit())
            kennung = direkt_aktionen.kennung(type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk))
        mail.outbox.clear()
        r = Client().post(self._link('mieter'), {'aktion': 'vorschlag_bestaetigen', 'kennung': kennung})
        self.assertEqual(r.status_code, 302)
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual(a.termin_status, 'vereinbart')
        self.assertEqual(len(_an('verwaltung-a@example.ch')), 1)
        self.assertEqual(len(_an('hw-a@example.ch')), 1)

    def test_gegenvorschlag_per_link(self):
        from tickets import termin_abstimmung
        with organisation_kontext(self.a.organisation):
            termin_abstimmung.vorschlagen(self.a.dk_auftrag, 'handwerker', _zeit(2, 9))
        Client().post(self._link('mieter'), {'aktion': 'termin_vorschlagen',
                                              'termin': _zeit(4, 17).strftime('%Y-%m-%dT%H:%M')})
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual((a.termin_status, a.termin_vorschlag_von), ('vorgeschlagen', 'mieter'))

    def test_link_der_vorschlagenden_seite_bestaetigt_nicht(self):
        from tickets import direkt_aktionen, termin_abstimmung
        with organisation_kontext(self.a.organisation):
            termin_abstimmung.vorschlagen(self.a.dk_auftrag, 'handwerker', _zeit())
            kennung = direkt_aktionen.kennung(type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk))
        Client().post(self._link('handwerker'), {'aktion': 'vorschlag_bestaetigen', 'kennung': kennung})
        with organisation_kontext(self.a.organisation):
            a = type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk)
        self.assertEqual(a.termin_status, 'vorgeschlagen')

    def test_chat_per_link(self):
        Client().post(self._link('mieter'), {'aktion': 'direkt', 'text': 'Hallo per Link'})
        self.assertEqual(self._chat(self.a), ['Hallo per Link'])
        self.assertEqual([m.to for m in mail.outbox], [['hw-a@example.ch']])

    def test_gefaelschter_und_fremder_link_ist_404(self):
        url = self._link('mieter')
        kaputt = url[:-3] + ('aaa' if not url.endswith('aaa/') else 'bbb') + '/'
        for u in (kaputt, '/direkt/quatsch/', self._link('mieter').replace('/direkt/', '/direkt/x')):
            self.assertEqual(Client().get(u).status_code, 404, u)
        self.assertEqual(Client().post(kaputt, {'aktion': 'direkt', 'text': 'rein'}).status_code, 404)
        self.assertEqual(self._chat(self.a), [])

    def test_link_zeigt_nur_den_eigenen_auftrag(self):
        from tickets import direktkanal
        with organisation_kontext(self.b.organisation):
            direktkanal.schreiben(self.b.dk_auftrag, 'mieter', 'B-GEHEIM')
        with organisation_kontext(self.a.organisation):
            direktkanal.schreiben(self.a.dk_auftrag, 'mieter', 'A-SICHTBAR')
        r = Client().get(self._link('mieter'))
        self.assertContains(r, 'A-SICHTBAR')
        self.assertNotContains(r, 'B-GEHEIM')

    def test_abgelaufener_link(self):
        url = self._link('mieter')
        with mock.patch('tickets.direktkanal.LINK_GUELTIG_SEKUNDEN', -1):
            self.assertEqual(Client().get(url).status_code, 404)

    def test_widerrufener_handwerker_link_sperrt_auch_den_chat_link(self):
        from tickets.handwerker_zugang import link_erzeugen, link_widerrufen
        with organisation_kontext(self.a.organisation):
            link_erzeugen(self.a.dk_auftrag)
            link_widerrufen(type(self.a.dk_auftrag).objects.get(pk=self.a.dk_auftrag.pk))
        self.assertEqual(Client().get(self._link('handwerker')).status_code, 404)
        self.assertEqual(Client().get(self._link('mieter')).status_code, 200)    # der Mieter bleibt

    def test_token_kann_nicht_in_andere_signatur_umgebaut_werden(self):
        """Ein Token mit anderem Salt (z. B. aus einer anderen Funktion der App) öffnet nichts."""
        fremd = signing.dumps({'a': self.a.dk_auftrag.pk, 'w': 'mieter'}, salt='irgendwas')
        self.assertEqual(Client().get(f'/direkt/{fremd}/').status_code, 404)

    def test_csrf_beim_link(self):
        c = Client(enforce_csrf_checks=True, raise_request_exception=False)
        r = c.post(self._link('mieter'), {'aktion': 'direkt', 'text': 'ohne Token'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._chat(self.a), [])


class ErinnerungTests(TestCase):
    """Der Chat des Handwerkers zählt als Rückmeldung: keine Erinnerung «keine Rückmeldung»."""

    @MAIL
    def test_antwort_im_chat_verhindert_die_erinnerung_an_den_handwerker(self):
        from tickets import direktkanal
        from tickets.erinnerungen import erinnerungen_senden
        t, a = _auftrag_einfach()
        direktkanal.schreiben(a, 'handwerker', 'Ich melde mich beim Mieter.')
        mail.outbox.clear()
        n = erinnerungen_senden(timezone.now() + timedelta(days=10))
        self.assertEqual(n['auftrag'], 0)

    @MAIL
    def test_ohne_chat_kommt_die_erinnerung_weiterhin(self):
        from tickets.erinnerungen import erinnerungen_senden
        t, a = _auftrag_einfach()
        n = erinnerungen_senden(timezone.now() + timedelta(days=10))
        self.assertEqual(n['auftrag'], 1)
