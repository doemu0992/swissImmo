/* DAS MENÜBAND DER KOPFZEILE (Zeile 2) — Markup in `core/templates/fw/base.html`,
   Regeln im Block «MODUL Kopfzeile v2» der Stilschicht.

   WAS ES TUT
   Das Band zeigt die Unterbereiche des aktiven Bereichs über die ganze Breite. Was
   nicht passt, wandert in «Mehr ▾»: Die Breite wird gemessen, die vorderen Punkte
   bleiben, der Rest steht im Überlauf (mit der Zahl der versteckten Punkte). Die
   Gruppe hinten («Vorgänge» unter Akten) läuft zuerst über und trägt im Überlauf
   ihre Überschrift. Der aktive Punkt wird nie versteckt: Er bleibt am Ende der
   sichtbaren Reihe. Steht ein Punkt mit Zahl (Schäden: ungelesene Meldungen) im
   Überlauf, trägt «Mehr» einen roten Punkt.

   OHNE SKRIPT scrollt das Band in sich; «Mehr» bleibt unsichtbar (`hidden`).
   AM TELEFON (bis 900 px) gibt es kein «Mehr»: Das Band scrollt in sich, der
   aktive Punkt wird ins Bild gerückt, weiche Ränder zeigen, dass es weiterläuft.

   TASTATUR  Der Knopf trägt `aria-expanded`/`aria-controls` (Offenlegung, kein
   Menü). Enter/Leertaste und ↓ öffnen, ↓ ↑ Pos1 Ende führen durch die Einträge,
   Esc schliesst und gibt den Fokus an den Knopf zurück; ein Klick daneben oder
   ein Tab aus der Liste heraus schliesst ebenfalls.

   Die Einträge des Überlaufs sind Kopien der Links im Band (cloneNode), gebaut als
   DOM-Knoten — nie als HTML-Zeichenkette. Alle Texte stehen schon in der Vorlage. */
(function () {
    'use strict';
    var band = document.querySelector('.fw-bereichsreiter');
    if (!band || document.documentElement.classList.contains('_embed')) return;
    var mehr = document.getElementById('fwMehr');
    var pop = document.getElementById('fwMehrPop');
    var telefon = window.matchMedia('(max-width:900px)');
    var name = band.querySelector('.fw-bereichsreiter-name');
    var ZUSATZ = 8;      // Mindestabstand vor «Mehr» in px
    var RESERVE = 2;     // gegen Rundung

    // ---------- die Punkte des Bandes (in der Reihenfolge der Vorlage) ----------
    var E = [];
    var offenerTrenner = null;
    Array.prototype.forEach.call(band.children, function (k) {
        if (k.classList.contains('fw-bereichsreiter-trenner')) { offenerTrenner = k; return; }
        if (k.tagName === 'A') { E.push({ a: k, sep: offenerTrenner, abschnitt: k.getAttribute('data-abschnitt') || '', w: 0 }); offenerTrenner = null; }
    });
    var aktiv = -1;
    E.forEach(function (e, i) { if (e.a.classList.contains('hier')) aktiv = i; });

    function fuerTelefon() {
        // Aktiven Punkt ins Bild rücken, Ränder nach Scrollstand
        var kanten = function () {
            var m = band.scrollWidth - band.clientWidth;
            band.classList.toggle('rand-l', m > 1 && band.scrollLeft > 2);
            band.classList.toggle('rand-r', m > 1 && band.scrollLeft < m - 2);
        };
        var hier = aktiv >= 0 ? E[aktiv].a : null;
        if (hier && band.scrollWidth > band.clientWidth)
            band.scrollLeft = Math.max(0, hier.offsetLeft - (band.clientWidth - hier.offsetWidth) / 2);
        kanten();
        if (!band.__kanten) { band.__kanten = true; band.addEventListener('scroll', kanten, { passive: true }); }
    }

    // ---------- Überlauf ----------
    var zuletzt = null;
    function alleZeigen() {
        E.forEach(function (e) { e.a.hidden = false; if (e.sep) e.sep.hidden = false; });
    }
    function fit() {
        alleZeigen();
        if (!mehr || !pop) return;
        if (telefon.matches) {
            band.classList.remove('fw-band-js');
            mehr.hidden = true; zu(false); zuletzt = null;
            fuerTelefon();
            return;
        }
        band.classList.add('fw-band-js');
        band.classList.remove('rand-l', 'rand-r');
        band.scrollLeft = 0;
        var n = E.length;
        mehr.hidden = false;
        mehr.querySelector('.fw-mehr-n').textContent = String(n);        // breiteste Fassung messen
        var cs = getComputedStyle(band);
        var gap = parseFloat(cs.columnGap) || 0;
        var avail = band.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        var breite = function (el) { return Math.ceil(el.getBoundingClientRect().width); };
        E.forEach(function (e) {
            e.w = breite(e.a);
            e.sw = 0;
            if (e.sep) { var m = getComputedStyle(e.sep); e.sw = breite(e.sep) + parseFloat(m.marginLeft) + parseFloat(m.marginRight); }
        });
        var nameW = name ? breite(name) : 0;
        var mehrW = breite(mehr);

        // Ein Trenner steht nur zwischen zwei Punkten, die auch an ihrem Platz stehen: Der aktive
        // Punkt hinten in der Reihe (er rückt auf) trägt keinen, ausser er wäre ohnehin der nächste.
        function trennerSichtbar(i, sicht, k) {
            return !!E[i].sep && !!sicht[i] && !!sicht[i - 1] && (k >= n || i < k || (i === aktiv && aktiv === k));
        }
        function gesamt(sicht, mitMehr, k) {
            var t = nameW + gap;
            for (var i = 0; i < n; i++) {
                if (!sicht[i]) continue;
                t += E[i].w + gap;
                if (trennerSichtbar(i, sicht, k)) t += E[i].sw + gap;
            }
            if (mitMehr) t += mehrW + gap + ZUSATZ;
            return t + RESERVE;
        }
        var k, sicht;
        for (k = n; k >= 0; k--) {
            sicht = [];
            for (var i = 0; i < n; i++) sicht[i] = i < k;
            if (k < n && aktiv >= k) sicht[aktiv] = true;       // der aktive Punkt bleibt
            if (gesamt(sicht, k < n, k) <= avail) break;
        }
        if (k < 0) k = 0;                                       // äusserster Notfall: nur der aktive Punkt
        var versteckt = [];
        E.forEach(function (e, i) {
            e.a.hidden = !sicht[i];
            if (e.sep) e.sep.hidden = !trennerSichtbar(i, sicht, k);
            if (!sicht[i]) versteckt.push(i);
        });
        mehr.hidden = versteckt.length === 0;
        mehr.querySelector('.fw-mehr-n').textContent = versteckt.length ? String(versteckt.length) : '';
        var punkt = mehr.querySelector('.fw-mehr-punkt');
        punkt.hidden = !versteckt.some(function (i) { return !!E[i].a.querySelector('.fw-z'); });
        // Neu aufbauen, sobald sich Auswahl oder Beschriftung (Zahlen) ändern; sonst bleibt die Liste stehen (Fokus)
        var sig = versteckt.join(',') + '|' + aktiv + '|' + versteckt.map(function (i) { return E[i].a.textContent; }).join(',');
        if (sig !== zuletzt) { zuletzt = sig; liste(versteckt); }
        if (!versteckt.length) zu(false);
    }

    function liste(versteckt) {
        while (pop.firstChild) pop.removeChild(pop.firstChild);
        var letzter = null;
        versteckt.forEach(function (i, j) {
            // Abschnitt des Punktes: der nächste davor (oder er selbst), der einen Namen trägt
            var abschnitt = '';
            for (var m = i; m >= 0; m--) { if (E[m].abschnitt) { abschnitt = E[m].abschnitt; break; } }
            if (j === 0 || abschnitt !== letzter) {
                if (abschnitt) {
                    var kopf = document.createElement('span');
                    kopf.className = 'fw-mehr-kopf';
                    kopf.appendChild(document.createTextNode(abschnitt));
                    pop.appendChild(kopf);
                }
                letzter = abschnitt;
            }
            pop.appendChild(E[i].a.cloneNode(true));
        });
    }

    // ---------- «Mehr» öffnen und schliessen ----------
    function offen() { return !!pop && !pop.hidden; }
    function auf(fokus) {
        if (!mehr || mehr.hidden) return;
        pop.hidden = false;
        mehr.setAttribute('aria-expanded', 'true');
        var l = eintraege();
        if (fokus === 'erster' && l.length) l[0].focus();
        if (fokus === 'letzter' && l.length) l[l.length - 1].focus();
    }
    function zu(fokusZurueck) {
        if (!pop || pop.hidden) return;
        pop.hidden = true;
        if (mehr) {
            mehr.setAttribute('aria-expanded', 'false');
            if (fokusZurueck) mehr.focus();
        }
    }
    function eintraege() { return Array.prototype.slice.call(pop.querySelectorAll('a')); }

    if (mehr && pop) {
        mehr.addEventListener('click', function () { if (offen()) zu(false); else auf(null); });
        mehr.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown') { e.preventDefault(); auf('erster'); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); auf('letzter'); }
        });
        pop.addEventListener('keydown', function (e) {
            var l = eintraege();
            var i = l.indexOf(document.activeElement);
            if (e.key === 'ArrowDown') { e.preventDefault(); l[(i + 1) % l.length].focus(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); l[i <= 0 ? l.length - 1 : i - 1].focus(); }
            else if (e.key === 'Home') { e.preventDefault(); l[0].focus(); }
            else if (e.key === 'End') { e.preventDefault(); l[l.length - 1].focus(); }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && offen()) { e.preventDefault(); zu(true); }
        });
        document.addEventListener('pointerdown', function (e) {
            if (offen() && !pop.contains(e.target) && !mehr.contains(e.target)) zu(false);
        });
        // Ein Tab aus der Liste (oder vom Knopf weg ins Leere) schliesst sie
        pop.addEventListener('focusout', function (e) {
            var n = e.relatedTarget;
            if (n && !pop.contains(n) && n !== mehr) zu(false);
        });
        window.addEventListener('pageshow', function (e) { if (e.persisted) zu(false); });
    }

    // ---------- anstossen ----------
    var laeuft = false;
    function neu() {
        if (laeuft) return;
        laeuft = true;
        try { fit(); } finally { laeuft = false; }
    }
    fit();
    if (window.ResizeObserver) new ResizeObserver(neu).observe(band);
    window.addEventListener('resize', neu);
    if (telefon.addEventListener) telefon.addEventListener('change', neu);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(neu);
    window.addEventListener('load', neu);
})();
