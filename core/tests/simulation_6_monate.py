"""Stress-Test: 6 Monate Liegenschaftsbewirtschaftung (01.11.2025 – 30.04.2026).

KEIN Bestandteil der normalen Suite (Dateiname ohne `test_`-Präfix). Aufruf:

    python manage.py test core.tests.simulation_6_monate --keepdb -v1

Die Zeit wird mit freezegun Tag für Tag vorgespult. Alles läuft über die echten
Wege, die ein Bewirtschafter benutzt: Scheduler-Commands (`monatslauf`,
`mahnlauf`, `taeglicher_lauf`-Teile) und die /neu/-Views per Test-Client.

Ergebnisse werden NICHT als Assertions abgebrochen, sondern in einem Protokoll
gesammelt (Befund-Liste), damit ein Fehler nicht die restlichen 5 Monate
verdeckt. Der Bericht landet in SIM_BERICHT (Umgebungsvariable) bzw. stdout.
"""
import json
import os
import traceback
from datetime import date, timedelta
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, Client
from freezegun import freeze_time

from ._helfer import User

D = Decimal
START = date(2025, 11, 1)
ENDE = date(2026, 4, 30)


class Protokoll:
    def __init__(self):
        self.eintraege = []

    def add(self, stufe, thema, text, tag=None):
        self.eintraege.append({'stufe': stufe, 'thema': thema, 'text': text,
                               'tag': str(tag) if tag else ''})

    def ok(self, thema, text, tag=None):
        self.add('OK', thema, text, tag)

    def fehler(self, thema, text, tag=None):
        self.add('FEHLER', thema, text, tag)

    def warn(self, thema, text, tag=None):
        self.add('WARNUNG', thema, text, tag)

    def info(self, thema, text, tag=None):
        self.add('INFO', thema, text, tag)

    def pruefe(self, bedingung, thema, ok_text, fehler_text, tag=None):
        (self.ok if bedingung else self.fehler)(thema, ok_text if bedingung else fehler_text, tag)
        return bool(bedingung)


P = Protokoll()


def schritt(thema, tag=None):
    """Dekorator: fängt Ausnahmen, damit die Simulation weiterläuft."""
    def deko(fn):
        def inner(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as e:                       # noqa: BLE001
                tb = traceback.format_exc().strip().splitlines()
                P.fehler(thema, f"ABSTURZ {type(e).__name__}: {e} @ {tb[-3].strip() if len(tb) > 3 else ''}", tag)
                return None
        return inner
    return deko


class Simulation(TestCase):
    maxDiff = None

    # ------------------------------------------------------------------ Aufbau
    def setUp(self):
        from core.tenancy import setze_organisation
        from crm.models import Eigentuemer, Mieter, Mitgliedschaft, Organisation, Handwerker
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        from django.contrib.auth.models import Group

        self.org = Organisation.objects.create(
            firma='Muster Immobilien Treuhand AG', strasse='Bahnhofstrasse 1', plz='8001', ort='Zürich',
            iban='CH9300762011623852957', email='info@muster-treuhand.ch',
            aktueller_referenzzinssatz=D('1.25'), aktueller_lik_punkte=D('107.1'))
        setze_organisation(self.org)
        grp, _ = Group.objects.get_or_create(name='Inhaber')
        self.user = User.objects.create_user('sim_inhaber', password='x', email='sim@muster-treuhand.ch')
        self.user.groups.add(grp)
        Mitgliedschaft.objects.create(benutzer=self.user, organisation=self.org, rolle='Inhaber')
        self.c = Client()
        self.c.force_login(self.user)

        self.eig_a = Eigentuemer.objects.create(firma_oder_name='Erbengemeinschaft Keller',
                                                email='keller@example.ch', iban='CH5604835012345678009')
        self.eig_b = Eigentuemer.objects.create(firma_oder_name='Pensionskasse Bern',
                                                email='pk@example.ch', iban='CH4431999123000889012')
        self.lg_a = Liegenschaft.objects.create(strasse='Seestrasse 12', plz='8002', ort='Zürich', kanton='ZH',
                                                eigentuemer=self.eig_a, organisation=self.org,
                                                versicherungswert=D('4000000')) \
            if self._hat_feld(Liegenschaft, 'kanton') else Liegenschaft.objects.create(
                strasse='Seestrasse 12', plz='8002', ort='Zürich', eigentuemer=self.eig_a,
                organisation=self.org, versicherungswert=D('4000000'))
        self.lg_b = Liegenschaft.objects.create(strasse='Aarbergergasse 5', plz='3011', ort='Bern',
                                                eigentuemer=self.eig_b, organisation=self.org,
                                                versicherungswert=D('2500000'))

        def einheit(lg, bez, typ, netto, nk):
            return Einheit.objects.create(liegenschaft=lg, bezeichnung=bez, typ=typ,
                                          nettomiete_aktuell=D(netto), nebenkosten_aktuell=D(nk))

        self.e = {
            'A1': einheit(self.lg_a, 'A1 3.5 Zi EG', 'whg', '1500', '200'),
            'A2': einheit(self.lg_a, 'A2 4.5 Zi 1.OG', 'whg', '1900', '250'),
            'A3': einheit(self.lg_a, 'A3 2.5 Zi 2.OG', 'whg', '1300', '180'),
            'A4': einheit(self.lg_a, 'A4 3.5 Zi 3.OG', 'whg', '1600', '210'),
            'G1': einheit(self.lg_a, 'G1 Ladenlokal', 'gew', '3200', '400'),
            'P1': einheit(self.lg_a, 'P1 Tiefgarage', 'pp', '180', '0'),
            'B1': einheit(self.lg_b, 'B1 3.5 Zi', 'whg', '1750', '220'),
            'B2': einheit(self.lg_b, 'B2 2.5 Zi', 'whg', '1250', '170'),
        }

        def mieter(v, n, mail_=True):
            return Mieter.objects.create(typ='person', vorname=v, nachname=n,
                                         email=f'{v.lower()}.{n.lower()}@example.ch' if mail_ else '',
                                         strasse='Alte Strasse 1', plz='8000', ort='Zürich')
        self.m = {
            'A1': mieter('Peter', 'Puenktlich'), 'A2': mieter('Tina', 'Teilzahler'),
            'A3': mieter('Norbert', 'Nichtzahler'), 'A4': mieter('Karin', 'Kuendigerin'),
            'G1': mieter('Boutique', 'Mode GmbH'), 'B1': mieter('Beat', 'Herabsetzer'),
            'B2': mieter('Bea', 'Brav', mail_=False),
        }
        self.v = {}

        def vertrag(key, beginn, netto, nk, kaution_monate=3, **extra):
            e = self.e[key if key in self.e else key[:2]]
            v = Mietvertrag.objects.create(
                mieter=self.m[key], einheit=e, beginn=beginn, netto_mietzins=D(netto), nebenkosten=D(nk),
                status='aktiv', kautions_betrag=(D(netto) + D(nk)) * kaution_monate, **extra)
            self.v[key] = v
            return v

        vertrag('A1', date(2023, 4, 1), '1500', '200')
        vertrag('A2', date(2024, 1, 1), '1900', '250')
        vertrag('A3', date(2024, 6, 1), '1300', '180')
        vertrag('A4', date(2022, 10, 1), '1600', '210')
        vertrag('G1', date(2021, 1, 1), '3200', '400', mwst_pflichtig=True, mwst_satz=D('8.1'),
                mietzins_modell='index', kuendigungsfrist_monate=6,
                kuendigungstermine='Ende März, Ende September')
        vertrag('B1', date(2024, 9, 1), '1750', '220')
        vertrag('B2', date(2025, 2, 1), '1250', '170')
        # Vertrag mit Beginn mitten im Monat (Pro-Rata-Test): Parkplatz an A1 ab 15.11.
        from crm.models import Mieter as _M
        self.v['P1'] = Mietvertrag.objects.create(
            mieter=self.m['A1'], einheit=self.e['P1'], beginn=date(2025, 11, 15),
            netto_mietzins=D('180'), nebenkosten=D('0'), status='aktiv', kuendigungsfrist_monate=0)

        self.hw_heizung = Handwerker.objects.create(firma='Heizung & Sanitär Meier AG', email='meier@example.ch',
                                                    branche='sanitaer')
        self.hw_maler = Handwerker.objects.create(firma='Maler Weiss GmbH', email='weiss@example.ch',
                                                  branche='maler')
        self.hw_storen = Handwerker.objects.create(firma='Storen Gross', email='', branche='allgemein')
        P.info('Aufbau', f"2 Liegenschaften, 8 Einheiten, 8 Mietverträge, Org. '{self.org.firma}'")

    @staticmethod
    def _hat_feld(model, name):
        return any(f.name == name for f in model._meta.get_fields())

    # ------------------------------------------------------------ Hilfsfunktionen
    def post(self, name_or_url, data=None, **kw):
        from django.urls import reverse
        url = name_or_url if name_or_url.startswith('/') else reverse(name_or_url, kwargs=kw or None)
        r = self.c.post(url, data or {}, follow=False)
        if r.status_code in (403, 404, 500) or (r.status_code == 302 and 'login' in (r.headers.get('Location') or '')):
            P.warn('HTTP', f"POST {url} → {r.status_code} {r.headers.get('Location', '')}")
        return r

    def rechnungen(self, key, titel_teil=None):
        from finance.models import DebitorenRechnung
        qs = DebitorenRechnung.objects.filter(vertrag=self.v[key]).exclude(status='storniert')
        if titel_teil:
            qs = qs.filter(titel__contains=titel_teil)
        return list(qs.order_by('faellig_am', 'id'))

    def zahle(self, key, betrag=None, rechnung=None, tag=None):
        """Zahlung über den Bankabgleich (der Weg des Bewirtschafters)."""
        offen = [r for r in self.rechnungen(key) if r.status in ('offen', 'teilbezahlt')]
        ziel = rechnung or (offen[0] if offen else None)
        if ziel is None:
            P.warn('Zahlung', f"{key}: keine offene Rechnung für Zahlung {betrag}", tag)
            return None
        daten = {'rechnung_id': ziel.id}
        if betrag is not None:
            daten['betrag'] = str(betrag)
        r = self.post('fw_bankabgleich_verbuchen', daten)
        ziel.refresh_from_db()
        return r

    def saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        s = Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False).aggregate(x=Sum('betrag'))['x'] or D('0')
        h = Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False).aggregate(x=Sum('betrag'))['x'] or D('0')
        return s - h

    # ------------------------------------------------------------------- Lauf
    def test_sechs_monate(self):
        heute = START
        with freeze_time(START) as ft:
            self.ft = ft
            self.szenario_start()
            while heute <= ENDE:
                ft.move_to(heute)
                self.tagesarbeit(heute)
                heute += timedelta(days=1)
        self.abschluss()
        self.sonden()
        self.bericht()

    # ------------------------------------------------------- Ausgangslage (t0)
    @schritt('Ausgangslage')
    def szenario_start(self):
        from rentals.models import Mietvertrag
        # Kaution: alle Verträge Sperrkonto einbezahlt (Bestandsübernahme)
        for key in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
            r = self.post('fw_kaution_aktion', {'aktion': 'einzahlung', 'einbezahlt_am': '2025-11-01',
                                                'kautions_konto': 'CH1234567890'}, vertrag_id=self.v[key].id)
        p = self.saldo('1015')
        P.pruefe(p > 0, 'Kaution', f"Sperrkonto 1015 nach Einzahlungen: CHF {p}", "Kautionen nicht bilanziert (1015 = 0)")
        # Kautions-Obergrenze: 5 Monatsmieten erfassen -> Deckel 3?
        from crm.models import Mieter
        e = self.e['A1']
        v = self.v['A1']
        v.kautions_betrag = D('9000'); v.save()
        v.refresh_from_db()
        P.pruefe(v.kautions_betrag <= (v.netto_mietzins + v.nebenkosten) * 3,
                 'Kaution Art. 257e', f"5-Monats-Kaution serverseitig auf CHF {v.kautions_betrag} geklemmt",
                 f"Kaution CHF {v.kautions_betrag} > 3 Monatsmieten erlaubt")
        v.kautions_betrag = D('5100'); v.save()

    # -------------------------------------------------------- Tageslogik
    def tagesarbeit(self, tag):
        self.c = Client()
        self.c.force_login(self.user)      # Session-Ablauf in Simulationszeit vermeiden
        # 1) Scheduler wie in PythonAnywhere
        if tag.day == 1:
            self.monatslauf(tag)
        if tag.weekday() == 0:                       # montags: Mahnlauf
            self.mahnlauf(tag)
        self.taeglich(tag)
        # 2) Ereignisse
        for ev in EREIGNISSE.get(tag, []):
            getattr(self, ev)(tag)
        # 3) Zahlungen
        self.zahlungen(tag)
        # 4) Monatsende: Abstimmung
        if (tag + timedelta(days=1)).day == 1:
            self.monatsende(tag)

    @schritt('Monatslauf')
    def monatslauf(self, tag):
        from finance.models import DebitorenRechnung
        vorher = DebitorenRechnung.objects.count()
        call_command('monatslauf', jahr=tag.year, monat=tag.month, stdout=open(os.devnull, 'w'))
        neu = DebitorenRechnung.objects.count() - vorher
        # zweiter Aufruf = Idempotenz
        call_command('monatslauf', jahr=tag.year, monat=tag.month, stdout=open(os.devnull, 'w'))
        doppelt = DebitorenRechnung.objects.count() - vorher - neu
        P.pruefe(doppelt == 0, 'Sollstellung', f"{tag:%m/%Y}: {neu} Rechnungen, idempotent",
                 f"{tag:%m/%Y}: 2. Lauf erzeugte {doppelt} Doppelrechnungen", tag)
        self.sollstellung_pruefen(tag, neu)

    def erwartete_monatsmiete(self, key, tag):
        v = self.v[key]
        ende = v.ende
        if v.beginn > date(tag.year, tag.month, 28) + timedelta(days=4):
            return None
        return v

    @schritt('Sollstellung-Prüfung')
    def sollstellung_pruefen(self, tag, neu):
        titel = f"Miete & NK {tag.month:02d}/{tag.year}"
        summe = {}
        for key, v in self.v.items():
            v.refresh_from_db()
            rs = self.rechnungen(key, titel)
            summe[key] = sum((r.betrag for r in rs), D('0'))
            if len(rs) > 1:
                P.fehler('Sollstellung', f"{key}: {len(rs)} Rechnungen '{titel}' (doppelt)", tag)
        P.info('Sollstellung', f"{titel}: " + ', '.join(f"{k}={s}" for k, s in summe.items()), tag)
        # Pro-Rata Parkplatz Nov 2025 (ab 15.11.: 16/30 von 180)
        if (tag.year, tag.month) == (2025, 11):
            erwartet = (D('180') * D(16) / D(30)).quantize(D('0.01'))
            P.pruefe(summe['P1'] == erwartet, 'Pro-Rata', f"Parkplatz Nov: {summe['P1']} (erwartet {erwartet})",
                     f"Parkplatz Nov: {summe['P1']} statt {erwartet}", tag)
        # MWST Gewerbe: 8.1% auf Netto+NK
        if key_g := self.rechnungen('G1', titel):
            erwartet = ((D('3200') + D('400')) * D('1.081')).quantize(D('0.01'))
            v = self.v['G1']
            exp = ((v.effektiver_netto_mietzins(tag) + v.effektive_nebenkosten(tag)) * D('1.081')).quantize(D('0.01'))
            P.pruefe(abs(key_g[0].betrag - exp) <= D('0.02'), 'MWST Gewerbe',
                     f"Gewerbe {titel}: {key_g[0].betrag} inkl. 8.1% MWST", f"Gewerbe {key_g[0].betrag} != {exp}", tag)

    @schritt('Mahnlauf')
    def mahnlauf(self, tag):
        vorher = len(mail.outbox)
        from finance.models import Mahnung
        m0 = Mahnung.objects.count()
        try:
            call_command('mahnlauf', stdout=open(os.devnull, 'w'))
        except Exception as e:                              # noqa: BLE001
            P.fehler('Mahnlauf', f"Command bricht ab: {e}", tag)
            return
        neu = Mahnung.objects.count() - m0
        if neu:
            for m in Mahnung.objects.order_by('-id')[:neu]:
                P.info('Mahnung', f"{m.debitoren_rechnung.vertrag.mieter} – {m.debitoren_rechnung.titel}: Stufe {m.stufe}, "
                                  f"offen {m.betrag_offen}, Gebühr {m.gebuehr}", tag)
        for msg in mail.outbox[vorher:]:
            if 'ahn' in msg.subject or 'rinner' in msg.subject or 'ahlung' in msg.subject:
                self.mails_mahn = getattr(self, 'mails_mahn', []) + [(tag, msg.to, msg.subject, msg.body)]

    @schritt('Täglicher Lauf')
    def taeglich(self, tag):
        from core.services.automation import generate_auto_pendenzen, run_adress_umzuege
        generate_auto_pendenzen(horizont_tage=90, user=None, organisation=self.org)
        run_adress_umzuege()

    @schritt('Zahlungen')
    def zahlungen(self, tag):
        """Zahlungsmoral. Tag 2 (bzw. nächster Werktag) eines Monats."""
        zahltag = self.zahltag(tag.year, tag.month)
        if tag != zahltag:
            return
        titel = f"Miete & NK {tag.month:02d}/{tag.year}"
        # Pünktliche: A1, P1, G1, B1, B2
        for key in ('A1', 'P1', 'G1', 'B1', 'B2'):
            for r in self.rechnungen(key, titel):
                if r.status in ('offen', 'teilbezahlt'):
                    self.zahle(key, rechnung=r, tag=tag)
        # A4 zahlt bis Kündigungsende
        for r in self.rechnungen('A4', titel):
            if r.status == 'offen':
                self.zahle('A4', rechnung=r, tag=tag)
        # Teilzahler A2: zahlt immer nur 1'000 auf die älteste offene Rechnung
        offen = [r for r in self.rechnungen('A2') if r.status in ('offen', 'teilbezahlt')]
        if offen:
            self.zahle('A2', D('1000'), rechnung=offen[0], tag=tag)
        # Nichtzahler A3: zahlt Nov (Startmonat), ab Dezember nichts mehr
        if (tag.year, tag.month) == (2025, 11):
            for r in self.rechnungen('A3', titel):
                self.zahle('A3', rechnung=r, tag=tag)

    @staticmethod
    def zahltag(jahr, monat):
        d = date(jahr, monat, 2)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    @schritt('Monatsende-Abstimmung')
    def monatsende(self, tag):
        from finance.models import DebitorenRechnung
        offen_nebenbuch = sum((r.offener_betrag for r in DebitorenRechnung.objects.filter(
            status__in=['offen', 'teilbezahlt'])), D('0'))
        haupt = self.saldo('1100')
        P.pruefe(abs(offen_nebenbuch - haupt) < D('0.05'), 'Abstimmung 1100',
                 f"{tag:%m/%Y}: Debitoren-Nebenbuch {offen_nebenbuch} = Hauptbuch 1100 {haupt}",
                 f"{tag:%m/%Y}: Nebenbuch {offen_nebenbuch} ≠ Hauptbuch 1100 {haupt} (Differenz {offen_nebenbuch - haupt})", tag)
        from finance.models import Buchung
        from django.db.models import Sum
        alles = Buchung.objects.filter(ist_storno=False).aggregate(x=Sum('betrag'))['x']
        # OP-Liste / Aging
        r = self.c.get('/neu/mahnwesen/')
        P.pruefe(r.status_code == 200, 'Mahnwesen-Seite', f"{tag:%m/%Y}: Mahnwesen-Übersicht lädt", f"Mahnwesen HTTP {r.status_code} → {r.headers.get('Location')}", tag)
        for url in ('/neu/mahnwesen/aging/', '/neu/sollstellung/', '/neu/schaeden/', '/neu/kautionen/'):
            rr = self.c.get(url)
            if rr.status_code >= 400:
                P.fehler('Seiten', f"{url} liefert HTTP {rr.status_code}", tag)

    # -------------------------------------------------------------- Ereignisse
    @schritt('E: Ticket Heizungsausfall')
    def ev_heizung_melden(self, tag):
        from tickets.models import SchadenMeldung
        r = self.post('fw_schaden_neu', {
            'liegenschaft_id': self.lg_a.id, 'einheit_id': self.e['A1'].id, 'titel': 'Heizungsausfall',
            'beschreibung': 'Heizkörper kalt seit gestern Abend, Aussentemperatur -6°C', 'prioritaet': 'hoch',
            'melder_vorname': 'Peter', 'melder_nachname': 'Puenktlich', 'email_melder': 'peter.puenktlich@example.ch',
            'gemeldet_von': self.m['A1'].id})
        t = SchadenMeldung.objects.filter(titel='Heizungsausfall').first()
        P.pruefe(t is not None, 'Ticket', f"Heizungsausfall erfasst (HTTP {r.status_code})",
                 f"Ticket 'Heizungsausfall' nicht angelegt (HTTP {r.status_code}, Formular-Felder?)", tag)
        self.t_heizung = t

    @schritt('E: Heizung beauftragen')
    def ev_heizung_auftrag(self, tag):
        t = self.t_heizung
        if not t:
            return
        self.post('fw_schaden_auftrag', {'handwerker_id': self.hw_heizung.id,
                                         'auftragstext': 'Notfall: Brenner prüfen, Heizung wieder in Betrieb'}, pk=t.id)
        from tickets.models import HandwerkerAuftrag
        a = HandwerkerAuftrag.objects.filter(ticket=t).first()
        P.pruefe(a is not None, 'Handwerkerauftrag', 'Auftrag erstellt', 'Kein Auftrag erstellt', tag)
        self.a_heizung = a

    @schritt('E: Heizung Kosten')
    def ev_heizung_kosten(self, tag):
        a = self.a_heizung
        if not a:
            return
        self.post('fw_auftrag_kosten', {'kosten_geschaetzt': '1800', 'kosten_effektiv': '2350.40',
                                        'kreditor_erstellen': 'on'}, pk=a.id)
        a.refresh_from_db()
        P.pruefe(a.kreditoren_rechnung_id, 'Handwerkerrechnung', f"Kreditorenrechnung {a.kreditoren_rechnung} zugewiesen",
                 'Keine Kreditorenrechnung zugewiesen', tag)
        P.pruefe(a.freigabe_status == 'ausstehend', 'Freigabe Eigentümer',
                 f"Schätzung CHF 1800 ≥ 1000 → Eigentümerfreigabe ausstehend",
                 f"Freigabestatus '{a.freigabe_status}' trotz Schätzung ≥ Schwelle", tag)
        # Ohne Freigabe: lässt sich die Rechnung trotzdem freigeben/bezahlen?
        kr = a.kreditoren_rechnung
        if kr:
            from finance.models import Buchungskonto
            ko = Buchungskonto.objects.filter(nummer='4000').first() or Buchungskonto.objects.filter(typ='aufwand').first()
            r = self.post('fw_kreditor_freigeben', {'konto_id': ko.id if ko else ''}, pk=kr.id)
            kr.refresh_from_db()
            if kr.status != 'neu' and a.freigabe_status == 'ausstehend':
                P.fehler('Freigabe-Kontrolle',
                         "Kreditorenrechnung wurde freigegeben/gebucht, obwohl die Reparaturfreigabe des Eigentümers "
                         "noch AUSSTEHEND ist (kein Sperrmechanismus zwischen Auftrag-Freigabe und Kreditor-Freigabe)", tag)
            self.kr_heizung = kr

    @schritt('E: Heizung zahlen/schliessen')
    def ev_heizung_abschluss(self, tag):
        kr = getattr(self, 'kr_heizung', None)
        if kr:
            kr.refresh_from_db()
            if kr.status in ('freigegeben', 'offen', 'teilbezahlt'):
                self.post('fw_kreditor_bezahlen', {'rechnung_id': kr.id, 'valuta': str(tag)})
                kr.refresh_from_db()
                P.pruefe(kr.status == 'bezahlt', 'Kreditor bezahlt', 'Handwerkerrechnung bezahlt', f"Status {kr.status}", tag)
        if self.t_heizung:
            self.post('fw_schaden_status', {'status': 'erledigt', 'melder_informieren': 'on'}, pk=self.t_heizung.id)

    @schritt('E: Wasserschaden')
    def ev_wasserschaden(self, tag):
        from tickets.models import SchadenMeldung
        self.post('fw_schaden_neu', {
            'liegenschaft_id': self.lg_a.id, 'einheit_id': self.e['A2'].id, 'titel': 'Wasserschaden Bad',
            'beschreibung': 'Frostbedingter Leitungsbruch unter Lavabo, Wasser im Parkett', 'prioritaet': 'hoch',
            'melder_vorname': 'Tina', 'melder_nachname': 'Teilzahler', 'gemeldet_von': self.m['A2'].id})
        t = SchadenMeldung.objects.filter(titel='Wasserschaden Bad').first()
        P.pruefe(t is not None, 'Ticket', 'Wasserschaden erfasst', 'Wasserschaden-Ticket nicht angelegt', tag)
        self.t_wasser = t
        if not t:
            return
        for hw, text, est, eff in ((self.hw_heizung, 'Leitung reparieren', '900', '1240.00'),
                                   (self.hw_maler, 'Wände und Decke trocknen, streichen', '1500', '1720.00')):
            self.post('fw_schaden_auftrag', {'handwerker_id': hw.id, 'auftragstext': text}, pk=t.id)
        from tickets.models import HandwerkerAuftrag
        self.a_wasser = list(HandwerkerAuftrag.objects.filter(ticket=t))
        P.pruefe(len(self.a_wasser) == 2, 'Handwerkerauftrag', 'Zwei Aufträge (Sanitär + Maler) am selben Ticket',
                 f"{len(self.a_wasser)} Aufträge statt 2", tag)
        for a, (est, eff) in zip(self.a_wasser, (('900', '1240.00'), ('1500', '1720.00'))):
            self.post('fw_auftrag_kosten', {'kosten_geschaetzt': est, 'kosten_effektiv': eff, 'kreditor_erstellen': 'on'}, pk=a.id)

    @schritt('E: Wasserschaden Weiterverrechnung')
    def ev_wasser_weiterverrechnen(self, tag):
        """Teilverschulden Mieter (Frost: Fenster gekippt gelassen) 30%."""
        krs = [a.kreditoren_rechnung for a in getattr(self, 'a_wasser', []) if a.kreditoren_rechnung_id]
        for a in self.a_wasser:
            a.refresh_from_db()
        krs = [a.kreditoren_rechnung for a in self.a_wasser if a.kreditoren_rechnung_id]
        P.pruefe(len(krs) == 2, 'Handwerkerrechnungen', 'Beide Rechnungen erfasst und zugewiesen',
                 f"Nur {len(krs)} von 2 Rechnungen zugewiesen", tag)
        if krs:
            kr = krs[0]
            r = self.post('fw_weiterverrechnung', {'vertrag_id': self.v['A2'].id, 'betrag': '372.00',
                                                   'titel': 'Anteil Mieter (Fenster gekippt)'}, kreditor_id=kr.id)
            P.info('Weiterverrechnung', f"HTTP {r.status_code} → {r.headers.get('Location', '')}", tag)

    @schritt('E: Storen-Ticket über Mieterportal')
    def ev_storen(self, tag):
        from tickets.models import SchadenMeldung
        c = Client()
        mu = User.objects.create_user('mieter_a1', password='x', email=self.m['A1'].email)
        self.m['A1'].benutzer = mu
        self.m['A1'].save()
        c.force_login(mu)
        r = c.post('/mieter/schaden/', {'titel': 'Storen klemmt', 'beschreibung': 'Lamellenstoren Wohnzimmer',
                                        'prioritaet': 'tief'})
        P.info('Mieterportal', f"Schadenmeldung Mieterportal HTTP {r.status_code} → {r.headers.get('Location')}", tag)
        t = SchadenMeldung.objects.filter(titel__icontains='Storen').first()
        if t is None:
            # Direktes Anlegen (Verwalter erfasst telefonische Meldung)
            self.post('fw_schaden_neu', {'liegenschaft_id': self.lg_a.id, 'einheit_id': self.e['A1'].id,
                                         'titel': 'Storen klemmt', 'beschreibung': 'Lamellenstoren Wohnzimmer',
                                         'prioritaet': 'niedrig'})
            t = SchadenMeldung.objects.filter(titel__icontains='Storen').first()
            P.warn('Mieterportal', "Storen-Meldung kam nicht über das Mieterportal an – manuell erfasst", tag)
        self.t_storen = t
        if t:
            self.post('fw_schaden_auftrag', {'handwerker_id': self.hw_storen.id, 'auftragstext': 'Storen richten'}, pk=t.id)

    @schritt('E: Ticket-Überwachung')
    def ev_ticket_ueberblick(self, tag):
        from tickets.models import SchadenMeldung
        r = self.c.get('/neu/schaeden/')
        P.pruefe(r.status_code == 200, 'Ticketliste', 'Schadenliste lädt', f"HTTP {r.status_code}", tag)
        offen = SchadenMeldung.objects.exclude(status='erledigt')
        alt = [t for t in offen if (tag - t.erstellt_am.date()).days > 14]
        if alt:
            P.warn('Ticket-SLA', f"{len(alt)} Ticket(s) älter als 14 Tage ohne Erledigt: " + ', '.join(t.titel for t in alt)
                   + " – prüfen, ob das System eine Eskalation auslöst (keine automatische Eskalation vorhanden)", tag)

    @schritt('E: 257d Zahlungsaufforderung')
    def ev_257d(self, tag):
        from core.models import Pendenz
        r = self.post('fw_verzug_257d', {'versand_am': str(tag), 'sendungsnummer': '98.00.123456.12345678'},
                      vertrag_id=self.v['A3'].id)
        p = Pendenz.objects.filter(vertrag=self.v['A3'], titel__startswith='Art. 257d').first()
        P.pruefe(p is not None, '257d', f"Zahlungsaufforderung erstellt, provisorische Frist {p.faellig_am if p else ''}",
                 f"257d-Aufforderung nicht erstellt (HTTP {r.status_code})", tag)
        self.p257 = p

    @schritt('E: 257d Zugang bestätigen')
    def ev_257d_zugang(self, tag):
        p = getattr(self, 'p257', None)
        if p:
            self.post('fw_verzug_zugang', {'zugang_am': str(tag)}, pk=p.id)
            p.refresh_from_db()
            P.info('257d', f"Zugang {p.zugang_am}, Frist bis {p.faellig_am}", tag)

    @schritt('E: 257d Kündigung')
    def ev_257d_kuendigung(self, tag):
        p = self.p257
        p.refresh_from_db()
        v = self.v['A3']
        from finance.models import DebitorenRechnung
        offen = sum((r.offener_betrag for r in self.rechnungen('A3') if r.status in ('offen', 'teilbezahlt')), D('0'))
        P.info('257d', f"Frist {p.faellig_am} abgelaufen? heute {tag}; offen CHF {offen}", tag)
        if tag <= p.faellig_am:
            P.fehler('257d', f"Kündigungstermin {tag} liegt vor/auf Fristende {p.faellig_am}", tag)
        from rentals.services import termin_257d
        ziel = termin_257d(tag)
        r = self.post('fw_kuendigung_erfassen', {
            'absender': 'vermieter', 'eingang_datum': str(tag), 'zustellung': 'einschreiben',
            'ausserordentlich': 'on', 'ausserordentlich_grund': 'Zahlungsverzug (Art. 257d OR)',
            'gewuenschtes_ende': str(ziel), 'bestaetigen': 'on', 'leerstand_anlegen': 'on'}, vertrag_id=v.id)
        v.refresh_from_db()
        P.pruefe(v.status == 'gekuendigt' and v.ende == ziel, '257d Kündigung',
                 f"A3 ausserordentlich gekündigt per {v.ende}", f"Status {v.status}, Ende {v.ende}, erwartet {ziel}", tag)

    @schritt('E: Kündigung A4')
    def ev_kuendigung_a4(self, tag):
        v = self.v['A4']
        from rentals.services import berechne_kuendigungstermin
        erwartet = date(2026, 3, 31)
        errechnet = berechne_kuendigungstermin(v, tag)
        P.pruefe(errechnet == erwartet, 'Kündigungstermin',
                 f"Eingang {tag} → Termin {errechnet} (3 Mt. Frist, Termine ausser Dezember)",
                 f"Eingang {tag} → Termin {errechnet}, erwartet {erwartet}", tag)
        r = self.post('fw_kuendigung_erfassen', {'absender': 'mieter', 'eingang_datum': str(tag),
                                                 'zustellung': 'einschreiben', 'bestaetigen': 'on',
                                                 'leerstand_anlegen': 'on'}, vertrag_id=v.id)
        v.refresh_from_db()
        P.pruefe(v.status == 'gekuendigt' and v.ende == erwartet, 'Kündigung',
                 f"A4 gekündigt, Ende {v.ende}", f"Status {v.status}, Ende {v.ende}", tag)
        from core.models import Pendenz
        n = Pendenz.objects.filter(vertrag=v, erledigt=False).count()
        P.info('Kündigung', f"{n} Auszugs-Pendenzen automatisch angelegt", tag)

    @schritt('E: Inserat/Bewerbungen')
    def ev_bewerbungen(self, tag):
        from mietprozess.models import Mietbewerbung
        self.bew = []
        for i, (vn, nn, ek) in enumerate((('Lena', 'Neumieter', '95000-110000'), ('Marco', 'Zweiter', '70000-85000'),
                                          ('Anja', 'Dritte', '60000-70000'))):
            self.bew.append(Mietbewerbung.objects.create(
                einheit=self.e['A4'], vorname=vn, nachname=nn, geburtsdatum=date(1988 + i, 3, 3),
                mobilnummer='079 111 22 3%d' % i, email=f'{vn.lower()}@example.ch', beruf='Ingenieur',
                einkommen_jahr=ek, gewuenschter_bezugstermin=date(2026, 4, 1)))
        P.ok('Neuvermietung', f"{len(self.bew)} Bewerbungen für A4 erfasst", tag)

    @schritt('E: Zusage & Vertragsentwurf')
    def ev_zusage(self, tag):
        b = self.bew[0]
        self.post('fw_bewerber_entscheid', {'entscheid': 'zusage'}, pk=b.id)
        self.post('fw_bewerber_absage_uebrige', {}, einheit_id=self.e['A4'].id)
        r = self.post('fw_bewerbung_zu_vertrag', {}, pk=b.id)
        from rentals.models import Mietvertrag
        neu = Mietvertrag.objects.filter(einheit=self.e['A4'], status='entwurf').first()
        P.pruefe(neu is not None, 'Neuvermietung', 'Vertragsentwurf aus Bewerbung erzeugt', 'Kein Entwurf erzeugt', tag)
        if neu:
            P.info('Neuvermietung', f"Entwurf: Netto {neu.netto_mietzins}, NK {neu.nebenkosten}, Kaution {neu.kautions_betrag}, "
                                    f"Basis-Ref.Zins {neu.basis_referenzzinssatz}, LIK {neu.basis_lik_punkte}, Beginn {neu.beginn}", tag)
            self.v_neu = neu

    @schritt('E: Abnahme A4')
    def ev_abnahme(self, tag):
        v = self.v['A4']
        r = self.post('fw_abnahme_neu', {
            'typ': 'auszug', 'datum': str(tag), 'mieter_anwesend': 'on', 'verwalter_name': 'V. Walter',
            'allgemein_zustand': 'gut', 'schluessel_anzahl': '3', 'zaehler_strom': '12345', 'abgeschlossen': 'on',
            'm_raum': ['Wohnzimmer', 'Küche', 'Bad'],
            'm_beschreibung': ['Grosses Loch in Wand (Dübel)', 'Herdplatte gesprungen', 'Fugen abgenutzt'],
            'm_verursacher': ['mieter', 'mieter', 'abnutzung'], 'm_kosten': ['320', '540', '200']}, vertrag_id=v.id)
        from rentals.models import Abnahmeprotokoll
        ab = Abnahmeprotokoll.objects.filter(vertrag=v, typ='auszug').first()
        P.pruefe(ab is not None, 'Abnahme', f"Abnahmeprotokoll erfasst, {ab.maengel.count() if ab else 0} Mängel",
                 f"Abnahme nicht gespeichert (HTTP {r.status_code})", tag)
        if ab:
            P.info('Abnahme', f"Mieteranteil-Summe: CHF {ab.kosten_mieter_total}", tag)
            self.abnahme = ab
        # Mängelrüge 267a
        if ab:
            r = self.post('fw_abnahme_ruege_267a', {}, pk=ab.id)
            P.info('Abnahme', f"Mängelrüge Art. 267a HTTP {r.status_code}", tag)

    @schritt('E: Schlussabrechnung A4')
    def ev_schlussabrechnung(self, tag):
        v = self.v['A4']
        r = self.post('fw_schlussabrechnung', {
            'aktion': 'buchen', 'auszug_datum': '2026-03-31', 'kaution_verrechnen': 'on',
            'pos_text': ['Mängel Abnahme zulasten Mieter (Dübellöcher, Herdplatte)'],
            'pos_betrag': ['560'], 'pos_richtung': ['zulasten'], 'pos_mwst': ['0']}, vertrag_id=v.id)
        v.refresh_from_db()
        P.info('Schlussabrechnung', f"HTTP {r.status_code}; Kaution zurückbezahlt am {v.kautions_zurueckbezahlt_am}, "
                                    f"Rückzahlung {v.kautions_rueckzahlung_betrag}, Abzug {v.kautions_abzug_betrag}", tag)
        b1015 = self.saldo('1015')
        P.info('Schlussabrechnung', f"Saldo 1015 (Sperrkonten) danach: {b1015}; 2010: {self.saldo('2010')}", tag)

    @schritt('E: Neuer Vertrag aktivieren')
    def ev_vertrag_aktivieren(self, tag):
        neu = getattr(self, 'v_neu', None)
        if not neu:
            return
        neu.refresh_from_db()
        r = self.post('fw_vertrag_status', {'status': 'aktiv'}, pk=neu.id)
        neu.refresh_from_db()
        alt = self.v['A4']
        P.pruefe(neu.status == 'aktiv', 'Neuvermietung', f"Neuer Vertrag aktiv ab {neu.beginn}", f"Status {neu.status}", tag)
        # Kaution neuer Mieter + Formular Anfangsmietzins (ZH: Formularpflicht)
        self.post('fw_kaution_aktion', {'aktion': 'einzahlung', 'einbezahlt_am': str(tag),
                                        'kautions_konto': 'CH4400000000'}, vertrag_id=neu.id)
        r2 = self.c.get(f'/neu/mietzins/{neu.id}/anfangsmietzins/')
        P.info('Anfangsmietzins', f"Formular /anfangsmietzins/ HTTP {r2.status_code} (ZH Formularpflicht bei Leerstand<Mieterwechsel: Vormiete {alt.netto_mietzins}→{neu.netto_mietzins})", tag)

    @schritt('E: Täglicher Lauf komplett')
    def ev_taeglicher_lauf(self, tag):
        import io
        out = io.StringIO()
        vor = self.org.aktueller_referenzzinssatz
        try:
            call_command('taeglicher_lauf', '--digest-weekday=-1', stdout=out, stderr=out)
        except Exception as e:          # noqa: BLE001
            P.fehler('Täglicher Lauf', f"bricht ab: {e}", tag)
        self.org.refresh_from_db()
        P.info('Täglicher Lauf', out.getvalue().strip().replace('\n', ' | ')[:400] + f" | Ref.Zins vorher {vor} nachher {self.org.aktueller_referenzzinssatz}", tag)
        self.org.aktueller_referenzzinssatz = vor
        self.org.save(update_fields=['aktueller_referenzzinssatz'])

    @schritt('E: Referenzzins sinkt')
    def ev_referenzzins(self, tag):
        self.org.aktueller_referenzzinssatz = D('1.00')
        self.org.save(update_fields=['aktueller_referenzzinssatz'])
        # Mieter B1 Herabsetzungsbegehren -> System zeigt Senkungsanspruch?
        v = self.v['B1']
        v.refresh_from_db()
        P.info('Referenzzins', f"B1 anzeige: {getattr(v, 'mietzins_potenzial_typ', None)}; potenzial={v.mietzinspotenzial if hasattr(v, 'mietzinspotenzial') else ''}", tag)
        r = self.c.get(f'/neu/mietzins/{v.id}/anpassung/')
        P.pruefe(r.status_code == 200, 'Mietzinsanpassung', 'Anpassungsformular lädt', f"HTTP {r.status_code}", tag)
        try:
            pot = r.context['pot']
            P.info('Referenzzins', f"Potenzial-Berechnung B1: {pot}", tag)
            if pot and pot.get('delta_prozent') is not None and pot['delta_prozent'] >= 0:
                P.fehler('Referenzzins', f"Referenzzins 1.25→1.00 (Senkung) aber Potenzial {pot.get('delta_prozent')}% ≥ 0", tag)
        except Exception as e:                    # noqa: BLE001
            P.warn('Referenzzins', f"Kein pot im Kontext: {e}", tag)
        # Der eingestellte Referenzzins wird nur manuell gepflegt:
        P.warn('Referenzzins', "Referenzzinssatz muss von Hand in der Organisation nachgeführt werden; der tägliche "
                               "Lauf holt ihn nur 'best effort' (Fehler werden verschluckt).", tag)

    @schritt('E: Mietzinssenkung B1')
    def ev_senkung(self, tag):
        v = self.v['B1']
        neu = (D('1750') * D('0.9709')).quantize(D('0.05'))     # -2.91 % ≈ 1 Viertelpunkt
        r = self.post('fw_mietzins_anpassung', {
            'aktion': 'speichern', 'neu_netto': str(neu), 'neu_zins': '1.00', 'neu_lik': '107.1',
            'wirksam_ab': '2026-04-01', 'begruendung': 'Senkung Referenzzinssatz 1.25% → 1.00%',
            'basis_zins': '1.25', 'basis_lik': '107.1'}, vertrag_id=v.id)
        from rentals.models import MietzinsAnpassung
        a = MietzinsAnpassung.objects.filter(vertrag=v).first()
        P.pruefe(a is not None, 'Mietzinsanpassung', f"Senkung erfasst: {a.alter_netto_mietzins if a else ''} → {a.neuer_netto_mietzins if a else ''} ab {a.wirksam_ab if a else ''}",
                 f"Senkung nicht erfasst (HTTP {r.status_code})", tag)
        v.refresh_from_db()
        P.info('Mietzinsanpassung', f"Vertrag.netto_mietzins nach Anpassung: {v.netto_mietzins}; effektiv ab 1.4.: {v.effektiver_netto_mietzins(date(2026, 4, 1))}; "
                                    f"basis_ref: {v.basis_referenzzinssatz}; effektive_basis: {v.effektive_basis()}", tag)

    @schritt('E: Indexanpassung Gewerbe')
    def ev_index_gewerbe(self, tag):
        v = self.v['G1']
        # zu frühes Wirksamkeitsdatum muss abgelehnt werden
        r = self.post('fw_mietzins_anpassung', {'aktion': 'speichern', 'neu_netto': '3290', 'neu_zins': '1.25',
                                                'neu_lik': '108.9', 'wirksam_ab': '2026-02-01',
                                                'basis_zins': '1.25', 'basis_lik': '107.1'}, vertrag_id=v.id)
        from rentals.models import MietzinsAnpassung
        n0 = MietzinsAnpassung.objects.filter(vertrag=v).count()
        P.pruefe(n0 == 0, 'Frist Art. 269d', "Zu frühe Erhöhung (6 Mt. Kündigungsfrist Geschäftsraum) korrekt abgelehnt",
                 "Erhöhung zum 01.02. akzeptiert obwohl Kündigungsfrist 6 Mt./Termine März+Sept.", tag)
        from rentals.services import naechster_anpassungstermin
        frueh = naechster_anpassungstermin(v, tag)
        P.info('Frist Art. 269d', f"Frühester Anpassungstermin für G1 (Mitteilung {tag}): {frueh}", tag)
        # zulässiges Datum: der vom System berechnete
        self.post('fw_mietzins_anpassung', {'aktion': 'speichern', 'neu_netto': '3290', 'neu_zins': '1.25',
                                            'neu_lik': '108.9', 'wirksam_ab': str(frueh),
                                            'basis_zins': '1.25', 'basis_lik': '107.1'}, vertrag_id=v.id)
        a = MietzinsAnpassung.objects.filter(vertrag=v).first()
        P.pruefe(a is not None, 'Indexmiete', f"Indexanpassung erfasst: {a.alter_netto_mietzins if a else ''}→{a.neuer_netto_mietzins if a else ''} ab {frueh}",
                 'Indexanpassung nicht erfasst', tag)
        self.g1_anpassung_ab = frueh

    @schritt('E: Nebenkostenabrechnung 2025')
    def ev_nk_abrechnung(self, tag):
        from finance.models import AbrechnungsPeriode, KreditorenRechnung, Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        for e in self.e.values():
            e.flaeche_m2 = D('80') if e.typ == 'whg' else D('120') if e.typ == 'gew' else D('12')
            e.save()
        per = AbrechnungsPeriode.objects.create(liegenschaft=self.lg_a, bezeichnung='HNK 2025 Seestrasse 12',
                                                start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        for lief, betrag, kto in (('Heizöl AG', '8400', '4100'), ('Stadtwerke Wasser', '2100', '4110'),
                                  ('Hauswart Kunz', '3600', '4120')):
            KreditorenRechnung.objects.create(
                lieferant=lief, betrag=D(betrag), liegenschaft=self.lg_a, status='bezahlt', is_hnk_relevant=True,
                leistungs_von=date(2025, 1, 1), leistungs_bis=date(2025, 12, 31), datum=date(2025, 12, 20),
                konto=Buchungskonto.objects.get(nummer=kto))
        from core.utils.billing import berechne_abrechnung
        res = berechne_abrechnung(per.id)
        if res.get('error'):
            P.fehler('Nebenkosten', f"Engine-Fehler: {res['error']}", tag)
            return
        P.info('Nebenkosten', f"Total Kosten 2025: {res.get('total_kosten')}", tag)
        summe_akonto = D('0')
        for a in res.get('abrechnungen', []):
            P.info('Nebenkosten', f"{a.get('einheit')}: Kosten {a.get('kosten_anteil')} Akonto {a.get('akonto')} Saldo {a.get('saldo')} ({a.get('info')})", tag)
        # Akonto-Realität: gestellt wurde im Zeitraum nur Nov/Dez 2025 (Simulationsstart), das System unterstellt 12 Monate
        v = self.v['A2']
        gestellt = sum((r.betrag for r in self.rechnungen('A2') if r.titel.startswith('Miete') and '/2025' in r.titel), D('0'))
        P.warn('Nebenkosten', "Akonto-Basis der Abrechnung = AKTUELLER Vertragswert × Tage (nicht die tatsächlich gestellten/bezahlten "
                              "Akontobeträge); unterjährige Akonto-Anpassungen, Gratismonate, NK-Erlass und Teilzahlungen fliessen nicht ein.", tag)
        self.per_2025 = per
        r = self.post('fw_nebenkosten_verbuchen', {}, pk=per.id)
        P.info('Nebenkosten', f"Verbuchen HTTP {r.status_code}", tag)
        nk = [x for x in self.rechnungen('A1') + self.rechnungen('A2') + self.rechnungen('A3') if x.titel.startswith('NK-Abrechnung')]
        P.pruefe(bool(nk), 'Nebenkosten', f"{len(nk)} NK-Nachzahlungen als Debitor gestellt", "NK-Abrechnung erzeugte keine Nachzahlung/Debitor", tag)
        # Wiederholung: darf nicht doppelt buchen
        n1 = len(nk)
        self.post('fw_nebenkosten_verbuchen', {}, pk=per.id)
        nk2 = [x for x in self.rechnungen('A1') + self.rechnungen('A2') + self.rechnungen('A3') if x.titel.startswith('NK-Abrechnung')]
        P.pruefe(len(nk2) == n1, 'Nebenkosten Idempotenz', "2. Verbuchen erzeugt nichts Neues", f"Doppelt verbucht: {n1}→{len(nk2)}", tag)

    @schritt('E: Eigentümer-Auszahlung')
    def ev_eigentuemer(self, tag):
        r = self.c.get(f'/neu/mandate/{self.eig_a.id}/abrechnung/')
        P.info('Eigentümer', f"Eigentümerabrechnung HTTP {r.status_code}", tag)
        try:
            call_command('send_eigentuemer_reports', stdout=open(os.devnull, 'w'))
        except Exception as e:                  # noqa: BLE001
            P.fehler('Eigentümerreport', f"send_eigentuemer_reports: {e}", tag)

    # ----------------------------------------------------------- Abschluss
    @schritt('Abschluss')
    def abschluss(self):
        from finance.models import Buchung, DebitorenRechnung, Mahnung
        # Mahn-Verlauf A3
        ms = list(Mahnung.objects.filter(debitoren_rechnung__vertrag=self.v['A3']).order_by('datum', 'stufe'))
        P.info('Mahnverlauf A3', ' | '.join(f"{m.datum} {m.debitoren_rechnung.titel[-7:]} St.{m.stufe}" for m in ms))
        ms2 = list(Mahnung.objects.filter(debitoren_rechnung__vertrag=self.v['A2']).order_by('datum', 'stufe'))
        P.info('Mahnverlauf A2 (Teilzahler)', ' | '.join(f"{m.datum} {m.debitoren_rechnung.titel[-7:]} St.{m.stufe}" for m in ms2))
        # Mahn-Mails
        for (tag, to, subj, body) in getattr(self, 'mails_mahn', [])[:60]:
            pass
        mm = getattr(self, 'mails_mahn', [])
        P.info('Mahn-Mails', f"{len(mm)} Mahnmails verschickt")
        stufe3 = [x for x in mm if '257d' in x[3] or 'ündigung' in x[3]]
        P.info('Mahn-Mails', f"davon mit Kündigungsandrohung/257d im Text: {len(stufe3)}")
        for x in mm[:4]:
            P.info('Mahn-Mail-Beispiel', f"{x[0]} an {x[1]} «{x[2]}»: {x[3][:220]!r}")
        # Mieter A3 bewohnt weiter -> wird Nutzungsentschädigung gestellt?
        v = self.v['A3']
        v.refresh_from_db()
        apr = self.rechnungen('A3', 'Miete & NK 04/2026')
        P.pruefe(bool(apr), 'Nutzungsentschädigung',
                 'April-Miete/Entschädigung für A3 gestellt', "Nach Vertragsende (28.02.) wird für A3 nichts mehr gestellt, "
                 "obwohl der Mieter nicht ausgezogen ist (keine Entschädigung für unrechtmässige Weiterbenützung)")
        offen = sum((r.offener_betrag for r in self.rechnungen('A3') if r.status in ('offen', 'teilbezahlt')), D('0'))
        P.info('Forderung A3', f"Offene Forderungen A3 gesamt: CHF {offen}; Kaution Sperrkonto A3 CHF {v.kautions_betrag}")

    @schritt('Sonden')
    def sonden(self):
        from finance.models import DebitorenRechnung, Zahlungseingang, Mahnung
        from rentals.models import Leerstand
        from core.models import Pendenz
        tag = ENDE
        with freeze_time(ENDE):
            # (a) Mahngebühr auf Mahngebühr
            geb = list(DebitorenRechnung.objects.filter(vertrag=self.v['A3'], titel__contains='Mahngebühr').exclude(status='storniert'))
            roh = list(DebitorenRechnung.objects.filter(vertrag=self.v['A3'], titel__startswith='Miete'))
            gemahnt_geb = Mahnung.objects.filter(debitoren_rechnung__in=geb).count()
            P.pruefe(gemahnt_geb == 0, 'Mahngebühr-Kaskade',
                     'Mahngebühren werden nicht selbst gemahnt',
                     f"A3: {len(geb)} Mahngebühr-Rechnungen (total CHF {sum(g.betrag for g in geb)}) – {gemahnt_geb} Mahnungen wurden auf "
                     f"Mahngebühr-Rechnungen selbst erzeugt (Gebühr auf Gebühr), bei nur {len(roh)} Mietrechnungen", tag)
            # (b) Überzahlung
            vz = getattr(self, 'v_neu', self.v['B2'])
            r1 = [r for r in self.rechnungen_vertrag(vz, 'Miete & NK 04/2026') if r.status in ('offen', 'teilbezahlt')]
            if r1:
                rr = r1[0]
                offen_vor = rr.offener_betrag
                sum_vor = sum((z.betrag for z in Zahlungseingang.objects.filter(vertrag=vz)), D('0'))
                self.post('fw_bankabgleich_verbuchen', {'rechnung_id': rr.id, 'betrag': str(offen_vor + D('300'))})
                sum_nach = sum((z.betrag for z in Zahlungseingang.objects.filter(vertrag=vz)), D('0'))
                erfasst = sum_nach - sum_vor
                P.pruefe(erfasst >= offen_vor + D('300'),
                         'Überzahlung', 'Überzahlung als Guthaben erfasst',
                         f"Mieter überweist CHF 300 zu viel (offen {offen_vor}, Bankeingang {offen_vor + D('300')}): erfasst wird nur {erfasst} – "
                         f"die CHF 300 verschwinden ohne Hinweis (kein Mieterguthaben 2030, keine Warnung)", tag)
            # (c) Leerstand nach Neuvermietung
            ls = Leerstand.objects.filter(einheit=self.e['A4'], ende__isnull=True)
            P.pruefe(not ls.exists(), 'Leerstand', 'Kein offener Leerstand für A4',
                     f"A4 ist seit 01.04. wieder vermietet, aber {ls.count()} Leerstand-Eintrag/Einträge sind weiterhin offen "
                     f"(beginn {[l.beginn for l in ls]})", tag)
            # (d) Pendenzen
            for k in ('A3', 'A4'):
                offen = Pendenz.objects.filter(vertrag=self.v[k], erledigt=False)
                P.info('Pendenzen', f"{k}: {offen.count()} offen: " + '; '.join(f"{p.titel[:45]} ({p.faellig_am})" for p in offen[:12]), tag)
            # (e) Mahnbrief-Inhalt: Monat + Kündigungsandrohung
            from rentals.models import Dokument
            docs = Dokument.objects.filter(vertrag=self.v['A3'], bezeichnung__icontains='ahnung').order_by('id')
            P.info('Mahnbrief', f"{docs.count()} Mahn-PDFs in Akte A3", tag)
            import pypdf
            for d in list(docs[:1]) + list(docs.filter(bezeichnung__icontains='3')[:1]):
                try:
                    d.datei.open('rb')
                    txt = ' '.join(pg.extract_text() or '' for pg in pypdf.PdfReader(d.datei).pages)
                    d.datei.close()
                    P.info('Mahnbrief', f"'{d.bezeichnung}': {txt[:1800]!r}", tag)
                    P.info('Mahnbrief', f"enthält '257d'={('257d' in txt)}; 'Kündigung'={('ündig' in txt)}; '30 TAGEN'={('30 TAGEN' in txt)}", tag)
                except Exception as e:      # noqa: BLE001
                    P.warn('Mahnbrief', f"PDF nicht lesbar: {e}", tag)
            # (f) Referenzzins-Basis nach Wirksamkeit
            v = self.v['B1']; v.refresh_from_db()
            P.info('Referenzzins', f"B1 nach Senkung: effektive_basis={v.effektive_basis()}; Vertragsfeld basis_ref={v.basis_referenzzinssatz}; "
                                   f"Potenzial-Typ={v.mietzinspotenzial if not callable(getattr(v,'mietzinspotenzial',None)) else ''}", tag)
            a = v.anpassungen.first()
            P.pruefe(a and v.effektive_basis()[0] == a.neuer_referenzzinssatz, 'Referenzzins-Basis',
                     'Basis Referenzzins folgt der Anpassung',
                     f"Nach Senkung auf 1.00% steht die Vertragsbasis weiter auf {v.effektive_basis()[0]}%", tag)
            # (g) LIK-/Basis-Fallback bei Neuvertrag
            n = getattr(self, 'v_neu', None)
            if n:
                P.info('Neuvertrag', f"Basis Ref.Zins {n.basis_referenzzinssatz} (Org.: {self.org.aktueller_referenzzinssatz}); "
                                     f"Basis-LIK {n.basis_lik_punkte} (Org.: {self.org.aktueller_lik_punkte}); Einheit.ref_zinssatz={n.einheit.ref_zinssatz}", tag)
                if D(str(n.basis_referenzzinssatz)) != D(str(self.org.aktueller_referenzzinssatz)):
                    P.fehler('Neuvertrag', f"Neuer Vertrag startet 01.04. mit Basis-Referenzzins {n.basis_referenzzinssatz}% – "
                             f"aktueller Referenzzins ist {self.org.aktueller_referenzzinssatz}% (stammt aus Einheit/Hardcode-Fallback 1.25)", tag)
                April = self.rechnungen_vertrag(n, 'Miete & NK 04/2026')
                P.pruefe(bool(April), 'Neuvermietung', f"April-Sollstellung für Nachmieter: {[r.betrag for r in April]}",
                         "Nachmieter hat für April keine Sollstellung erhalten", tag)
            # (h0) Buchungsdatum Kaution-Auflösung + Schlussabrechnung-Vorbelegung
            from finance.models import Buchung
            kb = Buchung.objects.filter(beleg_text__contains=f"[V{self.v['A4'].pk}]", ist_storno=False).order_by('id')
            P.info('Kaution', "Kautions-Auflösung A4 gebucht mit Datum: " + ', '.join(sorted({str(b.datum) for b in kb})) +
                   " (Erfassung am 02.04.2026)", tag)
            gr = self.c.get(f"/neu/vertraege/{self.v['A4'].id}/schlussabrechnung/")
            html = gr.content.decode('utf-8', 'ignore')
            P.pruefe('Herdplatte' in html or 'Dübel' in html, 'Schlussabrechnung',
                     'Abnahme-Mängel sind in der Schlussabrechnung vorbelegt',
                     'Mängel aus dem Abnahmeprotokoll (Mieteranteil CHF 860) erscheinen NICHT in der Schlussabrechnung – '
                     'Positionen müssen von Hand abgetippt werden', tag)
            # (h1) Handwerkerauftrag-Status
            from tickets.models import HandwerkerAuftrag
            for a in HandwerkerAuftrag.objects.select_related('ticket'):
                P.info('Auftrag', f"Ticket '{a.ticket.titel}' ({a.ticket.status}) → Auftrag {a.handwerker.firma}: status='{a.status}', "
                                  f"geschätzt {a.kosten_geschaetzt} effektiv {a.kosten_effektiv}, Freigabe {a.freigabe_status}, Kreditor {a.kreditoren_rechnung.status if a.kreditoren_rechnung_id else '-'}", tag)
            # (h2) Weiterverrechnung einer noch nicht freigegebenen Rechnung
            w = DebitorenRechnung.objects.filter(quell_kreditor__isnull=False).first()
            if w:
                P.pruefe(w.quell_kreditor.status != 'neu', 'Weiterverrechnung',
                         'Weiterverrechnete Lieferantenrechnung war freigegeben',
                         f"CHF {w.betrag} wurden dem Mieter weiterverrechnet, obwohl die Lieferantenrechnung "
                         f"({w.quell_kreditor.lieferant}) noch Status '{w.quell_kreditor.status}' hat (nie gebucht/freigegeben)", tag)
            # (h3) Portal
            # (h) Kaution Nachmieter / Kautionsliste
            rr = self.c.get('/neu/kautionen/')
            P.info('Kaution', f"Kautionsübersicht HTTP {rr.status_code}", tag)
            # (i) Tickets Endstatus
            from tickets.models import SchadenMeldung
            for t in SchadenMeldung.objects.all():
                P.info('Ticket-Ende', f"#{t.id} {t.titel}: {t.status}, Prio {t.prioritaet}, {t.handwerker_auftraege.count()} Aufträge, "
                                      f"Kosten eff. {sum((a.kosten_effektiv or 0) for a in t.handwerker_auftraege.all())}, "
                                      f"Nachrichten {t.nachrichten.count()}", tag)

    def rechnungen_vertrag(self, v, titel_teil):
        from finance.models import DebitorenRechnung
        return list(DebitorenRechnung.objects.filter(vertrag=v, titel__contains=titel_teil).exclude(status='storniert'))

    def bericht(self):
        pfad = os.environ.get('SIM_BERICHT')
        daten = P.eintraege
        if pfad:
            with open(pfad, 'w') as f:
                json.dump(daten, f, ensure_ascii=False, indent=1)
        for e in daten:
            print(f"[{e['stufe']:8}] {e['tag']:10} {e['thema']}: {e['text']}")


EREIGNISSE = {
    date(2025, 12, 10): ['ev_kuendigung_a4'],
    date(2025, 12, 15): ['ev_heizung_melden'],
    date(2025, 12, 16): ['ev_heizung_auftrag', 'ev_257d'],
    date(2025, 12, 18): ['ev_257d_zugang'],
    date(2025, 12, 22): ['ev_heizung_kosten'],
    date(2026, 1, 15): ['ev_heizung_abschluss', 'ev_nk_abrechnung', 'ev_bewerbungen'],
    date(2026, 1, 19): ['ev_257d_kuendigung', 'ev_ticket_ueberblick'],
    date(2026, 1, 30): ['ev_index_gewerbe'],
    date(2026, 2, 6): ['ev_wasserschaden'],
    date(2026, 2, 9): ['ev_wasser_weiterverrechnen'],
    date(2026, 2, 16): ['ev_zusage'],
    date(2026, 3, 2): ['ev_referenzzins', 'ev_taeglicher_lauf'],
    date(2026, 3, 5): ['ev_senkung'],
    date(2026, 3, 12): ['ev_storen'],
    date(2026, 3, 20): ['ev_eigentuemer'],
    date(2026, 3, 31): ['ev_abnahme'],
    date(2026, 3, 25): ['ev_vertrag_aktivieren'],
    date(2026, 4, 2): ['ev_schlussabrechnung'],
    date(2026, 4, 30): ['ev_ticket_ueberblick'],
}
