"""Löschschutz (FUNK-03 / FIN-16, Audit 28.10.2026): kein hartes Löschen, wo Daten hängen.

Der Befund: «Person löschen», «Liegenschaft löschen» und «Mandat löschen» sperrten
nur bei AKTIVEN Verträgen bzw. vorhandenen Liegenschaften. Alles andere fiel in
der Kaskade mit: alle Verträge, NK-Abrechnungen samt eingefrorenem Snapshot,
Abnahmen, Dokumente, Abschlüsse, Anlagen, Auszahlungen. Ein aktiver Vertrag mit
offenen Rechnungen liess sich löschen; die Rechnungen blieben `offen`, verloren
aber den Vertrag (`SET_NULL`) und fielen aus Mieterkonto und Mahnlauf.

Zwei Schichten, beide hier geprüft:
  1. die Ansicht sperrt mit einer Meldung, die nennt, WAS hängt;
  2. die Fremdschlüssel sind `PROTECT`: ein `delete()` an der Ansicht vorbei
     endet in `ProtectedError`, ohne Teilschaden.

GEGENPROBEN (28.10.2026, je einzeln eingebaut, rot gesehen, zurückgebaut):
  * `hindernisse(m)` in `fw_person_loeschen` wieder durch «nur aktive Verträge»
    ersetzt → `test_person_mit_beendetem_vertrag…` und `…mit_rechnung…` rot;
  * `fw_vertrag_loeschen` ohne Sperre → `test_aktiver_vertrag_mit_offener_rechnung…` rot;
  * in `rentals/models.py` `Mietvertrag.mieter` zurück auf CASCADE
    → `test_mieter_delete_an_der_ansicht_vorbei…` und `test_die_fremdschluessel…` rot;
  * `transaction.atomic()` in `Mietvertrag.delete` entfernt
    → `test_gesperrter_vertrag_behaelt_seine_paketdokumente` rot.
"""
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.db.models import PROTECT, ProtectedError
from django.test import Client, TestCase

from core.services.loeschschutz import hindernisse
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture


class LoeschBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)              # Inhaber von A
        self._kontext = organisation_kontext(self.a.organisation)
        self._kontext.__enter__()
        self.addCleanup(self._kontext.__exit__, None, None, None)

    # -- Bausteine: eigene, ABHÄNGIGKEITSFREIE Objekte in A -------------------

    def neue_liegenschaft(self, **extra):
        from portfolio.models import Liegenschaft
        return Liegenschaft.objects.create(
            strasse='Leergasse 1', plz='8000', ort='Zürich', organisation=self.a.organisation,
            versicherungswert=Decimal('1'), **extra)

    def neue_einheit(self, lg=None):
        from portfolio.models import Einheit
        return Einheit.objects.create(liegenschaft=lg or self.neue_liegenschaft(),
                                      bezeichnung='Leer 1', typ='whg')

    def neuer_mieter(self):
        from crm.models import Mieter
        return Mieter.objects.create(typ='person', vorname='Leer', nachname='Person')

    def neuer_vertrag(self, status='entwurf', einheit=None, mieter=None):
        from rentals.models import Mietvertrag
        return Mietvertrag.objects.create(
            mieter=mieter or self.neuer_mieter(), einheit=einheit or self.neue_einheit(),
            beginn=date(2025, 1, 1), netto_mietzins=Decimal('1000'), nebenkosten=Decimal('100'),
            status=status)

    def loeschen(self, name, objekt):
        return self.c.post(f'/neu/{name}/{objekt.pk}/loeschen/', follow=True)

    def text(self, antwort):
        return ' '.join(str(m) for m in antwort.context['messages'])

    def gibt_es(self, objekt):
        return type(objekt)._base_manager.filter(pk=objekt.pk).exists()


# ---------------------------------------------------------------------------
# Person / Mieter
# ---------------------------------------------------------------------------

class PersonLoeschenTests(LoeschBasis):

    def test_person_mit_vertrag_rechnung_und_zahlung_bleibt(self):
        antwort = self.loeschen('personen', self.a.mieter)
        self.assertTrue(self.gibt_es(self.a.mieter))
        meldung = self.text(antwort)
        self.assertIn('kann nicht gelöscht werden', meldung)
        for was in ('Mietverträge', 'Rechnungen', 'Zahlungen', 'Abnahmeprotokolle'):
            self.assertIn(was, meldung, f'Die Meldung nennt nicht, dass {was} hängen.')
        self.assertIn('958f', meldung)
        self.assertIn('Anonymisierung', meldung)

    def test_person_mit_beendetem_vertrag_bleibt(self):
        """Bisher gesperrt war nur der AKTIVE Vertrag."""
        v = self.neuer_vertrag(status='archiviert')
        self.loeschen('personen', v.mieter)
        self.assertTrue(self.gibt_es(v.mieter))
        self.assertTrue(self.gibt_es(v))

    def test_person_mit_entwurfsvertrag_bleibt(self):
        v = self.neuer_vertrag(status='entwurf')
        self.loeschen('personen', v.mieter)
        self.assertTrue(self.gibt_es(v.mieter))

    def test_person_nur_mit_dokument_bleibt(self):
        from rentals.models import Dokument
        m = self.neuer_mieter()
        Dokument.objects.create(mieter=m, datei='dok/ausweis.pdf', kategorie='sonstiges')
        self.loeschen('personen', m)
        self.assertTrue(self.gibt_es(m))

    def test_person_als_mitmieter_bleibt(self):
        v = self.neuer_vertrag(status='archiviert')
        zweite = self.neuer_mieter()
        v.mitmieter = zweite
        v.save(update_fields=['mitmieter'])
        self.loeschen('personen', zweite)
        self.assertTrue(self.gibt_es(zweite))

    def test_gesperrte_person_behaelt_ihren_portal_login(self):
        """Die Sperre kommt VOR jeder Änderung: Kein halb gelöschter Zustand."""
        from django.contrib.auth import get_user_model
        v = self.neuer_vertrag(status='archiviert')
        login = get_user_model().objects.create_user(username='portal_leer', password='x')
        v.mieter.benutzer = login
        v.mieter.save(update_fields=['benutzer'])
        self.loeschen('personen', v.mieter)
        v.mieter.refresh_from_db()
        self.assertEqual(v.mieter.benutzer_id, login.pk, 'Die Sperre hat den Portal-Login gelöst.')

    def test_person_ohne_abhaengige_daten_wird_geloescht(self):
        """Gegenprobe: Sonst wäre die Sperre grün, indem sie alles verbietet."""
        m = self.neuer_mieter()
        antwort = self.loeschen('personen', m)
        self.assertFalse(self.gibt_es(m))
        self.assertIn('gelöscht', self.text(antwort))

    def test_person_mit_nur_journal_und_adresse_wird_geloescht(self):
        """Adressen und Korrespondenz allein sind kein Grund zur Sperre."""
        from crm.models import Kommunikation
        m = self.neuer_mieter()
        Kommunikation.objects.create(mieter=m, inhalt='Notiz')
        self.loeschen('personen', m)
        self.assertFalse(self.gibt_es(m))

    def test_protect_faengt_auch_ab_was_die_zaehlung_nicht_kennt(self):
        """Zweite Schicht: Zählt `hindernisse()` etwas nicht, hält der Fremdschlüssel.

        Die Ansicht fängt den `ProtectedError`, rollt ZURÜCK (der Portal-Login wurde
        vorher gelöst!) und meldet, statt mit 500 zu antworten.
        """
        from unittest.mock import patch

        from django.contrib.auth import get_user_model
        v = self.neuer_vertrag(status='archiviert')
        login = get_user_model().objects.create_user(username='portal_zwei', password='x')
        v.mieter.benutzer = login
        v.mieter.save(update_fields=['benutzer'])
        with patch('core.services.loeschschutz.hindernisse', return_value=[]):
            antwort = self.loeschen('personen', v.mieter)
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(self.gibt_es(v.mieter))
        self.assertIn('kann nicht gelöscht werden', self.text(antwort))
        v.mieter.refresh_from_db()
        self.assertEqual(v.mieter.benutzer_id, login.pk, 'Der Portal-Login blieb gelöst, obwohl nichts gelöscht wurde.')
        self.assertTrue(get_user_model().objects.filter(pk=login.pk).exists())

    def test_fremde_person_gibt_404(self):
        antwort = self.c.post(f'/neu/personen/{self.b.mieter.pk}/loeschen/')
        self.assertEqual(antwort.status_code, 404)
        self.assertTrue(self.gibt_es(self.b.mieter))


# ---------------------------------------------------------------------------
# Liegenschaft
# ---------------------------------------------------------------------------

class LiegenschaftLoeschenTests(LoeschBasis):

    def test_liegenschaft_mit_allem_bleibt_und_nennt_was_haengt(self):
        antwort = self.loeschen('liegenschaften', self.a.liegenschaft)
        self.assertTrue(self.gibt_es(self.a.liegenschaft))
        meldung = self.text(antwort)
        for was in ('Mietverträge', 'Rechnungen', 'Zahlungen', 'Nebenkostenabrechnungen', 'Abnahmeprotokolle'):
            self.assertIn(was, meldung)
        self.assertIn('Archiviert', meldung, 'Die Meldung verweist nicht auf die Archivierung.')

    def test_liegenschaft_mit_beendetem_vertrag_bleibt(self):
        v = self.neuer_vertrag(status='archiviert')
        self.loeschen('liegenschaften', v.einheit.liegenschaft)
        self.assertTrue(self.gibt_es(v.einheit.liegenschaft))
        self.assertTrue(self.gibt_es(v))

    def _sperre_durch(self, anlegen):
        lg = self.neue_liegenschaft()
        anlegen(lg)
        self.loeschen('liegenschaften', lg)
        self.assertTrue(self.gibt_es(lg), 'Die Liegenschaft wurde trotz anhängender Daten gelöscht.')

    def test_liegenschaft_mit_kreditorenrechnung_bleibt(self):
        from finance.models import KreditorenRechnung
        self._sperre_durch(lambda lg: KreditorenRechnung.objects.create(
            lieferant='Handwerk AG', betrag=Decimal('10'), liegenschaft=lg, status='neu'))

    def test_liegenschaft_mit_nk_abrechnung_bleibt(self):
        from finance.models import AbrechnungsPeriode
        self._sperre_durch(lambda lg: AbrechnungsPeriode.objects.create(
            liegenschaft=lg, bezeichnung='HNK 2025', start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31)))

    def test_liegenschaft_mit_jahresabschluss_bleibt(self):
        from finance.models import Jahresabschluss
        self._sperre_durch(lambda lg: Jahresabschluss.objects.create(liegenschaft=lg))

    def test_liegenschaft_mit_anlage_bleibt(self):
        from finance.models import Anlage
        self._sperre_durch(lambda lg: Anlage.objects.create(
            liegenschaft=lg, bezeichnung='Heizung', anschaffungsdatum=date(2020, 1, 1)))

    def test_liegenschaft_mit_hypothek_bleibt(self):
        from finance.models import Hypothek
        self._sperre_durch(lambda lg: Hypothek.objects.create(liegenschaft=lg))

    def test_liegenschaft_mit_dokument_bleibt(self):
        from portfolio.models import Dokument
        self._sperre_durch(lambda lg: Dokument.objects.create(liegenschaft=lg, titel='Police', datei='d/p.pdf'))

    def test_liegenschaft_mit_buchung_bleibt(self):
        from finance.models import Buchung
        self._sperre_durch(lambda lg: Buchung.objects.create(
            beleg_text='x', soll_konto=self.a.konto_soll, haben_konto=self.a.konto_haben,
            betrag=Decimal('1'), datum=date(2025, 1, 1), liegenschaft=lg))

    def test_liegenschaft_mit_schadenmeldung_bleibt(self):
        from tickets.models import SchadenMeldung
        self._sperre_durch(lambda lg: SchadenMeldung.objects.create(
            liegenschaft=lg, titel='Wasser', beschreibung='x'))

    def test_liegenschaft_mit_stweg_abrechnung_bleibt(self):
        from stweg.models import StwegAbrechnung
        self._sperre_durch(lambda lg: StwegAbrechnung.objects.create(liegenschaft=lg, jahr=2025))

    def test_leere_liegenschaft_wird_geloescht(self):
        """Gegenprobe: Objekte, Zähler und Geräte allein sperren nicht."""
        from portfolio.models import Ausstattung
        lg = self.neue_liegenschaft()
        e = self.neue_einheit(lg)
        Ausstattung.objects.create(einheit=e, raum='Bad', kategorie='sanitaer')
        antwort = self.loeschen('liegenschaften', lg)
        self.assertFalse(self.gibt_es(lg))
        self.assertFalse(self.gibt_es(e))
        self.assertIn('gelöscht', self.text(antwort))


# ---------------------------------------------------------------------------
# Mandat / Eigentümer
# ---------------------------------------------------------------------------

class EigentuemerLoeschenTests(LoeschBasis):

    def neuer_eigentuemer(self):
        from crm.models import Eigentuemer
        return Eigentuemer.objects.create(firma_oder_name='Leer AG')

    def test_mandat_mit_liegenschaft_bleibt(self):
        antwort = self.loeschen('mandate', self.a.eigentuemer)
        self.assertTrue(self.gibt_es(self.a.eigentuemer))
        self.assertIn('Liegenschaften', self.text(antwort))

    def test_mandat_mit_auszahlung_bleibt(self):
        """Das Löschen kaskadierte `EigentuemerAuszahlung` — das Kontokorrent des Eigentümers."""
        from finance.models import EigentuemerAuszahlung
        e = self.neuer_eigentuemer()
        EigentuemerAuszahlung.objects.create(eigentuemer=e, betrag=Decimal('500'))
        antwort = self.loeschen('mandate', e)
        self.assertTrue(self.gibt_es(e))
        self.assertIn('Auszahlungen', self.text(antwort))
        self.assertEqual(EigentuemerAuszahlung.objects.filter(eigentuemer=e).count(), 1)

    def test_mandat_mit_dokument_bleibt(self):
        from rentals.models import Dokument
        e = self.neuer_eigentuemer()
        Dokument.objects.create(eigentuemer=e, datei='d/e.pdf', kategorie='sonstiges')
        self.loeschen('mandate', e)
        self.assertTrue(self.gibt_es(e))

    def test_mandat_mit_stockwerkeinheit_bleibt(self):
        e = self.neuer_eigentuemer()
        einheit = self.neue_einheit()
        einheit.stockwerkeigentuemer = e
        einheit.save(update_fields=['stockwerkeigentuemer'])
        self.loeschen('mandate', e)
        self.assertTrue(self.gibt_es(e))

    def test_leeres_mandat_wird_geloescht(self):
        e = self.neuer_eigentuemer()
        self.loeschen('mandate', e)
        self.assertFalse(self.gibt_es(e))


# ---------------------------------------------------------------------------
# Vertrag
# ---------------------------------------------------------------------------

class VertragLoeschenTests(LoeschBasis):

    def test_aktiver_vertrag_mit_offener_rechnung_bleibt(self):
        """t13-8 aus dem Audit: Rechnung 6 behielt `offen`, der Vertrag war weg."""
        antwort = self.loeschen('vertraege', self.a.vertrag)
        self.assertTrue(self.gibt_es(self.a.vertrag))
        self.a.debitor.refresh_from_db()
        self.assertEqual(self.a.debitor.vertrag_id, self.a.vertrag.pk,
                         'Die Rechnung hat ihren Vertrag verloren.')
        self.assertIn('Rechnungen', self.text(antwort))

    def test_vertrag_mit_nur_einer_zahlung_bleibt(self):
        from finance.models import Zahlungseingang
        v = self.neuer_vertrag()
        Zahlungseingang.objects.create(vertrag=v, betrag=Decimal('10'), datum_eingang=date(2025, 2, 1),
                                       buchungs_monat=date(2025, 2, 1))
        self.loeschen('vertraege', v)
        self.assertTrue(self.gibt_es(v))

    def test_vertrag_mit_mahnung_bleibt(self):
        from finance.models import Mahnung
        v = self.neuer_vertrag()
        Mahnung.objects.create(vertrag=v)
        self.loeschen('vertraege', v)
        self.assertTrue(self.gibt_es(v))

    def test_vertrag_mit_abnahme_bleibt(self):
        from rentals.models import Abnahmeprotokoll
        v = self.neuer_vertrag()
        Abnahmeprotokoll.objects.create(vertrag=v)
        self.loeschen('vertraege', v)
        self.assertTrue(self.gibt_es(v))

    def test_vertrag_mit_kuendigung_bleibt(self):
        from rentals.models import Kuendigung
        v = self.neuer_vertrag()
        Kuendigung.objects.create(vertrag=v)
        self.loeschen('vertraege', v)
        self.assertTrue(self.gibt_es(v))

    def test_vertrag_mit_dokument_bleibt(self):
        from rentals.models import Dokument
        v = self.neuer_vertrag()
        Dokument.objects.create(vertrag=v, datei='d/x.pdf', kategorie='sonstiges', bezeichnung='Zusatzvereinbarung')
        self.loeschen('vertraege', v)
        self.assertTrue(self.gibt_es(v))

    def test_sauberer_vertrag_wird_samt_paketdokumenten_geloescht(self):
        """Gegenprobe: Die Paket-Dokumente (automatisch erzeugt) sind kein Hindernis."""
        from core.views.pdf import VERTRAGSPAKET_TITEL
        from rentals.models import Dokument
        v = self.neuer_vertrag()
        titel = next(iter(VERTRAGSPAKET_TITEL))
        paket = Dokument.objects.create(vertrag=v, datei='d/paket.pdf', kategorie='vertrag', bezeichnung=titel)
        antwort = self.loeschen('vertraege', v)
        self.assertFalse(self.gibt_es(v))
        self.assertFalse(self.gibt_es(paket))
        self.assertIn('gelöscht', self.text(antwort))

    def test_gesperrter_vertrag_behaelt_seine_paketdokumente(self):
        """`Mietvertrag.delete()` löscht zuerst die Paket-Dokumente — dann erst den Vertrag.

        Wirft der Vertrag einen `ProtectedError`, dürfen die Dokumente nicht schon weg sein.
        """
        from core.views.pdf import VERTRAGSPAKET_TITEL
        from finance.models import DebitorenRechnung
        from rentals.models import Dokument
        v = self.neuer_vertrag()
        titel = next(iter(VERTRAGSPAKET_TITEL))
        paket = Dokument.objects.create(vertrag=v, datei='d/paket.pdf', kategorie='vertrag', bezeichnung=titel)
        DebitorenRechnung.objects.create(vertrag=v, titel='Miete', betrag=Decimal('1'),
                                         datum=date(2025, 1, 1), faellig_am=date(2025, 1, 31))
        with self.assertRaises(ProtectedError):
            v.delete()
        self.assertTrue(self.gibt_es(paket), 'Das Paket-Dokument ging verloren, obwohl der Vertrag bleibt.')
        self.assertTrue(self.gibt_es(v))

    def test_fremder_vertrag_gibt_404(self):
        antwort = self.c.post(f'/neu/vertraege/{self.b.vertrag.pk}/loeschen/')
        self.assertEqual(antwort.status_code, 404)
        self.assertTrue(self.gibt_es(self.b.vertrag))


# ---------------------------------------------------------------------------
# Objekt (Einheit) und alle Wege an den Ansichten vorbei
# ---------------------------------------------------------------------------

class ObjektUndDirektesLoeschenTests(LoeschBasis):

    def test_objekt_mit_vertrag_ist_nicht_loeschbar(self):
        """Es gibt keine Ansicht «Objekt löschen»; der Fremdschlüssel hält es trotzdem."""
        self.assertTrue(hindernisse(self.a.einheit))
        with self.assertRaises(ProtectedError):
            self.a.einheit.delete()
        self.assertTrue(self.gibt_es(self.a.einheit))

    def test_objekt_ohne_geschaeftsunterlagen_ist_loeschbar(self):
        e = self.neue_einheit()
        self.assertEqual(hindernisse(e), [])
        e.delete()
        self.assertFalse(self.gibt_es(e))

    def test_objekt_mit_dokument_oder_abnahme_ist_nicht_loeschbar(self):
        from rentals.models import Abnahmeprotokoll
        v = self.neuer_vertrag()
        Abnahmeprotokoll.objects.create(vertrag=v, einheit=v.einheit)
        with self.assertRaises(ProtectedError):
            v.einheit.delete()

    def test_mieter_delete_an_der_ansicht_vorbei_endet_im_schutz(self):
        for modell, objekt in (('Mieter', self.a.mieter), ('Liegenschaft', self.a.liegenschaft),
                               ('Eigentuemer', self.a.eigentuemer), ('Mietvertrag', self.a.vertrag),
                               ('Einheit', self.a.einheit)):
            with self.subTest(modell=modell):
                with self.assertRaises(ProtectedError):
                    objekt.delete()
                self.assertTrue(self.gibt_es(objekt))

    def test_queryset_delete_ist_genauso_geschuetzt(self):
        from crm.models import Mieter
        with self.assertRaises(ProtectedError):
            Mieter.objects.filter(pk=self.a.mieter.pk).delete()

    def test_rechnungen_zahlungen_und_abschluesse_verlieren_den_bezug_nie(self):
        """Das war der stille Teil: `SET_NULL` am Vertrag, am Mieterkonto vorbei."""
        from finance.models import DebitorenRechnung
        with self.assertRaises(ProtectedError):
            self.a.vertrag.delete()
        self.a.debitor.refresh_from_db()
        self.assertEqual(self.a.debitor.vertrag_id, self.a.vertrag.pk)
        self.assertEqual(DebitorenRechnung.objects.filter(vertrag=self.a.vertrag).count(), 1)

    def test_die_fremdschluessel_sind_protect(self):
        """Wächter: Die Liste der geschützten Verweise ist festgehalten.

        Wer einen davon auf CASCADE/SET_NULL zurückstellt, bricht den Löschschutz
        für Verträge, Rechnungen, Buchungen, Abrechnungen oder Abschlüsse. Eine
        neue Liste gehört in eine Entscheidung, nicht in eine Reparatur.
        """
        geschuetzt = {
            ('rentals.Mietvertrag', 'mieter'), ('rentals.Mietvertrag', 'einheit'),
            ('rentals.Dokument', 'mieter'), ('rentals.Dokument', 'einheit'),
            ('rentals.Dokument', 'liegenschaft'), ('rentals.Dokument', 'vertrag'),
            ('rentals.Kuendigung', 'vertrag'), ('rentals.Abnahmeprotokoll', 'vertrag'),
            ('rentals.Abnahmeprotokoll', 'einheit'),
            ('portfolio.Dokument', 'liegenschaft'), ('portfolio.Dokument', 'einheit'),
            ('portfolio.Liegenschaft', 'eigentuemer'),
            ('finance.DebitorenRechnung', 'vertrag'), ('finance.DebitorenRechnung', 'liegenschaft'),
            ('finance.DebitorenRechnung', 'einheit'), ('finance.Zahlungseingang', 'vertrag'),
            ('finance.Zahlungseingang', 'liegenschaft'), ('finance.Mahnung', 'vertrag'),
            ('finance.Betreibung', 'vertrag'), ('finance.Zahlungsvereinbarung', 'vertrag'),
            ('finance.Buchung', 'liegenschaft'), ('finance.KreditorenRechnung', 'liegenschaft'),
            ('finance.KreditorenRechnung', 'einheit'), ('finance.AbrechnungsPeriode', 'liegenschaft'),
            ('finance.Jahresabschluss', 'liegenschaft'), ('finance.Anlage', 'liegenschaft'),
            ('finance.Hypothek', 'liegenschaft'), ('finance.Erneuerungsfonds', 'liegenschaft'),
            ('finance.EigentuemerAuszahlung', 'eigentuemer'), ('finance.Bankbewegung', 'liegenschaft'),
        }
        abweichend = []
        for label, feld in sorted(geschuetzt):
            f = apps.get_model(label)._meta.get_field(feld)
            if f.remote_field.on_delete is not PROTECT:
                abweichend.append(f'{label}.{feld}: {f.remote_field.on_delete.__name__}')
        self.assertEqual(abweichend, [], 'Diese Fremdschlüssel sind nicht mehr PROTECT')

    def test_jedes_hindernis_ist_auch_ein_fremdschluessel_oder_ausdruecklich_nur_ansicht(self):
        """Alles, was die Ansicht zählt und die Datenbank NICHT schützt, ist benannt.

        Die Ansicht zählt mehr als der Fremdschlüssel schützt (Schadenmeldungen,
        STWEG-Beschlüsse). Die Differenz ist hier festgehalten: Wer sie vergrössert,
        muss bewusst entscheiden, dass an dieser Stelle nur die Ansicht schützt.
        """
        nur_ansicht = {
            ('tickets.SchadenMeldung', 'liegenschaft'), ('stweg.StwegAbrechnung', 'liegenschaft'),
            ('stweg.StwegBudget', 'liegenschaft'), ('stweg.StwegDokument', 'liegenschaft'),
            ('stweg.Versammlung', 'liegenschaft'), ('stweg.Zirkularbeschluss', 'liegenschaft'),
            ('crm.Kommunikation', 'mieter'),
        }
        for label, feld in sorted(nur_ansicht):
            f = apps.get_model(label)._meta.get_field(feld)
            self.assertIsNot(f.remote_field.on_delete, PROTECT, f'{label}.{feld} ist inzwischen PROTECT — Liste nachführen')

    def test_alle_loeschwege_der_fuenf_objekte_sind_gesperrt(self):
        """Jede URL, die eines der fünf Objekte löscht, antwortet auf einen Bestand mit Daten mit einer Sperre."""
        wege = (('personen', self.a.mieter), ('liegenschaften', self.a.liegenschaft),
                ('mandate', self.a.eigentuemer), ('vertraege', self.a.vertrag))
        for name, objekt in wege:
            with self.subTest(weg=name):
                antwort = self.loeschen(name, objekt)
                self.assertEqual(antwort.status_code, 200)
                self.assertTrue(self.gibt_es(objekt), f'/neu/{name}/<pk>/loeschen/ hat gelöscht')

    def test_der_admin_loescht_nichts(self):
        """Admin-Aktionen: Löschen ist in der Verwaltungsoberfläche des Betreibers abgeschaltet."""
        from django.contrib import admin
        from django.test import RequestFactory
        anfrage = RequestFactory().get('/admin/')
        anfrage.user = type('U', (), {'is_active': True, 'is_staff': True, 'is_superuser': True,
                                      'has_perm': lambda self, p: True})()
        for label in ('crm.Mieter', 'crm.Eigentuemer', 'portfolio.Liegenschaft', 'portfolio.Einheit',
                      'rentals.Mietvertrag'):
            with self.subTest(modell=label):
                modell_admin = admin.site._registry[apps.get_model(label)]
                self.assertFalse(modell_admin.has_delete_permission(anfrage),
                                 f'Der Admin erlaubt das Löschen von {label}')
                self.assertNotIn('delete_selected', modell_admin.get_actions(anfrage))
