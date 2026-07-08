"""Standard-Vorlagen: vorbelegte, editierbare Texte für alle Kategorien.
Werden per Button „Standardvorlagen erstellen" angelegt (idempotent — legt nur
fehlende an, überschreibt bestehende nie)."""

STANDARD_VORLAGEN = [
    # --- Korrespondenz ---
    {
        'name': 'Allgemeines Anschreiben',
        'kategorie': 'brief',
        'betreff': '{objekt}',
        'inhalt': (
            "Sehr geehrte(r) Frau/Herr {mieter_name}\n\n"
            "[Ihr Text]\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Information / Rundschreiben',
        'kategorie': 'info',
        'betreff': 'Information zu {liegenschaft}',
        'inhalt': (
            "Sehr geehrte Mieterinnen und Mieter\n\n"
            "Wir möchten Sie über Folgendes informieren:\n\n"
            "[Ihr Text]\n\n"
            "Besten Dank für Ihre Kenntnisnahme.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Kündigungsbestätigung',
        'kategorie': 'kuendigung',
        'betreff': 'Bestätigung Ihrer Kündigung – {objekt}',
        'inhalt': (
            "Sehr geehrte(r) Frau/Herr {mieter_name}\n\n"
            "Wir bestätigen Ihnen den Eingang Ihrer Kündigung für das Mietobjekt "
            "{objekt} an der {liegenschaft}.\n\n"
            "Das Mietverhältnis endet per [Datum]. Wir werden uns rechtzeitig für die "
            "Wohnungsabnahme bei Ihnen melden.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Zahlungserinnerung',
        'kategorie': 'mahnung',
        'betreff': 'Zahlungserinnerung – {objekt}',
        'inhalt': (
            "Sehr geehrte(r) Frau/Herr {mieter_name}\n\n"
            "Bei der Kontrolle unserer Konten haben wir festgestellt, dass folgender "
            "Betrag noch offen ist. Sollten Sie die Zahlung bereits getätigt haben, "
            "betrachten Sie dieses Schreiben bitte als gegenstandslos.\n\n"
            "Wir bitten Sie um baldige Begleichung.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Wohnungsabnahme-Protokoll',
        'kategorie': 'protokoll',
        'betreff': 'Abnahmeprotokoll {objekt}',
        'inhalt': (
            "Abnahmeprotokoll\n\n"
            "Objekt: {objekt}, {liegenschaft}\n"
            "Mieter: {mieter_name}\n"
            "Datum: {datum}\n\n"
            "Zustand der Räume:\n- [Raum]: [Zustand]\n\n"
            "Mängel / Bemerkungen:\n- [...]\n\n"
            "Zählerstände:\n- Strom: [...]\n- Wasser: [...]\n\n"
            "Unterschriften:\nMieter: ____________   Verwaltung: ____________"
        ),
    },
    # --- Schadensfall / Ticket ---
    {
        'name': 'Schaden – Eingangsbestätigung',
        'kategorie': 'ticket_eingang',
        'betreff': 'Eingangsbestätigung: {schaden} (Ticket #{ticket_id})',
        'inhalt': (
            "Guten Tag {melder_name}\n\n"
            "Vielen Dank für Ihre Meldung. Wir bestätigen den Eingang Ihrer "
            "Schadenmeldung „{schaden}“ in der Liegenschaft {liegenschaft} "
            "(Ticket #{ticket_id}).\n\n"
            "Wir kümmern uns darum und melden uns, sobald ein Handwerker beauftragt "
            "wurde.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Schaden – Auftrag an Handwerker',
        'kategorie': 'ticket_handwerker',
        'betreff': 'Reparaturauftrag: {objekt} (Ticket #{ticket_id})',
        'inhalt': (
            "Sehr geehrte Damen und Herren\n\n"
            "Wir beauftragen Sie mit der Behebung des folgenden Schadens:\n\n"
            "Objekt: {objekt}\nSchaden: {schaden}\n\n"
            "Bitte kontaktieren Sie den Mieter {melder_name} ({melder_tel}) direkt zur "
            "Terminvereinbarung. Als Referenz nutzen Sie bitte Ticket #{ticket_id}.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Schaden – Info an Melder',
        'kategorie': 'ticket_melder',
        'betreff': 'Ihre Schadenmeldung wurde weitergegeben (Ticket #{ticket_id})',
        'inhalt': (
            "Guten Tag {melder_name}\n\n"
            "Vielen Dank für Ihre Meldung „{schaden}“.\n\n"
            "Wir haben den Auftrag an die Firma {handwerker} weitergegeben. Diese wird "
            "sich in Kürze für einen Termin bei Ihnen melden.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
    {
        'name': 'Schaden – Erledigt-Meldung',
        'kategorie': 'ticket_erledigt',
        'betreff': 'Schaden behoben (Ticket #{ticket_id})',
        'inhalt': (
            "Guten Tag {melder_name}\n\n"
            "Der von Ihnen gemeldete Schaden „{schaden}“ wurde behoben und das Ticket "
            "abgeschlossen.\n\n"
            "Sollte das Problem weiterhin bestehen, melden Sie sich bitte bei uns.\n\n"
            "Freundliche Grüsse\n{vermieter}"
        ),
    },
]


def seed_standard_vorlagen():
    """Legt fehlende Standardvorlagen an (idempotent). Gibt Anzahl erstellter zurück."""
    from crm.models import Vorlage
    erstellt = 0
    for d in STANDARD_VORLAGEN:
        if not Vorlage.objects.filter(name=d['name']).exists():
            Vorlage.objects.create(**d)
            erstellt += 1
    return erstellt
