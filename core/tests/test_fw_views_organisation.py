"""Etappe 6.1, letzte Scheibe — die authentifizierten fw-Views.

Hier ist der Mandantenkontext gesetzt (die Middleware liest ihn aus der
`Mitgliedschaft`), `Organisation.objects.first()` war also nicht falsch,
sondern **ungenau**: Es funktioniert, solange die Middleware greift, und wird
zur stillen Fehlzuordnung, sobald eine View ohne sie aufgerufen wird — aus
einem Command, einem Signal, einer Shell, einem Test.

Ersetzt wurde in zwei Richtungen:

- **Liegt ein Objekt vor** (Vertrag, Liegenschaft, Mieter, Ticket), kommt die
  Verwaltung von dort. Das ist auch dann richtig, wenn der Kontext fehlt oder
  ein anderer ist.
- **Sonst** `aktuelle_organisation()` — der Kontext ausdrücklich statt
  „irgendeine aus dem Bestand".

Der Portal-Feed ist der Sonderfall und bekommt hier das meiste Gewicht: Dort
war die Richtung selbst verkehrt.
"""
from django.test import TestCase
from django.urls import reverse

from crm.models import Organisation

from ._isolation import MandantenFixture


class ZweiBestaende(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        assert Organisation.objects.order_by('pk').first().pk == cls.a.organisation.pk


class PortalFeedTokenTests(ZweiBestaende):
    """Der Token bestimmt die Verwaltung — nicht umgekehrt.

    Vorher wurde er gegen den Token der ERSTEN Organisation gehalten. Das geht
    auf zwei Arten schief, und die zweite ist die schlimmere:

    1. Der gültige Token der zweiten Verwaltung wird abgewiesen.
    2. Wer den Token der ersten hat, bekommt die Ausschreibungen **aller**
       Verwaltungen geliefert — `feed_objekte()` las ungefiltert.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for fixture, token in ((cls.a, 'token-a-geheim'), (cls.b, 'token-b-geheim')):
            o = fixture.organisation
            o.portal_feed_token = token
            o.save(update_fields=['portal_feed_token'])
            einheit = fixture.einheit
            einheit.zur_ausschreibung = True
            einheit.save(update_fields=['zur_ausschreibung'])

    def _feed(self, token):
        return self.client.get(reverse('fw_vermarktung_feed'), {'token': token})

    def test_token_der_zweiten_verwaltung_wird_angenommen(self):
        antwort = self._feed('token-b-geheim')
        self.assertEqual(antwort.status_code, 200,
                         'Ein gültiger Token wurde abgewiesen.')
        self.assertEqual(antwort.json()['anbieter'], 'Verwaltung B AG')

    def test_feed_zeigt_nur_die_objekte_dieser_verwaltung(self):
        # Der eigentliche Punkt. Vorher lieferte ein gültiger Token den ganzen
        # Bestand — Adressen und Mietzinsen fremder Verwaltungen.
        antwort = self._feed('token-b-geheim')
        inhalt = antwort.content.decode()
        self.assertIn('B-Weg 7', inhalt)
        self.assertNotIn('A-Weg 7', inhalt)
        self.assertEqual(antwort.json()['anzahl'], 1)

    def test_gegenprobe_der_andere_token_zeigt_den_anderen_bestand(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass oben gefiltert wird —
        # der Test bestünde auch, wenn der Feed immer leer wäre.
        antwort = self._feed('token-a-geheim')
        self.assertEqual(antwort.status_code, 200)
        inhalt = antwort.content.decode()
        self.assertIn('A-Weg 7', inhalt)
        self.assertNotIn('B-Weg 7', inhalt)

    def test_falscher_token_bleibt_verboten(self):
        self.assertEqual(self._feed('falsch').status_code, 403)

    def test_leerer_token_bleibt_verboten(self):
        self.assertEqual(self._feed('').status_code, 403)

    def test_leerer_token_trifft_keine_verwaltung_ohne_token(self):
        # Eine Verwaltung ohne gesetzten Token darf nicht durch einen leeren
        # Parameter getroffen werden — sonst wäre der Feed für jeden offen.
        o = self.b.organisation
        o.portal_feed_token = ''
        o.save(update_fields=['portal_feed_token'])
        self.assertEqual(self._feed('').status_code, 403)
        self.assertEqual(self._feed('token-b-geheim').status_code, 403)


class FeedObjekteTests(ZweiBestaende):
    """Die Filterung sitzt im Service, nicht nur in der View."""

    def test_ohne_organisation_liefert_der_service_weiterhin_alles(self):
        # Bewusst: Der Parameter ist optional, damit interne Aufrufe (Vorschau
        # in der Oberfläche, wo der Kontext ohnehin gilt) unverändert laufen.
        # Der ÖFFENTLICHE Weg gibt ihn zwingend mit — das prüft die Klasse oben.
        from core.services.portal_feed import feed_objekte
        for fixture in (self.a, self.b):
            e = fixture.einheit
            e.zur_ausschreibung = True
            e.save(update_fields=['zur_ausschreibung'])
        self.assertEqual(len(feed_objekte()), 2)

    def test_mit_organisation_nur_deren_objekte(self):
        from core.services.portal_feed import feed_objekte
        for fixture in (self.a, self.b):
            e = fixture.einheit
            e.zur_ausschreibung = True
            e.save(update_fields=['zur_ausschreibung'])
        objekte = feed_objekte(organisation=self.b.organisation)
        self.assertEqual(len(objekte), 1)
        self.assertIn('B-Weg 7', str(objekte))


class ObjektVorKontextTests(ZweiBestaende):
    """Wo ein Objekt vorliegt, kommt die Verwaltung von dort — kontextunabhängig.

    Diese Tests laufen bewusst OHNE gesetzten Mandantenkontext. Genau das ist
    der Unterschied zwischen `aktuelle_organisation()` und dem Objektbezug:
    Der Objektbezug trägt auch dann, wenn die Middleware nicht gelaufen ist.
    """

    def test_vertrag_kennt_seine_verwaltung(self):
        self.assertEqual(self.b.vertrag.organisation_id, self.b.organisation.pk)

    def test_mieter_kennt_seine_verwaltung(self):
        self.assertEqual(self.b.mieter.organisation_id, self.b.organisation.pk)

    def test_ticket_kennt_seine_verwaltung(self):
        # Grundlage des Reparaturauftrag-PDF (Auftraggeber gegenüber dem
        # Handwerker).
        self.assertEqual(self.b.schaden.organisation_id, self.b.organisation.pk)

    def test_zinsstand_kommt_vom_vertrag_nicht_aus_dem_bestand(self):
        # `Mietvertrag.mietzinspotenzial` las den Referenzzinssatz der ersten
        # Verwaltung. Massgeblich für eine Anpassung nach OR 269a ist der Stand
        # der Verwaltung, die den Vertrag führt.
        from decimal import Decimal
        self.a.organisation.aktueller_referenzzinssatz = Decimal('1.25')
        self.a.organisation.aktueller_lik_punkte = Decimal('100.0')
        self.a.organisation.save(update_fields=['aktueller_referenzzinssatz',
                                                'aktueller_lik_punkte'])
        self.b.organisation.aktueller_referenzzinssatz = Decimal('1.75')
        self.b.organisation.aktueller_lik_punkte = Decimal('100.0')
        self.b.organisation.save(update_fields=['aktueller_referenzzinssatz',
                                                'aktueller_lik_punkte'])

        vertrag = self.b.vertrag
        vertrag.basis_referenzzinssatz = Decimal('1.75')
        vertrag.basis_lik_punkte = Decimal('100.0')
        vertrag.save(update_fields=['basis_referenzzinssatz', 'basis_lik_punkte'])
        vertrag.refresh_from_db()

        # Gleicher Stand wie die EIGENE Verwaltung → kein Anpassungsbedarf.
        # Gegen die erste Verwaltung gerechnet (1.25 < 1.75) wäre es 'decrease'.
        self.assertEqual(vertrag.mietzinspotenzial, 'neutral')


class AutomationZinsTests(ZweiBestaende):
    """Die Automation laeuft ohne Kontext — und darf trotzdem nicht raten.

    `generate_auto_pendenzen` wird aus dem taeglichen Lauf aufgerufen, also ohne
    Request und ohne Mandantenkontext. Wer dort einen kontextabhaengigen Helfer
    benutzt, bekommt den festen Notwert 1.25 zurueck — und legt fuer jeden
    Vertrag mit hoeherer Basis eine Senkungs-Pendenz nach Art. 270a OR an, die
    es gar nicht gibt. Der Zinsstand muss deshalb je Vertrag von dessen
    Verwaltung kommen.
    """

    def _stand_setzen(self, fixture, zins):
        from decimal import Decimal
        o = fixture.organisation
        o.aktueller_referenzzinssatz = Decimal(str(zins))
        o.save(update_fields=['aktueller_referenzzinssatz'])
        v = fixture.vertrag
        v.mietzins_modell = 'fest'
        v.basis_referenzzinssatz = Decimal('1.50')
        v.status = 'aktiv'
        v.save(update_fields=['mietzins_modell', 'basis_referenzzinssatz', 'status'])
        return v

    def test_keine_pendenz_wenn_die_eigene_verwaltung_nicht_gesenkt_hat(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        # B liegt UEBER seiner Vertragsbasis → kein Senkungsanspruch.
        # Mit dem Notwert 1.25 gerechnet waere es faelschlich einer.
        v = self._stand_setzen(self.b, '1.75')
        self._stand_setzen(self.a, '1.75')
        generate_auto_pendenzen(horizont_tage=90)
        self.assertFalse(
            Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').exists(),
            'Senkungs-Pendenz angelegt, obwohl der Zins der eigenen Verwaltung hoeher liegt.')

    def test_gegenprobe_bei_echter_senkung_entsteht_die_pendenz(self):
        # Ohne diese Gegenprobe waere nicht belegt, dass der Test oben die
        # Zinslage misst — er bestuende auch, wenn nie eine Pendenz entstuende.
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        v = self._stand_setzen(self.b, '1.00')
        self._stand_setzen(self.a, '1.75')
        generate_auto_pendenzen(horizont_tage=90)
        self.assertTrue(
            Pendenz.objects.filter(vertrag=v, titel__icontains='Referenzzinssenkung').exists())

    def test_jede_verwaltung_wird_an_ihrem_eigenen_stand_gemessen(self):
        # A gesenkt, B nicht — es darf genau eine Pendenz geben, und zwar bei A.
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        va = self._stand_setzen(self.a, '1.00')
        vb = self._stand_setzen(self.b, '1.75')
        generate_auto_pendenzen(horizont_tage=90)
        offen = Pendenz.objects.filter(titel__icontains='Referenzzinssenkung')
        self.assertTrue(offen.filter(vertrag=va).exists())
        self.assertFalse(offen.filter(vertrag=vb).exists())


class ZinshelferBezugTests(TestCase):
    """Fachlogik darf den Zinsstand nie ohne Verwaltungsbezug holen.

    `get_current_ref_zins()` und `get_current_lik()` sind zugleich Vorgabe
    zweier Modellfelder und muessen deshalb argumentlos aufrufbar bleiben —
    ohne Kontext liefern sie einen festen Notwert. Genau daran ist die
    Automation einmal gescheitert: Sie holte den Wert global, bekam 1.25 statt
    des echten Standes und legte Senkungs-Pendenzen nach Art. 270a OR an, die
    es nicht gab.

    Eine Laufzeit-Warnung waere der falsche Waechter (sie feuerte 1'874-mal in
    der Suite, weil die Feldvorgabe bei jeder Objekterzeugung greift). Also
    prueft dieser Test die AUFRUFSTELLEN: In der Fachlogik muss ein Argument
    stehen. Neue argumentlose Aufrufe fallen hier auf, bevor sie in eine
    Mietzinsrechnung geraten.
    """

    #: Wo der argumentlose Aufruf richtig ist — die Feldvorgaben.
    ERLAUBT = {
        'rentals/models.py',       # basis_referenzzinssatz / basis_lik_punkte
        'portfolio/models.py',     # ref_zinssatz / lik_punkte
        'core/models.py',          # Import fuer dieselben Vorgaben
        'core/utils/__init__.py',  # die Definition selbst
    }

    def test_zinshelfer_werden_nie_ohne_bezug_aufgerufen(self):
        import re
        from pathlib import Path as _P

        from django.conf import settings

        wurzel = _P(settings.BASE_DIR)
        muster = re.compile(r'get_current_(?:ref_zins|lik)\(\s*\)')
        funde = []
        for datei in wurzel.rglob('*.py'):
            rel = datei.relative_to(wurzel).as_posix()
            if rel.startswith(('.venv', 'node_modules')) or '/migrations/' in rel:
                continue
            if '/tests/' in rel or rel in self.ERLAUBT:
                continue
            for nr, zeile in enumerate(datei.read_text(encoding='utf-8').splitlines(), 1):
                if zeile.lstrip().startswith('#'):
                    continue          # Kommentare erklaeren den Fall, sie rufen nicht auf
                if muster.search(zeile):
                    funde.append(f'{rel}:{nr}: {zeile.strip()}')

        self.assertEqual(funde, [], 'Zinsstand ohne Verwaltungsbezug geholt:\n' + '\n'.join(funde))
