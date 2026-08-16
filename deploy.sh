#!/usr/bin/env bash
# Deploy auf PythonAnywhere — selbstheilend.
#
# Holt den aktuellen Stand des Branches HART (fetch + reset --hard, damit stray
# Dateien / lokale Änderungen den Deploy NICHT mehr blockieren), installiert
# Abhängigkeiten, wendet Migrationen an, sammelt statische Dateien und lädt die
# Web-App neu.
#
# Sicher, weil die Produktionsdaten NICHT im Git liegen (db.sqlite3, media/,
# staticfiles/ sind .gitignore) — reset --hard fasst sie nicht an.
#
# Aufruf (einmalig):              bash deploy.sh
# Dauerlauf (Always-on-Task):     bash deploy.sh --dauerlauf
# Anderer Branch:                 bash deploy.sh mein/anderer-branch
# Anderes Intervall:              PA_INTERVALL=60 bash deploy.sh --dauerlauf
# WSGI-Pfad überschreiben:        PA_WSGI=/var/www/DEIN_wsgi.py bash deploy.sh
# Anderer Python (venv):          PA_PY=/home/USER/.virtualenvs/ENV/bin/python bash deploy.sh
set -uo pipefail

cd "$(dirname "$0")"

# --- Dauerlauf ------------------------------------------------------------
# `deploy.sh --dauerlauf` prüft alle 30 s und ruft sich dabei selbst auf.
#
# Warum das hier steht und nicht im Task-Feld des Hosters: Ein
# `while true; do … done` im Task-Feld ist Shell-Code an einem Ort ohne
# Versionierung, ohne Syntaxprüfung und mit genau einer Zeile Platz. Genau
# daran ist es am 16.08.2026 gescheitert — erst inhaltlich, dann startete die
# mehrzeilige Ersatzfassung gar nicht erst. Der Task lautet jetzt schlicht:
#
#     bash /home/swissimmo/swiss-manager/deploy.sh --dauerlauf
#
# Keine Schleife, keine Variablen, keine Anführungszeichen.
INTERVALL="${PA_INTERVALL:-30}"
if [ "${1:-}" = "--dauerlauf" ]; then
    shift
    echo "→ Dauerlauf, Prüfung alle ${INTERVALL} s. Abbruch mit Strg-C."
    while true; do
        bash "$0" "$@" || true      # ein Fehlschlag darf die Schleife nie beenden
        sleep "$INTERVALL"
    done
fi

# `main` ist seit Etappe 4 der Hauptzweig. Bis zum 16.08.2026 stand hier
# `claude/fairwalter-rebuild` — solange beide auf denselben Commit zeigen,
# faellt das nicht auf. Sobald sie auseinanderlaufen, deployt der Server den
# falschen Stand UND meldet dabei Erfolg; das ist die unangenehmere Sorte
# Fehler, weil nichts auf ihn hinweist.
BRANCH="${1:-main}"

# Eine Option, die diese Fassung nicht kennt, landete bisher als Branchname bei
# `git fetch` — und git antwortete mit vierzig Zeilen Hilfetext, an deren Ende
# die eigentliche Meldung unterging. Genau so sah das Always-on-Log am
# 16.08.2026 aus: Der Task rief `--dauerlauf` auf, auf der Platte lag die
# zurueckgerollte Fassung, die das noch nicht kannte.
#
# Ein Branchname beginnt nie mit `--`. Also hier abfangen, mit einer Zeile.
case "$BRANCH" in
    --*)
        echo "✗ Unbekannte Option '$BRANCH'."
        echo "  Diese Fassung kennt: --dauerlauf"
        echo "  Ein Branchname beginnt nicht mit '--'. Liegt hier eine aeltere"
        echo "  Fassung von deploy.sh? Einmal von Hand nachziehen:"
        echo "  PA_PY=\$HOME/.virtualenvs/myenv/bin/python bash deploy.sh"
        exit 1 ;;
esac

# --- Python finden --------------------------------------------------------
# WAS HIER GEPRUEFT WIRD, UND WARUM NICHT WENIGER
#
# Die erste Fassung fragte nur `import django`. Das reichte nicht: Auf der
# Produktion liegt Django AUCH systemweit (Python 3.13), das Projekt braucht
# aber das virtualenv (3.10) mit allen Abhaengigkeiten. Der System-Python
# bestand die Pruefung, und der Deploy scheiterte erst Sekunden spaeter mit
#
#     ModuleNotFoundError: No module named 'unfold'
#
# `django.setup()` ist der ehrliche Test: Es laedt JEDE App aus
# INSTALLED_APPS. Was das ueberlebt, kann auch `manage.py migrate`. Kein
# hartkodierter Paketname noetig — die Liste steht in den Settings.
#
# REIHENFOLGE: virtualenv VOR System-Python. Auf einem Hoster ist das venv
# fast immer das Richtige; der System-Python ist der Zufallsfund.
projekt_python() {
    DJANGO_SETTINGS_MODULE=swiss_immo.settings \
        "$1" -c "import django; django.setup()" >/dev/null 2>&1
}

finde_python() {
    local kandidat
    for kandidat in "${PA_PY:-}" "$HOME"/.virtualenvs/*/bin/python python python3; do
        [ -n "$kandidat" ] || continue
        command -v "$kandidat" >/dev/null 2>&1 || continue
        if projekt_python "$kandidat"; then
            echo "$kandidat"; return 0
        fi
    done
    return 1
}

# Ein ausdrücklich gesetztes PA_PY, das nicht trägt, wird NICHT stillschweigend
# übergangen. Der Ersatz mag funktionieren — aber wer den Wert gesetzt hat,
# meinte ihn, und ein leiser Wechsel des Interpreters ist genau die Art
# Abweichung, die man erst drei Fehlersuchen später bemerkt.
if [ -n "${PA_PY:-}" ] && ! projekt_python "${PA_PY}"; then
    echo "⚠ PA_PY='${PA_PY}' kann das Projekt nicht laden — suche Ersatz."
fi
if ! PY="$(finde_python)"; then
    echo "✗ Kein Python gefunden, das Django importieren kann."
    echo "  Gesucht: \$PA_PY, python, python3, \$HOME/.virtualenvs/*/bin/python"
    echo "  Setze PA_PY auf den Python des virtualenv, z.B.:"
    echo "  PA_PY=\$HOME/.virtualenvs/myenv/bin/python bash deploy.sh"
    exit 1
fi
[ "${PA_PY:-}" = "$PY" ] || echo "· Python: $PY"

# ---------------------------------------------------------------------------
# REMOTE AUF HTTPS ZWINGEN
#
# Zwei Gruende, historisch beide eingetreten:
#
# 1. Repo-Umzug — die alte URL zeigt ins Leere.
# 2. SSH ohne Schluessel. Genau daran ist der Deploy am 12.08.2026 um 14:43
#    gestorben und hat es danach nicht ein einziges Mal mehr geschafft:
#
#      git@github.com: Permission denied (publickey).
#      fatal: Could not read from remote repository.
#
#    Der Always-on-Task lief weiter, holte aber nichts mehr. Weil `git fetch`
#    der erste Befehl seiner &&-Kette war, blieb der Rest stumm — kein
#    `migrate`, keine Meldung ausser dieser einen Zeile im Log.
#
# Das Repository ist oeffentlich, HTTPS braucht also keinerlei Anmeldung.
# Deshalb wird die URL hier hart darauf gesetzt, statt auf einen Schluessel zu
# hoffen, den im Zweifel niemand erneuert.
# ---------------------------------------------------------------------------
CANONICAL="https://github.com/doemu0992/swissImmo.git"
CUR_URL="$(git remote get-url origin 2>/dev/null || echo '')"
case "$CUR_URL" in
    *doemu0992/swissimmo*|*doemu0992/swissImmo*)
        if [ "$CUR_URL" != "$CANONICAL" ]; then
            case "$CUR_URL" in
                git@*|ssh://*) echo "→ Remote ist SSH ($CUR_URL) — auf HTTPS umstellen." ;;
                *)             echo "→ Remote auf die kanonische URL setzen." ;;
            esac
            git remote set-url origin "$CANONICAL" || true
            echo "  jetzt: $CANONICAL"
        fi ;;
esac

echo "→ git fetch origin $BRANCH"
if ! git fetch origin "$BRANCH"; then
    echo "✗ git fetch fehlgeschlagen — Abbruch (alte Version bleibt aktiv)."; exit 1
fi

# Stand VOR dem Umschalten merken. Er wird gebraucht, wenn die Migration
# scheitert — siehe `zurueckrollen` unten.
#
# `DEPLOY_VORHER` wird gesetzt, wenn sich dieses Skript weiter unten selbst neu
# startet. Ohne das waere der gemerkte Stand nach dem Neustart der NEUE Commit,
# und `zurueckrollen` wuerde auf genau den zurueckrollen, der gerade scheitert —
# also auf nichts.
VORHER_COMMIT="${DEPLOY_VORHER:-$(git rev-parse HEAD)}"

# Fassung dieses Skripts VOR dem Umschalten. Siehe Selbstneustart unten.
SKRIPT_VORHER="$(git rev-parse 'HEAD:deploy.sh' 2>/dev/null || echo '')"

# ---------------------------------------------------------------------------
# ZWEI GRUENDE, ETWAS ZU TUN — NICHT NUR EINER
#
# Der Always-on-Task fragte bis zum 16.08.2026 nur: „gibt es einen neuen
# Commit?" Damit war eine Datenbank, die aus IRGENDEINEM Grund hinter dem Code
# zurueckliegt, fuer immer verloren: Kein neuer Commit heisst kein Deploy,
# heisst kein `migrate`. Genau so blieb die Produktion mit neuem Code auf
# altem Schema stehen und meldete `no such table: crm_mitgliedschaft`.
#
# Deshalb sind es hier ZWEI Bedingungen. Offene Migrationen loesen einen Lauf
# auch dann aus, wenn sich am Code nichts geaendert hat — der Deploy holt die
# Datenbank von selbst wieder ein.
#
# Und nur wenn eine davon zutrifft, wird die Web-App am Ende neu geladen.
# Sonst wuerde ein Task, der alle 30 s laeuft, die Anwendung alle 30 s
# durchstarten.
# ---------------------------------------------------------------------------
NEUER_CODE=0
[ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ] && NEUER_CODE=1
# Nach einem Selbstneustart steht der Checkout bereits auf dem neuen Stand —
# der Vergleich oben meldet dann „nichts Neues", obwohl `pip install` und alles
# Weitere noch aussteht. Der Neustart zaehlt deshalb selbst als neuer Code.
[ "${DEPLOY_NEUSTART:-0}" = "1" ] && NEUER_CODE=1

# Zaehlt die noch nicht angewendeten Migrationen. Wichtig ist der Fehlerfall:
# Laesst sich das gar nicht feststellen, wird das NICHT als „null offene"
# gewertet, sondern als Grund, den Deploy laufen zu lassen. Ein Zaehler, der
# bei einem Fehler still 0 meldet, haette dieselbe Bauart wie der Bug, den er
# verhindern soll — er wuerde schweigen, wenn es darauf ankommt.
#
# (Geprueft: `showmigrations --plan` laeuft auch auf einer Datenbank, die noch
# vor der Benutzer-Uebernahme steht — anders als `migrate`, das dort mit
# InconsistentMigrationHistory abbricht. Der Zaehler meldet dort korrekt 8.)
offene_migrationen() {
    local ausgabe
    if ! ausgabe="$("$PY" manage.py showmigrations --plan 2>/dev/null)"; then
        echo "unbekannt"; return
    fi
    printf '%s\n' "$ausgabe" | grep -c '^\[ \]' || true
}
OFFEN="$(offene_migrationen)"

if [ "$OFFEN" = "unbekannt" ]; then
    echo "⚠ Migrationsstand nicht feststellbar — Deploy laeuft trotzdem."
    OFFEN=1
fi

if [ "$NEUER_CODE" = "0" ] && [ "${OFFEN:-0}" -eq 0 ]; then
    echo "· nichts zu tun (Code aktuell, keine offenen Migrationen)"
    exit 0
fi
[ "${OFFEN:-0}" -gt 0 ] && echo "→ ${OFFEN} offene Migration(en) — Lauf auch ohne neuen Commit"

if [ "$NEUER_CODE" = "1" ]; then
    echo "→ git reset --hard origin/$BRANCH"
    git reset --hard "origin/$BRANCH" || { echo "✗ reset fehlgeschlagen."; exit 1; }
fi

# ---------------------------------------------------------------------------
# WENN SICH DIESES SKRIPT SELBST GEAENDERT HAT: LAUF MIT DER NEUEN FASSUNG
# WIEDERHOLEN
#
# Alles oberhalb — vor allem die Python-Suche — lief noch mit der ALTEN Fassung,
# die zu diesem Zeitpunkt auf der Platte lag. Eine Verbesserung an genau diesen
# Zeilen wirkt also erst beim naechsten Lauf. Zusammen mit `zurueckrollen`
# (setzt den Checkout zurueck, frueher samt deploy.sh) ergab das eine Schleife,
# aus der sich der Deploy nicht selbst befreien konnte:
#
#   alte Python-Pruefung  →  System-Python besteht sie  →  pip baut pycairo fuer
#   den falschen Interpreter  →  `No module named 'unfold'`  →  Rollback auf die
#   alte Fassung  →  von vorne.
#
# Real eingetreten am 16.08.2026, ueber mehrere Laeufe hinweg unveraendert.
#
# `DEPLOY_NEUSTART` verhindert eine Endlosschleife: Der neu gestartete Lauf
# vergleicht nicht noch einmal.
# ---------------------------------------------------------------------------
if [ "${DEPLOY_NEUSTART:-0}" = "0" ]; then
    SKRIPT_JETZT="$(git rev-parse 'HEAD:deploy.sh' 2>/dev/null || echo '')"
    if [ -n "$SKRIPT_VORHER" ] && [ -n "$SKRIPT_JETZT" ] \
       && [ "$SKRIPT_VORHER" != "$SKRIPT_JETZT" ]; then
        echo "→ deploy.sh hat sich geaendert — Lauf mit der neuen Fassung wiederholen."
        DEPLOY_NEUSTART=1 DEPLOY_VORHER="$VORHER_COMMIT" exec bash "$0" "$BRANCH"
    fi
fi

DEPLOY_COMMIT="$(git rev-parse --short HEAD)"
echo "  jetzt auf Commit $DEPLOY_COMMIT"

# ---------------------------------------------------------------------------
# WARUM DER CODE ZURUECKGEROLLT WIRD, WENN DIE MIGRATION SCHEITERT
#
# Die frühere Fassung sagte: „bei gescheiterter Migration wird NICHT neu
# geladen — die alte Version bleibt aktiv." Das stimmte nur für den laufenden
# Prozess. Auf der Platte lag nach `git reset --hard` bereits der NEUE Code.
# Sobald der Hoster seinen Worker recycelt — und das tut er von sich aus —
# lädt er den neuen Code gegen das ALTE Schema.
#
# Real passiert am 16.08.2026: `no such table: crm_mitgliedschaft` auf der
# Startseite, obwohl kein Reload angestossen wurde.
#
# Deshalb: Scheitert ein Schritt, der die Datenbank braucht, geht der Code auf
# den vorherigen Stand zurück. Damit passen Platte und Datenbank wieder
# zusammen, und die Zusicherung stimmt auch über einen Worker-Neustart hinweg.
# ---------------------------------------------------------------------------
zurueckrollen() {
    echo "✗ $1"
    echo "→ Code zurück auf $(git rev-parse --short "$VORHER_COMMIT") — sonst laedt der"
    echo "  naechste Worker-Neustart neuen Code gegen ein altes Schema."
    git reset --hard "$VORHER_COMMIT" || echo "⚠ Rueckrollen fehlgeschlagen — VON HAND pruefen!"

    # DIESES SKRIPT IST VOM ROLLBACK AUSGENOMMEN.
    #
    # Der Rollback existiert, damit Code und Datenbankschema zusammenpassen.
    # deploy.sh liest kein Schema — es hat in diesem Vergleich nichts verloren.
    # Es mitzurollen hatte am 16.08.2026 zwei Folgen, beide beobachtet:
    #
    #   · Eine Korrektur am Deploy wurde von ihrem eigenen Fehlschlag wieder
    #     entfernt. Der naechste Lauf machte denselben Fehler.
    #   · Die zurueckgerollte Fassung kannte `--dauerlauf` noch nicht und hielt
    #     es fuer einen Branchnamen. Der Always-on-Task fetchte `origin
    #     --dauerlauf`, scheiterte sofort und sah aus, als starte er nicht.
    #
    # Der Arbeitsbaum ist danach absichtlich „schmutzig". Das stoert nicht: Der
    # naechste Lauf sieht HEAD != origin, macht `reset --hard` und ueberschreibt
    # die Datei ohnehin mit demselben Inhalt.
    if git checkout "origin/$BRANCH" -- deploy.sh 2>/dev/null; then
        echo "· deploy.sh bleibt auf der neuen Fassung (vom Rollback ausgenommen)."
    fi
    exit 1
}

if [ "$NEUER_CODE" = "1" ]; then
    echo "→ pip install -r requirements.txt"
    "$PY" -m pip install -q -r requirements.txt || echo "⚠ pip install meldete Fehler — fahre fort."

    # „fahre fort" gilt fuer eine einzelne unwichtige Abhaengigkeit, nicht fuer
    # einen kaputten Interpreter. Ohne diese Zeile marschierte der Deploy weiter
    # und meldete den Schaden erst zwei Schritte spaeter als rohen
    # `ModuleNotFoundError: No module named 'unfold'` — eine Fehlermeldung, die
    # in die falsche Richtung zeigt. Die echte Ursache war der falsche Python.
    if ! projekt_python "$PY"; then
        zurueckrollen "'$PY' kann das Projekt nach dem Update nicht mehr laden — fehlende Abhaengigkeit."
    fi
fi

# Bevor irgendetwas geschrieben wird: Ist das ueberhaupt die richtige Datenbank?
#
# Auf PythonAnywhere hat jeder Prozess eigene Umgebungsvariablen — Web-App,
# Always-on-Task und Konsole. Setzt jemand DB_ENGINE=postgres nur im Web-Tab,
# laeuft die Website auf PostgreSQL, waehrend DIESER Task weiter die
# SQLite-Datei migriert. Beide Seiten funktionieren fuer sich, der Deploy meldet
# Erfolg — und die Website sieht die Migration nie. Ein Fehler, der erst beim
# Kunden auffaellt.
#
# `.datenbank-erwartet` liegt im Repo und kommt mit dem Code mit, ist also fuer
# alle drei Prozesse dieselbe Angabe. Fehlt die Datei, prueft der Befehl nichts
# und meldet Erfolg — bestehende Installationen bleiben unberuehrt.
echo "→ manage.py datenbank_pruefen"
if ! "$PY" manage.py datenbank_pruefen; then
    zurueckrollen "Falsche Datenbank — KEIN migrate, KEIN Reload."
fi

# Seit Etappe 3 hat swissImmo ein eigenes Benutzermodell (benutzer.Benutzer),
# das die bestehende Tabelle auth_user übernimmt. Auf einer Bestandsdatenbank
# bricht `migrate` sonst ab, BEVOR eine Migration läuft:
#   InconsistentMigrationHistory: admin.0001_initial is applied before its
#   dependency benutzer.0001_initial
# Keine Migration kann das lösen — Djangos Konsistenzprüfung greift davor.
# Der Command ist idempotent: Er tut genau einmal etwas und ist danach (und auf
# jeder frischen Datenbank) ein Leerlauf.
#
# Scheitert die Übernahme, ist die Datenbank unberührt und `zurueckrollen`
# stellt den alten Code wieder her.
echo "→ manage.py benutzer_uebernahme"
if ! "$PY" manage.py benutzer_uebernahme; then
    zurueckrollen "Benutzer-Übernahme fehlgeschlagen — KEIN Reload."
fi

echo "→ manage.py migrate"
if ! "$PY" manage.py migrate --noinput; then
    zurueckrollen "migrate fehlgeschlagen — KEIN Reload."
fi

# Absicherung gegen den Fall, der am 16.08.2026 die Startseite lahmlegte: Der
# Deploy meldete Erfolg, aber `migrate` war gar nicht gelaufen (falscher
# Python, kein Django im Pfad). `showmigrations --plan` listet dann offene
# Schritte. Ein Deploy, der ausstehende Migrationen zurücklaesst, darf nicht
# neu laden.
NACHHER="$(offene_migrationen)"
if [ "${NACHHER:-0}" -gt 0 ]; then
    zurueckrollen "$NACHHER Migration(en) nicht angewendet, obwohl migrate durchlief."
fi

echo "→ manage.py collectstatic"
"$PY" manage.py collectstatic --noinput || echo "⚠ collectstatic meldete Fehler — fahre fort."

# Web-App neu laden = WSGI-Datei „berühren".
WSGI="${PA_WSGI:-/var/www/${USER}_pythonanywhere_com_wsgi.py}"
if [ -f "$WSGI" ]; then
    touch "$WSGI"
    echo "→ Web-App neu geladen ($WSGI) — Commit $DEPLOY_COMMIT ist live."
else
    echo "⚠ WSGI-Datei nicht gefunden ($WSGI)."
    echo "  PA_WSGI mit dem korrekten Pfad setzen — sonst läuft weiter die alte Version."
    exit 1
fi

# Der Zugriffsschutz für /media/ greift nur, wenn die Anfragen bei Django
# ankommen. Ist /media/ beim Hoster als statisches Verzeichnis gemappt, liefert
# der Webserver die Dateien direkt aus — sensible Uploads wären dann für jeden
# mit der URL abrufbar, ohne dass es irgendwo auffällt. Deshalb nach dem Reload
# ein Test von aussen. Schlägt er an, steht der Befund im Deploy-Protokoll.
# Webhook-Secrets: Die Endpunkte weisen ohne Secret ab (fail-closed). Wer eine
# Integration bisher ohne Secret betrieben hat, verliert sonst lautlos den
# Rücklauf — bei DocuSeal die Ablage unterschriebener Verträge.
# Djangos eigene Produktionspruefung. Sie meldet unter anderem ein
# eingeschaltetes DEBUG — am 15.08.2026 zeigte die Produktion eine vollstaendige
# Fehlerseite mit Traceback, Dateipfaden und Python-Pfad, also stand die
# Umgebungsvariable auf True. Auf einem oeffentlich erreichbaren System mit
# Mieterdaten, Betreibungsauszuegen und Lohnausweisen ist das ein eigenes
# Problem, unabhaengig vom damaligen Ausfall.
#
# Der Befund steht im Protokoll und bricht den Deploy NICHT ab: Er meldet auch
# Dinge, die bewusst so sind, und ein Deploy, der an einer Empfehlung scheitert,
# wird beim naechsten Mal umgangen.
echo "→ manage.py check --deploy"
"$PY" manage.py check --deploy || echo "⚠ check --deploy meldete Befunde (siehe oben)."

echo "→ manage.py pruefe_webhook_secrets"
"$PY" manage.py pruefe_webhook_secrets || true

echo "→ manage.py pruefe_media_schutz"
"$PY" manage.py pruefe_media_schutz || echo "⚠ Media-Schutz-Prüfung meldete einen Befund (siehe oben)."

echo "✓ Deploy fertig — prüfen auf https://swissimmo.pythonanywhere.com/version/"
