/* Aktionen per Datenattribut statt Inline-Handler (Roadmap Nr. 23, Etappe 3; docs/CSP.md).
 *
 * Mit CSP sind `onclick="…"` & Co. gesperrt. Dieser Verteiler hört einmal am Dokument zu und liest, was am
 * Element steht. Er gilt auch für Inhalte, die später in die Seite kommen (Schublade, nachgeladene Teile).
 *
 *   data-umschalten="id"        Klick: Klasse `hidden` an #id umschalten (data-klasse="x" für eine andere)
 *   data-verstecken="id"        Klick: #id ausblenden (Klasse `hidden` setzen)
 *   data-sichtbar-wenn="id"     Änderung an einem Kontrollkästchen: #id sichtbar, wenn angehakt
 *   data-absenden               Änderung: das Formular abschicken (data-absenden="request": mit Prüfung)
 *   data-gehe-zu="/url/"        Klick (z. B. auf eine Tabellenzeile): zur Adresse wechseln
 *   data-gehe-zu-wert="/url/?x=" Änderung an einer Auswahl: zu Adresse + Wert wechseln (leerer Wert: nichts)
 *   data-neues-fenster="/url/" Klick: Adresse in einem neuen Tab öffnen
 *   data-ausser="a,button"       Klick auf solche Kindelemente löst die Aktionen dieses Elements nicht aus
 *   data-stop                   Klick hier löst die Aktionen darüberliegender Elemente (z. B. der Zeile) nicht aus
 *   data-kopieren="id"          Klick: Wert von #id in die Zwischenablage (data-kopiert="Kopiert ✓" als Rückmeldung)
 *   data-auswaehlen             Fokus/Klick: Inhalt des Feldes markieren
 *   data-scrollen="id"          Klick: sanft zu #id scrollen
 *   data-entfernen=".sel"       Klick: das nächste Elternelement `.sel` entfernen
 *   data-bei-klick="funktion"   Klick: globale Funktion aufrufen (data-args='["a","$el"]'; "$el" = das Element selbst;
 *                               gibt sie `false` zurück, wird die Standardaktion – z. B. ein Link – unterdrückt)
 *   data-bei-eingabe="funktion" Eingabe (input): dasselbe für Tastatureingaben
 *   data-bei-aenderung="funktion" Änderung (change): dasselbe für Auswahl/Kontrollkästchen
 *   data-modal="Titel"          Klick auf einen Link: in der Schublade öffnen (data-modal-breit: breit)
 *   (bei-Attribute nehmen mehrere Funktionen, durch Leerzeichen getrennt)
 *   data-bei-absenden="funktion" Absenden: Funktion(Formular) aufrufen; `false` bricht das Absenden ab
 *   data-drucken                Klick: Druckdialog
 *   data-passwort-zeigen="id"   Klick: Feld #id zwischen Passwort und Klartext umschalten
 *   data-schliesse-schublade    Klick: im Rahmen der Schublade diese schliessen, sonst normal weiter
 *   data-zurueck                Klick: eine Seite zurück, wenn es eine vorherige gibt, sonst normal weiter
 *   data-auswahl-sync           Änderung: Klasse `fw-on` an den Beschriftungen der Auswahl (.fw-auswahl) nachführen
 *   data-grund-abfragen="Text"  Absenden: Grund erfragen (`|` = Zeilenumbruch) und ins Feld `grund` schreiben
 *   data-pruefe-gewaehlt=".sel" Absenden nur, wenn `.sel` mindestens einmal passt (data-pruefe-meldung = Hinweis)
 */
(function () {
    'use strict';

    function byId(id) { return id ? document.getElementById(id) : null; }

    // Ein `data-stop`-Element zwischen Ziel und `el` hält die Aktion von `el` auf (wie stopPropagation()).
    function gestoppt(el, ziel) {
        var s = ziel.closest('[data-stop]');
        if (s && s !== el && el.contains(s)) return true;
        var a = el.getAttribute('data-ausser');   // Klick auf diese Kinder löst nichts aus (z. B. Formulare in der Zeile)
        var k = a ? ziel.closest(a) : null;
        return !!k && k !== el && el.contains(k);
    }

    // Ruft die globale Funktion `name` mit den Argumenten aus data-args auf; "$el" steht für das Element.
    function aufrufen(el, namen) {
        var args = [], ergebnis;
        try { args = JSON.parse(el.getAttribute('data-args') || '[]'); } catch (x) { args = []; }
        args = args.map(function (a) { return a === '$el' ? el : a; });
        (namen || '').split(/\s+/).forEach(function (name) {
            var f = name ? window[name] : null;
            if (typeof f !== 'function') return;
            var r = f.apply(el, args);
            if (r === false) ergebnis = false;
        });
        return ergebnis;
    }

    document.addEventListener('click', function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var el;

        if ((el = t.closest('[data-bei-klick]')) && !gestoppt(el, t)) {
            if (aufrufen(el, el.getAttribute('data-bei-klick')) === false) e.preventDefault();
        }
        if ((el = t.closest('[data-drucken]')) && !gestoppt(el, t)) window.print();
        if ((el = t.closest('[data-passwort-zeigen]')) && !gestoppt(el, t)) {
            var pw = byId(el.getAttribute('data-passwort-zeigen'));
            if (pw) pw.type = pw.type === 'password' ? 'text' : 'password';
        }
        if ((el = t.closest('[data-schliesse-schublade]')) && !gestoppt(el, t) && window.parent !== window) {
            if (window.parent.fwModalClose) window.parent.fwModalClose();
            e.preventDefault();
        }
        if ((el = t.closest('[data-zurueck]')) && !gestoppt(el, t) && document.referrer) {
            history.back();
            e.preventDefault();
        }
        if ((el = t.closest('[data-modal]')) && !gestoppt(el, t) && typeof window.fwModalOpen === 'function') {
            if (window.fwModalOpen(el, el.getAttribute('data-modal'), el.hasAttribute('data-modal-breit')) === false) {
                e.preventDefault();
            }
        }

        if ((el = t.closest('[data-umschalten]')) && !gestoppt(el, t)) {
            var z = byId(el.getAttribute('data-umschalten'));
            if (z) z.classList.toggle(el.getAttribute('data-klasse') || 'hidden');
        }
        if ((el = t.closest('[data-verstecken]')) && !gestoppt(el, t)) {
            var v = byId(el.getAttribute('data-verstecken'));
            if (v) v.classList.add('hidden');
        }
        if ((el = t.closest('[data-scrollen]')) && !gestoppt(el, t)) {
            var s = byId(el.getAttribute('data-scrollen'));
            if (s) s.scrollIntoView({behavior: 'smooth'});
        }
        if ((el = t.closest('[data-entfernen]')) && !gestoppt(el, t)) {
            var r = el.closest(el.getAttribute('data-entfernen'));
            if (r) r.remove();
        }
        if ((el = t.closest('[data-kopieren]')) && !gestoppt(el, t)) {
            var quelle = byId(el.getAttribute('data-kopieren'));
            if (quelle && navigator.clipboard) {
                navigator.clipboard.writeText(quelle.value).then(function () {
                    var rueck = el.getAttribute('data-kopiert');
                    if (!rueck) return;
                    var vorher = el.innerHTML;
                    el.textContent = rueck;
                    setTimeout(function () { el.innerHTML = vorher; }, 1500);
                });
            }
        }
        if ((el = t.closest('[data-neues-fenster]')) && !gestoppt(el, t)) {
            window.open(el.getAttribute('data-neues-fenster'), '_blank');
        }
        if ((el = t.closest('[data-auswaehlen]')) && !gestoppt(el, t) && el.select) el.select();
        // Zuletzt: Zeilen-Verweis. Er gilt nicht, wenn auf ein `data-stop`-Element in der Zeile geklickt wurde.
        if ((el = t.closest('[data-gehe-zu]')) && !gestoppt(el, t)) {
            window.location = el.getAttribute('data-gehe-zu');
        }
    });

    document.addEventListener('focusin', function (e) {
        var el = e.target && e.target.closest ? e.target.closest('[data-auswaehlen]') : null;
        if (el && el.select) el.select();
    });

    document.addEventListener('submit', function (e) {
        var f = e.target;
        if (!f || !f.hasAttribute) return;
        if (f.hasAttribute('data-pruefe-gewaehlt') &&
            !f.ownerDocument.querySelectorAll(f.getAttribute('data-pruefe-gewaehlt')).length) {
            alert(f.getAttribute('data-pruefe-meldung') || '');
            e.preventDefault();
            return;
        }
        if (f.hasAttribute('data-grund-abfragen')) {
            var g = prompt(f.getAttribute('data-grund-abfragen').replace(/\|/g, '\n'));
            if (g === null) { e.preventDefault(); return; }
            if (f.elements.grund) f.elements.grund.value = g;
        }
        if (f.hasAttribute('data-bei-absenden') && aufrufen(f, f.getAttribute('data-bei-absenden')) === false) {
            e.preventDefault();
        }
    });

    document.addEventListener('input', function (e) {
        var el = e.target && e.target.closest ? e.target.closest('[data-bei-eingabe]') : null;
        if (el) aufrufen(el, el.getAttribute('data-bei-eingabe'));
    });

    document.addEventListener('change', function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var el;
        if ((el = t.closest('[data-auswahl-sync]')) && el.closest('.fw-auswahl')) {
            el.closest('.fw-auswahl').querySelectorAll('label').forEach(function (c) {
                var i = c.querySelector('input');
                if (i) c.classList.toggle('fw-on', i.checked);
            });
        }
        if ((el = t.closest('[data-bei-aenderung]'))) aufrufen(el, el.getAttribute('data-bei-aenderung'));
        if ((el = t.closest('[data-absenden]')) && el.form) {
            if (el.getAttribute('data-absenden') === 'request' && el.form.requestSubmit) el.form.requestSubmit();
            else el.form.submit();
        }
        if ((el = t.closest('[data-gehe-zu-wert]')) && el.value) {
            window.location = el.getAttribute('data-gehe-zu-wert') + encodeURIComponent(el.value);
        }
        if ((el = t.closest('[data-sichtbar-wenn]'))) {
            var z = byId(el.getAttribute('data-sichtbar-wenn'));
            if (z) z.classList.toggle('hidden', !el.checked);
        }
    });
})();
