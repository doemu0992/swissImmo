// Liegenschaftsliste (Mockup Modul 2): Ansicht «Liste | Karten» und die Vorschau rechts neben der Liste.
// Beides ist Zugabe: ohne Skript bleibt die Tabelle, und die Zeile öffnet die Akte wie bisher.
(function () {
    'use strict';
    var KEY = 'fwLgAnsicht';
    var liste = document.getElementById('lgListe');
    var spalten = document.getElementById('lgSpalten');
    var vorschau = document.getElementById('lgVorschau');
    var schalter = document.getElementById('lgAnsicht');
    if (!liste) return;

    function lese() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
    function schreibe(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* ohne Speicher gilt die Liste */ } }
    function ansicht(wert) {
        var karten = wert === 'karten';
        liste.classList.toggle('fw-karten', karten);
        if (!schalter) return;
        schalter.querySelectorAll('[data-ansicht]').forEach(function (k) {
            k.setAttribute('aria-pressed', (k.getAttribute('data-ansicht') === 'karten') === karten ? 'true' : 'false');
        });
    }
    if (schalter) {
        schalter.hidden = false;
        schalter.addEventListener('click', function (e) {
            var k = e.target.closest ? e.target.closest('[data-ansicht]') : null;
            if (!k) return;
            schreibe(k.getAttribute('data-ansicht'));
            ansicht(k.getAttribute('data-ansicht'));
        });
    }
    ansicht(lese());

    var offen = null;
    function zu() {
        if (!vorschau) return;
        vorschau.hidden = true;
        vorschau.textContent = '';
        if (spalten) spalten.classList.remove('mit-vorschau');
        if (offen) {
            offen.setAttribute('aria-expanded', 'false');
            var z = offen.closest('tr'); if (z) z.classList.remove('sel');
            offen = null;
        }
    }
    document.addEventListener('click', function (e) {
        if (!vorschau || !e.target.closest) return;
        if (e.target.closest('[data-lg-vorschau-zu]')) { var alt = offen; zu(); if (alt) alt.focus(); return; }
        var knopf = e.target.closest('[data-lg-vorschau]');
        if (!knopf) return;
        if (knopf === offen) { zu(); return; }
        var vorlage = knopf.parentNode.querySelector('template');
        if (!vorlage || !vorlage.content) return;
        zu();
        vorschau.appendChild(vorlage.content.cloneNode(true));
        vorschau.hidden = false;
        if (spalten) spalten.classList.add('mit-vorschau');
        knopf.setAttribute('aria-expanded', 'true');
        var zeile = knopf.closest('tr'); if (zeile) zeile.classList.add('sel');
        offen = knopf;
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && offen) { var alt = offen; zu(); alt.focus(); }
    });
})();
