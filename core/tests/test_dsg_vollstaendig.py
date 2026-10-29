"""Anonymisierung (DSG Art. 32 Abs. 2 lit. c) vollständig und Auskunftsrecht (DSG Art. 25).

Der Befund (SICH-07): Nach `anonymisiere_person` standen Name, E-Mail, Telefon und IBAN
noch in 18 Spalten (davon ein Dateiname) und in der Vertragsdatei selbst. Dieser Test
sucht nicht in einer Liste, die man vergessen kann, sondern in JEDER Textspalte JEDER
Tabelle der Datenbank nach den Kennzeichen der Person. Was bleiben darf, steht ausdrücklich
in `AUFBEWAHRT` (Buchungsbelege, Art. 958f OR), mit Grund.

GEGENPROBEN (28.10.2026): je Schritt in `anonymisiere_person` entfernt -> der Scan nennt
die Spalte; Schlussbericht.
"""
import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.test import override_settings

from .test_loeschschutz import LoeschBasis

NAME, VORNAME = 'Zebrowski', 'Zora'
MAIL = 'zebra.zebrowski@example.ch'
TEL = '0791234567'
IBAN = 'CH5604835012345678009'
AHV = '756.1234.5678.97'
STRASSE = 'Zebraweg 9'
MITMIETER = 'Zeno Zebrowski'

#: Spalten, in denen die Person BLEIBEN darf, mit Grund. Buchungsbelege sind zehn Jahre
#: aufzubewahren (Art. 958f OR) und unveränderlich (DB-Trigger); sie tragen den Namen
#: nur im Belegtext. Ob auch der Belegtext pseudonymisiert werden müsste, ist ein Fachpunkt (F2).
AUFBEWAHRT = {
    ('core_buchung', 'beleg_text'): 'Buchungsbeleg, unveränderlich (Art. 958f OR)',
    ('core_debitorenrechnung', 'titel'): 'Rechnungsbeleg (Art. 958f OR)',
}
KENNZEICHEN = (NAME, MAIL, TEL, IBAN, STRASSE, AHV, 'ZebraAG')


def _rest_in_datenbank():
    """Sucht die Kennzeichen in JEDER Text-/Datei-Spalte JEDES Modells (nicht in einer Liste von Hand)."""
    from django.apps import apps
    treffer = {}
    text_typen = ('CharField', 'TextField', 'EmailField', 'FileField', 'ImageField', 'URLField', 'SlugField')
    for modell in apps.get_models():
        for feld in modell._meta.concrete_fields:
            if feld.get_internal_type() not in text_typen:
                continue
            for muster in KENNZEICHEN:
                try:
                    # Savepoint: Ein Fehler (z. B. verschlüsseltes Feld) darf auf PostgreSQL nicht die
                    # ganze Test-Transaktion abbrechen, sonst scheitert jede folgende Abfrage.
                    with transaction.atomic():
                        n = modell._base_manager.filter(**{f'{feld.name}__contains': muster}).count()
                except Exception:                                          # noqa: BLE001  (verschlüsselte Felder u. ä.)
                    continue
                if n:
                    treffer.setdefault((modell._meta.db_table, feld.column), []).append((muster, n))
    return treffer


class AnonymisierungVollstaendigTests(LoeschBasis):

    def setUp(self):
        super().setUp()
        self._media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._media, True)
        ueberschreiben = override_settings(MEDIA_ROOT=self._media)
        ueberschreiben.enable()
        self.addCleanup(ueberschreiben.disable)
        self._person_anlegen()

    def _person_anlegen(self):
        from core.models import AktivitaetsLog
        from crm.models import Kommunikation, Mieter
        from finance.models import Buchung, DebitorenRechnung, Zahlungseingang
        from mietprozess.models import Mietbewerbung
        from rentals.models import Dokument, Mietvertrag
        from tickets.models import SchadenMeldung, TicketNachricht
        a = self.a
        m = Mieter.objects.create(
            typ='person', vorname=VORNAME, nachname=NAME, email=MAIL, mobile=TEL, telefon_privat=TEL, iban=IBAN,
            strasse=STRASSE, plz='8000', ort='Zürich', geburtsdatum=date(1980, 1, 1), ahv_nummer=AHV,
            notizen=f'{NAME} ruft nur abends an', arbeitgeber='ZebraAG')
        v = Mietvertrag.objects.create(
            mieter=m, einheit=a.einheit, beginn=date(2015, 1, 1), netto_mietzins=Decimal('1000'),
            nebenkosten=Decimal('100'), status='archiviert', mitmieter_name=MITMIETER)
        Kommunikation.objects.create(mieter=m, vertrag=v, inhalt=f'Telefonat mit Frau {NAME}, Tel {TEL}',
                                     betreff=f'Mahnung {NAME}')
        s = SchadenMeldung.objects.create(
            liegenschaft=a.liegenschaft, betroffene_einheit=a.einheit, gemeldet_von=m,
            titel=f'Schaden bei {NAME}', beschreibung=f'Name: {VORNAME} {NAME}\nTel: {TEL}\nEmail: {MAIL}',
            melder_vorname=VORNAME, melder_nachname=NAME, email_melder=MAIL, tel_melder=TEL)
        TicketNachricht.objects.create(ticket=s, absender_name=f'{VORNAME} {NAME}', nachricht=f'Gruss {NAME} {MAIL}')
        d = DebitorenRechnung.objects.create(vertrag=v, titel=f'Miete {NAME}', betrag=Decimal('1100'),
                                             datum=date(2024, 1, 1), faellig_am=date(2024, 1, 28), status='bezahlt')
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('1100'), datum_eingang=date(2024, 1, 5),
                                       buchungs_monat=date(2024, 1, 1), debitoren_rechnung=d,
                                       bemerkung=f'Zahler {NAME} {IBAN}', bank_referenz=f'{NAME}-REF')
        Buchung.objects.create(beleg_text=f'Miete {NAME} Januar', soll_konto=a.konto_soll if hasattr(a, 'konto_soll') else a.buchung.soll_konto,
                               haben_konto=a.konto_haben if hasattr(a, 'konto_haben') else a.buchung.haben_konto,
                               betrag=Decimal('1100'), datum=date(2024, 1, 5))
        dok = Dokument(vertrag=v, mieter=m, kategorie='vertrag', bezeichnung=f'Vertrag {NAME}')
        dok.datei.save(f'Vertrag_{NAME}.pdf', ContentFile(b'%PDF-1.4 x'), save=True)
        AktivitaetsLog.objects.create(aktion='Mieter bearbeitet', objekt=f'{VORNAME} {NAME}', details=f'E-Mail {MAIL}')
        Mietbewerbung.objects.create(einheit=a.einheit, vorname=VORNAME, nachname=NAME, geburtsdatum=date(1980, 1, 1),
                                     mobilnummer=TEL, email=MAIL, beruf='x', einkommen_jahr='90000', adresse=STRASSE)
        self.m, self.v, self.dok = m, v, dok

    def test_nach_der_anonymisierung_steht_die_person_nirgends_ausser_in_den_belegen(self):
        from core.services.dsg import anonymisiere_person
        vorher = _rest_in_datenbank()
        self.assertGreater(len(vorher), 15, 'Der Scan findet die Person nicht - er prüft nichts.')
        ok, meldung = anonymisiere_person(self.m, grund='Test')
        self.assertTrue(ok, meldung)
        rest = {k: v for k, v in _rest_in_datenbank().items() if k not in AUFBEWAHRT}
        self.assertEqual(rest, {}, 'Personenbezogene Reste: ' + json.dumps(
            {f'{t}.{c}': v for (t, c), v in rest.items()}, ensure_ascii=False))

    def test_der_dateiname_der_vertragsdatei_wird_neutral_der_inhalt_bleibt_aufbewahrt(self):
        import os

        from core.services.dsg import anonymisiere_person
        alt = self.dok.datei.path
        self.assertTrue(os.path.exists(alt))
        anonymisiere_person(self.m)
        self.assertFalse(os.path.exists(alt), 'Die Datei liegt noch unter dem Namen der Person.')
        self.dok.refresh_from_db()
        self.assertNotIn(NAME, self.dok.bezeichnung)
        self.assertNotIn(NAME, self.dok.datei.name)
        self.assertTrue(os.path.exists(self.dok.datei.path), 'Die Vertragsdatei ist verschwunden (Aufbewahrung, Art. 958f OR).')
        with open(self.dok.datei.path, 'rb') as f:
            self.assertEqual(f.read(), b'%PDF-1.4 x')

    def test_schalter_vertragsdatei_loeschen_entfernt_die_datei(self):
        import os
        from unittest import mock

        from core.services.dsg import anonymisiere_person
        alt = self.dok.datei.path
        with mock.patch('core.services.dsg.VERTRAGSDATEI_LOESCHEN', True):
            anonymisiere_person(self.m)
        self.dok.refresh_from_db()
        self.assertFalse(os.path.exists(alt))
        self.assertFalse(self.dok.datei)

    def test_fremde_personen_und_texte_bleiben_unberuehrt(self):
        from core.models import AktivitaetsLog
        from core.services.dsg import anonymisiere_person
        AktivitaetsLog.objects.create(aktion='Andere Person', objekt='Muster Hans', details='hans@example.ch')
        anonymisiere_person(self.m)
        self.assertTrue(AktivitaetsLog.objects.filter(objekt='Muster Hans', details='hans@example.ch').exists())

    def test_buchungen_und_rechnungen_bleiben_mit_betrag_und_nummer(self):
        from core.services.dsg import anonymisiere_person
        from finance.models import Buchung, DebitorenRechnung
        n_b = Buchung.objects.count()
        anonymisiere_person(self.m)
        self.assertEqual(Buchung.objects.count(), n_b)
        self.assertTrue(DebitorenRechnung.objects.filter(vertrag=self.v, betrag=Decimal('1100')).exists())

    def test_aktive_vertraege_blockieren_weiterhin(self):
        from core.services.dsg import anonymisiere_person
        self.v.status = 'aktiv'
        self.v.save(update_fields=['status'])
        ok, _meldung = anonymisiere_person(self.m)
        self.assertFalse(ok)


class AuskunftTests(AnonymisierungVollstaendigTests):
    """Auskunftsrecht (DSG Art. 25): alle Daten der Person als ZIP. Erbt den Aufbau der Person."""

    # Die vererbten Anonymisierungstests laufen hier nicht noch einmal.
    test_nach_der_anonymisierung_steht_die_person_nirgends_ausser_in_den_belegen = None
    test_der_dateiname_der_vertragsdatei_wird_neutral_der_inhalt_bleibt_aufbewahrt = None
    test_schalter_vertragsdatei_loeschen_entfernt_die_datei = None
    test_fremde_personen_und_texte_bleiben_unberuehrt = None
    test_buchungen_und_rechnungen_bleiben_mit_betrag_und_nummer = None
    test_aktive_vertraege_blockieren_weiterhin = None

    def _zip(self, antwort):
        import io
        import zipfile
        return zipfile.ZipFile(io.BytesIO(antwort.content))

    def test_paket_enthaelt_alle_bereiche_und_die_dokumente(self):
        antwort = self.c.post(f'/neu/personen/{self.m.pk}/auskunft/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/zip')
        z = self._zip(antwort)
        daten = json.loads(z.read('auskunft.json'))
        self.assertEqual(daten['person']['email'], MAIL)
        self.assertEqual(daten['person']['ahv_nummer'], AHV)
        self.assertEqual(len(daten['mietvertraege']), 1)
        self.assertEqual(len(daten['rechnungen']), 1)
        self.assertEqual(len(daten['zahlungen']), 1)
        self.assertEqual(len(daten['korrespondenz']), 1)
        self.assertEqual(len(daten['schadenmeldungen']), 1)
        self.assertEqual(len(daten['schaden_nachrichten']), 1)
        self.assertEqual(len(daten['bewerbungen']), 1)
        self.assertEqual(len(daten['dokumente']), 1)
        beigelegt = [n for n in z.namelist() if n.startswith('dokumente/')]
        self.assertEqual(len(beigelegt), 1)
        self.assertEqual(z.read(beigelegt[0]), b'%PDF-1.4 x')

    def test_paket_enthaelt_nichts_aus_einer_anderen_verwaltung(self):
        z = self._zip(self.c.post(f'/neu/personen/{self.m.pk}/auskunft/'))
        text = z.read('auskunft.json').decode()
        self.assertNotIn(self.b.mieter.email, text)
        self.assertNotIn(self.b.organisation.firma, text)

    def test_fremde_person_404_get_405_und_rollen(self):
        from core.tests._helfer import _team_user
        self.assertEqual(self.c.post(f'/neu/personen/{self.b.mieter.pk}/auskunft/').status_code, 404)
        self.assertEqual(self.c.get(f'/neu/personen/{self.m.pk}/auskunft/').status_code, 405)
        from django.test import Client
        lesend = Client()
        lesend.force_login(_team_user('Lesend'))
        self.assertEqual(lesend.post(f'/neu/personen/{self.m.pk}/auskunft/').status_code, 403)

    def test_der_abruf_steht_im_audit_log(self):
        from core.models import AktivitaetsLog
        self.c.post(f'/neu/personen/{self.m.pk}/auskunft/')
        self.assertTrue(AktivitaetsLog.objects.filter(aktion__startswith='Auskunft nach DSG').exists())
