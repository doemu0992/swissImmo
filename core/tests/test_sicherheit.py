"""Testmodul sicherheit — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 11 Klassen, unveraendert uebernommen."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import admin
from django.test import TestCase, Client, RequestFactory
from ._helfer import (_test_organisation,
    _team_user, _basis_objekte, _heute, Mieter, Organisation, Liegenschaft,
    Einheit, Mietvertrag, User)



class ModalFramingTests(TestCase):
    def test_xframe_options_erlaubt_eigene_iframes(self):
        """X-Frame-Options muss SAMEORIGIN sein — sonst bleiben die Popups leer."""
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        for url in ('/neu/mieterwechsel/', f'/neu/vertraege/{v.id}/', '/neu/schaeden/'):
            r = c.get(url)
            xf = r.headers.get('X-Frame-Options', '')
            self.assertEqual(xf.upper(), 'SAMEORIGIN', f"{url}: {xf!r}")

    def test_vertragsliste_oeffnet_detail_als_seite(self):
        lg, e, m, v = _basis_objekte()
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/vertraege/').content.decode()
        # Klick auf die Zeile navigiert zur vollen Detailseite (kein Modal)
        self.assertIn(f"window.location='/neu/vertraege/{v.id}/'", body)
        self.assertNotIn(f"fwModalOpenUrl('/neu/vertraege/{v.id}/'", body)

    def test_debitorenliste_ansehen_im_modal(self):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(vertrag=v, liegenschaft=lg, einheit=e,
                                         titel='Miete', betrag=Decimal('1700'),
                                         faellig_am=date.today(), status='offen')
        team = _team_user()
        c = Client(); c.force_login(team)
        body = c.get('/neu/debitoren/').content.decode()
        self.assertIn("fwModalOpen(this,'Vertrag',true)", body)   # breit für Vorschau daneben
        self.assertIn('id="fwModal"', body)


class PrueferRunde2SecurityUITests(TestCase):
    """Security-/UI-Funde aus dem tiefen Durchgang."""

    def test_public_report_leakt_keine_mieternamen(self):
        # Öffentliche QR-Schadenseite (ohne Login) darf keine Mieter-Nachnamen
        # oder "Leerstand" ausgeben (DSG / ID-Enumeration).
        lg, e, m, v = _basis_objekte()   # Mieter Nachname 'Muster'
        c = Client()
        r = c.get(f'/report/{lg.id}/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('Muster', body)
        self.assertNotIn('Leerstand', body)
        self.assertIn(e.bezeichnung, body)   # Objekt-Auswahl weiterhin möglich

    def test_kuendigungsbestaetigung_kein_anfechtungshinweis_bei_mieterkuendigung(self):
        # Anfechtung/Erstreckung (Art. 271/273 OR) gelten nur für Vermieterkündigung.
        # Der Rechtshinweis-Block ist auf absender=='vermieter' gegated.
        src = open('core/templates/core/dok_kuendigungsbestaetigung.html', encoding='utf-8').read()
        idx = src.find('angefochten')
        self.assertGreaterEqual(idx, 0)
        block = src[max(0, idx - 400):idx]
        self.assertRegex(block, r"absender\s*==\s*'vermieter'")


class SecurityBatchTests(TestCase):
    """GET-Endpoints müssen seiteneffektfrei sein; Storno ist Verwaltungs-only."""

    def test_get_mieter_liste_mutiert_adresse_nicht(self):
        # Fälliger Umzug (datierte Adress-Zeile) darf beim reinen Lesen (GET)
        # NICHT auf die Flat-Felder synchronisiert werden.
        # Bis E1c über crm.api.list_mieter geprüft; jetzt über die Personenliste
        # in /neu/, die dieselbe Rolle hat: reines Lesen darf nichts mutieren.
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2020, 1, 1),
                                     strasse='Neuweg 9', plz='3000', ort='Bern')
        c = Client(); c.force_login(_team_user())
        c.get('/neu/personen/')
        m.refresh_from_db()
        self.assertEqual(m.strasse, 'Seeweg 3')            # GET synchronisiert nicht

    def test_scheduler_aktiviert_adresswechsel(self):
        from core.services.automation import run_adress_umzuege
        from crm.models import MieterAdresse
        _lg, _e, m, _v = _basis_objekte()
        MieterAdresse.objects.create(mieter=m, art='wohn', gueltig_ab=date(2020, 1, 1),
                                     strasse='Neuweg 9', plz='3000', ort='Bern')
        n = run_adress_umzuege()
        m.refresh_from_db()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(m.strasse, 'Neuweg 9')            # jetzt via Scheduler synchronisiert

    # `test_ticket_gelesen_nur_mit_schreibrolle` ist mit E1c entfallen. Es prüfte
    # tickets.api.get_ticket: eine reine Leserolle durfte ein Ticket NICHT als
    # gelesen markieren. Die /neu/-Oberfläche hält das nicht ein —
    # fw_schaden_detail läuft unter TEAM_ROLLEN (Leserolle eingeschlossen) und
    # setzt `gelesen = True` beim Öffnen. Der Test liesse sich also nicht
    # umschreiben, er würde fehlschlagen. Das ist ein bestehender kleiner Fehler
    # in /neu/, nicht von E1c verursacht; er gehört in einen eigenen PR.

    def test_storno_ist_verwaltung_only(self):
        # Storno einer Journalbuchung ist ein buchhalterischer Korrektureingriff.
        #
        # Der Test las die Quelle bis Etappe 1 über den festen Pfad
        # 'core/views/fw.py'. Seit der Zerlegung ist fw ein Paket, und die View
        # wandert im Lauf der Etappe von Modul zu Modul. Deshalb wird jetzt die
        # Datei gelesen, in der die Funktion TATSÄCHLICH steht — dann überlebt
        # der Test jeden weiteren Block, ohne angefasst zu werden.
        import inspect
        from core.views.fw import fw_buchung_stornieren
        quelle = inspect.getsourcefile(inspect.unwrap(fw_buchung_stornieren))
        src = open(quelle, encoding='utf-8').read()
        idx = src.find('def fw_buchung_stornieren')
        self.assertNotEqual(idx, -1, f"fw_buchung_stornieren nicht in {quelle} gefunden")
        deko = src[max(0, idx - 120):idx]
        self.assertRegex(deko, r"rolle_erforderlich\(ROLLE_VERWALTER\)")

    def test_oeffentliches_schadenformular_leakt_kein_portfolio(self):
        # Das anonyme Schadenformular darf nicht das gesamte Portfolio (alle
        # Liegenschafts-Adressen) in die Seite dumpen (Adress-Enumeration/DSG).
        Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Geheimweg 7', plz='8000', ort='Zürich')
        Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Privatgasse 2', plz='3000', ort='Bern')
        c = Client()
        r = c.get('/schaden/melden/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('Geheimweg 7', body)
        self.assertNotIn('Privatgasse 2', body)
        # Freitext-Adressfeld bleibt erhalten (Meldung weiterhin möglich).
        self.assertIn('name="adresse"', body)


class MediaSchutzTests(TestCase):
    """Sensible Media-Dateien (Verträge, Bewerber-Dokumente) nur für Team;
    Objektfotos/Logos öffentlich."""

    def test_klassifikation_oeffentlich_vs_sensibel(self):
        from core.views.media_protected import ist_oeffentlich
        self.assertFalse(ist_oeffentlich('bewerbungen/ausweis/hans.jpg'))   # PII trotz Bild
        self.assertFalse(ist_oeffentlich('roh_vertraege/vertrag.pdf'))
        self.assertFalse(ist_oeffentlich('uploads/2026-01-01/Mietvertrag.pdf'))  # PDF
        # Ein Bild im Alt-Ordner `uploads/` galt früher als öffentlich — die
        # Annahme «Bild = Inseratfoto» stimmte aber nicht: Im selben Ordner
        # lagen Schadenfotos aus fremden Wohnungen und eingescannte Dokumente.
        # Der Ordner ist deshalb geschützt; Inseratfotos werden über die
        # Datenbank erkannt (`ist_objektfoto`) bzw. liegen neu in `objekt_fotos/`.
        self.assertFalse(ist_oeffentlich('uploads/2026-01-01/objektfoto.jpg'))
        self.assertTrue(ist_oeffentlich('objekt_fotos/2026-01-01/inserat.jpg'))
        self.assertTrue(ist_oeffentlich('logos/firma.png'))

    def test_anonymer_zugriff_auf_sensible_datei_404(self):
        import os
        from django.conf import settings
        rel = 'roh_vertraege/geheim_test.pdf'
        pfad = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, 'wb') as fh:
            fh.write(b'%PDF-1.4 geheim')
        try:
            anon = Client()
            self.assertEqual(anon.get('/media/' + rel).status_code, 404)   # anonym gesperrt
            team = Client(); team.force_login(_team_user())
            r = team.get('/media/' + rel)
            self.assertEqual(r.status_code, 200)                            # Team darf
        finally:
            os.remove(pfad)


class MediaZugriffTests(TestCase):
    """Welche hochgeladene Datei darf ein Fremder ohne Anmeldung abrufen?

    Sieben Dateifelder landeten alle im selben Topf `uploads/<datum>/` —
    Objektfotos fürs Inserat neben Schadenfotos aus fremden Wohnungen,
    eingescannten Mieterdokumenten, Unterhaltsbelegen und Innenaufnahmen der
    Ausstattung. Die Zugriffsregel unterscheidet nach Pfad und liess Bilder
    anonym durch, weil der Portal-Feed die Inserat-Fotos braucht. In einem
    gemeinsamen Topf KONNTE sie Inserat- nicht von Wohnungsfoto trennen.

    Jetzt hat jedes Modell seinen Ordner. Dieser Test hält fest, welcher
    öffentlich ist — und zwingt jedes NEUE Dateifeld zu einer Entscheidung.
    """

    #: Ordner, deren Bilder bewusst ohne Anmeldung ausgeliefert werden.
    OEFFENTLICH_GEWOLLT = {'logos', 'objekt_fotos'}

    def _felder(self):
        from django.apps import apps
        from django.db.models import FileField
        for m in apps.get_models():
            for f in m._meta.get_fields():
                if not isinstance(f, FileField):
                    continue
                ut = f.upload_to
                pfad = ut(m(), 'datei.jpg') if callable(ut) else (str(ut).rstrip('/') + '/datei.jpg')
                yield f"{m.__name__}.{f.name}", pfad

    def test_nur_inserat_und_logo_sind_oeffentlich(self):
        from core.views.media_protected import ist_oeffentlich
        offen = sorted({(name, pfad) for name, pfad in self._felder() if ist_oeffentlich(pfad)})
        ordner = {p.split('/')[0] for _n, p in offen}
        self.assertEqual(ordner, self.OEFFENTLICH_GEWOLLT,
                         'Ohne Anmeldung abrufbar sind: ' +
                         ', '.join(f'{n} ({p})' for n, p in offen))

    def test_schadenfotos_und_dokumente_brauchen_anmeldung(self):
        """Die konkreten Fälle beim Namen genannt — damit klar bleibt, worum
        es geht, falls jemand die Ordner wieder zusammenlegt."""
        from core.views.media_protected import ist_oeffentlich
        for feld, pfad in self._felder():
            if feld.split('.')[0] in ('SchadenMeldung', 'SchadenFoto', 'Dokument',
                                      'Unterhalt', 'Ausstattung'):
                self.assertFalse(ist_oeffentlich(pfad),
                                 f'{feld} ({pfad}) wäre ohne Anmeldung abrufbar')

    def test_alt_ordner_ist_geschuetzt_ausser_inseratfotos(self):
        """Bereits hochgeladene Dateien liegen weiter in `uploads/`. Der Ordner
        ist jetzt geschützt — sonst blieben die Alt-Bestände offen. Damit
        veröffentlichte Inserate nicht ins Leere laufen, bleiben Objektfotos
        auch dort öffentlich; erkannt über die Datenbank."""
        from core.views.media_protected import ist_oeffentlich, ist_objektfoto
        from portfolio.models import EinheitFoto
        from django.core.files.base import ContentFile
        alt = 'uploads/2026-01-01/wohnzimmer.jpg'
        self.assertFalse(ist_oeffentlich(alt))
        self.assertFalse(ist_objektfoto(alt))          # noch kein Objektfoto

        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Fotoweg 1', plz='3000', ort='Bern')
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='1 Zi', typ='wohnung')
        foto = EinheitFoto(einheit=e)
        foto.bild.name = alt                            # Alt-Pfad wie im Bestand
        foto.save()
        self.assertTrue(ist_objektfoto(alt))            # jetzt als Inserat-Bild erkannt

    def test_fremder_bekommt_schadenfoto_nicht(self):
        """Nicht nur die Regel, sondern die Auslieferung."""
        import os, shutil
        from django.conf import settings
        from django.test import Client
        rel = 'schaden_fotos/2026-01-01/bad.jpg'
        ziel = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, 'wb') as fh:
            fh.write(b'\xff\xd8\xff\xe0JFIF-Testbild')
        try:
            self.assertEqual(Client().get('/media/' + rel).status_code, 404)
            c = Client(); c.force_login(_team_user())
            self.assertEqual(c.get('/media/' + rel).status_code, 200)
        finally:
            shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'schaden_fotos'),
                          ignore_errors=True)

    def test_pfad_umweg_umgeht_den_schutz_nicht(self):
        """Ein vorangestelltes «./» oder «x/../» darf die Sensibel-Prüfung
        nicht austricksen. Vorher entschied `ist_oeffentlich` auf der rohen
        URL, während `safe_join` den Umweg wieder wegnormalisierte und die
        echte, sensible Datei öffnete — zwei Codestellen, zwei Pfade. Der
        Client normalisiert «./» selbst weg, «%2e» aber nicht; getestet wird
        deshalb der aufgelöste Pfad direkt über die View."""
        import os, shutil
        from django.conf import settings
        from django.test import RequestFactory
        from django.http import Http404
        from core.views.media_protected import geschuetzte_media
        rel = 'schaden_fotos/2026-01-01/geheim.jpg'
        ziel = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, 'wb') as fh:
            fh.write(b'\xff\xd8\xff\xe0JFIF')
        rf = RequestFactory()
        try:
            for umweg in ('./schaden_fotos/2026-01-01/geheim.jpg',
                          'x/../schaden_fotos/2026-01-01/geheim.jpg',
                          './/schaden_fotos/2026-01-01/geheim.jpg'):
                req = rf.get('/media/' + umweg)
                from django.contrib.auth.models import AnonymousUser
                req.user = AnonymousUser()
                with self.assertRaises(Http404,
                                       msg=f'Umweg «{umweg}» lieferte die Datei aus'):
                    geschuetzte_media(req, umweg)
        finally:
            shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'schaden_fotos'),
                          ignore_errors=True)

    def test_html_beleg_wird_nie_inline_gerendert(self):
        """Ein hochgeladener «Beleg» rechnung.html liefe sonst als Stored XSS
        gegen das nächste Team-Mitglied, das ihn öffnet. HTML/XML müssen wie
        SVG als Download (attachment, nosniff) rausgehen, nicht inline."""
        import os, shutil
        from django.conf import settings
        from django.test import Client
        rel = 'kreditoren_belege/boese.html'
        ziel = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, 'w') as fh:
            fh.write('<html><script>alert(1)</script></html>')
        try:
            c = Client(); c.force_login(_team_user())
            r = c.get('/media/' + rel)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Disposition'], 'attachment')
            self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        finally:
            shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'kreditoren_belege'),
                          ignore_errors=True)


class MediaDeployPruefungTests(TestCase):
    """Der Media-Schutz greift nur, wenn /media/ überhaupt bei Django ankommt.

    Ist /media/ beim Hoster als statisches Verzeichnis gemappt, liefert der
    Webserver die Dateien direkt aus. Der View wird dann nie aufgerufen, alle
    Regeln aus `media_protected` sind wirkungslos — und nichts weist darauf
    hin. Aus dem Code heraus lässt sich das nicht feststellen, deshalb prüft
    `pruefe_media_schutz` es beim Deploy von aussen: eine Kanarienvogel-Datei
    unter geschütztem Prefix ablegen, ohne Anmeldung abrufen, wieder löschen.

    Getestet wird die Auswertung (der Netzabruf selbst wird ersetzt) und die
    Voraussetzung, auf der die ganze Prüfung ruht: dass der gewählte Pfad für
    Django wirklich tabu ist.
    """

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()

    def tearDown(self):
        self._ov.disable()
        self._tmp.cleanup()

    def _lauf(self, antwort):
        """Führt den Befehl mit einer vorgegebenen HTTP-Antwort aus.

        Gibt (ausgabe, exitcode) zurück; exitcode None = kein Abbruch."""
        import io
        from unittest import mock
        from django.core.management import call_command
        from core.management.commands import pruefe_media_schutz as cmd
        raus, fehler = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(cmd, '_hole', return_value=antwort):
            try:
                call_command('pruefe_media_schutz', '--url', 'https://example.ch',
                             stdout=raus, stderr=fehler)
            except SystemExit as e:
                code = e.code
        return raus.getvalue() + fehler.getvalue(), code

    def test_kanarienvogel_pfad_ist_fuer_django_tabu(self):
        """Trägt der Test überhaupt? Läge der Pfad in einem öffentlichen
        Ordner, käme die Datei zu Recht zurück und die Prüfung würde bei jedem
        Deploy fälschlich Alarm schlagen."""
        from core.views.media_protected import ist_oeffentlich, ist_objektfoto
        from core.management.commands.pruefe_media_schutz import KANARIENVOGEL_PFAD
        self.assertFalse(ist_oeffentlich(KANARIENVOGEL_PFAD))
        self.assertFalse(ist_objektfoto(KANARIENVOGEL_PFAD))

    def test_inhalt_kommt_zurueck_ist_ein_befund(self):
        from core.management.commands.pruefe_media_schutz import KANARIENVOGEL_INHALT
        text, code = self._lauf((200, KANARIENVOGEL_INHALT))
        self.assertEqual(code, 2, 'Befund muss den Lauf mit Code 2 markieren')
        self.assertIn('MEDIA-SCHUTZ WIRKUNGSLOS', text)

    def test_abweisung_ist_kein_befund(self):
        text, code = self._lauf((404, b'<h1>Not Found</h1>'))
        self.assertIsNone(code)
        self.assertIn('Media-Schutz aktiv', text)

    def test_anmeldeseite_mit_status_200_ist_kein_befund(self):
        """Eine Weiterleitung auf die Anmeldung endet ebenfalls bei 200.
        Entscheidend ist deshalb der Inhalt, nicht der Status."""
        text, code = self._lauf((200, b'<html><form action="/login/">Anmelden</form>'))
        self.assertIsNone(code)
        self.assertIn('Media-Schutz aktiv', text)

    def test_nicht_erreichbar_meldet_keine_aussage(self):
        text, code = self._lauf((None, None))
        self.assertIsNone(code)
        self.assertIn('nicht geprüft', text)
        self.assertNotIn('WIRKUNGSLOS', text)

    def test_kanarienvogel_bleibt_nicht_liegen(self):
        """Die Testdatei liegt unter geschütztem Prefix in der echten
        Medienablage — sie darf nach dem Lauf nicht zurückbleiben."""
        import os
        from django.conf import settings
        from core.management.commands.pruefe_media_schutz import (
            KANARIENVOGEL_PFAD, KANARIENVOGEL_INHALT)
        self._lauf((200, KANARIENVOGEL_INHALT))
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT,
                                                     KANARIENVOGEL_PFAD)))

    def test_deploy_ruft_die_pruefung_auf(self):
        """Ein Befehl, den niemand ausführt, prüft nichts."""
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, 'deploy.sh')) as fh:
            self.assertIn('pruefe_media_schutz', fh.read(),
                          'deploy.sh ruft die Media-Schutz-Prüfung nicht auf')


class RollentrennungTests(TestCase):
    """Was darf ein Team-Mitglied mit eingeschränkter Rolle?

    Bisher geprüft war nur die äussere Schranke: Fremde kommen nicht an fremde
    Daten. Innerhalb der Verwaltung gibt es jedoch drei Stufen — Verwaltung
    (alles), Sachbearbeitung (erfassen/bearbeiten), Lesend (Treuhand/Revision,
    nur Ansicht). Diese Trennung nützt nur, wenn sie auch dort greift, wo eine
    Seite lesbar sein SOLL, aber einzelne Aktionen darauf nicht.

    Gefunden und behoben wurden drei Stellen, die für alle Team-Rollen
    schreibbar waren:

      Jahresabschluss   ein Buchungslauf, der die Periode versiegelt
      Mängelrüge        setzt eine Frist nach Art. 259 OR in Gang
      Untermiete        rechtsverbindliche Zustimmung/Ablehnung, Art. 262 OR
    """

    #: Views, die für alle Team-Rollen schreiben dürfen — mit Begründung.
    #: Wer hier etwas einträgt, trifft bewusst eine Entscheidung.
    ERLAUBT_OHNE_SCHREIBSCHRANKE = {
        'fw_modus_wechsel': 'setzt nur die eigene Ansicht (Einfach/Profi) in der Session',
    }

    def test_lesende_rolle_kann_nirgends_unbemerkt_schreiben(self):
        """Register-Prüfung: Jede View, die für alle Team-Rollen erreichbar ist
        und POST/Datei-Uploads verarbeitet, braucht INNEN eine Schreibschranke
        — oder einen Eintrag in der Ausnahmeliste oben. Eine neue Seite, die
        beides vergisst, fällt hier auf, nicht erst im Betrieb."""
        import ast
        import pathlib
        offen = []
        for pfad in sorted(pathlib.Path('core/views').rglob('*.py')):
            quelle = pfad.read_text(encoding='utf-8')
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for knoten in baum.body:
                if not isinstance(knoten, ast.FunctionDef):
                    continue
                rollen = []
                for d in knoten.decorator_list:
                    if isinstance(d, ast.Call) and getattr(d.func, 'id', '') == 'rolle_erforderlich':
                        rollen = [getattr(a.value, 'id', '') for a in d.args
                                  if isinstance(a, ast.Starred)]
                if 'TEAM_ROLLEN' not in rollen:
                    continue
                seg = ast.get_source_segment(quelle, knoten) or ''
                if 'request.POST' not in seg and 'request.FILES' not in seg:
                    continue
                if 'hat_rolle(request.user' in seg:
                    continue                      # innere Schranke vorhanden
                if knoten.name in self.ERLAUBT_OHNE_SCHREIBSCHRANKE:
                    continue
                offen.append(f'{knoten.name} ({pfad})')
        self.assertEqual(offen, [], 'Für ALLE Team-Rollen schreibbar, auch «Lesend»: '
                                    + ', '.join(offen))

    def _lesend(self):
        c = Client(); c.force_login(_team_user('Lesend')); return c

    def _sachbearbeitung(self):
        c = Client(); c.force_login(_team_user('Sachbearbeitung')); return c

    def test_lesend_darf_die_buchhaltung_ansehen(self):
        """Die Trennung soll nicht aussperren: Treuhand/Revision braucht die
        Buchhaltung. Ohne diese Prüfung wäre «kein Abschluss» auch durch ein
        pauschales Sperren der Seite erfüllt — das wäre die falsche Lösung."""
        self.assertEqual(self._lesend().get('/neu/buchhaltung/').status_code, 200)

    def _abschluss_versuch(self, client):
        """Löst den Jahresabschluss aus und meldet, ob der Buchungslauf lief.

        Gemessen wird der Aufruf selbst, nicht die Zahl neuer Buchungen: Ohne
        Erfolgsbuchungen im Jahr bucht der Abschluss ohnehin nichts, die
        Zählung bliebe also auch ohne Rollenschranke gleich — die Prüfung
        würde dann nichts belegen. Beim Gegentest aufgefallen."""
        from unittest import mock
        with mock.patch('core.services.jahresabschluss.buche_jahresabschluss',
                        return_value=(3, Decimal('1000.00'))) as gebucht:
            client.post('/neu/buchhaltung/', {'aktion': 'jahresabschluss', 'jahr': '2025'})
        return gebucht.called

    def test_lesend_darf_den_jahresabschluss_nicht_buchen(self):
        self.assertFalse(self._abschluss_versuch(self._lesend()),
                         'Rolle «Lesend» hat einen Buchungslauf ausgelöst')

    def test_sachbearbeitung_darf_den_jahresabschluss_nicht_buchen(self):
        """Auch die Sachbearbeitung nicht — laut Rollenkonzept sind
        Buchungsläufe der Verwaltung vorbehalten."""
        self.assertFalse(self._abschluss_versuch(self._sachbearbeitung()),
                         'Rolle «Sachbearbeitung» hat einen Buchungslauf ausgelöst')

    def test_verwaltung_darf_den_jahresabschluss_buchen(self):
        """Gegenstück — sonst würden die Prüfungen oben auch dann bestehen,
        wenn der Abschluss für niemanden mehr funktioniert."""
        c = Client(); c.force_login(_team_user('Verwaltung'))
        self.assertTrue(self._abschluss_versuch(c),
                        'Verwaltung kommt nicht mehr an den Jahresabschluss')

    def test_lesend_kann_keine_maengelruege_und_keine_untermiete_erklaeren(self):
        """Beides sind Erklärungen der Vermieterschaft mit Rechtsfolgen —
        Frist nach Art. 259 OR bzw. Zustimmung nach Art. 262 OR. Sie landen in
        der Vertragsakte. Die Rolle «Lesend» darf sie nicht abgeben."""
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        c = self._lesend()
        vorher = Dokument.objects.count()
        r1 = c.post(f'/neu/vertraege/{v.id}/maengelruege/',
                    {'mangel': 'Heizung defekt', 'frist_tage': '14'})
        r2 = c.post(f'/neu/vertraege/{v.id}/untermiete/',
                    {'untermieter': 'Frau Beispiel', 'entscheid': 'zustimmung'})
        for r, name in ((r1, 'Mängelrüge'), (r2, 'Untermiete')):
            self.assertEqual(r.status_code, 403,
                             f'{name}: Rolle «Lesend» wurde nicht abgewiesen ({r.status_code})')
        self.assertEqual(Dokument.objects.count(), vorher,
                         'Rolle «Lesend» hat ein Vertragsdokument erzeugt')

    def test_sachbearbeitung_darf_beides_weiterhin(self):
        """Gegenstück: Die Verschärfung darf die Sachbearbeitung nicht treffen."""
        from rentals.models import Dokument
        _lg, _e, _m, v = _basis_objekte()
        c = self._sachbearbeitung()
        c.post(f'/neu/vertraege/{v.id}/maengelruege/',
               {'mangel': 'Heizung defekt', 'frist_tage': '14'})
        c.post(f'/neu/vertraege/{v.id}/untermiete/',
               {'untermieter': 'Frau Beispiel', 'entscheid': 'zustimmung'})
        self.assertEqual(Dokument.objects.count(), 2,
                         'Sachbearbeitung kann Mängelrüge/Untermiete nicht mehr erstellen')

    def test_jeder_schreibende_api_endpunkt_nennt_seine_rolle(self):
        """Die API erbt `auth_lesen` als Vorgabe — ein POST/PUT/DELETE ohne
        eigenes `auth=` stünde damit auch der Rolle «Lesend» offen. Diese
        Prüfung hält fest, dass jeder schreibende Endpunkt seine Rolle
        ausdrücklich nennt."""
        import ast
        import pathlib
        ohne = []
        for pfad in sorted(pathlib.Path('.').rglob('*api*.py')):
            if '.venv' in str(pfad) or 'migrations' in str(pfad):
                continue
            quelle = pfad.read_text(encoding='utf-8')
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for knoten in ast.walk(baum):
                if not isinstance(knoten, ast.FunctionDef):
                    continue
                for d in knoten.decorator_list:
                    if not isinstance(d, ast.Call):
                        continue
                    if getattr(d.func, 'attr', '') not in ('post', 'put', 'patch', 'delete'):
                        continue
                    if not any(kw.arg == 'auth' for kw in d.keywords):
                        ohne.append(f'{knoten.name} ({pfad})')
        self.assertEqual(ohne, [], 'Schreib-Endpunkte ohne eigenes auth=: ' + ', '.join(ohne))

    def test_gesperrte_knoepfe_werden_gar_nicht_erst_gezeigt(self):
        """Die Schranke im View ist das Eine — ein Knopf, der die angemeldete
        Person auf die Anmeldeseite wirft, sieht nach Defekt aus. Was eine
        Rolle nicht darf, soll sie auch nicht sehen."""
        _lg, _e, _m, v = _basis_objekte()
        c_lesend, c_sb = self._lesend(), self._sachbearbeitung()
        c_vw = Client(); c_vw.force_login(_team_user('Verwaltung'))

        lesend = c_lesend.get(f'/neu/vertraege/{v.id}/').content.decode()
        schreib = c_sb.get(f'/neu/vertraege/{v.id}/').content.decode()
        for pfad in (f'/neu/vertraege/{v.id}/maengelruege/', f'/neu/vertraege/{v.id}/untermiete/'):
            self.assertNotIn(f'href="{pfad}"', lesend,
                             f'«Lesend» bekommt {pfad} noch als Verknüpfung angeboten')
            self.assertIn(f'href="{pfad}"', schreib,
                          f'Sachbearbeitung sieht {pfad} nicht mehr')
        self.assertIn('nicht für Ihre Rolle', lesend,
                      'Gesperrte Einträge werden «Lesend» nicht als gesperrt gekennzeichnet')

        self.assertNotIn('value="jahresabschluss"',
                         c_sb.get('/neu/buchhaltung/').content.decode(),
                         'Sachbearbeitung sieht den Jahresabschluss-Knopf')
        self.assertIn('value="jahresabschluss"', c_vw.get('/neu/buchhaltung/').content.decode(),
                      'Verwaltung sieht den Jahresabschluss-Knopf nicht mehr')

    def test_falsche_rolle_landet_nicht_wieder_auf_der_anmeldung(self):
        """Angemeldet, aber falsche Rolle → 403, nicht zurück zur Anmeldung.
        Der alte Weg führte im Kreis: erneut anmelden, wieder hier landen."""
        _lg, _e, _m, v = _basis_objekte()
        r = self._lesend().get(f'/neu/vertraege/{v.id}/maengelruege/')
        self.assertEqual(r.status_code, 403, f'erwartet 403, kam {r.status_code}')

    def test_nicht_angemeldet_geht_weiterhin_zur_anmeldung(self):
        """Gegenstück: Für Nichtangemeldete bleibt die Weiterleitung richtig —
        sie sollen sich ja anmelden können."""
        _lg, _e, _m, v = _basis_objekte()
        r = Client().get(f'/neu/vertraege/{v.id}/maengelruege/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])


def _heute():
    from django.utils import timezone
    return timezone.localdate()


class WebhookFailClosedTests(TestCase):
    """Webhooks weisen ab, wenn kein Secret konfiguriert ist.

    `/docuseal/webhook/` liess einen nicht angemeldeten POST durch, solange
    DOCUSEAL_WEBHOOK_SECRET nicht gesetzt war — begründet mit
    „Rückwärtskompatibilität". Der Endpunkt setzt aber `sign_status` auf
    'unterzeichnet' und ersetzt das Vertrags-PDF. Ein Fremder konnte damit
    eine Unterschrift vortäuschen.

    Bitter daran: Dieselbe Route gibt es ein zweites Mal in `rentals/api.py`,
    dort seit je fail-closed und durch Tests gehalten. Die ältere View-Fassung
    war schlicht nicht nachgezogen worden. Fehlende Prüfmöglichkeit ist kein
    Grund, nicht zu prüfen.
    """

    def _post(self, **extra):
        return Client().post('/docuseal/webhook/', data='{}',
                             content_type='application/json', **extra)

    def test_ohne_konfiguriertes_secret_wird_abgewiesen(self):
        from django.test import override_settings
        with override_settings(DOCUSEAL_WEBHOOK_SECRET=None):
            self.assertEqual(self._post().status_code, 403)

    def test_falsches_secret_wird_abgewiesen(self):
        from django.test import override_settings
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='richtig'):
            self.assertEqual(self._post(HTTP_X_WEBHOOK_SECRET='falsch').status_code, 403)
            self.assertEqual(self._post().status_code, 403)

    def test_richtiges_secret_wird_verarbeitet(self):
        """Gegenstück — sonst wäre „weist ab" auch dann erfüllt, wenn der
        Webhook überhaupt nicht mehr funktioniert."""
        from django.test import override_settings
        with override_settings(DOCUSEAL_WEBHOOK_SECRET='richtig'):
            self.assertEqual(self._post(HTTP_X_WEBHOOK_SECRET='richtig').status_code, 200)

    def test_fremder_kann_keinen_vertrag_auf_unterzeichnet_setzen(self):
        """Der Kern der Sache, nicht nur der Statuscode."""
        from django.test import override_settings
        _lg, _e, _m, v = _basis_objekte()
        vorher = v.sign_status
        nutzlast = ('{"event_type":"submission.completed","data":'
                    f'{{"name":"Mietvertrag {v.id}"}}}}')
        with override_settings(DOCUSEAL_WEBHOOK_SECRET=None):
            Client().post('/docuseal/webhook/', data=nutzlast,
                          content_type='application/json')
        v.refresh_from_db()
        self.assertEqual(v.sign_status, vorher,
                         'Ein nicht angemeldeter POST hat den Vertrag verändert')

    def test_brevo_webhook_ebenfalls_fail_closed(self):
        """Nicht verdrahtet und damit heute nicht erreichbar — die Funktion
        wird aber direkt geprüft, damit sie beim späteren Anschliessen nicht
        offen ist."""
        from core.views.webhooks import brevo_inbound_webhook
        from django.test import RequestFactory, override_settings
        req = RequestFactory().post('/', data='{}', content_type='application/json')
        with override_settings(BREVO_WEBHOOK_SECRET=None):
            self.assertEqual(brevo_inbound_webhook(req).status_code, 403)
        with override_settings(BREVO_WEBHOOK_SECRET='geheim'):
            r2 = RequestFactory().post('/', data='{}', content_type='application/json',
                                       HTTP_X_WEBHOOK_SECRET='geheim')
            self.assertEqual(brevo_inbound_webhook(r2).status_code, 200)

    def test_kein_webhook_bleibt_ohne_secret_offen(self):
        """Register-Prüfung: Jede csrf-freie View, die POST verarbeitet, muss
        ihr Secret prüfen. Ein neuer Webhook ohne Schranke fällt hier auf."""
        import ast
        import pathlib
        offen = []
        for pfad in sorted(pathlib.Path('core/views').rglob('*.py')):
            quelle = pfad.read_text(encoding='utf-8')
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for k in baum.body:
                if not isinstance(k, ast.FunctionDef):
                    continue
                namen = [getattr(d, 'id', getattr(d, 'attr', '')) for d in k.decorator_list]
                if 'csrf_exempt' not in namen:
                    continue
                seg = ast.get_source_segment(quelle, k) or ''
                if 'compare_digest' not in seg and '_webhook_secret_ok' not in seg:
                    offen.append(f'{k.name} ({pfad})')
        self.assertEqual(offen, [], 'csrf-freie POST-Views ohne Secret-Prüfung: '
                                    + ', '.join(offen))


class AusgehendeAufrufeTests(TestCase):
    """Kein ausgehender Aufruf ohne Zeitlimit, keiner unnötig im Anfragepfad.

    Antwortet ein fremder Dienst nicht, wartet `requests` ohne `timeout`
    unbegrenzt. Auf einem Hosting mit einem einzigen Arbeitsprozess hängt
    damit die ganze Anwendung an einem fremden Server.
    """

    def test_kein_requests_aufruf_ohne_zeitlimit(self):
        """Register-Prüfung über den ganzen Code — auch mehrzeilige Aufrufe."""
        import ast
        import pathlib
        ohne = []
        for pfad in sorted(pathlib.Path('.').glob('*/**/*.py')):
            if any(t in pfad.parts for t in ('.git', 'migrations')) or pfad.name.startswith('test'):
                continue
            quelle = pfad.read_text(encoding='utf-8', errors='ignore')
            if 'requests.' not in quelle:
                continue
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            for k in ast.walk(baum):
                if not isinstance(k, ast.Call):
                    continue
                f = k.func
                if not (isinstance(f, ast.Attribute)
                        and getattr(f.value, 'id', '') in ('requests', 'httpx')
                        and f.attr in ('get', 'post', 'put', 'patch', 'delete')):
                    continue
                if not any(kw.arg == 'timeout' for kw in k.keywords):
                    ohne.append(f'{pfad}:{k.lineno}')
        self.assertEqual(ohne, [], 'Ausgehende Aufrufe ohne timeout: ' + ', '.join(ohne))

    def test_marktdaten_holt_nur_bei_altem_stand_nach(self):
        """Der Endpunkt war mit gut einer Sekunde die langsamste Route. Ist der
        gespeicherte Stand frisch, darf er gar nicht erst ins Internet."""
        from unittest import mock
        from django.utils import timezone
        from crm.models import Organisation
        vw = Organisation.objects.first() or _test_organisation(
            firma='Test AG', strasse='Weg 1', plz='3000', ort='Bern')
        vw.letztes_update_marktdaten = timezone.now()
        vw.save()
        c = Client(); c.force_login(_team_user())
        with mock.patch('core.utils.market_data.update_verwaltung_rates') as geholt:
            r = c.get('/neu/marktdaten/live/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(geholt.called, 'Frischer Stand — trotzdem ins Internet gegangen')

    def test_marktdaten_holt_bei_altem_stand_doch_nach(self):
        """Gegenstück: Ist der Stand alt, muss der Weg noch funktionieren."""
        from unittest import mock
        from django.utils import timezone
        from crm.models import Organisation
        vw = Organisation.objects.first() or _test_organisation(
            firma='Test AG', strasse='Weg 1', plz='3000', ort='Bern')
        vw.letztes_update_marktdaten = timezone.now() - timedelta(days=5)
        vw.save()
        c = Client(); c.force_login(_team_user())
        with mock.patch('core.utils.market_data.update_verwaltung_rates') as geholt:
            c.get('/neu/marktdaten/live/')
        self.assertTrue(geholt.called, 'Alter Stand wird nicht mehr nachgeholt')


class ApiOberflaecheNachE1cTests(TestCase):
    """E1c: Von 82 Endpunkten sind genau zwei geblieben — beide öffentlich.

    Der Rest bediente die in E1b entfernte Vue-Oberfläche. Diese Klasse hält
    fest, dass die Fläche auch geschlossen bleibt: Ein versehentlich wieder
    eingehängter Router fiele hier auf, nicht erst im Betrieb."""

    # Je ein Pfad aus jedem der vier entfernten Router, plus die Doku-Seite.
    ENTFERNT = [
        '/api/portfolio/liegenschaften',
        '/api/crm/mieter',
        '/api/tickets/',
        '/api/finance/konten',
        '/api/docs',
    ]

    def test_entfernte_endpunkte_sind_weg(self):
        # Angemeldet geprüft: Ein 404 darf nicht bloss die Anmeldeweiche sein.
        c = Client(); c.force_login(_team_user())
        for pfad in self.ENTFERNT:
            with self.subTest(pfad=pfad):
                self.assertEqual(c.get(pfad).status_code, 404)

    def test_beide_oeffentlichen_endpunkte_antworten_anonym(self):
        # Ohne Anmeldung erreichbar — kein 302 auf den Login, kein 403 aus der
        # Session-Pflicht. Der Inhalt wird anderswo geprüft (Bewerbung: fehlende
        # Pflichtfelder → 4xx; Webhook: fehlendes Secret → 403).
        c = Client()
        self.assertNotIn(c.post('/api/mietprozess/public/bewerben', {}).status_code, (301, 302, 404))
        self.assertEqual(
            c.post('/api/rentals/webhook/docuseal', data='{}',
                   content_type='application/json').status_code, 403)   # fail-closed ohne Secret


class AdminNurLesendTests(TestCase):
    """E2: Der Unfold-Admin ist Auskunftswerkzeug, kein zweiter Schreibpfad.

    Geprüft wird über die tatsächliche Registrierung, nicht über eine Liste im
    Test — ein neuer ModelAdmin auf der schreibenden Unfold-Basisklasse fällt
    hier auf, nicht erst im Betrieb. Das ist der eigentliche Zweck dieser
    Klasse: Die Regel muss auch für Code gelten, den heute noch niemand
    geschrieben hat.
    """

    RECHTE = ('has_add_permission', 'has_change_permission', 'has_delete_permission')

    def _superuser_request(self):
        # Bewusst mit einem Superuser: Wären die Rechte an Django-Permissions
        # geknüpft statt hart verneint, würde genau er sie alle bestehen.
        req = RequestFactory().get('/admin/')
        req.user = User.objects.create_superuser('admin_e2', 'e2@example.com', 'x')
        return req

    def test_kein_registrierter_admin_darf_schreiben(self):
        req = self._superuser_request()
        self.assertGreaterEqual(len(admin.site._registry), 27)   # Regression: nichts still abgemeldet
        for modell, adm in admin.site._registry.items():
            for recht in self.RECHTE:
                with self.subTest(modell=modell._meta.label, recht=recht):
                    pruef = getattr(adm, recht)
                    self.assertFalse(pruef(req), f"{modell._meta.label}.{recht} erlaubt Schreiben")

    def test_auch_kein_inline_darf_schreiben(self):
        # Inlines haben eigene Rechte. Ein lesender ModelAdmin mit schreibendem
        # Inline wäre der offene Seiteneingang.
        req = self._superuser_request()
        gepruefte = 0
        for modell, adm in admin.site._registry.items():
            for inline_klasse in (getattr(adm, 'inlines', []) or []):
                inline = inline_klasse(modell, admin.site)
                gepruefte += 1
                for recht in self.RECHTE:
                    with self.subTest(inline=inline_klasse.__name__, recht=recht):
                        self.assertFalse(getattr(inline, recht)(req, None),
                                         f"{inline_klasse.__name__}.{recht} erlaubt Schreiben")
        self.assertGreaterEqual(gepruefte, 17)   # sonst prüft der Test nichts mehr

    def test_benutzerverwaltung_bleibt_in_neu_moeglich(self):
        # Der Admin ist zu; die Rechteverwaltung darf deshalb nicht mit ihm
        # zugehen. /neu/benutzer/ ist ab E2 der einzige Schreibpfad.
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/benutzer/').status_code, 200)
        c.post('/neu/benutzer/neu/', {'username': 'neuer_e2', 'passwort': 'Geheim!2345',
                                      'rolle': 'Lesend', 'vorname': 'Neu', 'nachname': 'Benutzer'})
        neuer = User.objects.filter(username='neuer_e2').first()
        self.assertIsNotNone(neuer, "Benutzer liess sich über /neu/ nicht anlegen")
        self.assertIn('Lesezugriff', list(neuer.groups.values_list('name', flat=True)))
