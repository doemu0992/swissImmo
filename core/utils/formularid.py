"""IDs aus Formular, Querystring und JSON — nie ungeprüft in einen Fremdschlüssel.

WARUM ES DAS GIBT (Audit 28.10.2026, SICH-01)

`Pendenz.objects.create(liegenschaft_id=request.POST['liegenschaft_id'])`
legte eine Zeile in der Verwaltung an, der die Liegenschaft gehört — auch wenn
das eine FREMDE war: `OrganisationAusKette` leitet die Organisation aus der
Kette ab, nicht aus dem Request. Der Registrylauf des Isolationstests sah das
nicht, weil die ID im Body steht und nicht im Pfad.

Die Regel dazu: Eine ID, die der Benutzer mitschickt, wird über den
Mandanten-Manager aufgelöst (`Modell.objects`) und erst das GEFUNDENE Objekt
zugewiesen. Eine Zahl aus dem Formular ist eine Behauptung, kein Besitz.

`Benutzer` hat KEINEN Mandantenfilter (siehe `team_der_organisation` in
`core/views/fw/_basis.py`): Für Personen des Teams gilt dieser Helfer nicht,
dort läuft die Auflösung über die Mitgliedschaft.
"""

#: Grösster Wert, den eine ID in der Datenbank tragen kann (PostgreSQL `bigint`).
#: Alles darüber ist keine ID und führt sonst zu einem Datenbankfehler (500).
_MAX_ID = 2 ** 63 - 1


def ganzzahl(roh):
    """Eine positive ganze Zahl aus Formulartext — oder `None`.

    Nie eine Ausnahme: Leerstring, Buchstaben, Dezimalzahl, Minus, eine 20-stellige
    Zahl und `None` ergeben alle `None`, damit die Ansicht einen Formularfehler
    melden kann statt mit 500 zu antworten.
    """
    if roh is None:
        return None
    text = str(roh).strip()
    if not text.isascii() or not text.isdigit():
        return None
    zahl = int(text)
    if zahl < 1 or zahl > _MAX_ID:
        return None
    return zahl


def eigenes_objekt(modell, roh, **filter_):
    """Das Objekt `modell` mit der ID `roh` aus der EIGENEN Verwaltung, sonst `None`.

    `modell.objects` ist der Mandanten-Manager; ein fremdes oder nicht
    vorhandenes Objekt ist hier dasselbe: `None`. Zusätzliche Bedingungen
    (`liegenschaft=lg`) gehen als Schlüsselwörter durch.
    """
    zahl = ganzzahl(roh)
    if zahl is None:
        return None
    return modell.objects.filter(pk=zahl, **filter_).first()
