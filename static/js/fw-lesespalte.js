/* Lesespalte: Seiten ohne Tabelle, Cockpit oder Kachelraster stehen ab 1280 px schmal (920 px).
 *
 * WARUM EIN SKRIPT UND KEINE STILREGEL (24.11.2026, Meldung «Software wurde extrem langsam»):
 * Die Regel stand als `.fw-inhalt:not(:has(table)):not(:has(.fw-cockpit))… > *` in der Schicht, zwölf `:has()` am
 * Inhaltsbereich der Seite. Der Browser musste sie bei JEDER Änderung irgendwo im Inhalt neu auswerten (Tippen, Maus über
 * einer Zeile, Aufklappen): gemessen 113 ms -> 900 ms Stilberechnung für dieselben Handgriffe. Die Frage «hat die Seite
 * eine Tabelle?» wird hier einmal beantwortet und als Klasse `fw-lesespalte` gesetzt.
 *
 * Die Datei wird direkt nach </main> geladen: Der Inhalt ist dann vollständig, die Klasse steht vor dem ersten Bild.
 * Kommt später eine Tabelle dazu (nachgeladener Inhalt), stellt der Beobachter die Seite auf volle Breite.
 */
(function () {
    'use strict';
    var main = document.getElementById('fw-inhalt');
    if (!main) return;
    var BREIT = 'table,.fw-cockpit,.fw-bento,.fw-kpis,.fw-split,.fw-zwei,.fw-assistent,.fw-raster.l3,' +
                '.fw-schadenliste,.fw-spalte,.fw-la-spalten,.fw-einst-spalten';
    function setzen() {
        main.classList.toggle('fw-lesespalte', !main.querySelector(BREIT));
        // Einstellungsseiten: ohne Tabelle 860 px breit (vorher `.fw-einst-seite:not(:has(table))`).
        var einst = main.querySelector('.fw-einst-seite');
        if (einst) einst.classList.toggle('fw-ohne-tabelle', !einst.querySelector('table'));
    }
    setzen();
    if (!window.MutationObserver) return;
    var geplant = false;
    new MutationObserver(function () {
        if (geplant) return;
        geplant = true;
        (window.requestAnimationFrame || window.setTimeout)(function () { geplant = false; setzen(); });
    }).observe(main, { childList: true, subtree: true });
})();
