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
        'Kündigung an. Zahlt der Mieter nicht, ist eine Kündigung mit mindestens 30 Tagen Frist auf Ende eines Monats möglich. '
        'Genannt und angedroht werden nur fällige Mietzinse und Nebenkosten, keine anderen Forderungen.')),
    'verzugszins': (_('Verzugszins'), _(
        'Ab Verzug schuldet der Mieter Verzugszins von 5 % pro Jahr (Art. 104 OR), sofern nichts anderes vereinbart ist.')),
    # Die Hinweise zu Mahngebühren (vertragliche Grundlage) und zur Zinsbasis (360 Tage)
    # stehen auf den Seiten Mahnwesen und Mahnstufen, nicht in diesen Einträgen: Ein
    # geänderter Text verlöre seine Übersetzung, bis die Kataloge nachgeführt sind.
    'betreibung': (_('Betreibung'), _(
        'Zwangsvollstreckung nach SchKG: Mit dem Betreibungsbegehren stellt das Betreibungsamt einen Zahlungsbefehl zu. '
        'Erhebt der Mieter Rechtsvorschlag, braucht es eine Rechtsöffnung.')),
    'rechtsvorschlag': (_('Rechtsvorschlag'), _(
        'Der Schuldner kann innert 10 Tagen nach Zustellung des Zahlungsbefehls ohne Begründung Rechtsvorschlag '
        'erheben (Art. 74 SchKG); dann steht die Betreibung still. Auch ein später erhobener Rechtsvorschlag kann '
        'gelten — etwa bei Betreibungsferien oder nachträglichem Rechtsvorschlag; das klärt das Betreibungsamt.')),
    'rechtsoeffnung': (_('Rechtsöffnung'), _(
        'Beseitigt den Rechtsvorschlag. Mit einer unterschriebenen Schuldanerkennung, etwa dem Mietvertrag oder einer '
        'Zahlungsvereinbarung, gibt das Gericht provisorische Rechtsöffnung (Art. 82 SchKG), mit einem Urteil '
        'definitive (Art. 80 SchKG). Zwischen Gesuch und Entscheid steht die Jahresfrist für die Fortsetzung still.')),
    'fortsetzung': (_('Fortsetzungsbegehren'), _(
        'Frühestens 20 Tage nach Zustellung des Zahlungsbefehls, bei Rechtsvorschlag erst nach der Rechtsöffnung; '
        'spätestens ein Jahr nach der Zustellung, verlängert um die Dauer des Rechtsöffnungsverfahrens '
        '(Art. 88 SchKG). Danach pfändet das Betreibungsamt.')),
    'betreibungskosten': (_('Betreibungskosten'), _(
        'Die Kosten der Betreibung trägt der Schuldner, der Gläubiger schiesst sie vor (Art. 68 SchKG). '
        '«Kosten dem Mieter belasten» stellt sie als eigene Forderung in Rechnung; sie zählt nicht zum '
        'Mietzinsrückstand nach Art. 257d OR.')),
    'verlustschein': (_('Verlustschein'), _(
        'Deckt die Pfändung die Forderung nicht, stellt das Betreibungsamt einen Verlustschein aus (Art. 149 SchKG). '
        'Die offenen Beträge werden dann als Debitorenverlust (Konto 3805) abgeschrieben; die Forderung gegen den '
        'Schuldner bleibt bestehen.')),
    'ratenplan': (_('Ratenplan'), _(
        'Der fällige Rückstand wird auf gleich hohe Raten verteilt, die letzte trägt den Rest. Bis zur Erfüllung '
        'ruhen nur die gedeckten Forderungen im Mahnlauf — neue Mieten werden normal gemahnt.')),
    'ratenbruch': (_('Bruch der Vereinbarung'), _(
        'Liegt die bezahlte Summe nach einer kurzen Toleranz unter dem, was an Raten fällig war, gilt die '
        'Vereinbarung als gebrochen. Dann laufen die gedeckten Forderungen wieder im Mahnlauf, und eine Pendenz '
        'erinnert an die Fortsetzung des Mahnprozesses.')),
    'schuldanerkennung': (_('Schuldanerkennung'), _(
        'Unterschreibt der Mieter die Zahlungsvereinbarung, anerkennt er den Rückstand schriftlich. Das ist ein '
        'provisorischer Rechtsöffnungstitel (Art. 82 SchKG): Erhebt er in einer Betreibung Rechtsvorschlag, '
        'lässt sich dieser damit beseitigen.')),
    'vereinbarung_257d': (_('Vereinbarung und Art. 257d OR'), _(
        'Eine Zahlungsvereinbarung hemmt eine bereits laufende Zahlungsfrist nach Art. 257d OR nicht, es sei denn, '
        'der Vermieter verzichtet ausdrücklich darauf.')),
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
    'vorbehalt': (_('Vorbehalt'), _(
        'Wer die mögliche Anpassung nicht ganz ausschöpft, kann sich den Rest für später vorbehalten. '
        'Der Vorbehalt wird beziffert — in Franken oder Prozent —, damit er sich später nachvollziehen lässt.')),
    # Vertragsassistent, Block «Mietzinsmodell» (27.10.2026)
    'festmiete': (_('Fester Mietzins'), _(
        'Der Mietzins ist im Vertrag als fester Betrag vereinbart. Spätere Anpassungen gehen mit dem amtlichen '
        'Formular (Art. 269d OR); die Gründe stehen in Art. 269a OR, etwa Referenzzinssatz oder Kostensteigerung.')),
    'index_weitergabe': (_('Weitergabe der Teuerung'), _(
        'Der Anteil der Teuerung, der in den Mietzins einfliesst. Höchstens 100 Prozent: Die Erhöhung darf die '
        'Zunahme des Landesindexes nicht übersteigen (Art. 17 Abs. 1 VMWG). Sinkt der Index, ist der Mietzins '
        'entsprechend anzupassen (Art. 17 Abs. 2 VMWG).')),
    'index_intervall': (_('Mindestintervall'), _(
        'Der Abstand zwischen zwei Anpassungen, den die Parteien im Vertrag vereinbaren. Die Ankündigung selbst '
        'erfolgt mit mindestens 30 Tagen auf ein Monatsende (Art. 17 Abs. 3 VMWG).')),
    'indexmiete': (_('Indexmiete'), _(
        'Der Mietzins folgt dem Landesindex der Konsumentenpreise, nach oben wie nach unten und höchstens im '
        'Umfang der Teuerung (Art. 269b OR, Art. 17 VMWG). Der Vertrag muss mindestens fünf Jahre fest dauern; ein '
        'Kündigungsverzicht des Vermieters für fünf Jahre genügt (Art. 17 Abs. 4 VMWG). Jede Anpassung geht mit dem '
        'amtlichen Formular, mindestens 30 Tage vor einem Monatsende.')),
    'staffelmiete': (_('Staffelmiete'), _(
        'Die Erhöhungen sind im Vertrag als Frankenbeträge vereinbart, höchstens einmal jährlich, bei einer '
        'Vertragsdauer von mindestens drei Jahren (Art. 269c OR). Dass auch ein Kündigungsverzicht des Vermieters '
        'als feste Dauer zählt, ist sinngemäss von Art. 17 Abs. 4 VMWG übernommen. Der Mietzins folgt den Stufen — '
        'die Anpassung nach Referenzzins und Teuerung gilt für ihn nicht.')),
    'index_staffel_kombination': (_('Index und Staffel zusammen?'), _(
        'Eine Indexklausel darf nicht mit einer Staffelung kombiniert werden (Art. 269b und 269c OR, BGE 124 III 57). '
        'Pro Vertrag gilt deshalb genau ein Mietzinsmodell: fest, Index oder Staffel.')),
    'kuendigungsverzicht': (_('Kündigungsverzicht des Vermieters'), _(
        'Bei einem unbefristeten Vertrag zählt die Dauer als fest, wenn der Vermieter für die verlangte Zeit auf die '
        'Kündigung verzichtet: fünf Jahre bei der Indexmiete (Art. 17 Abs. 4 VMWG), drei Jahre bei der Staffelmiete '
        '(sinngemäss, Art. 269c OR). Die Frist läuft ab Mietbeginn; das genannte Enddatum zählt mit.')),
    'staffel_mitteilung': (_('Mitteilung der Staffelerhöhung'), _(
        'Jede Erhöhung wird dem Mieter schriftlich mitgeteilt, frühestens vier Monate vor ihrem Eintritt '
        '(Art. 269d Abs. 5 OR, Art. 19a VMWG). Das amtliche Formular braucht es dafür nicht, die Mitteilung aber '
        'schon: Der Vertrag allein ersetzt sie nicht.')),
    'herabsetzung': (_('Herabsetzung'), _(
        'Sinkt der Referenzzins, kann der Mieter eine Herabsetzung verlangen (Art. 270a OR). Der Vermieter '
        'antwortet innert 30 Tagen; lehnt er ab, kann der Mieter innert 30 Tagen die Schlichtungsbehörde anrufen.')),
    'zugang': (_('Zugang'), _(
        'Fristen laufen ab dem Tag, an dem ein Schreiben beim Empfänger ankommt — nicht ab dem Versand und nicht ab '
        'der Abholeinladung. Wird ein Einschreiben abgeholt, ist es der Tag der Abholung; wird es nicht abgeholt, gilt es '
        'am letzten Tag der siebentägigen Abholfrist als zugegangen (BGE 119 II 147). Ist der Zugang noch nicht bestätigt, '
        'rechnet die Anwendung vom spätestmöglichen Zugang (Postweg und Abholfrist) und sperrt eine Kündigung bis dahin.')),
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
        'Ein Teil der Heizkosten (Grundkosten) wird nach Volumen (m³) verteilt, der Rest nach gemessenem Verbrauch. '
        'Ob sie vorgeschrieben ist, regelt das kantonale Energierecht.')),
    'pro_rata': (_('Zeitanteilig (pro rata)'), _(
        'Wer nur einen Teil der Periode Mieter war, trägt die Kosten nach den Tagen seiner Mietdauer.')),
    'akonto_anpassung': (_('Akonto anpassen'), _(
        'Weicht das Akonto deutlich vom tatsächlichen Bedarf ab, schlägt die Anwendung einen neuen Betrag vor. '
        'Übernommen wird er über die Mietzinsanpassung mit Formular und Termin; der neue Betrag gilt erst ab '
        'diesem Termin.')),
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
        'Von Hand gesetzt: Für diese Person läuft kein automatischer Mahnlauf. Eine Zahlungsvereinbarung braucht '
        'das Häkchen nicht — sie nimmt nur die Forderungen aus, die ihr Ratenplan deckt. Offene Rechnungen bleiben sichtbar.')),
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
    # ---- Vorlagen und Dokumente (Modul 5, 27.10.2026) ----
    'dokumentregel': (_('Regel «Wenn … dann …»'), _(
        'Eine Vorlage mit Ereignis erzeugt bei diesem Ereignis ein zusätzliches Dokument in der Akte. Es gilt die '
        'eigene Vorlage vor der mitgelieferten und die Sprache des Empfängers vor Deutsch. Amtliche Formulare und '
        'Mahnungen bleiben, wie sie sind.')),
    'platzhalter': (_('Platzhalter'), _(
        'Ein Platzhalter wie {mieter.name} wird beim Erzeugen durch den Wert aus Vertrag, Objekt oder Verwaltung '
        'ersetzt. Unbekannte Platzhalter lassen sich nicht speichern; die älteren Schreibweisen gelten weiter.')),
    'vorlage_gueltig_ab': (_('Gültig ab'), _(
        'Ab diesem Tag gilt die Fassung. Gilt die Vorlage heute schon und liegt der Tag in der Zukunft, entsteht beim '
        'Speichern eine neue Fassung; bis dahin gilt die bisherige. Leer heisst: gilt sofort.')),
    # ---- Schlüssel (Modul 2, 27.10.2026) ----
    'schliessanlage': (_('Schliessanlage'), _(
        'Hersteller, Sicherungskarte und Bestellberechtigte der Anlage, dazu alle Schlüssel und die Türen, die sie '
        'öffnen. Jede Ausgabe und Rücknahme erzeugt eine Quittung mit Unterschrift in der Ablage.')),
    'schluesselart': (_('Schlüsselart'), _(
        'Ein Hauptschlüssel öffnet alle Türen der Anlage, ein Gruppenschlüssel mehrere (etwa Haustür und Keller), ein '
        'Einzelschlüssel eine bestimmte Tür wie die Wohnungstür.')),
    # ---- Indexanpassung (Art. 269b OR, Art. 17 und 19 VMWG, 27.10.2026) ----
    'index_anpassung_bekanntgabe': (_('Bekanntgabe des Indexstandes'), _(
        'Bei einer Indexmiete darf die Mitteilung erst nach der öffentlichen Bekanntgabe des neuen Indexstandes '
        'erfolgen (Art. 19 Abs. 2 VMWG). Annahme der Anwendung: Ein Monat gilt als bekannt gegeben, sobald er in '
        'ihrer LIK-Tabelle steht; ein Veröffentlichungsdatum des BFS ist nicht hinterlegt.')),
    'index_anpassung_grenze': (_('Höchstbetrag'), _(
        'Die Erhöhung darf die Zunahme des Landesindexes nicht übersteigen (Art. 17 Abs. 1 VMWG), bei vereinbarter '
        'Teil-Weitergabe nur deren Anteil. Sinkt der Index, ist der Mietzins nach unten anzupassen (Abs. 2). Der '
        'Vorschlag wird auf 5 Rappen abgerundet, damit er die Grenze nie überschreitet.')),
    'index_anpassung_frist': (_('Frist und Termin'), _(
        'Die Anpassung ist mindestens 30 Tage im Voraus auf ein Monatsende anzukündigen (Art. 17 Abs. 3 VMWG). '
        'Die Anwendung rechnet ab Zugang beim Mieter, ohne bestätigten Zugang ab Versand plus Zustellpuffer. Frühere '
        'Termine stehen nicht zur Wahl.')),
    'index_anpassung_vertragsgrenzen': (_('Vertragliche Grenzen'), _(
        'Weitergabe, Mindestintervall und letzte Anpassung stammen aus dem Mietvertrag, nicht aus dem Gesetz. Ein '
        'laufendes Mindestintervall wird gemeldet, blockiert aber nicht: Der Vertrag entscheidet.')),
    'index_anpassung_formular': (_('Amtliches Formular bei der Indexanpassung'), _(
        'Das amtliche Formular (Art. 269d OR) gilt sinngemäss auch für die Indexanpassung (Art. 19 Abs. 2 VMWG). '
        'Nicht für jeden Kanton liegt ein Original vor; dann nennt die Anwendung die Lücke und erzeugt kein '
        'Ersatzformular.')),
    # ---- Staffelmiete: Mitteilung der Erhöhung (Art. 269d Abs. 5 OR, Art. 19a VMWG, 27.10.2026) ----
    'staffel_mitteilung_fenster': (_('Mitteilungsfenster'), _(
        'Der erste Tag, an dem die Mitteilung versandt werden darf: vier Monate vor der Erhöhung. Bei einer Erhöhung '
        'am 31. März ist es der 1. Dezember, nicht der 30. November, der vier Monate und einen Tag davor liegt. '
        'Vorher erstellt die Anwendung kein Schreiben und nimmt kein Versanddatum an.')),
}


def eintrag(schluessel):
    """(titel, text) oder None."""
    return HILFE.get(schluessel)
