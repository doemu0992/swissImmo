"""Tests des Zulaufs.

Die schärfste Anforderung ist eine negative: **Der Zulauf darf nicht raten.**
Eine falsche Zuordnung ist teurer als eine fehlende, weil sie nicht auffällt.
Die Tests prüfen deshalb ebenso sorgfältig, wann *kein* Vorschlag entsteht, wie
sie prüfen, wann einer entsteht.
"""
from django.test import TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.models import Fall, Fallart
from faelle.zulauf import KEINER, SICHER, uebernehmen, vorschlagen
from faelle.zulauf_models import Eingang, Zuordnungsregel, normalisieren


def _fallart(org, schluessel='zulaufpruefung'):
    art = Fallart(organisation=org, schluessel=schluessel, bezeichnung='Prüfung')
    art.save()
    from faelle.models import SchrittVorlage
    for nr in (1, 2):
        SchrittVorlage(fallart=art, nr=nr, etappe_nr=1, etappe='E',
                       bezeichnung=f'Schritt {nr}').save()
    return art


class NormalisierungTests(TestCase):
    def test_schreibweisen_fallen_zusammen(self):
        for variante in ('Muster AG', 'MUSTER  AG.', 'muster-ag', ' Muster   AG '):
            with self.subTest(variante=variante):
                self.assertEqual(normalisieren(variante), 'musterag')

    def test_leer_bleibt_leer(self):
        self.assertEqual(normalisieren(''), '')
        self.assertEqual(normalisieren(None), '')

    def test_ziffern_bleiben(self):
        self.assertEqual(normalisieren('QR 2026-1188'), 'qr20261188')


class _Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _eingang(self, org=None, **felder):
        felder.setdefault('quelle', Eingang.MAIL)
        felder.setdefault('betreff', 'Test')
        e = Eingang(organisation=org or self.a.organisation, **felder)
        e.save()
        return e


class VorschlagTests(_Basis):
    def test_ohne_merkmale_kein_vorschlag(self):
        """Der wichtigste Test dieser Datei."""
        with mandant(self.a.organisation):
            v = vorschlagen(self._eingang(betreff='Guten Tag'))
            self.assertEqual(v.sicherheit, KEINER)
            self.assertFalse(bool(v))
            self.assertIn('von Hand', v.begruendung)

    def test_gelernte_referenz_traegt(self):
        with mandant(self.a.organisation):
            Zuordnungsregel(
                organisation=self.a.organisation, merkmal=Zuordnungsregel.REFERENZ,
                wert=normalisieren('QR-4471'), wert_anzeige='QR-4471',
                akte=self.a.vertrag).save()
            v = vorschlagen(self._eingang(referenz='QR-4471'))
            self.assertEqual(v.sicherheit, SICHER)
            self.assertEqual(v.ziel, self.a.vertrag)

    def test_gelernter_absender_traegt(self):
        with mandant(self.a.organisation):
            Zuordnungsregel(
                organisation=self.a.organisation, merkmal=Zuordnungsregel.ABSENDER,
                wert=normalisieren('Sozialdienst Nyon'),
                wert_anzeige='Sozialdienst Nyon', akte=self.a.vertrag).save()
            v = vorschlagen(self._eingang(absender='SOZIALDIENST  NYON'))
            self.assertEqual(v.sicherheit, SICHER)

    def test_referenz_geht_dem_absender_vor(self):
        """Eine Referenz ist konstruiert, ein Name wiederholt sich."""
        with mandant(self.a.organisation):
            zweiter = self.a.vertrag
            Zuordnungsregel(
                organisation=self.a.organisation, merkmal=Zuordnungsregel.REFERENZ,
                wert='qr1', wert_anzeige='QR1', akte=zweiter).save()
            Zuordnungsregel(
                organisation=self.a.organisation, merkmal=Zuordnungsregel.ABSENDER,
                wert='meier', wert_anzeige='Meier', akte=self.a.liegenschaft).save()
            v = vorschlagen(self._eingang(referenz='QR1', absender='Meier'))
            self.assertEqual(v.ziel, zweiter)

    def test_bekannte_mieteradresse_traegt(self):
        with mandant(self.a.organisation):
            mieter = self.a.vertrag.mieter
            mieter.email = 'a.weber@example.ch'
            mieter.save()
            v = vorschlagen(self._eingang(absender_email='a.weber@example.ch'))
            self.assertEqual(v.sicherheit, SICHER)
            self.assertEqual(v.ziel, self.a.vertrag)

    def test_adresse_mit_zwei_vertraegen_ergibt_keinen_vorschlag(self):
        """Beim Umzug im Portfolio hat ein Mieter zwei Verträge — nicht raten."""
        with mandant(self.a.organisation):
            from rentals.models import Mietvertrag
            mieter = self.a.vertrag.mieter
            mieter.email = 'doppelt@example.ch'
            mieter.save()
            zweiter = Mietvertrag.objects.get(pk=self.a.vertrag.pk)
            zweiter.pk = None
            zweiter.save()
            v = vorschlagen(self._eingang(absender_email='doppelt@example.ch'))
            self.assertEqual(v.sicherheit, KEINER)

    def test_unbekannte_adresse_ergibt_keinen_vorschlag(self):
        with mandant(self.a.organisation):
            v = vorschlagen(self._eingang(absender_email='fremd@example.ch'))
            self.assertEqual(v.sicherheit, KEINER)

    def test_inaktive_regel_greift_nicht(self):
        with mandant(self.a.organisation):
            Zuordnungsregel(
                organisation=self.a.organisation, merkmal=Zuordnungsregel.REFERENZ,
                wert='qr9', wert_anzeige='QR9', akte=self.a.vertrag,
                aktiv=False).save()
            self.assertEqual(vorschlagen(self._eingang(referenz='QR9')).sicherheit,
                             KEINER)


class UebernahmeTests(_Basis):
    def test_zuordnen_ohne_fall(self):
        with mandant(self.a.organisation):
            e = self._eingang()
            fall = uebernehmen(e, ziel=self.a.vertrag)
            e.refresh_from_db()
            self.assertIsNone(fall)
            self.assertEqual(e.status, Eingang.ZUGEORDNET)
            self.assertEqual(e.akte, self.a.vertrag)

    def test_zuordnen_eroeffnet_fall_mit_schritten(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            e = self._eingang(betreff='Heizung kalt')
            fall = uebernehmen(e, ziel=self.a.vertrag, fallart=art)
            self.assertIsNotNone(fall)
            self.assertEqual(fall.schritte.count(), 2)
            self.assertEqual(fall.betreff, 'Heizung kalt')
            self.assertEqual(fall.akte, self.a.vertrag)

    def test_ohne_ziel_und_ohne_vorschlag_wird_geworfen(self):
        """Still nichts tun wäre die gefährliche Antwort."""
        with mandant(self.a.organisation):
            with self.assertRaises(ValueError):
                uebernehmen(self._eingang())

    def test_uebernehmen_ist_idempotent(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            e = self._eingang()
            uebernehmen(e, ziel=self.a.vertrag, fallart=art)
            vorher = Fall.objects.count()
            uebernehmen(e, ziel=self.a.vertrag, fallart=art)
            self.assertEqual(Fall.objects.count(), vorher)

    def test_regel_wird_gelernt_und_greift_beim_naechsten_mal(self):
        with mandant(self.a.organisation):
            erster = self._eingang(absender='Service social Nyon',
                                   referenz='QR-777')
            uebernehmen(erster, ziel=self.a.vertrag, regel_lernen=True)
            zweiter = self._eingang(absender='Service social Nyon',
                                    referenz='QR-777')
            v = vorschlagen(zweiter)
            self.assertEqual(v.sicherheit, SICHER)
            self.assertEqual(v.ziel, self.a.vertrag)

    def test_treffer_werden_gezaehlt(self):
        with mandant(self.a.organisation):
            uebernehmen(self._eingang(referenz='QR-1'), ziel=self.a.vertrag,
                        regel_lernen=True)
            zweiter = self._eingang(referenz='QR-1')
            uebernehmen(zweiter)
            regel = Zuordnungsregel.objects.get(wert=normalisieren('QR-1'))
            self.assertEqual(regel.treffer, 1)
            self.assertIsNotNone(regel.zuletzt)

    def test_gelerntes_merkmal_ist_das_staerkste(self):
        """Referenz vor Adresse vor Name."""
        with mandant(self.a.organisation):
            uebernehmen(
                self._eingang(referenz='QR-5', absender_email='x@example.ch',
                              absender='Meier'),
                ziel=self.a.vertrag, regel_lernen=True)
            self.assertTrue(Zuordnungsregel.objects.filter(
                merkmal=Zuordnungsregel.REFERENZ).exists())
            self.assertFalse(Zuordnungsregel.objects.filter(
                merkmal=Zuordnungsregel.ABSENDER).exists())


class AblageTests(_Basis):
    def test_ablegen_braucht_einen_grund(self):
        with mandant(self.a.organisation):
            e = self._eingang()
            for leer in ('', '   ', None):
                with self.subTest(grund=leer):
                    with self.assertRaises(ValueError):
                        e.ablegen(leer)
            e.refresh_from_db()
            self.assertEqual(e.status, Eingang.OFFEN)

    def test_abgelegter_eingang_ist_nicht_mehr_offen(self):
        with mandant(self.a.organisation):
            e = self._eingang()
            self.assertIn(e, Eingang.objects.offen())
            e.ablegen('Werbung')
            self.assertNotIn(e, Eingang.objects.offen())
            self.assertEqual(e.ablage_grund, 'Werbung')


class MandantentrennungTests(_Basis):
    def setUp(self):
        with mandant(self.a.organisation):
            self.eingang_a = self._eingang(absender='Nur für A', referenz='QR-A')
            Zuordnungsregel(
                organisation=self.a.organisation, merkmal=Zuordnungsregel.REFERENZ,
                wert=normalisieren('QR-A'), wert_anzeige='QR-A',
                akte=self.a.vertrag).save()
        with mandant(self.b.organisation):
            self.eingang_b = self._eingang(org=self.b.organisation,
                                           absender='Nur für B')

    def test_b_sieht_den_eingang_von_a_nicht(self):
        with mandant(self.b.organisation):
            self.assertEqual(
                Eingang.objects.filter(pk=self.eingang_a.pk).count(), 0)

    def test_b_sieht_die_regeln_von_a_nicht(self):
        with mandant(self.a.organisation):
            regel_a = Zuordnungsregel.objects.get(wert=normalisieren('QR-A'))
        with mandant(self.b.organisation):
            self.assertEqual(
                Zuordnungsregel.objects.filter(pk=regel_a.pk).count(), 0)

    def test_b_sieht_die_eigenen_sehr_wohl(self):
        """Gegenprobe: Ein Manager, der nichts liefert, bestünde sonst alles.

        Beide Verwaltungen führen einen Zulauf — das Mandantenfixture legt für
        jede einen Eingang und eine Zuordnungsregel an. Ohne diese Zeile
        prüften die Tests darüber nur, dass B leer ist, und das wäre auch bei
        einem durchweg leeren Manager erfüllt.
        """
        with mandant(self.b.organisation):
            self.assertEqual(
                Eingang.objects.filter(pk=self.eingang_b.pk).count(), 1)
            self.assertGreater(Zuordnungsregel.objects.count(), 0)

    def test_regel_von_a_erzeugt_bei_b_keinen_vorschlag(self):
        """Die gefährlichste Variante: eine Zuordnung über die Mandantengrenze."""
        with mandant(self.b.organisation):
            fremd = self._eingang(org=self.b.organisation, referenz='QR-A')
            self.assertEqual(vorschlagen(fremd).sicherheit, KEINER)

    def test_abgeleitete_organisation_stimmt(self):
        for modell in (Eingang, Zuordnungsregel):
            with self.subTest(modell=modell.__name__):
                fremde = modell.alle_organisationen.exclude(
                    organisation__in=[self.a.organisation, self.b.organisation])
                self.assertEqual(fremde.count(), 0)
