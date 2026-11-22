// Vorschau neben einer Liste (Kontakte, Modul 7): «Vorschau» zeigt die Eckdaten rechts, ohne die Akte zu öffnen.
// Der Inhalt steht fertig in der `template`-Marke der Zeile; hier wird er nur umgesetzt. Ohne Skript öffnet die Zeile die Akte.
(function () {
    'use strict';
    var vorschau = document.getElementById('fwVorschau');
    var spalten = document.getElementById('fwVorschauSpalten');
    if (!vorschau) return;
    var offen = null;
    function zu() {
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
        if (!e.target.closest) return;
        if (e.target.closest('[data-vorschau-zu]')) { var alt = offen; zu(); if (alt) alt.focus(); return; }
        var knopf = e.target.closest('[data-vorschau]');
        if (!knopf) return;
        if (knopf === offen) { zu(); return; }
        var zelle = knopf.closest('td');
        var vorlage = zelle ? zelle.querySelector('template') : null;
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
