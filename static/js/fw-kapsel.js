/* Ember: Lastbalken — bis 15.11.2026 als Inline-Skript in `core/templates/fw/base.html`.
   Kennzahlen stehen sofort im Endwert; das Hochzählen ist seit 19.11.2026 weg (UI-Zielbild, Phase 0, Befund 1): Wer eine
   Zahl liest, soll nicht warten, bis sie stimmt.
   Als Datei, damit der Browser es zwischenspeichert statt es mit jeder Seite neu zu laden (Audit P15).
   Texte und Schalter der Seite kommen aus dem Datenblock `#fw-rahmen-daten` (siehe base.html). */
// ─── Ember: Lastbalken ───
(function () {
    // Lastbalken (Team, Leerstand): Breite aus data-w, im nächsten Bild — dann gleitet sie auf
    var balken = document.querySelectorAll('.fw-lastbalken[data-w] > i');
    requestAnimationFrame(function () { balken.forEach(function (i) {
        fwStil(i, {width: Math.max(0, Math.min(100, parseFloat(i.parentNode.getAttribute('data-w')) || 0)) + '%'}); }); });
})();
