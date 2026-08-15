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
# `_rest.py` ist der noch nicht aufgeteilte Rest der Originaldatei. Er
# schrumpft mit jedem Block und verschwindet am Ende ganz; dann fällt auch
# der Stern-Import hier weg.

# Der noch nicht aufgeteilte Rest zuerst — die herausgeloesten Bloecke
# danach. Die Reihenfolge ist kein Zufall: Bei einem Stern-Import gewinnt der
# LETZTE. Bliebe beim Verschieben versehentlich eine alte Fassung in
# _rest.py stehen, ueberschreibt sie so das bereits herausgeloeste Modul
# nicht, sondern wird von ihm ueberschrieben.
from ._rest import *                   # noqa: F401,F403

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
from .sollstellung import *            # noqa: F401,F403



# Der Stern-Import überträgt KEINE Namen mit führendem Unterstrich. Diese
# neun werden aber von aussen gebraucht (core/tests.py, core/services/) und
# müssen deshalb einzeln stehen. Die Liste ist Absicht und kein Versehen:
# Sie ist zugleich das Verzeichnis der Helfer, die über die Modulgrenze
# hinaus benutzt werden — wer einen entfernt, sieht sofort, wen es trifft.
from ._rest import (          # noqa: F401
    _auszugscheckliste_anlegen,
    _bank_csv_parse,
    _bewerber_mail,
    _camt_kopf,
    _camt_parse,
    _erfolg_bilanz,
    _formulare_prozesse,
    _num,
    _pendenz_ziel,
)
