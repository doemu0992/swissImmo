# Schlüssel für verschlüsselte Werte (`GEHEIMNIS_SCHLUESSEL`)

Stand 07.11.2026. Früher hiess die Variable `IMAP_SCHLUESSEL` (der alte Name gilt weiter).

## Was er schützt

Ein Fernet-Schlüssel (AES-128-CBC mit HMAC-Prüfung, aus der Bibliothek `cryptography`) verschlüsselt Werte, die sonst im
Klartext in jedem `pg_dump` und jeder Sicherung stünden:

| Wert | Wo |
|---|---|
| AHV-Nummern der Mieter | `crm.Mieter.ahv_nummer` |
| Zugangsdaten der eigenen Postfächer («Erweitert») | `core.Postfach.passwort_geheim`, `refresh_token_geheim` |

Schutz gegen einen **abhandengekommenen Datenbankauszug** (kopierte Sicherung, falscher Datenträger). Kein Schutz gegen
jemanden, der auf dem Server ist: Dort liegt der Schlüssel neben der Anwendung.

## Es braucht kein Terminal

* **Der Schlüssel entsteht von selbst.** Ist weder in der `.env` noch als Datei einer gesetzt, legt die Anwendung beim ersten
  Bedarf (spätestens beim ersten `migrate`/Start) die Datei `.geheimnis_schluessel` neben `.secret_key` an: nur für den
  Betriebsbenutzer lesbar (`600`), nicht in Git (`.gitignore`), nicht in der Datenbank, nicht in `sicherung`. Starten zwei
  Prozesse gleichzeitig, gewinnt genau einer (`O_EXCL`); ist die Datei nicht anlegbar, bleibt es bei einer klaren Meldung.
* **Der Altbestand wird nach jedem `migrate` von selbst verschlüsselt** (`post_migrate`): AHV-Nummern im Klartext, ohne
  `ahv_verschluesseln` von Hand. Fehler dabei stören das Deploy nie, sie stehen im Log.
* **Betreiber-Portal → Sicherheit** (`/betreiber/sicherheit/`; nur Betreiber/Superuser, weil der Schlüssel die ganze Installation betrifft): Zustand,
  «Jetzt alles verschlüsseln», «Schlüssel erneuern» (neuer Schlüssel, alles umstellen, alter weg, in einem Klick) und
  «Kopie des Schlüssels herunterladen» für den Passwortmanager (protokolliert). Abschaltbar: `GEHEIMNIS_AUTOSCHLUESSEL=False`.

Grenze: Ein Schlüssel auf demselben Server schützt vor einem **abhandengekommenen Datenbankauszug**, nicht vor jemandem auf
dem Server. Geht der Server samt Schlüsseldatei verloren, sind AHV-Nummern und Postfach-Zugangsdaten unlesbar — deshalb die
Kopie.

## Wo der Schlüssel sonst liegen kann (bewusste Vorgabe)

1. **`GEHEIMNIS_SCHLUESSEL=…`** in der `.env` oder als Einstellung — hat Vorrang vor der selbst angelegten Datei.
2. **`GEHEIMNIS_SCHLUESSEL_DATEI=/pfad`**: eigene Datei ausserhalb von `.env` und Webroot (`chmod 600`); passt zu
   Docker-Secrets und systemd-Credentials.

## Schlüsselwechsel ohne Verlust (nur für Schlüssel aus `.env`/Datei; der selbst angelegte wird per Knopf erneuert)

Es dürfen **mehrere** Schlüssel stehen, durch Komma getrennt: Der **erste** verschlüsselt, **alle** entschlüsseln.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # 1. neuer Schlüssel
# 2. .env:  GEHEIMNIS_SCHLUESSEL=<NEU>,<ALT>   → Web-App neu laden
python manage.py schluessel_wechseln               # 3. prüfen: was ist womit lesbar?
python manage.py schluessel_wechseln --ausfuehren  #    umschreiben (eine Transaktion, bricht nichts halb ab)
# 4. .env:  GEHEIMNIS_SCHLUESSEL=<NEU>             → Web-App neu laden
```

Sicherungen, die vor Schritt 3 entstanden sind, brauchen `<ALT>` zum Zurückspielen. Wer das nicht will, bewahrt den alten
Schlüssel so lange auf, wie die älteste Sicherung gilt (`docs/SICHERUNG.md`: bis zu 10 Jahre).

Neue verschlüsselte Spalten gehören in `GEHEIME_FELDER` in `core/management/commands/schluessel_wechseln.py`; sonst
überleben sie keinen Wechsel.

## Warum nicht mehr (Abwägung)

* **Aus dem `SECRET_KEY` ableiten:** nein. Der `SECRET_KEY` wird bei Verdacht gewechselt und soll nur Anmeldungen kosten.
* **Schlüsselverwaltung eines Cloud-Anbieters (KMS, Vault):** die moderne Lösung, wenn die Anwendung dort läuft: Pro Wert ein
  Datenschlüssel, der vom KMS-Schlüssel umhüllt wird; der Hauptschlüssel verlässt den Dienst nie, jeder Zugriff ist
  protokolliert. Ohne eigene Cloud-Identität (Rolle der Maschine) braucht die Anwendung aber wieder ein Zugangsgeheimnis zum
  KMS, das auf dem Server liegt — man verschöbe das Problem. Lohnt sich, sobald das Hosting auf eine Plattform mit
  Maschinenidentität wechselt. Die Stelle dafür ist `core/services/geheimnis.py::_fernet()`.
* **Datenvermeidung:** Die AHV-Nummer wird nur gespeichert und angezeigt (Personenakte), nicht gesucht oder verglichen. Wer
  sie nicht braucht, speichert sie nicht: Das Feld lässt sich entfernen, dann entfällt der Schutzbedarf.

## Verlust

Ohne Schlüssel sind AHV-Nummern und Postfach-Zugangsdaten **endgültig** unlesbar (keine Hintertür, das ist der Sinn). Eine
Kopie ausserhalb des Servers gehört zur Sorgfalt wie das Datenbankpasswort (Passwortmanager der Inhaberin).
