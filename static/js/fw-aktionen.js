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
 *   data-stop                   Klick hier löst die Aktionen darüberliegender Elemente (z. B. der Zeile) nicht aus
 *   data-kopieren="id"          Klick: Wert von #id in die Zwischenablage (data-kopiert="Kopiert ✓" als Rückmeldung)
 *   data-auswaehlen             Fokus/Klick: Inhalt des Feldes markieren
 *   data-scrollen="id"          Klick: sanft zu #id scrollen
 *   data-entfernen=".sel"       Klick: das nächste Elternelement `.sel` entfernen
 */
(function () {
    'use strict';

    function byId(id) { return id ? document.getElementById(id) : null; }

    // Ein `data-stop`-Element zwischen Ziel und `el` hält die Aktion von `el` auf (wie stopPropagation()).
    function gestoppt(el, ziel) {
        var s = ziel.closest('[data-stop]');
        return !!s && s !== el && el.contains(s);
    }

    document.addEventListener('click', function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var el;

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

    document.addEventListener('change', function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var el;
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
