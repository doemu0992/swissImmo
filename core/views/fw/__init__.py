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
# liegen in 33 Fachmodulen, die blockübergreifenden Helfer in `_basis.py`.
# Was hier steht, ist nur noch die Fassade.

# Herausgeloeste Bloecke, alphabetisch. Die Blocknummern aus dem
# Arbeitsauftrag stehen hier bewusst NICHT: Sie zaehlen die Kommentarbanner
# in _rest.py durch und verschieben sich deshalb bei jedem Umzug — nach elf
# Bloecken trug die Liste bereits dreimal "Block 11" fuer drei verschiedene
# Module. Eine Nummer, die sich unter der Hand aendert, ist schlechter als
# gar keine; der Modulname sagt ohnehin mehr.
from .abnahme import *                 # noqa: F401,F403
from .anlagen import *                 # noqa: F401,F403
from .assets import *                  # noqa: F401,F403
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
from .kuendigung import *    # noqa: F401,F403 — Block 10
from .mietprozess import *   # noqa: F401,F403 — Block 10
from .schaeden import *      # noqa: F401,F403 — Block 5
from .buchhaltung import *   # noqa: F401,F403 — Block 5
from .mietzins import *      # noqa: F401,F403 — Block 5
from .kreditoren import *    # noqa: F401,F403 — Block 4
from .bankabgleich import *  # noqa: F401,F403 — Block 2
from .vertragserstellung import * # noqa: F401,F403 — Block 3
from .person import *        # noqa: F401,F403 — Block 2
from .profil import *        # noqa: F401,F403 — Block 2
from .listen import *        # noqa: F401,F403 — Block 0
from .aktionen import *      # noqa: F401,F403 — Block 1
from .detailseiten import *  # noqa: F401,F403 — Block 0
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
from .detailseiten import _formulare_prozesse             # noqa: F401
from .kuendigung import _auszugscheckliste_anlegen        # noqa: F401
from .mietprozess import _bewerber_mail                   # noqa: F401
