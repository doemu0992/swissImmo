"""DSG-Löschung/Anonymisierung von Personendaten.

Nach dem Datenschutzgesetz (DSG) haben betroffene Personen ein Recht auf
Löschung ihrer Personendaten, sobald diese für den Zweck nicht mehr benötigt
werden. Buchhaltungsbelege (Debitorenrechnungen, Buchungen) unterliegen aber
der 10-jährigen Aufbewahrungspflicht (Art. 958f OR) und dürfen NICHT gelöscht
werden. Deshalb wird die Person nicht gelöscht, sondern ihre Stammdaten werden
ANONYMISIERT — die Buchungshistorie bleibt für die Revision erhalten, der
Personenbezug der Master-Daten wird aber entfernt.

Zusätzlich werden die hochgeladenen Bewerber-Dokumente (Ausweis, Lohnausweis,
Betreibungsauszug) physisch gelöscht — diese besonders schützenswerten Daten
haben keine Aufbewahrungspflicht.
"""
from django.utils import timezone


def kann_anonymisieren(mieter):
    """(ok, grund) — ein aktives Mietverhältnis blockiert die Anonymisierung."""
    aktiv = mieter.vertraege.filter(status='aktiv').count()
    aktiv += mieter.vertraege_als_mitmieter.filter(status='aktiv').count()
    if aktiv:
        return False, f"Person hat {aktiv} aktives/aktive Mietverhältnis(se) — zuerst beenden."
    if mieter.anonymisiert:
        return False, "Person ist bereits anonymisiert."
    return True, ""


def anonymisiere_person(mieter, *, grund='', user=None):
    """Anonymisiert die Stammdaten der Person + löscht Bewerber-Dokumente.
    Buchungsbelege bleiben erhalten (OR 958f). Gibt (ok, meldung) zurück."""
    ok, warum = kann_anonymisieren(mieter)
    if not ok:
        return False, warum

    pid = mieter.id
    # 1) Verknüpften Portal-Login entfernen (enthält Name/E-Mail).
    if mieter.benutzer_id:
        try:
            mieter.benutzer.delete()
        except Exception:
            pass
        mieter.benutzer = None

    # 2) Bewerbungen der Person anonymisieren + hochgeladene Dokumente löschen.
    from mietprozess.models import Mietbewerbung
    bewerbungen = Mietbewerbung.objects.filter(email__iexact=(mieter.email or '\x00'))
    for b in bewerbungen:
        for feld in ('betreibungsauszug', 'ausweiskopie', 'lohnausweis', 'weitere_dokumente'):
            datei = getattr(b, feld, None)
            if datei:
                try:
                    datei.delete(save=False)
                except Exception:
                    pass
        b.vorname = 'Anonymisiert'; b.nachname = f'#{pid}'
        b.email = f'anon-{pid}@example.invalid'; b.mobilnummer = ''
        b.adresse = ''; b.einkommen_jahr = ''; b.arbeitgeber = ''
        try:
            b.save()
        except Exception:
            pass

    # 3) Stammdaten der Person überschreiben (Buchungsbelege bleiben unberührt).
    mieter.anrede = ''; mieter.kontaktperson = ''
    mieter.vorname = 'Anonymisiert'; mieter.nachname = f'Person #{pid}'
    mieter.firmen_name = ''; mieter.uid_nummer = ''
    mieter.geburtsdatum = None; mieter.ahv_nummer = ''
    mieter.zivilstand = ''; mieter.nationalitaet = ''; mieter.heimatort = ''
    mieter.erwerbsstatus = ''; mieter.beruf = ''; mieter.arbeitgeber = ''; mieter.einkommen_jahr = ''
    mieter.email = ''; mieter.telefon_privat = ''; mieter.telefon_geschaeft = ''; mieter.mobile = ''
    mieter.strasse = ''; mieter.adresszusatz = ''; mieter.postfach = ''; mieter.plz = ''; mieter.ort = ''
    mieter.zukuenftige_strasse = ''; mieter.zukuenftige_plz = ''; mieter.zukuenftiger_ort = ''
    mieter.zukuenftig_ab = None
    mieter.iban = ''; mieter.bank_name = ''; mieter.bonitaet_datum = None
    heute = timezone.localdate()
    mieter.notizen = f"[{heute:%d.%m.%Y}] DSG-Anonymisierung{f' — {grund}' if grund else ''}."
    mieter.anonymisiert = True
    mieter.anonymisiert_am = heute
    mieter.save()

    from core.models import AktivitaetsLog
    AktivitaetsLog.objects.create(aktion="DSG-Anonymisierung", objekt=f"Person #{pid}",
                                  details=(grund or "Personendaten anonymisiert; Belege bleiben (OR 958f)."))
    return True, f"Person #{pid} anonymisiert — Buchungsbelege bleiben aufbewahrt (OR 958f)."
