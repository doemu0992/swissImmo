/* Fehlerseite 500: das Ziel von «Zur Übersicht» nach Herkunft setzen (Mieter- und Eigentümerportal).
 * Eigene Datei statt Inline-Skript: 500.html wird ohne Anfrage gerendert und hat deshalb keinen CSP-Nonce. */
(function () {
    var p = location.pathname, a = document.getElementById('fehlerZiel');
    if (!a) return;
    if (p.indexOf('/mieter/') === 0) a.href = '/mieter/';
    else if (p.indexOf('/portal/') === 0) a.href = '/portal/';
})();
