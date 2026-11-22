// Finanzen (Mockup Modul 6): Kreditoren «Tabelle | Spalten» und das Kontoblatt neben der Liste der Mieterkonten.
// Beides ist Zugabe: ohne Skript bleibt die Tabelle, und die Zeile öffnet das Kontoblatt als Seite.
(function () {
    'use strict';
    function lese(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
    function schreibe(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ohne Speicher gilt die Tabelle */ } }

    // ---- Kreditoren: Tabelle | Spalten ----
    var schalter = document.getElementById('krAnsicht');
    var spalten = document.getElementById('krSpalten');
    var tabelle = document.getElementById('krTabelle');
    function ansicht(wert) {
        var sp = wert === 'spalten';
        spalten.hidden = !sp;
        tabelle.hidden = sp;
        schalter.querySelectorAll('[data-ansicht]').forEach(function (k) {
            k.setAttribute('aria-pressed', (k.getAttribute('data-ansicht') === 'spalten') === sp ? 'true' : 'false');
        });
    }
    if (schalter && spalten && tabelle) {
        schalter.hidden = false;
        schalter.addEventListener('click', function (e) {
            var k = e.target.closest ? e.target.closest('[data-ansicht]') : null;
            if (!k) return;
            schreibe('fwKrAnsicht', k.getAttribute('data-ansicht'));
            ansicht(k.getAttribute('data-ansicht'));
        });
        spalten.addEventListener('click', function (e) {
            var k = e.target.closest ? e.target.closest('[data-kr-zeige]') : null;
            if (!k) return;
            ansicht('tabelle');
            var zeile = document.getElementById(k.getAttribute('data-kr-zeige'));
            if (!zeile) return;
            zeile.scrollIntoView({block: 'center'});
            zeile.classList.add('sel');
            setTimeout(function () { zeile.classList.remove('sel'); }, 2400);
        });
        ansicht(lese('fwKrAnsicht'));
    }

    // ---- Mieterkonten: Kontoblatt neben der Liste ----
    var blatt = document.getElementById('mkBlatt');
    var rahmen = document.getElementById('mkBlattRahmen');
    var titel = document.getElementById('mkBlattTitel');
    var mkSpalten = document.getElementById('mkSpalten');
    var offen = null;
    function zu() {
        if (!blatt) return;
        blatt.hidden = true;
        rahmen.src = 'about:blank';
        if (mkSpalten) mkSpalten.classList.remove('mit-vorschau');
        if (offen) {
            offen.setAttribute('aria-expanded', 'false');
            var z = offen.closest('tr'); if (z) z.classList.remove('sel');
            offen = null;
        }
    }
    if (blatt && rahmen) {
        document.addEventListener('click', function (e) {
            if (!e.target.closest) return;
            if (e.target.closest('[data-mk-zu]')) { var alt = offen; zu(); if (alt) alt.focus(); return; }
            var k = e.target.closest('[data-mk-blatt]');
            if (!k) return;
            if (k === offen) { zu(); return; }
            zu();
            rahmen.src = k.getAttribute('data-mk-blatt');
            titel.textContent = k.getAttribute('data-mk-titel') || '';
            blatt.hidden = false;
            if (mkSpalten) mkSpalten.classList.add('mit-vorschau');
            k.setAttribute('aria-expanded', 'true');
            var zeile = k.closest('tr'); if (zeile) zeile.classList.add('sel');
            offen = k;
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && offen) { var alt = offen; zu(); alt.focus(); }
        });
    }
})();
