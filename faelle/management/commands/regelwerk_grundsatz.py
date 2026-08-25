"""Legt je Organisation einen Grund-Regelsatz an — ausdrücklich ungeprüft.

WARUM ALS BEFEHL UND NICHT BEIM ANLEGEN DER ORGANISATION

Ein Regelsatz, der von selbst entsteht, sieht aus wie eine Zusicherung. Er ist
aber ein **Entwurf**: die gesetzliche Grundregel für Wohnräume, ohne
ortsübliche Termine, ohne kantonale Besonderheit, ohne Geschäftsräume. Wer ihn
will, ruft ihn ab; dann ist es eine Entscheidung und kein Nebeneffekt.

WAS ANGELEGT WIRD

    Frist       drei Monate (Art. 266c OR — Mindestfrist für Wohnräume)
    Termine     KEINE. Das Feld bleibt leer, und das ist die wichtigste
                Entscheidung dieses Befehls: Ortsübliche Termine sind kantonal
                verschieden. Ein hier eingetragenes 31.03/30.06/30.09 wäre für
                einen Teil der Schweiz schlicht falsch und würde als geprüfte
                Regel aussehen. Ohne Termine greift die Prüfung auf das zurück,
                was im einzelnen Vertrag steht — die einzige Angabe, die für
                diesen Vertrag mit Sicherheit gilt.
    geprueft    False. Der Satz warnt, er sperrt nicht.

Der Befehl ist wiederholbar: Ein bestehender Regelsatz wird nicht angefasst —
seine Regeln werden aber NACHGETRAGEN, wenn eine dazugekommen ist.

WARUM DAS NACHTRAGEN NOETIG WURDE (E2.34)

Bis hierher sprang der Befehl bei einer Organisation mit Regelsatz einfach
weiter («hat bereits … — unveraendert»). Als E2.32 die Kautionsregel und E2.34
die Zahlungsfrist ergaenzten, hiess das: Auf jeder Installation, die den
Befehl schon einmal ausgefuehrt hatte, entstanden die neuen Regeln NIE.

Nachgemessen: Nach `regelwerk_grundsatz` auf einem Bestand mit Regelsatz stand
dort weiterhin genau eine Regel, und `pruefen('zahlungsfrist', …)` antwortete
«Fuer diese Pruefung ist keine Regel hinterlegt». Beide Etappen waeren dort
wirkungslos geblieben — die Rechnung im Code, die Regel nirgends.

Was NICHT nachgetragen wird: eine Regel, die es schon gibt. Wer ihre Parameter
angepasst hat, behaelt sie. Nachgetragen wird nur, was fehlt.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


def _regelvorlagen(Regel):
    """Die Regeln des Grundsatzes — als Daten, nicht als Folge von Aufrufen.

    Vorher standen sie als drei `create()`-Bloecke hintereinander im
    Anlegepfad. Das ging, solange nur angelegt wurde; zum Nachtragen braucht
    es sie als Liste, die sich mit dem Bestand vergleichen laesst.
    """
    return [
        (Regel.KUENDIGUNGSTERMIN, {'frist_monate': 3},
         'Art. 266c OR: drei Monate bei Wohnräumen.'),

        # KAUTIONSHOECHSTBETRAG — und warum er NUR fuer Wohnraeume gilt
        #
        # Art. 257e Abs. 2 OR: Bei Wohnraeumen darf die Sicherheit drei
        # Monatszinse nicht uebersteigen. Bei GESCHAEFTSRAEUMEN gilt die
        # Grenze NICHT — dort ist sie frei vereinbar.
        #
        # Das steht bereits im Modell (`Mietvertrag.kaution_max_monate` gibt
        # 3 bei `mietrecht_kategorie == 'wohnen'` und sonst None). Die Regel
        # wiederholt es nicht, sie macht es pruefbar: Der Parameter nennt die
        # Grenze UND den Geltungsbereich, damit eine Verwaltung mit
        # Gewerbebestand nicht faelschlich gewarnt wird.
        (Regel.KAUTION_HOECHSTBETRAG,
         {'hoechst_monate': 3, 'gilt_fuer': ['wohnen']},
         'Art. 257e Abs. 2 OR: hoechstens drei Monatszinse bei Wohnraeumen. '
         'Bei Geschaeftsraeumen frei vereinbar.'),

        # ZAHLUNGSFRIST BEI VERZUG — Art. 257d Abs. 1 OR
        #
        # DREISSIG TAGE BEI WOHN- UND GESCHAEFTSRAEUMEN, ZEHN SONST.
        #
        # Die erste Fassung trug `{'mindest_tage': 30}` und die Notiz, hier
        # gebe es «keinen Geltungsbereich wie bei der Kaution». Der Bestand
        # wusste es besser: `fw_verzug_257d` rechnet seit jeher
        # `min_frist = 30 if v.ist_geschuetzt else 10`. Bei einem gesondert
        # vermieteten Parkplatz sind es zehn Tage.
        #
        # Ein fester Parameter haette das ueberfahren — die Regel haette bei
        # jedem Parkplatzvertrag «zwanzig Tage zu frueh» gemeldet, wo Gesetz
        # und Anwendung die Kuendigung zulassen. Deshalb KEIN `mindest_tage`
        # hier: Ohne Parameter rechnet die Regel nach Kategorie.
        #
        # Wer strenger fuehren will, traegt `mindest_tage` nach — laenger ist
        # zulaessig, kuerzer nicht, und eine trotzdem ausgesprochene
        # Kuendigung waere NICHTIG.
        (Regel.ZAHLUNGSFRIST, {},
         'Art. 257d Abs. 1 OR: mindestens dreissig Tage Zahlungsfrist mit '
         'Kuendigungsandrohung bei Wohn- und Geschaeftsraeumen, zehn bei '
         'Nebenobjekten.'),
    ]


def _fehlende_nachtragen(Regel, organisation, satz):
    """Legt die Regeln an, die dem Satz noch fehlen. Gibt ihre Arten zurück.

    Bestehende Regeln bleiben unberührt — auch wenn ihre Parameter von der
    Vorlage abweichen. Wer sie angepasst hat, hat das absichtlich getan.
    """
    vorhanden = set(Regel.alle_organisationen.filter(
        regelsatz=satz).values_list('art', flat=True))
    nachgetragen = []
    for art, parameter, begruendung in _regelvorlagen(Regel):
        if art in vorhanden:
            continue
        Regel.alle_organisationen.create(
            organisation=organisation, regelsatz=satz, art=art,
            verbindlichkeit=Regel.WARNUNG, parameter=parameter,
            begruendung=begruendung, aktiv=True)
        nachgetragen.append(art)
    return nachgetragen


class Command(BaseCommand):
    help = ('Legt je Organisation einen ungeprüften Grund-Regelsatz an '
            '(Kündigungsfrist drei Monate, Termine aus dem Vertrag).')

    def add_arguments(self, parser):
        parser.add_argument(
            '--organisation', type=int, default=None,
            help='Nur für diese Organisations-ID. Ohne Angabe: für alle.')
        parser.add_argument(
            '--probe', action='store_true',
            help='Nur zeigen, was geschähe — nichts schreiben.')

    def handle(self, *args, **optionen):
        from crm.models import Organisation
        from faelle.regelwerk_models import Regel, Regelsatz

        organisationen = Organisation.objects.all()
        if optionen['organisation']:
            organisationen = organisationen.filter(pk=optionen['organisation'])

        angelegt = uebersprungen = ergaenzt = 0
        for organisation in organisationen:
            # `alle_organisationen`, weil dieser Befehl bewusst über alle
            # Mandanten läuft — der ausdrücklich benannte Weg, nicht eine
            # stille Umgehung des Standardmanagers.
            bestand = Regelsatz.alle_organisationen.filter(
                organisation=organisation, kanton='')
            if bestand.exists():
                satz = bestand.first()
                if optionen['probe']:
                    fehlen = [a for a, _p, _b in _regelvorlagen(Regel)
                              if a not in set(Regel.alle_organisationen.filter(
                                  regelsatz=satz).values_list('art', flat=True))]
                    hinweis = (f' — {len(fehlen)} Regel(n) würden nachgetragen'
                               if fehlen else ' — vollständig')
                    self.stdout.write(
                        f'  · {organisation.firma}: hat «{satz}»{hinweis}.')
                    uebersprungen += 1
                    continue
                # NACHTRAGEN, NICHT UEBERSPRINGEN.
                #
                # Bis E2.34 sprang der Befehl hier weiter. Kam eine Regelart
                # dazu (E2.32 Kaution, E2.34 Zahlungsfrist), entstand sie auf
                # jeder Installation mit bestehendem Regelsatz NIE — die
                # Rechnung stand im Code, die Regel nirgends, und `pruefen()`
                # antwortete «keine Regel hinterlegt».
                nachgetragen = _fehlende_nachtragen(Regel, organisation, satz)
                if nachgetragen:
                    self.stdout.write(self.style.SUCCESS(
                        f'  · {organisation.firma}: «{satz}» ergänzt um '
                        f'{", ".join(nachgetragen)}.'))
                    ergaenzt += len(nachgetragen)
                else:
                    self.stdout.write(
                        f'  · {organisation.firma}: hat bereits '
                        f'«{satz}» — unverändert.')
                uebersprungen += 1
                continue

            if optionen['probe']:
                self.stdout.write(f'  + {organisation.firma}: würde angelegt.')
                angelegt += 1
                continue

            satz = Regelsatz.alle_organisationen.create(
                organisation=organisation,
                bezeichnung='Grundsatz Wohnräume (Entwurf)',
                kanton='', stand=timezone.localdate(), geprueft=False,
                hinweis=('Angelegt von `manage.py regelwerk_grundsatz`. Gibt die '
                         'gesetzliche Mindestfrist nach Art. 266c OR wieder. '
                         'Ortsübliche Kündigungstermine sind NICHT hinterlegt — '
                         'es gilt, was im jeweiligen Vertrag steht. Vor dem '
                         'Kennzeichen «geprüft» juristisch gegenlesen lassen.'),
                aktiv=True)
            _fehlende_nachtragen(Regel, organisation, satz)
            self.stdout.write(self.style.SUCCESS(
                f'  + {organisation.firma}: «{satz}» angelegt.'))
            angelegt += 1

        self.stdout.write('')
        self.stdout.write(
            f'{angelegt} angelegt, {uebersprungen} bestehend'
            + (f' (davon {ergaenzt} Regel(n) nachgetragen)' if ergaenzt else '')
            + '.')
        if angelegt and not optionen['probe']:
            self.stdout.write(self.style.WARNING(
                'Die Regeln sind NICHT juristisch geprüft und warnen deshalb '
                'nur. Sie sperren erst, wenn jemand den Regelsatz unter '
                '/neu/regelwerk/ als geprüft kennzeichnet.'))
