# Go-Live-Härtetest (30.09.2026)

Vier Schritte, je mit Test im Bestand.

| Schritt | Befund | Massnahme | Test |
|---|---|---|---|
| 1 Lebenszyklus | Kein Bruch zwischen Liegenschaft, Finanzen, Ticket | – | `test_golive_lebenszyklus` |
| 2 Löschlogik | Mieter/Vertrag/Einheit/Liegenschaft mit offenen Rechnungen löschbar (Forderung ohne Schuldner); gekündigter Vertrag sperrte nicht; Fälle blieben ohne Akte | `core/loeschschutz.py`, `delete()`-Sperren, Signal in `core/signals.py` | `test_golive_loeschen` |
| 3 Performance | `hat_rolle()` je Tabellenzeile: `/neu/mahnwesen/` 2016 Queries bei 1000 Verträgen | Zwischenspeicher je Benutzer+Organisation (`core/auth.py`), Invalidierung per Signal | `test_golive_performance` |
| 4 Fuzzing | 8 Routen mit 500 bei unlesbaren Ids/Beträgen | `core/middleware_eingabe.py` (400 statt 500) | `test_golive_fuzz` |

## Bewusst nicht getan
- Keine Soft-Deletes: Liegenschaft/Mieter werden weiter hart gelöscht (Kaskade). Bezahlte Belege bleiben (SET_NULL, Art. 958f OR), verlieren aber ihre Verknüpfung.
- `/neu/` (≈66 Queries bei 50×20) nicht weiter zerlegt; wächst nicht mehr mit den Zeilen, aber nicht einzeln geprüft.
- Kein Lasttest auf PostgreSQL; alle Messungen auf SQLite.
- Die Middleware ist ein Sicherheitsnetz; die einzelnen Views validieren weiterhin selbst nicht.
