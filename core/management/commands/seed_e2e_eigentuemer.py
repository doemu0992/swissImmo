"""Daten für `e2e/tests/zz-eigentuemerportal.spec.ts` (Eigentümerportal v2).

Läuft NACH `seed_e2e` (braucht die Organisation «E2E Verwaltung AG»). Idempotent.
Nur für Test-/E2E-Datenbanken.

Drei Eigentümer derselben Verwaltung, jeder mit eigenem Login (Passwort e2e-pass):

* `e2e-eigentuemer`  Portal Eigentümer AG: eine aktive Liegenschaft (drei Objekte,
  eines leer, ein überfälliger offener Posten, Erträge, eine Auszahlung, ein
  freigegebenes und ein internes Dokument) und eine archivierte.
* `e2e-eigentuemer-fremd`  Fremder Eigentümer AG: eigene Liegenschaft und ein
  freigegebenes Dokument. Die Gegenprobe: Er darf von den anderen nichts sehen.
* `e2e-eigentuemer-ende`  Ehemaliger Eigentümer AG: Mandat mit Mandatsende
  archiviert, seine Liegenschaft ebenfalls.
"""
from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Seedet drei Eigentümer-Logins samt Liegenschaften für die E2E-Spec des Eigentümerportals."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from crm.models import Eigentuemer, Mieter, Organisation
        from core.services import archiv
        from core.tenancy import organisation_kontext
        from core.zeit import datum_heute
        from finance.booking import buche, ensure_kontenplan
        from finance.models import Buchungskonto, DebitorenRechnung, EigentuemerAuszahlung
        from portfolio.models import Dokument, Einheit, Liegenschaft
        from rentals.models import Mietvertrag

        User = get_user_model()
        org = Organisation.objects.filter(firma="E2E Verwaltung AG").first()
        if org is None:
            raise CommandError("Zuerst `seed_e2e` ausführen.")

        def konto_fuer(name):
            u, _ = User.objects.get_or_create(username=name)
            u.set_password("e2e-pass")
            u.is_active = True
            u.save()
            return u

        heute = datum_heute()
        with organisation_kontext(org):
            ensure_kontenplan()

            def eigentuemer(name, login):
                e, _ = Eigentuemer.objects.get_or_create(
                    firma_oder_name=name,
                    defaults=dict(strasse="Mandatsweg 5", plz="8000", ort="Zürich",
                                  email=f"{login}@example.ch"))
                if e.benutzer_id is None:
                    e.benutzer = konto_fuer(login)
                    e.save(update_fields=["benutzer"])
                return e

            def liegenschaft(eig, strasse, ort):
                lg, _ = Liegenschaft.objects.get_or_create(
                    strasse=strasse, plz="8000", ort=ort,
                    defaults=dict(eigentuemer=eig, baujahr=1985))
                return lg

            def dokument(lg, titel, sichtbar):
                if Dokument.objects.filter(liegenschaft=lg, titel=titel).exists():
                    return
                d = Dokument(liegenschaft=lg, titel=titel, kategorie="Verwaltung",
                             im_portal_sichtbar=sichtbar)
                d.datei.save(f"{titel}.pdf", ContentFile(b"%PDF-1.4 e2e"), save=True)

            # --- Portal Eigentümer AG ---
            eig = eigentuemer("Portal Eigentümer AG", "e2e-eigentuemer")
            lg = liegenschaft(eig, "Portalweg 1", "Zürich")
            lg_alt = liegenschaft(eig, "Zuletztweg 9", "Zürich")
            einheiten = {}
            for bez, typ, netto in (("Portal-Whg 1", "whg", "1800"), ("Portal-Whg 2", "whg", "1600"),
                                    ("Portal-Atelier", "gew", "2100")):
                einheiten[bez], _ = Einheit.objects.get_or_create(
                    liegenschaft=lg, bezeichnung=bez,
                    defaults=dict(typ=typ, nettomiete_aktuell=Decimal(netto),
                                  nebenkosten_aktuell=Decimal("200"), flaeche_m2=Decimal("70")))
            for bez, vorname, nachname, netto in (("Portal-Whg 1", "Paula", "Portal", "1800"),
                                                  ("Portal-Atelier", "Atilla", "Atelier", "2100")):
                m, _ = Mieter.objects.get_or_create(
                    email=f"{nachname.lower()}-e2e@example.ch",
                    defaults=dict(typ="person", vorname=vorname, nachname=nachname,
                                  strasse="Seeweg 3", plz="8000", ort="Zürich"))
                v, _ = Mietvertrag.objects.get_or_create(
                    mieter=m, einheit=einheiten[bez],
                    defaults=dict(beginn=date(2023, 4, 1), netto_mietzins=Decimal(netto),
                                  nebenkosten=Decimal("200"), status="aktiv"))
                DebitorenRechnung.objects.get_or_create(
                    vertrag=v, titel="Portal offene Miete",
                    defaults=dict(liegenschaft=lg, einheit=einheiten[bez],
                                  datum=date(heute.year, 1, 1), faellig_am=date(heute.year, 1, 5),
                                  betrag=Decimal("2000"), forderungsart="miete", status="offen"))
            from finance.models import Buchung
            if not Buchung.objects.filter(beleg_text="Portal Mietertrag").exists():
                for jahr in (heute.year - 1, heute.year):
                    buche("1100", "3000", Decimal("3800"), "Portal Mietertrag",
                          datum=date(jahr, 2, 1), liegenschaft=lg)
                    buche("1020", "1100", Decimal("3800"), "Portal Mietzahlung",
                          datum=date(jahr, 2, 3), liegenschaft=lg)
                    buche("4000", "1020", Decimal("900"), "Portal Unterhalt",
                          datum=date(jahr, 3, 1), liegenschaft=lg)
            bank = Buchungskonto.objects.filter(nummer="1020").first()
            if not EigentuemerAuszahlung.objects.filter(eigentuemer=eig).exists():
                EigentuemerAuszahlung.objects.create(
                    eigentuemer=eig, betrag=Decimal("1500.00"), datum=date(heute.year - 1, 6, 30),
                    konto=bank, bemerkung="Quartalsauszahlung")
            dokument(lg, "Portal Verwaltungsvertrag", True)
            dokument(lg, "Portal interne Offerte", False)

            # --- Fremder Eigentümer derselben Verwaltung ---
            fremd = eigentuemer("Fremder Eigentümer AG", "e2e-eigentuemer-fremd")
            lg_fremd = liegenschaft(fremd, "Fremdgasse 7", "Bern")
            Einheit.objects.get_or_create(
                liegenschaft=lg_fremd, bezeichnung="Fremd-Whg",
                defaults=dict(typ="whg", nettomiete_aktuell=Decimal("1900"),
                              nebenkosten_aktuell=Decimal("150")))
            dokument(lg_fremd, "Fremder Vertrag", True)

            # --- Ehemaliger Eigentümer: Mandat und Liegenschaft archiviert ---
            ende = eigentuemer("Ehemaliger Eigentümer AG", "e2e-eigentuemer-ende")
            lg_ende = liegenschaft(ende, "Endeweg 3", "Basel")
            dokument(lg_ende, "Ende Schlussabrechnung", True)

            # Archivieren zuletzt (Liegenschaft zuerst, dann das Mandat).
            for objekt, grund, mandatsende in (
                    (lg_alt, "Verkauft", None), (lg_ende, "Mandat beendet", None),
                    (ende, "Mandat gekündigt", date(heute.year, 3, 31))):
                if not archiv.ist_archiviert(objekt):
                    archiv.archivieren(objekt, grund=grund, mandatsende=mandatsende)

        self.stdout.write(self.style.SUCCESS(
            "Eigentümerportal-Daten bereit (e2e-eigentuemer, e2e-eigentuemer-fremd, e2e-eigentuemer-ende)."))
