# core/views/fw — die Oberfläche unter /neu/.
#
# Bis Etappe 1 war das EINE Datei mit 14'983 Zeilen und 232 Views. Sie wird
# entlang der Blockkommentare, die schon drinstehen, in 33 Module zerlegt
# (Auftrag: docs/ETAPPE-1-ZERLEGEN.md). Dieses `__init__.py` hält die
# Fassade stabil: `swiss_immo/urls.py` und die Tests importieren weiter aus
# `core.views.fw`, ganz gleich, in welchem Modul eine View gerade liegt.
# Deshalb bleiben alle 293 benannten URLs während der gesamten Zerlegung
# unverändert — jeder Block ist für sich zurückrollbar.
#
# Etappe 1 ist abgeschlossen: Es gibt keine Restdatei mehr. Die 232 Views
# liegen in Fachmodulen, die blockübergreifenden Helfer in `_basis.py`.
# Was hier steht, ist nur noch die Fassade. Nachtrag (Roadmap 6.6, 11.11.2026):
# Die vier grössten Dateien (`detailseiten.py`, `listen.py`, `aktionen.py`,
# `kuendigung.py`) sind in 26 Module unter Namen wie `vertrag_detail`,
# `debitoren_liste`, `zahlungen_aktionen`, `verzug_257d` zerlegt; Zuordnung in
# docs/ETAPPE-1-ZERLEGEN.md («Nachtrag»).

# Herausgeloeste Bloecke, alphabetisch. Die Blocknummern aus dem
# Arbeitsauftrag stehen hier bewusst NICHT: Sie zaehlen die Kommentarbanner
# in _rest.py durch und verschieben sich deshalb bei jedem Umzug — nach elf
# Bloecken trug die Liste bereits dreimal "Block 11" fuer drei verschiedene
# Module. Eine Nummer, die sich unter der Hand aendert, ist schlechter als
# gar keine; der Modulname sagt ohnehin mehr.
from .abnahme import *                 # noqa: F401,F403
from .anlagen import *                 # noqa: F401,F403
# `assets` ist in 4b.20 aufgegangen: Die Seite listete Geraete und Raumbuch
# nur auf, ihre CRUD-Pfade waren eine zweite Fassung von `/neu/geraet/*`.
# Gerechnet wird beides jetzt in `/neu/ersatzplanung/`.
from .bankkonten import *              # noqa: F401,F403
from .benutzer import *                # noqa: F401,F403
from .debitor_qr import *              # noqa: F401,F403
from .dashboard import *               # noqa: F401,F403
# Phase 4b: Arbeit, Fallakte, Laeufe, Zulauf — die ersten Oberflaechen
# fuer die Bausteine aus Phase 4a.
from .arbeit import *                  # noqa: F401,F403
from .dienstleister import *           # noqa: F401,F403
from .dokumente import *               # noqa: F401,F403
from .eigentuemer import *             # noqa: F401,F403
from .eigentuemer_abrechnung import *  # noqa: F401,F403
from .hypotheken import *              # noqa: F401,F403
from .kommunikation import *           # noqa: F401,F403
from .mahnwesen import *               # noqa: F401,F403
from .mahnstufen import *              # noqa: F401,F403
from .mwst import *                    # noqa: F401,F403
from .nebenkosten import *             # noqa: F401,F403
from .pendenzen import *               # noqa: F401,F403
# Phase 4b.12: Mandats- und Dienstleisterakte — die beiden Aktentypen aus
# dem Register, die ueberhaupt keine Detailseite hatten.
from .akten_neu import *                # noqa: F401,F403
# Phase 4b.10: der Fristenwaechter. Die Rechenlogik lag seit Phase 4a in
# faelle/regelwerk.py und hatte keinen Aufrufer.
from .regelwerk import *               # noqa: F401,F403
from .sollstellung import *            # noqa: F401,F403



from .liegenschaft_crud import * # noqa: F401,F403 — Block 10
from .kautionen import *     # noqa: F401,F403 — Block 11
from .dokument_zustellung import *  # noqa: F401,F403
from .kuendigung_bestaetigung import *  # noqa: F401,F403
from .kuendigung_erfassen import *  # noqa: F401,F403
from .mietverfahren import *  # noqa: F401,F403
from .verzug_257d import *  # noqa: F401,F403
from .zahlungsvereinbarung import *  # noqa: F401,F403
from .mietprozess import *   # noqa: F401,F403 — Block 10
from .schaeden import *      # noqa: F401,F403 — Block 5
from .tickets_board import *  # noqa: F401,F403 — Ticket-Board (Kanban)
from .kalender import *       # noqa: F401,F403 — Monatskalender
from .portfolio_seite import *  # noqa: F401,F403 — Portfolio (Eigentümer)
from .leerstand_team import *   # noqa: F401,F403 — Leerstands-Cockpit, Team & Auslastung (UI-Audit)
from .zahlungsklaerung import (  # noqa: F401 — Zahlungs-Cockpit V12
    fw_zahlung_aufteilen, fw_zahlung_kaution, fw_zahlung_notiz, fw_guthaben_verwendung,
    fw_verrechnung_rueckgaengig, fw_guthaben_wiederherstellen, fw_zuordnung_aufheben)
from .phase2_formulare import *      # noqa: F401,F403 — Phase 2 (Audit)
from .verteilschluessel import *      # noqa: F401,F403 — Verteilschlüssel der Liegenschaft
from .nk_wizard import *              # noqa: F401,F403 — Nebenkosten-Wizard (Modul 1)
from .staffel_mitteilung import *      # noqa: F401,F403 — Staffelmiete: Mitteilung der Erhöhung (Art. 269d Abs. 5 OR)
from .anfangsformular import *          # noqa: F401,F403 — Nachweis zum Anfangsmietzins-Formular (Art. 270 Abs. 2 OR)
from .mahngebuehr import *             # noqa: F401,F403 — Mahngebühren im Vertrag vereinbart (Art. 106 OR)
from .daten import (  # noqa: F401 — Einstellungen «Daten»: Import für Wechselkunden, Mandats- und Buchungsexport
    fw_daten, fw_daten_import, fw_daten_import_vorlage, fw_daten_import_lauf, fw_daten_import_ausfuehren,
    fw_daten_import_verwerfen, fw_daten_export, fw_daten_export_format, fw_daten_export_journal,
    fw_daten_export_mandat)
from .api_zugang import *    # noqa: F401,F403 — Einstellungen «API-Zugang»: Schlüssel für die lesende Finanz-API
from .ablesung import *      # noqa: F401,F403 — Ablese-Aufruf an die Mieterschaft
from .anfragen import *      # noqa: F401,F403 — Anfragen aus den Portalen (Mieter, Eigentümer)
from .buchhaltung import *   # noqa: F401,F403 — Block 5
from .mietzins import *      # noqa: F401,F403 — Block 5
from .kreditoren import *    # noqa: F401,F403 — Block 4
from .bankabgleich import *  # noqa: F401,F403 — Block 2
from .vertragserstellung import * # noqa: F401,F403 — Block 3
from .person import *        # noqa: F401,F403 — Block 2
from .profil import *        # noqa: F401,F403 — Block 2
from .berichte import *  # noqa: F401,F403
from .debitoren_aktionen import *  # noqa: F401,F403
from .debitoren_liste import *  # noqa: F401,F403
from .liegenschaften_liste import *  # noqa: F401,F403
from .objekte_liste import *  # noqa: F401,F403
from .personen_liste import *  # noqa: F401,F403
from .vertraege_liste import *  # noqa: F401,F403
from .buchungen_aktionen import *  # noqa: F401,F403
from .einstellungen_aktionen import *  # noqa: F401,F403
from .kommunikation_aktionen import *  # noqa: F401,F403
from .kreditoren_aktionen import *  # noqa: F401,F403
from .stammdaten_aktionen import *  # noqa: F401,F403
from .zahlungen_aktionen import *  # noqa: F401,F403
from .liegenschaft_detail import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
from .objekt_detail import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
from .ausstattung import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
from .objekt_geraete import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
from .sollmietzins import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
from .vertrag_detail import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
from .schlussabrechnung import *  # noqa: F401,F403 — Detailseiten (ex detailseiten.py)
# Der Stern-Import überträgt KEINE Namen mit führendem Unterstrich. Diese
# neun werden aber von aussen gebraucht (core/tests.py,
# core/services/abschluss_pdf.py) und müssen deshalb einzeln stehen.
#
# Sie sind ausdrücklich NICHT alle aus `._rest` geholt, obwohl das technisch
# noch ginge: Ein Name, der über zwei Module weitergereicht wird, verdeckt,
# wo er wirklich steht. Jede Zeile zeigt hier auf den echten Fundort und
# wandert mit, wenn der Block wandert. `AlleNeunNamenErreichbarTests` in
# core/tests.py hält fest, dass keiner unterwegs verlorengeht.
from ._basis import (                                  # noqa: F401
    _num,
    _pendenz_ziel,
)
from .bankabgleich import (                            # noqa: F401
    _bank_csv_parse,
    _camt_kopf,
    _camt_parse,
)
from .buchhaltung import _erfolg_bilanz                   # noqa: F401
from .vertrag_detail import _formulare_prozesse            # noqa: F401
from .kuendigung_erfassen import _auszugscheckliste_anlegen  # noqa: F401
from .mietprozess import _bewerber_mail                   # noqa: F401
