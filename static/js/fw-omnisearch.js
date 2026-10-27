/* DIE OMNISEARCH (Kopfzeile, Zeile 1) — Markup in `core/templates/fw/_omnisearch.html`.

   WAS SIE TUT
   Ab zwei Zeichen öffnet unter dem Feld ein Popover: Filterkapseln mit
   Trefferzahlen, darunter die Treffer aus `/neu/palette/?q=…` nach Gruppen, am
   Ende die Gruppe «Seiten & Aktionen» (die Daten der früheren ⌘K-Palette,
   `fw-palette-data`). Ohne JavaScript bleibt das Feld ein Formular auf
   `/neu/suche/`.

   VERTRAG DES ENDPUNKTS
   { q, treffer: [{gruppe, art, label, zusatz, url, status:{text,ton}|null,
                   betrag:string|null}], zahlen: {gruppe: n} }
   `gruppe` ist personen, immobilien, vertraege, buchhaltung, tickets oder
   dokumente; `ton` ist crit, warn, good oder mut. Fehlt `gruppe` (älterer
   Endpunkt), wird sie aus `art` abgeleitet, fehlt `zahlen`, wird gezählt.

   ANFRAGEN
   Entprellt (150 ms). Jede neue Eingabe bricht die laufende Anfrage ab
   (AbortController); zusätzlich zählt nur die Antwort mit der höchsten Nummer.
   Während der ersten Antwort steht ein Gerüst in der Höhe echter Zeilen, bei
   weiteren Eingaben bleiben die letzten Treffer stehen (nichts springt).

   TASTATUR
   ↑ ↓ wählen (aria-activedescendant), ↵ öffnet, ⌘/Strg+↵ in neuem Tab, Esc
   schliesst und gibt den Fokus zurück, ⌘K / Strg+K fokussiert das Feld.

   Alle Texte stehen im <template id="fwOsTexte"> (übersetzt), nichts hier.
   Treffer werden als DOM-Knoten gebaut, nie als HTML-Zeichenkette. */
(function () {
    'use strict';
    var wurzel = document.getElementById('fwOs');
    if (!wurzel || document.documentElement.classList.contains('_embed')) return;   // im Rahmen steht kein Kopf
    var eingabe = document.getElementById('fwOsEingabe');
    var pop = document.getElementById('fwOsPop');
    var filterEl = document.getElementById('fwOsFilter');
    var liste = document.getElementById('fwOsListe');
    var alleLink = document.getElementById('fwOsAlle');
    var statusEl = document.getElementById('fwOsStatus');
    var zuKnopf = document.getElementById('fwOsZu');
    var taste = document.getElementById('fwOsTaste');
    var vorlage = document.getElementById('fwOsTexte');
    var NS = 'http://www.w3.org/2000/svg';
    var PALETTE_URL = wurzel.getAttribute('data-palette-url') || '/neu/palette/';
    var SUCHE_URL = wurzel.getAttribute('data-suche-url') || '/neu/suche/';
    var VERZOEGERUNG = 150;
    var MIN_ZEICHEN = 2;

    var T = {};
    if (vorlage && vorlage.content) {
        Array.prototype.forEach.call(vorlage.content.querySelectorAll('[data-k]'), function (s) {
            T[s.getAttribute('data-k')] = s.textContent;
        });
    }
    function t(k, werte) {
        var s = T[k] !== undefined ? T[k] : k;
        if (werte) Object.keys(werte).forEach(function (n) { s = s.split('{' + n + '}').join(werte[n]); });
        return s;
    }

    var GRUPPEN = ['personen', 'immobilien', 'vertraege', 'buchhaltung', 'tickets', 'dokumente'];
    var CHIPS = ['alle', 'personen', 'immobilien', 'buchhaltung', 'tickets', 'vertraege', 'dokumente'];
    var ZEICHEN = { personen: 'person', immobilien: 'liegenschaft', vertraege: 'vertrag',
                    buchhaltung: 'rechnung', tickets: 'meldung', dokumente: 'dokument', seiten: 'weiter' };
    var TOENE = { crit: 1, warn: 1, good: 1, mut: 1 };
    var ART_ZU_GRUPPE = { 'Person': 'personen', 'Liegenschaft': 'immobilien', 'Objekt': 'immobilien',
                          'Mietverhältnis': 'vertraege' };
    var SEITEN_MAX = 6;

    var seiten = [];
    try { seiten = JSON.parse(document.getElementById('fw-palette-data').textContent) || []; } catch (e) { seiten = []; }

    var st = { q: '', daten: null, datenQ: '', status: 'ruhe', filter: 'alle', sel: 0,
               items: [], seq: 0, ctrl: null, timer: null, vorher: null };

    // ---------- kleine Helfer ----------
    function el(tag, attr, kinder) {
        var n = document.createElement(tag);
        if (attr) Object.keys(attr).forEach(function (k) {
            if (k === 'class') n.className = attr[k]; else n.setAttribute(k, attr[k]);
        });
        (kinder || []).forEach(function (k) {
            if (k === null || k === undefined || k === false) return;
            n.appendChild(typeof k === 'string' ? document.createTextNode(k) : k);
        });
        return n;
    }
    function zeichen(name) {
        var s = document.createElementNS(NS, 'svg');
        s.setAttribute('class', 'fw-zeichen');
        s.setAttribute('aria-hidden', 'true');
        var u = document.createElementNS(NS, 'use');
        u.setAttribute('href', '#z-' + name);
        s.appendChild(u);
        return s;
    }
    function maskiert(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
    function woerter(q) { return q.split(/\s+/).filter(Boolean); }
    function hervor(text, q) {
        var w = woerter(q);
        if (!w.length) return [text];
        var re = new RegExp('(' + w.map(maskiert).join('|') + ')', 'gi');
        var teile = [], pos = 0, m;
        while ((m = re.exec(text)) !== null) {
            if (m[0] === '') { re.lastIndex++; continue; }
            if (m.index > pos) teile.push(text.slice(pos, m.index));
            teile.push(el('mark', null, [m[0]]));
            pos = m.index + m[0].length;
        }
        if (pos < text.length) teile.push(text.slice(pos));
        return teile;
    }
    function zahlText(n) { return n >= 99 ? '99+' : String(n); }
    function istMac() { return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || ''); }

    // ---------- Antwort und Seiten aufbereiten ----------
    function aufbereiten(d) {
        var roh = (d && Array.isArray(d.treffer)) ? d.treffer : [];
        var proGruppe = {};
        GRUPPEN.forEach(function (g) { proGruppe[g] = []; });
        roh.forEach(function (x) {
            if (!x || typeof x.url !== 'string' || x.url.charAt(0) !== '/') return;
            var g = GRUPPEN.indexOf(x.gruppe) >= 0 ? x.gruppe : ART_ZU_GRUPPE[x.art];
            if (!g) return;
            var ton = x.status && TOENE[x.status.ton] ? x.status.ton : 'mut';
            proGruppe[g].push({ gruppe: g, art: x.art || '', label: String(x.label || ''), zusatz: String(x.zusatz || ''),
                                url: x.url, status: x.status && x.status.text ? { text: String(x.status.text), ton: ton } : null,
                                betrag: x.betrag ? String(x.betrag) : null });
        });
        var zahlen = {};
        GRUPPEN.forEach(function (g) {
            var n = d && d.zahlen && typeof d.zahlen[g] === 'number' ? d.zahlen[g] : 0;
            zahlen[g] = Math.max(n, proGruppe[g].length);
        });
        return { gruppen: proGruppe, zahlen: zahlen };
    }
    function seitenTreffer(q) {
        var w = woerter(q.toLowerCase());
        if (!w.length) return [];
        return seiten.filter(function (d) {
            if (!d || typeof d.url !== 'string' || d.url.charAt(0) !== '/') return false;
            var heu = (d.label + ' ' + (d.gruppe || '')).toLowerCase();
            return w.every(function (x) { return heu.indexOf(x) !== -1; });
        }).slice(0, SEITEN_MAX).map(function (d) {
            return { gruppe: 'seiten', art: '', label: d.label, zusatz: d.gruppe || '', url: d.url, status: null, betrag: null };
        });
    }

    // ---------- Zeichnen ----------
    function kontext(it) {
        if (!it.art || it.zusatz.indexOf(it.art) === 0) return it.zusatz || it.art;
        return it.zusatz ? it.art + ' · ' + it.zusatz : it.art;
    }
    function optionKnoten(it, i, q) {
        var a = el('a', { 'class': 'fw-os-t', role: 'option', id: 'fwOsO' + i, href: it.url, tabindex: '-1',
                          'aria-selected': 'false', 'data-i': String(i) });
        a.appendChild(el('span', { 'class': 'fw-os-ico' + (it.gruppe === 'seiten' ? ' akt' : '') }, [zeichen(ZEICHEN[it.gruppe])]));
        a.appendChild(el('span', { 'class': 'fw-os-txt' }, [
            el('b', null, hervor(it.label, q)),
            el('small', null, [kontext(it)])
        ]));
        if (it.betrag || it.status) {
            a.appendChild(el('span', { 'class': 'fw-os-rechts' }, [
                it.betrag ? el('span', { 'class': 'fw-os-betrag' }, [it.betrag]) : null,
                it.status ? el('span', { 'class': 'fw-chip fw-' + it.status.ton }, [it.status.text]) : null
            ]));
        }
        a.appendChild(el('kbd', { 'class': 'fw-os-enter', 'aria-hidden': 'true' }, ['↵']));
        return a;
    }
    function geruest() {
        var g = el('div', { 'class': 'fw-os-geruest', 'aria-hidden': 'true' });
        [3, 2].forEach(function (n) {
            var gr = el('div', { 'class': 'fw-os-gruppe' }, [el('div', { 'class': 'fw-os-kopf' }, [el('span', { 'class': 'fw-os-balken kopf' })])]);
            for (var i = 0; i < n; i++) {
                gr.appendChild(el('div', { 'class': 'fw-os-t' }, [
                    el('span', { 'class': 'fw-os-ico' }),
                    el('span', { 'class': 'fw-os-txt' }, [el('span', { 'class': 'fw-os-balken lang' }), el('span', { 'class': 'fw-os-balken kurz' })])
                ]));
            }
            g.appendChild(gr);
        });
        return g;
    }
    function gruppeKnoten(g, kopfText, zahl, eintraege, q, zaehler) {
        var kid = 'fwOsK-' + g;
        var kopf = el('div', { 'class': 'fw-os-kopf', id: kid }, [el('span', null, [kopfText]),
            zahl !== null ? el('span', { 'class': 'fw-os-zahl' }, [zahlText(zahl)]) : null]);
        var gr = el('div', { 'class': 'fw-os-gruppe', role: 'group', 'aria-labelledby': kid }, [kopf]);
        eintraege.forEach(function (it) {
            var i = zaehler.n++;
            st.items.push(it);
            gr.appendChild(optionKnoten(it, i, q));
        });
        return gr;
    }

    function render() {
        var q = st.q;
        var daten = st.daten;
        var laedt = st.status === 'laedt';
        var fehler = st.status === 'fehler';
        var ruhe = laedt && !daten;                // erste Antwort steht noch aus
        var sichtbarSeiten = (fehler || !ruhe) ? seitenTreffer(q) : [];

        // Filter, der in dieser Antwort nichts mehr trifft, fällt auf «Alle» zurück.
        if (daten && st.filter !== 'alle' && !daten.zahlen[st.filter]) st.filter = 'alle';

        // Kapseln
        var summe = sichtbarSeiten.length;
        if (daten) GRUPPEN.forEach(function (g) { summe += daten.zahlen[g]; });
        filterEl.textContent = '';
        CHIPS.forEach(function (k) {
            var n = null;
            if (daten) n = k === 'alle' ? summe : daten.zahlen[k];
            var an = st.filter === k;
            var b = el('button', { type: 'button', 'class': 'fw-os-chip' + (an ? ' an' : ''), 'data-f': k, 'aria-pressed': an ? 'true' : 'false' },
                [t(k), n !== null ? el('i', null, [zahlText(n)]) : null]);
            if (k !== 'alle' && !an && (!daten || !n)) b.disabled = true;
            filterEl.appendChild(b);
        });
        if (daten || fehler) {
            var info = summe === 1 ? t('treffer_1') : t('treffer_n', { n: summe });
            filterEl.appendChild(el('span', { 'class': 'fw-os-info' }, [fehler ? '' : info]));
        }

        // Liste
        liste.textContent = '';
        st.items = [];
        liste.setAttribute('aria-busy', laedt ? 'true' : 'false');
        liste.classList.toggle('laedt', laedt && !!daten);
        var zaehler = { n: 0 };
        if (ruhe) {
            liste.appendChild(geruest());
            statusEl.textContent = t('laedt');
        } else {
            if (fehler) {
                var neu = el('button', { type: 'button', 'class': 'fw-btn fw-knapp', 'data-os-nochmals': '1' }, [t('nochmals')]);
                liste.appendChild(el('div', { 'class': 'fw-os-leer', role: 'alert' }, [
                    el('b', null, [t('fehler')]), el('p', null, [t('fehler_hinweis')]), neu]));
            }
            if (daten && !fehler) {
                GRUPPEN.forEach(function (g) {
                    if (st.filter !== 'alle' && st.filter !== g) return;
                    var l = daten.gruppen[g];
                    if (!l.length) return;
                    liste.appendChild(gruppeKnoten(g, t('g_' + g), daten.zahlen[g], l, st.datenQ || q, zaehler));
                });
            }
            if (st.filter === 'alle' && sichtbarSeiten.length) {
                liste.appendChild(gruppeKnoten('seiten', t('g_seiten'), null, sichtbarSeiten, q, zaehler));
            }
            if (!zaehler.n && !fehler && !laedt) {
                liste.appendChild(el('div', { 'class': 'fw-os-leer' }, [
                    el('b', null, [t('leer', { q: q })]), el('p', null, [t('leer_hinweis')])]));
            }
        }

        // Fuss
        alleLink.href = SUCHE_URL + '?q=' + encodeURIComponent(q);
        alleLink.textContent = fehler ? t('ausfuehrlich') : t('alle_ergebnisse', { q: q });

        if (st.sel >= st.items.length) st.sel = Math.max(0, st.items.length - 1);
        markiere(st.sel, false);
    }

    function markiere(i, scrollen) {
        st.sel = i;
        var optionen = liste.querySelectorAll('[role="option"]');
        Array.prototype.forEach.call(optionen, function (o, n) {
            var an = n === i;
            o.classList.toggle('sel', an);
            o.setAttribute('aria-selected', an ? 'true' : 'false');
            if (an && scrollen) o.scrollIntoView({ block: 'nearest' });
        });
        if (optionen.length && optionen[i]) eingabe.setAttribute('aria-activedescendant', optionen[i].id);
        else eingabe.removeAttribute('aria-activedescendant');
    }

    function ansagen() {
        var n = st.items.length;
        statusEl.textContent = n ? (n === 1 ? t('treffer_1') : t('treffer_n', { n: n })) : t('leer', { q: st.q });
    }

    // ---------- Öffnen, Schliessen ----------
    function popOffen() { return !pop.hidden; }
    function popAuf() {
        if (pop.hidden) pop.hidden = false;
        eingabe.setAttribute('aria-expanded', 'true');
    }
    function popZu() {
        pop.hidden = true;
        eingabe.setAttribute('aria-expanded', 'false');
        eingabe.removeAttribute('aria-activedescendant');
    }
    function abbrechen() {
        clearTimeout(st.timer);
        st.seq++;
        if (st.ctrl) { try { st.ctrl.abort(); } catch (e) { /* schon fertig */ } st.ctrl = null; }
    }
    function schliessen(fokusZurueck) {
        abbrechen();
        popZu();
        wurzel.classList.remove('offen');
        if (fokusZurueck) {
            var v = st.vorher;
            if (v && v !== eingabe && document.documentElement.contains(v) && typeof v.focus === 'function') v.focus();
            else if (document.activeElement && wurzel.contains(document.activeElement)) document.activeElement.blur();
        }
        st.vorher = null;
    }

    // ---------- Anfrage ----------
    function holen() {
        var q = st.q;
        if (q.length < MIN_ZEICHEN) return;
        if (st.ctrl) { try { st.ctrl.abort(); } catch (e) { /* schon fertig */ } }
        var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
        st.ctrl = ctrl;
        var nr = ++st.seq;
        var opt = { headers: { 'X-Requested-With': 'fetch', 'Accept': 'application/json' }, credentials: 'same-origin' };
        if (ctrl) opt.signal = ctrl.signal;
        fetch(PALETTE_URL + '?q=' + encodeURIComponent(q), opt)
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
            .then(function (d) {
                if (nr !== st.seq) return;               // eine neuere Anfrage ist unterwegs
                st.ctrl = null;
                st.daten = aufbereiten(d);
                st.datenQ = q;
                st.status = 'ok';
                st.sel = 0;
                render();
                ansagen();
            })
            .catch(function (e) {
                if (e && e.name === 'AbortError') return;
                if (nr !== st.seq) return;
                st.ctrl = null;
                st.daten = null;                          // alte Treffer wären hier eine Behauptung
                st.datenQ = '';
                st.status = 'fehler';
                render();
            });
    }

    function eingegeben() {
        var q = eingabe.value.trim();
        st.q = q;
        if (q.length < MIN_ZEICHEN) {
            abbrechen();
            st.daten = null; st.datenQ = ''; st.status = 'ruhe'; st.filter = 'alle';
            popZu();
            return;
        }
        wurzel.classList.add('offen');
        popAuf();
        st.status = 'laedt';
        st.sel = 0;
        render();
        clearTimeout(st.timer);
        st.timer = setTimeout(holen, VERZOEGERUNG);
    }

    // ---------- Ereignisse ----------
    eingabe.addEventListener('input', eingegeben);
    eingabe.addEventListener('focus', function (e) {
        wurzel.classList.add('offen');
        if (e.relatedTarget && !wurzel.contains(e.relatedTarget)) st.vorher = e.relatedTarget;
        if (eingabe.value.trim().length >= MIN_ZEICHEN && !popOffen()) eingegeben();
    });
    eingabe.addEventListener('keydown', function (e) {
        var n = st.items.length;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            if (!popOffen()) { if (eingabe.value.trim().length >= MIN_ZEICHEN) { e.preventDefault(); eingegeben(); } return; }
            if (!n) return;
            e.preventDefault();
            markiere(e.key === 'ArrowDown' ? Math.min(n - 1, st.sel + 1) : Math.max(0, st.sel - 1), true);
        } else if (e.key === 'Enter') {
            var it = popOffen() ? st.items[st.sel] : null;
            if (!it) return;                              // kein Treffer gewählt: das Formular sucht ausführlich
            e.preventDefault();
            if (e.metaKey || e.ctrlKey) window.open(it.url, '_blank', 'noopener');
            else window.location.href = it.url;
        }
    });
    // Esc gilt im ganzen Bereich (Feld, Kapseln, Treffer), nicht nur im Feld.
    wurzel.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && (popOffen() || wurzel.classList.contains('offen'))) { e.preventDefault(); schliessen(true); }
    });
    liste.addEventListener('mousemove', function (e) {
        var o = e.target.closest ? e.target.closest('[role="option"]') : null;
        if (o && +o.getAttribute('data-i') !== st.sel) markiere(+o.getAttribute('data-i'), false);
    });
    liste.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('[data-os-nochmals]')) {
            st.status = 'laedt'; render(); holen();
        }
    });
    filterEl.addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('button[data-f]') : null;
        if (!b || b.disabled) return;
        st.filter = b.getAttribute('data-f');
        st.sel = 0;
        render();
    });
    // Klicks im Popover nehmen dem Feld den Fokus nicht (Kapseln, Ränder).
    pop.addEventListener('mousedown', function (e) { e.preventDefault(); });
    document.addEventListener('pointerdown', function (e) {
        if (wurzel.classList.contains('offen') && !wurzel.contains(e.target)) schliessen(false);
    });
    wurzel.addEventListener('focusout', function (e) {
        var n = e.relatedTarget;
        if (n && !wurzel.contains(n)) schliessen(false);
    });
    if (zuKnopf) zuKnopf.addEventListener('click', function () { schliessen(true); });
    window.addEventListener('pageshow', function (e) { if (e.persisted) schliessen(false); });

    function fokussieren() {
        var a = document.activeElement;
        if (a && a !== document.body && !wurzel.contains(a)) st.vorher = a;
        eingabe.focus();
        eingabe.select();
    }
    document.addEventListener('keydown', function (e) {
        if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            fokussieren();
        }
    });
    window.fwSucheOeffnen = fokussieren;

    // Tastenhinweise: ⌘ auf dem Mac, sonst «Strg».
    if (!istMac()) {
        if (taste) taste.textContent = t('strg') + ' K';
        Array.prototype.forEach.call(wurzel.querySelectorAll('[data-os-meta]'), function (k) { k.textContent = t('strg'); });
    }
})();
