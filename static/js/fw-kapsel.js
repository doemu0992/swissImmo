/* Ember: gleitende Kapsel, hochzählende Kennzahlen — bis 15.11.2026 als Inline-Skript in `core/templates/fw/base.html`.
   Als Datei, damit der Browser es zwischenspeichert statt es mit jeder Seite neu zu laden (Audit P15).
   Texte und Schalter der Seite kommen aus dem Datenblock `#fw-rahmen-daten` (siehe base.html). */
// ─── Ember: gleitende Kapsel der Bereiche, hochzählende Kennzahlen ───
(function () {
    var ruhig = document.documentElement.classList.contains('fw-ruhig')
        || (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
    var nav = document.getElementById('fwHauptnav');
    if (nav) {
        var gleiter = nav.querySelector('.fw-gleiter');
        var setzen = function (a, sofort) {
            if (!a || !gleiter) return;
            fwStil(gleiter, {transition: sofort ? 'none' : null, width: a.offsetWidth + 'px', transform: 'translateX(' + a.offsetLeft + 'px)'});
            if (sofort) requestAnimationFrame(function () { fwStil(gleiter, {transition: null}); });
        };
        var aktiv = nav.querySelector('a.hier');
        if (aktiv) {
            setzen(aktiv, true);
            // Am Telefon steht der aktive Bereich im Bild
            if (nav.scrollWidth > nav.clientWidth) nav.scrollLeft = Math.max(0, aktiv.offsetLeft - (nav.clientWidth - aktiv.offsetWidth) / 2);
        } else if (gleiter) { fwStil(gleiter, {opacity: '0'}); }
        // Beim Zeigen gleitet die Kapsel mit, beim Verlassen zurück
        nav.querySelectorAll('a').forEach(function (a) {
            a.addEventListener('mouseenter', function () { if (!ruhig && aktiv) { setzen(a); nav.querySelectorAll('a').forEach(function (x) { x.classList.toggle('zeigt', x === a); }); } });
        });
        nav.addEventListener('mouseleave', function () { setzen(aktiv); nav.querySelectorAll('a.zeigt').forEach(function (x) { x.classList.remove('zeigt'); }); });
        window.addEventListener('resize', function () { setzen(nav.querySelector('a.hier'), true); });
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { setzen(nav.querySelector('a.hier'), true); });
    }
    // Lastbalken (Team, Leerstand): Breite aus data-w, im nächsten Bild — dann gleitet sie auf
    var balken = document.querySelectorAll('.fw-lastbalken[data-w] > i');
    requestAnimationFrame(function () { balken.forEach(function (i) {
        fwStil(i, {width: Math.max(0, Math.min(100, parseFloat(i.parentNode.getAttribute('data-w')) || 0)) + '%'}); }); });
    if (ruhig) return;
    // Zahlen zählen hoch — nur die grossen Kennzahlen, Formatierung bleibt (CHF, Apostroph, %).
    var ziele = document.querySelectorAll('.fw-kpi .fw-v, .fw-lage .fw-w, .fw-kachel-zahl [data-zaehlen], .fw-ampel-zahl b');
    ziele.forEach(function (el) {
        if (el.children.length) return;
        var text = el.textContent, m = text.match(/-?\d[\d']*(?:[.,]\d+)?/);
        if (!m) return;
        var roh = m[0], dez = (roh.split(/[.,]/)[1] || '').length, trenner = roh.indexOf("'") > -1;
        var ziel = parseFloat(roh.replace(/'/g, '').replace(',', '.'));
        if (!isFinite(ziel) || ziel === 0) return;
        var vor = text.slice(0, m.index), nach = text.slice(m.index + roh.length), komma = roh.indexOf(',') > -1;
        var fmt = function (v) {
            var t = v.toFixed(dez);
            if (komma) t = t.replace('.', ',');
            if (trenner) { var teile = t.split(/[.,]/); teile[0] = teile[0].replace(/\B(?=(\d{3})+(?!\d))/g, "'"); t = teile.join(komma ? ',' : '.'); }
            return vor + t + nach;
        };
        var t0 = null, dauer = 1100;
        el.textContent = fmt(0);
        var schritt = function (t) {
            if (t0 === null) t0 = t;
            var p = Math.min(1, (t - t0) / dauer), e = 1 - Math.pow(1 - p, 3);
            el.textContent = p < 1 ? fmt(ziel * e) : text;
            if (p < 1) requestAnimationFrame(schritt);
        };
        requestAnimationFrame(schritt);
    });
})();
