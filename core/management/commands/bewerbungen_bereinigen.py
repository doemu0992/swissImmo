"""Löscht Bewerbungsdossiers nach dem Vermietungsentscheid (DSG).

Ausweiskopie, Lohnausweis und Betreibungsauszug sind die heikelsten Daten der
Anwendung — und sie stammen von Menschen, die zur Verwaltung meist gar kein
Vertragsverhältnis haben. Nach dem Entscheid haben sie keinen Zweck mehr, und
anders als Buchungsbelege unterliegen sie keiner Aufbewahrungspflicht.

    python manage.py bewerbungen_bereinigen              # nur anzeigen
    python manage.py bewerbungen_bereinigen --apply      # tatsächlich löschen
    python manage.py bewerbungen_bereinigen --dokumente-tage 3 --apply

Läuft täglich mit `taeglicher_lauf`.

JE VERWALTUNG EIN LAUF. Gelöscht wird unwiderruflich; seit Etappe 6.2 wirft
`Mietbewerbung.objects` ohne Kontext, statt über den gesamten Bestand zu gehen.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.services.bewerbung_aufbewahrung import bereinige, faellige


class Command(BaseCommand):
    help = "Löscht Dokumente und anonymisiert Bewerbungen nach dem Entscheid (DSG)."

    def add_arguments(self, parser):
        parser.add_argument('--dokumente-tage', type=int, default=7,
                            help="Tage nach dem Entscheid bis die Dateien gelöscht werden (7).")
        parser.add_argument('--anonym-tage', type=int, default=365,
                            help="Tage bis das ganze Dossier anonymisiert wird (365).")
        parser.add_argument('--apply', action='store_true', help="Tatsächlich ausführen.")
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        _, fehler = je_organisation(lambda organisation: self._bereinigen(organisation, opts),
                                    auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"{len(fehler)} Verwaltung(en) abgebrochen — "
                               f"{', '.join(str(o) for o, _ in fehler)}.")

    def _bereinigen(self, organisation, opts):
        heute = timezone.localdate()
        dok_tage, anon_tage = opts['dokumente_tage'], opts['anonym_tage']
        if anon_tage < dok_tage:
            self.stderr.write("--anonym-tage darf nicht kleiner sein als --dokumente-tage.")
            return

        dok, anon = faellige(heute, dokumente_tage=dok_tage, anonym_tage=anon_tage)
        self.stdout.write(f"{organisation}: {len(dok)} Dossier(s) mit fälligen Dokumenten (> {dok_tage} Tage), "
                          f"{len(anon)} zum Anonymisieren (> {anon_tage} Tage).")
        for b in dok + anon:
            self.stdout.write(f"  · #{b.id} {b.vorname} {b.nachname} — {b.einheit}")

        if not opts['apply']:
            self.stdout.write("Trockenlauf — mit --apply tatsächlich ausführen.")
            return

        n_dok, n_anon = bereinige(heute, dokumente_tage=dok_tage,
                                  anonym_tage=anon_tage, anwenden=True)
        self.stdout.write(self.style.SUCCESS(
            f"✓ {n_dok} Dossier(s) bereinigt, {n_anon} anonymisiert."))
        return (n_dok, n_anon)
