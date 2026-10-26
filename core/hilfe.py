"""In-App-Hilfe: kurze Erklärungen zu Fachbegriffen (Tag `{% hilfe 'schluessel' %}`).

Ein Katalog statt verstreuter `title`-Attribute (UI-Audit 26.10.2026): `title`
ist am Telefon nicht erreichbar und für Screenreader unzuverlässig. Der Tag
zeichnet ein kleines ⓘ, das auf Klick eine Blase mit Titel und Text zeigt
(static/js/fw-bausteine.js).

REGELN FÜR DIE TEXTE
- Zwei bis drei Sätze, Alltagssprache, das Gesetz nur als Fundstelle.
- Keine Zahl, die das Gesetz nicht selbst nennt (siehe Skill `schweizer-fachlogik`):
  Was kantonal oder vertraglich verschieden ist, steht als «je nach Vertrag/Kanton».
- Jeder Schlüssel, den eine Vorlage nennt, muss hier stehen —
  `core/tests/test_bausteine.py` prüft das.
"""
from django.utils.translation import gettext_lazy as _

HILFE = {
    # ---- Mietrecht ----
    'mahnstufen': (_('Mahnstufen'), _(
        'Erinnerung, Mahnung und zuletzt die Fristansetzung nach Art. 257d OR. Welche Stufe gilt, '
        'ergibt sich aus den Tagen seit Fälligkeit; Tage und Gebühren stellst du unter «Mahnstufen anpassen» ein.')),
    'art_257d': (_('Fristansetzung nach Art. 257d OR'), _(
        'Bei Zahlungsverzug setzt der Vermieter schriftlich eine Zahlungsfrist von mindestens 30 Tagen und droht die '
        'Kündigung an. Zahlt der Mieter nicht, ist eine Kündigung mit mindestens 30 Tagen Frist auf Ende eines Monats möglich.')),
    'verzugszins': (_('Verzugszins'), _(
        'Ab Verzug schuldet der Mieter Verzugszins von 5 % pro Jahr (Art. 104 OR), sofern nichts anderes vereinbart ist.')),
    'betreibung': (_('Betreibung'), _(
        'Zwangsvollstreckung nach SchKG: Mit dem Betreibungsbegehren stellt das Betreibungsamt einen Zahlungsbefehl zu. '
        'Erhebt der Mieter Rechtsvorschlag, braucht es eine Rechtsöffnung.')),
    'kaution': (_('Mietkaution'), _(
        'Bei Wohnräumen höchstens drei Monatszinse; sie liegt auf einem Konto oder Depot auf den Namen des Mieters '
        '(Art. 257e OR). Die Bank gibt sie mit Zustimmung beider frei — oder dem Mieter, wenn der Vermieter innert '
        'eines Jahres nach Mietende keinen Anspruch rechtlich geltend gemacht hat.')),
    'referenzzins': (_('Referenzzinssatz'), _(
        'Hypothekarischer Referenzzinssatz des Bundesamts für Wohnungswesen, vierteljährlich publiziert. Ändert er sich, '
        'kann der Mietzins angepasst werden; wie stark, legt Art. 13 VMWG fest.')),
    'lik': (_('Landesindex der Konsumentenpreise (LIK)'), _(
        'Teuerungsindex des Bundesamts für Statistik. Die Teuerung darf zu 40 % auf den Mietzins überwälzt werden '
        '(Art. 16 VMWG); bei indexierten Verträgen gilt der Index direkt.')),
    'formularpflicht': (_('Amtliches Formular'), _(
        'Mietzinserhöhungen und Kündigungen durch den Vermieter brauchen das vom Kanton genehmigte Formular '
        '(Art. 269d und 266l OR). In einigen Kantonen gilt die Pflicht auch für den Anfangsmietzins.')),
    'kuendigungsfrist': (_('Kündigungsfristen'), _(
        'Für Wohnungen mindestens drei Monate auf einen ortsüblichen Termin (Art. 266c OR), für Geschäftsräume sechs '
        'Monate (Art. 266d OR) — der Vertrag kann längere Fristen vorsehen. Die Termine berechnet die Anwendung aus dem Vertrag.')),
    'familienwohnung': (_('Familienwohnung'), _(
        'Kündigt der Mieter eine Familienwohnung, braucht er die Zustimmung des Ehegatten oder eingetragenen Partners '
        '(Art. 266m OR). Kündigt der Vermieter, stellt er beiden je separat zu (Art. 266n OR).')),
    'ersatzmieter': (_('Vorzeitiger Auszug'), _(
        'Wer ohne Frist auszieht, wird frei, wenn er einen zumutbaren, zahlungsfähigen Ersatzmieter stellt, der den '
        'Vertrag zu gleichen Bedingungen übernimmt (Art. 264 OR).')),
    'untermiete': (_('Untermiete'), _(
        'Der Mieter braucht die Zustimmung des Vermieters; verweigert werden darf sie nur aus den Gründen in Art. 262 OR, '
        'etwa missbräuchliche Bedingungen oder wesentliche Nachteile.')),
    'maengelruege': (_('Mängelrüge bei der Abnahme'), _(
        'Bei der Rückgabe prüft der Vermieter den Zustand und meldet Mängel, für die der Mieter einsteht, sofort '
        '(Art. 267a OR). Später entdeckte, versteckte Mängel sind sofort nach Entdeckung zu rügen.')),
    # ---- Nebenkosten ----
    'akonto': (_('Akonto'), _(
        'Monatliche Vorauszahlung an die Nebenkosten. Einmal jährlich wird nach den tatsächlichen Kosten abgerechnet; '
        'Nachzahlung oder Rückzahlung ergeben sich aus der Differenz (Art. 257b OR, Art. 4 VMWG).')),
    'pauschale': (_('Pauschale'), _(
        'Fester Betrag ohne jährliche Abrechnung. Er muss den Durchschnittswerten dreier Jahre entsprechen '
        '(Art. 4 Abs. 2 VMWG).')),
    'nebenkosten_vereinbart': (_('Welche Nebenkosten?'), _(
        'Abrechnen lässt sich nur, was im Mietvertrag ausdrücklich als Nebenkosten vereinbart ist (Art. 257a OR). '
        'Unterhalt und Reparaturen gehören nicht dazu.')),
    'verteilschluessel': (_('Verteilschlüssel'), _(
        'Bestimmt, wie Kosten auf die Einheiten verteilt werden: nach Fläche, Volumen, Wertquote, Personen oder Zähler. '
        'Je Kostenart lässt sich ein eigener Schlüssel wählen.')),
    'hkvo': (_('Verbrauchsabhängige Heizkosten'), _(
        'Ein Teil der Heizkosten (Grundkosten) wird nach Fläche verteilt, der Rest nach gemessenem Verbrauch. '
        'Ob sie vorgeschrieben ist, regelt das kantonale Energierecht.')),
    'pro_rata': (_('Zeitanteilig (pro rata)'), _(
        'Wer nur einen Teil der Periode Mieter war, trägt die Kosten nach den Tagen seiner Mietdauer.')),
    'akonto_anpassung': (_('Akonto anpassen'), _(
        'Weicht das Akonto deutlich vom tatsächlichen Bedarf ab, schlägt die Anwendung einen neuen Betrag vor. '
        'Die Anpassung gilt für künftige Sollstellungen; die Mitteilung an den Mieter ist separat.')),
    'hnk': (_('HNK'), _(
        'Heiz- und Nebenkosten. Eine HNK-relevante Lieferantenrechnung fliesst über die Nebenkostenabrechnung '
        'an die Mieter — eine zusätzliche direkte Weiterverrechnung würde doppelt belasten.')),
    'weiterverrechnung': (_('Weiterverrechnung'), _(
        'Kosten, die ein bestimmter Mieter direkt trägt, etwa ein verlorener Schlüssel oder eine verursachte Reparatur. '
        'Es entsteht eine Debitorenrechnung an den Mieter.')),
    # ---- Zahlungsverkehr ----
    'qr_referenz': (_('QR-Referenz'), _(
        '27-stellige Referenz mit Prüfziffer auf der QR-Rechnung. Sie gehört zur QR-IBAN und lässt jede Zahlung '
        'automatisch der richtigen Rechnung zuordnen.')),
    'qr_iban': (_('QR-IBAN'), _(
        'Eine eigene IBAN für QR-Rechnungen mit Referenz; die Institutskennung liegt zwischen 30000 und 31999. '
        'Für Zahlungen ohne Referenz gilt die normale IBAN.')),
    'pain001': (_('pain.001'), _(
        'Zahlungsauftrag im Format ISO 20022. Der Zahllauf erzeugt die Datei; du lädst sie im E-Banking hoch.')),
    'camt': (_('camt.053 / camt.054'), _(
        'Kontoauszug bzw. Gutschriftsanzeige der Bank im Format ISO 20022. Der Bankabgleich liest sie ein und ordnet '
        'die Zahlungen den offenen Rechnungen zu.')),
    'sollstellung': (_('Sollstellung'), _(
        'Erzeugt monatlich die Mietzinsrechnungen aller aktiven Verträge (Netto, Akonto, Pauschalen). '
        'Erst danach können Zahlungen zugeordnet und gemahnt werden.')),
    'bankabgleich': (_('Bankabgleich'), _(
        'Ordnet Zahlungseingänge den offenen Rechnungen zu — automatisch über die QR-Referenz, sonst über gespeicherte Zahler-Zuordnungen. '
        'Was offen bleibt, ordnest du von Hand zu.')),
    'zahllauf': (_('Zahllauf'), _(
        'Fasst freigegebene Lieferantenrechnungen zu einem Zahlungsauftrag (pain.001) zusammen und verbucht den Lauf gesammelt.')),
    'mahnsperre': (_('Mahnsperre'), _(
        'Für diese Person läuft kein automatischer Mahnlauf, etwa während einer Zahlungsvereinbarung. '
        'Offene Rechnungen bleiben sichtbar.')),
    'abweichender_zahler': (_('Abweichender Zahler'), _(
        'Wenn jemand anders zahlt als der Mieter, zum Beispiel das Sozialamt oder ein Arbeitgeber. '
        'Der Bankabgleich erkennt die Zahlungen dann auch unter diesem Namen.')),
    'mwst_option': (_('MWST bei Vermietung'), _(
        'Vermietung ist grundsätzlich von der MWST ausgenommen (Art. 21 MWSTG). Bei Geschäftsräumen kann für die Steuer '
        'optiert werden, wenn der Mieter sie nicht ausschliesslich für Wohnzwecke nutzt (Art. 22 MWSTG).')),
    # ---- Zahlungs-Cockpit (V12) ----
    'durchlaufkonto': (_('Durchlaufkonto 1190'), _(
        'Hier wartet Geld, das sich nicht sicher zuordnen liess — ohne oder mit falscher Referenz. '
        'Es geht nicht verloren: Es wird zugeordnet, aufgeteilt, als Kaution erkannt oder an den Absender zurücküberwiesen.')),
    'mieterguthaben': (_('Mieterguthaben (Konto 2030)'), _(
        'Zahlt ein Mieter mehr als offen, gehört ihm der Überschuss. Er wird mit der nächsten Rechnung '
        'verrechnet, für die Nebenkostenabrechnung reserviert oder zurückerstattet — wie hinterlegt.')),
    'sammelzahlung': (_('Sammelzahlung'), _(
        'Eine Überweisung für mehrere Posten, etwa zwei Verträge oder ein Sozialdienst für mehrere Mieter. '
        'Jeder Teil wird einem Posten zugeteilt und einzeln gebucht; storniert wird die Zahlung nur als Ganzes.')),
    'teilzahlung': (_('Teilzahlung'), _(
        'Ist weniger eingegangen als geschuldet, gilt der Posten als «teilbezahlt». Der Rest bleibt offen '
        'und läuft in den Mahnlauf, solange keine Mahnsperre oder Zahlungsvereinbarung besteht.')),
    'tilgungsreihenfolge': (_('Welche Schuld wird getilgt?'), _(
        'Gibt der Zahler an, welche Schuld er bezahlt, gilt seine Erklärung (Art. 86 OR). Sonst wird die '
        'älteste fällige Schuld getilgt (Art. 87 OR) — so ist der Vorschlag vorbefüllt.')),
    'kleindifferenz': (_('Kleindifferenz'), _(
        'Ein kleiner Rest, etwa von der Bank abgezogene Spesen. Bis CHF 5.00 lässt er sich als '
        'Debitorenverlust (Konto 3805) ausbuchen, statt ihn zu mahnen.')),
    'rueckbuchung': (_('Rückbuchung'), _(
        'Die Bank bucht eine eingegangene Zahlung zurück, etwa wegen falscher Kontoangaben. Die Zahlung wird '
        'storniert, die Rechnung ist wieder offen und läuft ins Mahnwesen.')),
    'kautionskonto': (_('Kaution auf dem Mietzinskonto'), _(
        'Die Kaution gehört auf ein Sperrkonto auf den Namen des Mieters (Art. 257e OR). Ist sie auf dem '
        'Mietzinskonto eingegangen, wird sie als Kaution verbucht und danach auf das Sperrkonto überwiesen.')),

    # ---- Liegenschaft & Kennzahlen ----
    'egid': (_('EGID / EWID'), _(
        'Eidgenössischer Gebäude- bzw. Wohnungsidentifikator aus dem Gebäude- und Wohnungsregister (GWR). '
        'Die Anwendung versucht die EGID aus der Adresse zu ermitteln.')),
    'wertquote': (_('Wertquote'), _(
        'Anteil einer Stockwerkeinheit am Ganzen, meist in Tausendsteln (Art. 712e ZGB). '
        'Danach verteilen sich gemeinschaftliche Kosten und Stimmen, sofern nichts anderes beschlossen ist.')),
    'verkehrswert': (_('Verkehrswert'), _(
        'Der Marktwert der Liegenschaft — Grundlage der Rendite. Fehlt er, rechnet die Anwendung mit den Anlagekosten; '
        'der Versicherungswert taugt nicht, er bemisst den Wiederaufbau.')),
    'rendite': (_('Brutto- und Nettorendite'), _(
        'Brutto: Soll-Mietertrag eines Jahres geteilt durch den Verkehrswert. Netto: dasselbe nach Abzug des '
        'Betriebsaufwands der letzten zwölf Monate.')),
    'leerstandsquote': (_('Leerstandsquote'), _(
        'Leere Einheiten im Verhältnis zu allen Einheiten der Auswahl. Eine Einheit mit unterschriebenem Nachmieter '
        'zählt als versorgt, nicht als Leerstand.')),
    'versorgt': (_('Frei, aber versorgt'), _(
        'Die Einheit ist heute leer oder wird frei, aber ein Nachmieter hat schon unterschrieben. Es ist nichts zu tun.')),
    'ausfall': (_('Mietausfall'), _(
        'Netto-Mietzins, der wegen Leerstand nicht eingeht. Der bisherige Ausfall ist eine Schätzung: '
        'Mietzins mal Leermonate seit Vertragsende.')),
    'zahlungsquote': (_('Zahlungsquote'), _(
        'Anteil des fälligen Rechnungsbetrags des Jahres, der vollständig bezahlt ist. Teilbezahlte Rechnungen zählen noch nicht als bezahlt.')),
    'termintreue': (_('Termintreue'), _(
        'Anteil der erledigten Tickets, die bis zu ihrer Zielzeit erledigt wurden.')),
    # ---- Personen ----
    'ahv': (_('AHV-Nummer'), _(
        'Dreizehnstellige Sozialversicherungsnummer, beginnt mit 756. Nur erfassen, wenn sie für den Vertrag nötig ist.')),
    'korrespondenzadresse': (_('Korrespondenzadresse'), _(
        'Hat Vorrang für die Zustellung, etwa bei Wochenaufenthaltern oder einer Vertretung. Die Wohnadresse bleibt die Mietadresse.')),
    'bewilligung': (_('Aufenthaltsstatus'), _(
        'Hilft, Mietdauer und Befristung abzustimmen. Er ist kein Grund, eine Vermietung zu verweigern.')),
    'portal': (_('Portal-Zugang'), _(
        'Mieter und Eigentümer sehen im Portal ihre Rechnungen, Dokumente und Meldungen. '
        'Den Zugang richtest du auf der Personen- bzw. Mandatsseite ein.')),
}


def eintrag(schluessel):
    """(titel, text) oder None."""
    return HILFE.get(schluessel)
