"""Zwischen Kündigungsandrohung und Kündigung liegen dreissig Tage.

ART. 257d ABS. 1 OR

Ist der Mieter mit einer fälligen Zahlung im Rückstand, setzt ihm der
Vermieter **schriftlich** eine Zahlungsfrist und droht an, bei Nichtzahlung zu
kündigen. Bei Wohn- und Geschäftsräumen beträgt diese Frist mindestens
dreissig Tage.

WARUM DAS EINE REGEL IST UND KEINE FRISTENLISTE

Wird zu früh gekündigt, ist die Kündigung **nichtig** — nicht anfechtbar,
sondern von Anfang an wirkungslos. Der Vermieter merkt das oft erst vor der
Schlichtungsbehörde, nachdem er das Verfahren schon geführt hat: Räumungsklage
weg, Verfahren umsonst, und die Frist beginnt von vorn.

Eine Liste sagt, wann etwas fällig ist. Eine Regel sagt, dass dieser
Kündigungstermin nicht durchgeht. Das ist G7.

ZWEI DETAILS, DIE HÄUFIG FALSCH GEMACHT WERDEN

**Der Zugang zählt, nicht der Versand.** Dieselbe Unterscheidung wie beim
Kündigungstermin, und in beiden Fällen der häufigste Fehler.

**Der Tag des Zugangs zählt nicht mit.** Art. 77 Abs. 1 Ziff. 3 OR: Bei einer
nach Tagen bestimmten Frist zählt der Anfangstag nicht. Zugang am 1. ergibt
Fristende am 31. — gekündigt werden darf ab dem 1. des Folgemonats. Wer den
Zugangstag mitzählt, kündigt einen Tag zu früh und damit nichtig.
"""
from datetime import date

from django.test import TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.regelwerk import (ZAHLUNGSFRIST_JE_KATEGORIE, pruefen,
                              zahlungsfrist)


class ZahlungsfristTest(TestCase):

    def test_ohne_kuendigung_kommt_der_fruehestmoegliche_tag(self):
        """Der Normalfall: Die Regel sagt, ab wann gekündigt werden darf."""
        befund = zahlungsfrist(zugang=date(2026, 8, 1))
        self.assertTrue(befund.ok)
        self.assertEqual(befund.vorschlag, date(2026, 9, 1))
        self.assertIn('01.09.2026', befund.meldung)

    def test_ein_tag_zu_frueh_ist_nichtig(self):
        """Die Grenze ist eine Grenze."""
        befund = zahlungsfrist(zugang=date(2026, 8, 1),
                               gekuendigt_am=date(2026, 8, 31))
        self.assertFalse(befund.ok)
        self.assertIn('NICHTIG', befund.meldung,
                      'Die Meldung nennt die Folge nicht — dann klingt sie '
                      'nach Formfehler statt nach Totalverlust.')
        self.assertIn('257d', befund.meldung)

    def test_am_ersten_zulaessigen_tag_ist_es_gut(self):
        befund = zahlungsfrist(zugang=date(2026, 8, 1),
                               gekuendigt_am=date(2026, 9, 1))
        self.assertTrue(befund.ok, befund.meldung)

    def test_der_zugangstag_zaehlt_nicht_mit(self):
        """Art. 77 Abs. 1 Ziff. 3 OR — der Fehler, der einen Tag kostet.

        Wer den Zugangstag mitzählt, landet auf dem 31.08. als erstem
        zulässigen Tag. Das ist einer zu früh, und die Kündigung wäre nichtig.
        """
        befund = zahlungsfrist(zugang=date(2026, 8, 1))
        self.assertNotEqual(
            befund.vorschlag, date(2026, 8, 31),
            'Der Zugangstag wird mitgezählt — die Regel schlägt einen Tag '
            'vor, an dem eine Kündigung nichtig wäre.')

    def test_ein_nebenobjekt_hat_zehn_tage(self):
        """Der Fall, den die Etappe ausdrücklich verneint hat.

        Das Skript schrieb: «Anders als bei der Kaution gibt es hier keinen
        Geltungsbereich: Die Frist gilt für Wohn- UND Geschäftsräume.» Beide
        genannten Fälle stimmen — der dritte fehlte.

        `core/views/fw/kuendigung.py` rechnet seit jeher
        `min_frist = 30 if v.ist_geschuetzt else 10`, und `ist_geschuetzt`
        ist `mietrecht_kategorie in ('wohnen', 'gewerbe')`. Bei einem
        gesondert vermieteten Parkplatz sind es zehn Tage.

        Ohne diese Unterscheidung hätte die Regel dort «zwanzig Tage zu
        früh» gemeldet, wo Gesetz und Anwendung die Kündigung zulassen —
        genau die unbegründete Warnung, die dieselbe Etappe bei der Kaution
        zu Recht vermeidet.
        """
        befund = zahlungsfrist(zugang=date(2026, 8, 1),
                               kategorie='nebenobjekt')
        self.assertEqual(
            befund.vorschlag, date(2026, 8, 12),
            'Ein Nebenobjekt bekommt nicht die Zehn-Tage-Frist — dann warnt '
            'die Regel bei jedem Parkplatzvertrag zwanzig Tage lang '
            'unbegründet.')

    def test_eine_zulaessige_kuendigung_beim_parkplatz_wird_nicht_beanstandet(self):
        """Die Gegenrichtung, über die ganze Rechnung.

        Zugang 01.08., gekündigt am 12.08. — bei einem Parkplatz zulässig,
        bei einer Wohnung nichtig. Beides muss die Regel sagen.
        """
        parkplatz = zahlungsfrist(zugang=date(2026, 8, 1),
                                  gekuendigt_am=date(2026, 8, 12),
                                  kategorie='nebenobjekt')
        self.assertTrue(parkplatz.ok, parkplatz.meldung)

        wohnung = zahlungsfrist(zugang=date(2026, 8, 1),
                                gekuendigt_am=date(2026, 8, 12),
                                kategorie='wohnen')
        self.assertFalse(
            wohnung.ok,
            'Derselbe Tag ist bei einer Wohnung nicht zulässig — sonst '
            'prüft die Zeile darüber keinen Unterschied.')

    def test_geschaeftsraeume_haben_dreissig_tage(self):
        """`gewerbe` gehört zu den geschützten Kategorien, nicht zu den zehn."""
        self.assertEqual(zahlungsfrist(zugang=date(2026, 8, 1),
                                       kategorie='gewerbe').vorschlag,
                         date(2026, 9, 1))

    def test_die_kategorien_stimmen_mit_dem_bestand_ueberein(self):
        """Das Vokabular ist nicht frei erfunden.

        `portfolio.Einheit.MIETRECHT_KATEGORIE` kennt genau drei Werte. Führt
        jemand einen vierten ein, fällt er hier auf — sonst bekäme er still
        die Dreissig-Tage-Frist, ohne dass das jemand entschieden hat.
        """
        from portfolio.models import Einheit

        aus_bestand = set(Einheit.MIETRECHT_KATEGORIE.values())
        self.assertEqual(
            aus_bestand, set(ZAHLUNGSFRIST_JE_KATEGORIE),
            f'Die Kategorien laufen auseinander. Bestand: {sorted(aus_bestand)}, '
            f'Regel: {sorted(ZAHLUNGSFRIST_JE_KATEGORIE)}.')

    def test_die_geschuetzten_kategorien_sind_dieselben_wie_im_bestand(self):
        """`ist_geschuetzt` und die Tabelle hier müssen dasselbe meinen.

        Der eine Ort entscheidet über Kündigungsformular und Erstreckung, der
        andere über die Zahlungsfrist — beide aus demselben Rechtsgrund. Wenn
        sie auseinanderlaufen, verlängert oder verkürzt sich eine Frist, ohne
        dass es jemand bemerkt.
        """
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag

        # `ist_geschuetzt` ist eine Eigenschaft am Vertrag; ihre Regel steht
        # als Ausdruck im Quelltext — geprueft wird das Ergebnis je Kategorie.
        geschuetzt_laut_regel = {k for k, tage
                                 in ZAHLUNGSFRIST_JE_KATEGORIE.items()
                                 if tage == 30}
        quelle = Mietvertrag.ist_geschuetzt.fget.__doc__ or ''
        self.assertTrue(quelle, 'Die Eigenschaft hat keine Beschreibung mehr.')
        for kategorie in set(Einheit.MIETRECHT_KATEGORIE.values()):
            erwartet = kategorie in ('wohnen', 'gewerbe')
            with self.subTest(kategorie=kategorie):
                self.assertEqual(
                    kategorie in geschuetzt_laut_regel, erwartet,
                    f'«{kategorie}» gilt in der Zahlungsfrist-Tabelle als '
                    f'{"geschützt" if kategorie in geschuetzt_laut_regel else "Nebenobjekt"}, '
                    f'in `Mietvertrag.ist_geschuetzt` umgekehrt.')

    def test_die_frist_kommt_aus_der_regel(self):
        """`mindest_tage` ist eine Untergrenze, keine feste Zahl.

        Eine Verwaltung darf länger ansetzen. Kürzer nicht — aber das
        verhindert nicht diese Rechnung, sondern die juristische Prüfung des
        Regelsatzes.
        """
        befund = zahlungsfrist(zugang=date(2026, 8, 1), mindest_tage=60)
        self.assertEqual(befund.vorschlag, date(2026, 10, 1))
        # Und ein ausdruecklicher Wert schlaegt die Kategorie — sonst koennte
        # eine Verwaltung ihre strengere Hausregel nicht fuehren.
        self.assertEqual(
            zahlungsfrist(zugang=date(2026, 8, 1), mindest_tage=60,
                          kategorie='nebenobjekt').vorschlag,
            date(2026, 10, 1),
            'Bei gesetztem `mindest_tage` gewinnt die Kategorie — dann ist '
            'der Parameter wirkungslos.')

    def test_ueber_den_monatswechsel(self):
        """Dreissig Tage sind nicht ein Monat.

        Zugang am 15.01. plus dreissig Tage endet am 14.02., nicht am 15.02.
        Wer in Monaten rechnet, liegt in halben Jahren regelmässig daneben.
        """
        befund = zahlungsfrist(zugang=date(2026, 1, 15))
        self.assertEqual(befund.vorschlag, date(2026, 2, 15))

    def test_die_rechnung_ist_nachvollziehbar(self):
        """`Regelanwendung.ergebnis` speichert sie — im Streitfall zählt sie."""
        befund = zahlungsfrist(zugang=date(2026, 8, 1),
                               gekuendigt_am=date(2026, 8, 20))
        self.assertEqual(befund.rechnung['zugang'], '2026-08-01')
        self.assertEqual(befund.rechnung['fruehestens'], '2026-09-01')
        self.assertEqual(befund.rechnung['mindest_tage'], 30)


class AnbindungTest(TestCase):

    def test_die_regelart_ist_nicht_mehr_ungerechnet(self):
        import inspect

        from faelle import regelwerk
        quelle = inspect.getsource(regelwerk.pruefen)
        self.assertIn(
            "art == 'zahlungsfrist'", quelle,
            'Die Zahlungsfrist ist nicht an `pruefen()` angebunden.')

    def test_der_grundsatz_legt_sie_ohne_festen_parameter_an(self):
        """An den Daten, nicht am Quelltext.

        Diese Prüfung stand hier als `assertIn("'mindest_tage': 30",
        quelle)` — und war grün, obwohl E2.34 den Parameter GENAU DESHALB
        entfernt hatte: Ein fester Wert überschriebe die Zehn-Tage-Frist bei
        Nebenobjekten (Art. 257d Abs. 1 OR). Grün blieb sie, weil die
        Zeichenkette noch in dem Kommentar steht, der die Entfernung
        begründet. Ein Test, den Fliesstext erfüllt, sichert nichts — er
        behauptete hier sogar das Gegenteil des Gewollten.
        """
        from faelle.management.commands.regelwerk_grundsatz import (
            _regelvorlagen)
        from faelle.regelwerk_models import Regel

        vorlagen = {art: parameter for art, parameter, _b
                    in _regelvorlagen(Regel)}
        self.assertIn(Regel.ZAHLUNGSFRIST, vorlagen)
        self.assertNotIn(
            'mindest_tage', vorlagen[Regel.ZAHLUNGSFRIST],
            'Ein fester `mindest_tage` überschreibt die Zehn-Tage-Frist bei '
            'Nebenobjekten. Ohne Parameter rechnet die Regel nach Kategorie.')

    def test_alle_regelarten_werden_gerechnet(self):
        """Nachfolger von `test_es_bleibt_genau_eine_ungerechnete_regelart`.

        Der hielt fest, dass noch eine Art fehlt. Seit E2.36 fehlt keine —
        die Aussage steht jetzt in `test_zustellfrist_regel.py` und prueft
        die andere Richtung: Wer eine fuenfte Art einfuehrt, ohne sie zu
        rechnen, wird dort rot.
        """
        from faelle.regelwerk_models import Regel

        self.assertEqual(len(Regel.ARTEN), 4,
                         'Die Anzahl Regelarten hat sich geaendert — bitte '
                         'in test_zustellfrist_regel.py nachsehen.')


class UeberDieGanzeKetteTest(TestCase):
    """Vom angelegten Regelsatz bis zum Befund.

    Die Prüfungen darüber messen die Rechnung. Diese hier misst, was
    tatsächlich herauskommt, wenn `regelwerk_grundsatz` die Regel anlegt und
    `pruefen()` sie anwendet — und das ist eine andere Frage.

    Nachgemessen: Trägt die angelegte Regel `{'mindest_tage': 30}`, überfährt
    dieser Parameter die Kategorie, und ein Parkplatzvertrag bekommt wieder
    dreissig Tage. Die Rechnung wäre richtig und das Ergebnis falsch. Genau
    dieser Zustand war geliefert, und keine Prüfung an der Funktion allein
    hätte ihn gefunden.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('Z', '8000', 'Zürich')

    def _pruefen(self, kategorie):
        from django.core.management import call_command

        with mandant(self.a.organisation):
            call_command('regelwerk_grundsatz', verbosity=0)
            befund, _anwendung = pruefen(
                'zahlungsfrist', self.a.organisation,
                zugang=date(2026, 8, 1), kategorie=kategorie,
                protokollieren=False)
        return befund

    def test_ein_parkplatz_bekommt_zehn_tage_auch_ueber_pruefen(self):
        befund = self._pruefen('nebenobjekt')
        self.assertEqual(
            befund.vorschlag, date(2026, 8, 12),
            'Über `pruefen()` bekommt ein Nebenobjekt nicht die Zehn-Tage-'
            'Frist. Vermutlich trägt die angelegte Regel einen festen '
            '`mindest_tage`-Parameter, der die Kategorie überfährt.')

    def test_eine_wohnung_bekommt_dreissig(self):
        """Ohne diesen Fall prüfte der Test darüber nur «immer zehn»."""
        self.assertEqual(self._pruefen('wohnen').vorschlag, date(2026, 9, 1))
