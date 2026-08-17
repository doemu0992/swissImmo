"""Bulk-DSG-Anonymisierung nach Aufbewahrungsfrist.

Anonymisiert Personen, deren letztes Mietverhältnis vor mehr als N Jahren
endete (Default 10 = Ablauf der Buchungs-Aufbewahrungspflicht, OR 958f), die
kein aktives Verhältnis und keine offenen Forderungen mehr haben. Standardmässig
Trockenlauf — erst mit --apply wird tatsächlich anonymisiert.

    python manage.py dsg_anonymisieren            # nur anzeigen (dry-run)
    python manage.py dsg_anonymisieren --apply     # tatsächlich anonymisieren
    python manage.py dsg_anonymisieren --jahre 5 --apply
    python manage.py dsg_anonymisieren --organisation 3

JE VERWALTUNG EIN LAUF. Anonymisieren ist unumkehrbar: Der Name ist danach weg,
auch wenn er in der falschen Verwaltung stand. Seit Etappe 6.2 wirft
`Mieter.objects` ohne Kontext, statt über den gesamten Bestand zu gehen.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from crm.models import Mieter
from core.services.dsg import anonymisiere_person, kann_anonymisieren


class Command(BaseCommand):
    help = "Anonymisiert Personen nach Ablauf der Aufbewahrungsfrist (DSG)."

    def add_arguments(self, parser):
        parser.add_argument('--jahre', type=int, default=10,
                            help="Jahre seit Ende des letzten Mietverhältnisses (Default 10)")
        parser.add_argument('--apply', action='store_true', help="Tatsächlich anonymisieren")
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        _, fehler = je_organisation(lambda organisation: self._anonymisieren(organisation, opts),
                                    auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"{len(fehler)} Verwaltung(en) abgebrochen — "
                               f"{', '.join(str(o) for o, _ in fehler)}.")

    def _anonymisieren(self, organisation, opts):
        heute = timezone.localdate()
        grenze = heute.replace(year=heute.year - opts['jahre'])
        kandidaten = []
        for m in Mieter.objects.filter(anonymisiert=False, typ='person'):
            ok, _ = kann_anonymisieren(m)
            if not ok:
                continue
            vertraege = list(m.vertraege.all()) + list(m.vertraege_als_mitmieter.all())
            if not vertraege:
                continue   # nie Mieter gewesen (reiner Kontakt) — hier nicht automatisch anfassen
            enden = [v.ende for v in vertraege if v.ende]
            if not enden or max(enden) > grenze:
                continue   # noch innerhalb der Frist oder offenes Ende
            # keine offenen Forderungen
            offen = any(r.status in ('offen', 'teilbezahlt', 'ueberfaellig')
                        for v in vertraege for r in v.debitoren_rechnungen.all())
            if offen:
                continue
            kandidaten.append(m)

        self.stdout.write(f"{organisation}: {len(kandidaten)} Person(en) älter als {opts['jahre']} Jahre "
                          f"(letztes Verhältnis vor {grenze:%d.%m.%Y}).")
        n = 0
        for m in kandidaten:
            if opts['apply']:
                ok, msg = anonymisiere_person(m, grund=f"Aufbewahrungsfrist {opts['jahre']}J abgelaufen")
                if ok:
                    n += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ {msg}"))
            else:
                self.stdout.write(f"  · #{m.id} {m.display_name} (Trockenlauf)")
        if opts['apply']:
            self.stdout.write(self.style.SUCCESS(f"{n} Person(en) anonymisiert."))
        else:
            self.stdout.write("Trockenlauf — mit --apply tatsächlich anonymisieren.")
        return n
