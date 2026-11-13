// Laufzeit-Masse ohne Inline-Stil. `fwStil(el, {width: '42%'})` legt für das Element eine Regel in einem
// konstruierten Stylesheet an (`[data-fws="n"]{…}`). Ein Stylesheet-Objekt unterliegt der Content-Security-Policy
// nicht als Attribut: `style-src-attr` meldet nichts, anders als bei `el.style.width = …`, das Safari meldet.
// Fehlt die Unterstützung (ältere Browser), fällt es auf `el.style` zurück.
(function () {
    var blatt = null, regeln = new WeakMap(), zaehler = 0;
    try {
        if (window.CSSStyleSheet && document.adoptedStyleSheets !== undefined) {
            blatt = new CSSStyleSheet();
            document.adoptedStyleSheets = document.adoptedStyleSheets.concat([blatt]);
        }
    } catch (e) { blatt = null; }
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
                regel = blatt.cssRules[blatt.insertRule('[data-fws="' + id + '"]{}', blatt.cssRules.length)];
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
