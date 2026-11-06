"""Standard-Briefvorlagen für Verwaltungen (Schweizer Mietrecht).

Nur Anschreiben als Vorschlag, kein Rechtsgutachten: Die Verwaltung passt jeden Text an. Einschreiben und Frist sind
an der Vorlage vorbelegt (``einschreiben``, ``frist_art``, ``frist_tage``) und beim Erstellen änderbar. Platzhalter nur
aus ``core.services.platzhalter`` (``{frist}`` nur mit Frist-Art «datum», ``{frist.tage}`` mit jeder Frist)."""

_ANREDE = "{mieter.anrede}\n\n"
_GRUSS = "\n\nFreundliche Grüsse\n{verwaltung.name}"
_KONTAKT = "Bei Fragen erreichen Sie uns unter {verwaltung.telefon}."


def _v(name, kategorie, betreff, text, einschreiben=False, frist_art='', frist_tage=None, ereignis=''):
    d = {'name': name, 'kategorie': kategorie, 'betreff': betreff, 'inhalt': _ANREDE + text + _GRUSS,
         'einschreiben': einschreiben, 'frist_art': frist_art, 'frist_tage': frist_tage}
    if ereignis:
        d['ereignis'] = ereignis
    return d


BRIEF_VORLAGEN = [
    _v('Abmahnung mit Kündigungsandrohung', 'brief', 'Abmahnung – {objekt.bezeichnung}',
       "wir haben festgestellt, dass Sie Ihre Pflichten aus dem Mietvertrag für {objekt.bezeichnung}, "
       "{objekt.adresse} verletzen: [Sachverhalt, z. B. unberechtigte Nutzung eines Parkplatzes].\n\n"
       "Wir fordern Sie auf, diesen Zustand bis spätestens {frist} zu beheben. Andernfalls sehen wir uns "
       "gezwungen, das Mietverhältnis gestützt auf Art. 257f Abs. 3 OR ausserordentlich zu kündigen.\n\n"
       + _KONTAKT, einschreiben=True, frist_art='datum', frist_tage=14),
    _v('Fristansetzung zur Behebung eines Mangels', 'brief', 'Mangel in {objekt.bezeichnung}',
       "bei {objekt.bezeichnung}, {objekt.adresse} liegt folgender Mangel vor: [Beschreibung]. "
       "Bitte beheben Sie ihn innert {frist.tage} Tagen ab Erhalt dieses Schreibens.\n\n" + _KONTAKT,
       einschreiben=True, frist_art='zugang', frist_tage=30),
    _v('Zahlungserinnerung (erste)', 'mahnung', 'Zahlungserinnerung – {objekt.bezeichnung}',
       "bei der Kontrolle unserer Konten haben wir festgestellt, dass der Mietzins für {objekt.bezeichnung} noch "
       "offen ist. Falls Sie bereits bezahlt haben, betrachten Sie dieses Schreiben als gegenstandslos. "
       "Bitte begleichen Sie den Betrag bis {frist}.\n\n" + _KONTAKT, frist_art='datum', frist_tage=10),
    _v('Zweite Mahnung', 'mahnung', 'Mahnung – {objekt.bezeichnung}',
       "trotz unserer Zahlungserinnerung ist der Mietzins für {objekt.bezeichnung} nicht eingegangen. "
       "Wir bitten Sie, den offenen Betrag bis {frist} zu überweisen. Andernfalls leiten wir weitere Schritte ein.\n\n"
       + _KONTAKT, einschreiben=True, frist_art='datum', frist_tage=10),
    _v('Bestätigung der Kündigung durch den Mieter', 'kuendigung', 'Bestätigung Ihrer Kündigung – {objekt.bezeichnung}',
       "wir bestätigen den Eingang Ihrer Kündigung für {objekt.bezeichnung}, {objekt.adresse}. Das Mietverhältnis "
       "endet per [Datum]. Wir melden uns rechtzeitig für die Wohnungsabnahme.\n\n" + _KONTAKT),
    _v('Ablehnung einer Kündigung (Termin oder Form)', 'kuendigung', 'Ihre Kündigung – {objekt.bezeichnung}',
       "Ihre Kündigung für {objekt.bezeichnung} konnten wir nicht wie gewünscht entgegennehmen: "
       "[Grund, z. B. Kündigungstermin nicht eingehalten]. Das Mietverhältnis endet frühestens per [Datum].\n\n" + _KONTAKT,
       einschreiben=True),
    _v('Kündigung durch die Verwaltung (ordentlich)', 'kuendigung', 'Kündigung des Mietverhältnisses – {objekt.bezeichnung}',
       "hiermit kündigen wir das Mietverhältnis für {objekt.bezeichnung}, {objekt.adresse} auf den [Datum] "
       "unter Einhaltung der Kündigungsfrist. Für die Kündigung ist das amtliche Formular beigelegt. "
       "Sie können die Kündigung innert 30 Tagen bei der Schlichtungsbehörde anfechten.\n\n" + _KONTAKT,
       einschreiben=True),
    _v('Bestätigung des Mietbeginns', 'brief', 'Mietbeginn – {objekt.bezeichnung}',
       "wir freuen uns, Sie als Mieterin oder Mieter von {objekt.bezeichnung}, {objekt.adresse} zu begrüssen. "
       "Mietbeginn ist der {vertrag.beginn}. Die Schlüsselübergabe vereinbaren wir mit Ihnen gesondert.\n\n" + _KONTAKT),
    _v('Hausordnung und Ruhezeiten (Hinweis)', 'brief', 'Hausordnung – {objekt.bezeichnung}',
       "wir erinnern Sie an die Hausordnung, insbesondere an die Ruhezeiten. Bitte nehmen Sie Rücksicht auf die "
       "Nachbarschaft. Die Hausordnung ist Bestandteil Ihres Mietvertrags.\n\n" + _KONTAKT),
    _v('Lärmbeschwerde – Aufforderung zur Rücksicht', 'brief', 'Lärm – {objekt.bezeichnung}',
       "aus der Nachbarschaft sind Beschwerden wegen Lärms eingegangen: [Beschreibung]. Wir ersuchen Sie, künftig "
       "Rücksicht zu nehmen. Bei Wiederholung behalten wir uns weitere Schritte vor.\n\n" + _KONTAKT),
    _v('Ankündigung von Unterhaltsarbeiten', 'info', 'Unterhaltsarbeiten – {objekt.bezeichnung}',
       "an {objekt.adresse} führen wir folgende Arbeiten durch: [Arbeiten]. Zeitraum: [von – bis]. "
       "Der Zutritt zu Ihrer Wohnung ist dafür nötig; bitte sorgen Sie für Zugang. Wir bitten um Verständnis "
       "für allfällige Unannehmlichkeiten.\n\n" + _KONTAKT),
    _v('Zutrittsankündigung (Kontrolle, Ablesung)', 'info', 'Zutritt zur Wohnung – {objekt.bezeichnung}',
       "am [Datum] möchten wir [Zweck, z. B. die Zähler ablesen] in Ihrer Wohnung. Bitte ermöglichen Sie uns den "
       "Zutritt oder melden Sie sich für einen anderen Termin.\n\n" + _KONTAKT),
    _v('Mietzinsanpassung – Begleitschreiben', 'brief', 'Anpassung des Mietzinses – {objekt.bezeichnung}',
       "beiliegend erhalten Sie das amtliche Formular zur Anpassung Ihres Mietzinses für {objekt.bezeichnung}. "
       "Sie können sie innert 30 Tagen bei der Schlichtungsbehörde anfechten.\n\n" + _KONTAKT, einschreiben=True),
    _v('Nebenkostenabrechnung – Begleitschreiben', 'brief', 'Nebenkostenabrechnung – {objekt.bezeichnung}',
       "beiliegend erhalten Sie die Nebenkostenabrechnung für {objekt.bezeichnung}. Einwände richten Sie bitte "
       "innert 30 Tagen an uns.\n\n" + _KONTAKT),
    _v('Aufforderung zur Nachzahlung Nebenkosten', 'mahnung', 'Nachzahlung Nebenkosten – {objekt.bezeichnung}',
       "aus der Nebenkostenabrechnung ergibt sich eine Nachzahlung. Bitte überweisen Sie den Betrag bis {frist}.\n\n"
       + _KONTAKT, frist_art='datum', frist_tage=30),
    _v('Kautionsrückgabe – Bestätigung', 'brief', 'Rückgabe der Mietkaution – {objekt.bezeichnung}',
       "die Mietkaution für {objekt.bezeichnung} wird nach der Wohnungsabnahme und der Abrechnung freigegeben. "
       "Bitte teilen Sie uns Ihre Bankverbindung mit.\n\n" + _KONTAKT),
    _v('Aufforderung zum Reinigen und Räumen', 'brief', 'Reinigung und Räumung – {objekt.bezeichnung}',
       "für die Wohnungsabnahme am [Datum] bitten wir Sie, die Wohnung besenrein, gereinigt und vollständig geräumt "
       "zu übergeben. Mängel melden wir Ihnen mit einer Frist von {frist.tage} Tagen.\n\n" + _KONTAKT,
       frist_art='zugang', frist_tage=10),
    _v('Untermiete – Anfrage und Bewilligung', 'brief', 'Untermiete – {objekt.bezeichnung}',
       "zu Ihrer Anfrage betreffend Untermiete von {objekt.bezeichnung}: Wir bitten um folgende Angaben: "
       "[Name, Dauer, Untermietzins]. Die Zustimmung nach Art. 262 OR erteilen wir nach Prüfung.\n\n" + _KONTAKT),
    _v('Schlüsselverlust – Mitteilung', 'info', 'Schlüsselverlust – {objekt.bezeichnung}',
       "der Verlust Ihres Schlüssels ist bei uns erfasst. Wir ersetzen den Schlüssel zulasten des Mieters; "
       "gegebenenfalls ist ein Zylinderwechsel nötig.\n\n" + _KONTAKT),
    _v('Mahnung wegen Verstoss gegen die Haustierregeln', 'brief', 'Haustier – {objekt.bezeichnung}',
       "wir haben festgestellt, dass in {objekt.bezeichnung} ein Tier gehalten wird, für das keine Bewilligung "
       "vorliegt. Bitte reichen Sie innert {frist.tage} Tagen ab Erhalt ein Bewilligungsgesuch ein.\n\n" + _KONTAKT,
       einschreiben=True, frist_art='zugang', frist_tage=14),
    _v('Hinweis auf Heizperiode und Lüften', 'info', 'Heizen und Lüften – {objekt.bezeichnung}',
       "die Heizperiode beginnt. Bitte lüften Sie mehrmals täglich kurz, damit Feuchtigkeit und Schimmel keine "
       "Chance haben.\n\n" + _KONTAKT),
    _v('Antwort auf Mängelrüge', 'brief', 'Ihre Mängelrüge – {objekt.bezeichnung}',
       "Ihre Meldung zu {objekt.bezeichnung} haben wir erhalten. [Vorgehen und Termin]. Bitte ermöglichen Sie "
       "dem Handwerker den Zutritt.\n\n" + _KONTAKT),
    _v('Eintritt eines neuen Mieters (Nachmieter)', 'brief', 'Nachmieter – {objekt.bezeichnung}',
       "Sie schlagen einen Nachmieter für {objekt.bezeichnung} vor. Bitte reichen Sie uns dessen Unterlagen "
       "bis {frist} ein; wir prüfen die Zumutbarkeit nach Art. 264 OR.\n\n" + _KONTAKT,
       frist_art='datum', frist_tage=14),
    _v('Bestätigung Wohnsitz / Mietverhältnis', 'brief', 'Bestätigung des Mietverhältnisses',
       "wir bestätigen, dass Sie seit dem {vertrag.beginn} Mieterin oder Mieter von {objekt.bezeichnung}, "
       "{objekt.adresse} sind.\n\n" + _KONTAKT),
    _v('Tierhaltebewilligung', 'dokument', 'Tierhaltebewilligung – {objekt.bezeichnung}',
       "gestützt auf Ihre Angabe ({mieter.haustiere}) bewilligen wir die Haltung des genannten Tiers in "
       "{objekt.bezeichnung}, {objekt.adresse}, unter folgenden Bedingungen: Das Tier darf weder die Mitbewohner "
       "stören noch die Mietsache beschädigen; Schäden gehen zulasten des Halters; die Bewilligung kann bei "
       "wiederholten Störungen widerrufen werden.\n\n" + _KONTAKT, ereignis='vertrag_haustier'),
]
