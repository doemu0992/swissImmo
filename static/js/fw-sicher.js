// Maskierung für Werte, die in einen HTML-String gehen (`el.innerHTML = \`…${fwEsc(wert)}…\``).
// Wo es geht, ist `textContent` oder `new Option(text, wert)` besser: Dann braucht es diese Funktion gar nicht.
// Maskiert & < > " ' — damit ist der Wert in Elementinhalt UND in einem Attribut in Anführungszeichen sicher.
// Nicht geeignet für Werte in href/src (dort zusätzlich das Schema prüfen) und nicht für Skript- oder Stil-Kontext.
(function () {
    var ZEICHEN = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
    window.fwEsc = function (wert) {
        if (wert === null || wert === undefined) return '';
        return String(wert).replace(/[&<>"']/g, function (c) { return ZEICHEN[c]; });
    };
})();
