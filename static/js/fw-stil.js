// Laufzeit-Masse ohne Inline-Stil. `fwStil(el, {width: '42%'})` legt für das Element eine Regel in einem
// konstruierten Stylesheet an (`:is(#fws-gewicht,[data-fws="n"]){…}` — das `:is` mit einer ID gibt der Regel das
// Gewicht einer ID, damit sie wie ein Inline-Stil gegen Klassen gewinnt). Ein Stylesheet-Objekt unterliegt der Content-Security-Policy
// nicht als Attribut: `style-src-attr` meldet nichts, anders als bei `el.style.width = …`, das Safari meldet.
// Fehlt die Unterstützung (ältere Browser), trägt ein <style nonce> die Regeln; zuletzt bleibt `el.style`.
(function () {
    var blatt = null, regeln = new WeakMap(), zaehler = 0;
    try {
        if (window.CSSStyleSheet && document.adoptedStyleSheets !== undefined) {
            blatt = new CSSStyleSheet();
            document.adoptedStyleSheets = document.adoptedStyleSheets.concat([blatt]);
        }
    } catch (e) { blatt = null; }
    // Safari vor 16.4 kennt `adoptedStyleSheets` nicht. Dann trägt ein <style>-Element mit dem Nonce der Seite die Regeln;
    // erst wenn auch das scheitert, bleibt `el.style` (das die Richtlinie in Safari als Inline-Stil meldet).
    if (!blatt) {
        try {
            var mitNonce = document.querySelector('script[nonce], style[nonce]');
            var nonce = mitNonce && (mitNonce.nonce || mitNonce.getAttribute('nonce'));
            if (nonce) {
                var stil = document.createElement('style');
                stil.setAttribute('nonce', nonce);
                (document.head || document.documentElement).appendChild(stil);
                blatt = stil.sheet || null;
            }
        } catch (e) { blatt = null; }
    }
    // Eigene Meldung zu gesperrten Inline-Stilen: Der Bericht des Browsers nennt nur die Seite. Hier kommen das
    // betroffene Element und sein Stil dazu (höchstens fünf je Seitenaufruf) — daran ist die Ursache zu erkennen,
    // auch wenn sie ausserhalb der Anwendung liegt (Browser-Erweiterung).
    var gemeldet = 0;
    document.addEventListener('securitypolicyviolation', function (e) {
        try {
            if (String(e.effectiveDirective || e.violatedDirective).indexOf('style-src') !== 0 || gemeldet >= 5) return;
            gemeldet++;
            var el = e.target && e.target.nodeType === 1 ? e.target : null;
            var wer = el ? el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
                + (el.getAttribute('class') ? '.' + String(el.getAttribute('class')).split(/\s+/).slice(0, 3).join('.') : '') : '';
            var koerper = JSON.stringify({'csp-report': {
                'violated-directive': e.effectiveDirective || e.violatedDirective, 'blocked-uri': e.blockedURI || 'inline',
                'document-uri': location.href, 'line-number': e.lineNumber || '', 'source-file': e.sourceFile || '',
                'script-sample': (e.sample || (el && el.getAttribute('style')) || '').slice(0, 60),
                'element': wer.slice(0, 80)}});
            if (window.fetch) fetch('/csp-bericht/', {method: 'POST', body: koerper, keepalive: true, credentials: 'same-origin',
                headers: {'Content-Type': 'application/csp-report'}}).catch(function () {});
        } catch (f) { /* die Meldung ist Zugabe */ }
    });
    function eigenschaft(el, name, wert) {
        if (name.indexOf('--') === 0) el.style.setProperty(name, wert); else el.style[name] = wert;
    }
    window.fwStil = function (el, props) {
        if (!el) return;
        var regel = blatt && regeln.get(el);
        try {
            if (blatt && !regel) {
                var id = String(++zaehler);
                el.setAttribute('data-fws', id);
                regel = blatt.cssRules[blatt.insertRule(':is(#fws-gewicht,[data-fws="' + id + '"]){}', blatt.cssRules.length)];
                regeln.set(el, regel);
            }
            if (regel) {
                Object.keys(props).forEach(function (k) {
                    var wert = props[k];
                    if (wert === null || wert === '') regel.style.removeProperty(k.indexOf('--') === 0 ? k : k.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); }));
                    else regel.style.setProperty(k.indexOf('--') === 0 ? k : k.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); }), wert);
                });
                return;
            }
        } catch (e) { /* Rückfall */ }
        Object.keys(props).forEach(function (k) { eigenschaft(el, k, props[k] === null ? '' : props[k]); });
    };
})();
