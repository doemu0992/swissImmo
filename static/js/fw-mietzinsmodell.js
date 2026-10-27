/* Mietzinsmodell im Vertragsassistenten (27.10.2026): fest, Staffel oder Index.
 *
 * EINE Regelquelle: Dieses Skript kennt KEINE Mietrechtsregeln. Es schickt die Eingaben an
 * `GET /neu/vertraege/mietzinsmodell/pruefen/` (core/services/mietzinsmodell.py) und zeigt die
 * Befunde: Ampel für die feste Dauer, Meldungen an den Staffelzeilen, Fix-Knöpfe, Sperre. Was
 * es selbst rechnet, ist Darstellung: Datumsarithmetik für den Zeilengenerator, die Beispiel-
 * rechnung des Indexes (nur Anzeige) und die Umrechnung der Objekt-Staffelvorlage.
 *
 * Seite: fw/vertrag_neu.html. Wurzel `#mzm`, Konfiguration `#mzm-config` (JSON), Vorlagen für
 * Zeichen `<template data-mzm-zeichen="…">`. Daten gelangen nie als HTML in die Seite: Alles geht
 * über textContent und Attribute.
 *
 * Schnittstelle (window.fwMzm):
 *   init({geaendert})        einmal, nach dem Laden der Seite
 *   planen()                 Prüfung anstossen (entprellt)
 *   setzeModell(m, still)    Modell wählen; ohne `still` räumt der Wechsel das andere Modell
 *   stufenSetzen([{ab, erhoehung}])
 *   vorlage([{ab, netto}])   Objekt-Staffelvorlage (absolute Beträge) in Erhöhungen umrechnen
 *   modell()                 'fest' | 'staffel' | 'index'
 *   zusammenfassung()        [[Beschriftung, Wert], …] für den Abschluss
 */
(function () {
    'use strict';

    var W = null, A = null, K = {}, T = {};
    var zustand = { sperre: false, grund: '', weitere: 0, schritt: null, antwort: null, nichtErreichbar: false };
    var angewandt = 'fest';
    var seq = 0, timer = null, abbruch = null, rueckTimer = null, geaendert = null;

    function $(id) { return document.getElementById(id); }
    function el(tag, klasse, text) {
        var e = document.createElement(tag);
        if (klasse) e.className = klasse;
        if (text != null) e.textContent = text;
        return e;
    }
    function vorlageZeichen(name) {
        var t = W.querySelector('template[data-mzm-zeichen="' + name + '"]');
        return t ? t.content.firstElementChild.cloneNode(true) : null;
    }
    function ersetze(text, werte) {
        return String(text || '').replace(/\{(\w+)\}/g, function (m, k) { return werte && k in werte ? werte[k] : m; });
    }
    function pad(n, l) { n = String(n); while (n.length < (l || 2)) n = '0' + n; return n; }

    // ── Datum und Zahl (Darstellung) ────────────────────────────────────────────────────────────
    function dstr(iso) {
        var p = (iso || '').split('-');
        return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : '';
    }
    function mstr(ym) {
        var p = (ym || '').split('-');
        return p.length >= 2 ? p[1] + '.' + p[0] : '';
    }
    function schalt(y) { return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0; }
    // Gleicher Tag n Jahre später; der 29. Februar wird zum 1. März (wie core/services/mietzinsmodell.py)
    function plusJahr(iso, n) {
        var p = (iso || '').split('-');
        if (p.length !== 3) return '';
        var y = +p[0] + n, m = +p[1], d = +p[2];
        if (!y || !m || !d) return '';
        if (m === 2 && d === 29 && !schalt(y)) { m = 3; d = 1; }
        return pad(y, 4) + '-' + pad(m) + '-' + pad(d);
    }
    function bruch(t) {
        t = String(t == null ? '' : t).trim().replace(/['’\s]/g, '').replace(',', '.');
        if (!/^-?\d+(\.\d+)?$/.test(t)) return null;
        var teile = t.split('.');
        return { n: BigInt(teile[0] + (teile[1] || '')), d: BigInt(10) ** BigInt((teile[1] || '').length) };
    }
    function chfCents(cents) {
        var neg = cents < 0n; if (neg) cents = -cents;
        var ganz = (cents / 100n).toString(), rest = pad((cents % 100n).toString(), 2);
        ganz = ganz.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
        return (neg ? '-' : '') + ganz + '.' + rest;
    }
    function rundeHalbHoch(zaehler, nenner) { return (2n * zaehler + nenner) / (2n * nenner); }
    // Text einer Zahl als CHF mit zwei Stellen (kaufmännisch gerundet); '—' wenn nicht lesbar
    function chfText(t) {
        var b = bruch(t);
        if (!b) return '—';
        var neg = b.n < 0n, n = neg ? -b.n : b.n;
        var c = rundeHalbHoch(n * 100n, b.d);
        return chfCents(neg ? -c : c);
    }

    // ── Zugriff auf die Felder ──────────────────────────────────────────────────────────────────
    function modell() {
        var r = W && W.querySelector('input[name="mietzins_modell"]:checked');
        return r ? r.value : 'fest';
    }
    function wert(id) { var e = $(id); return e ? e.value : ''; }
    function zeilen() { return Array.prototype.slice.call($('mzm-staffel-zeilen').children); }
    function zeilenFelder(z) {
        return { ab: z.querySelector('[name="staffel_ab"]'), erh: z.querySelector('[name="staffel_erhoehung"]') };
    }
    function inhaltZeile(z) { var f = zeilenFelder(z); return !!(f.ab.value || f.erh.value); }
    function angeklickt() { if (typeof geaendert === 'function') geaendert(); else planen(); }

    // ── Staffelzeilen ───────────────────────────────────────────────────────────────────────────
    function nummerieren() {
        zeilen().forEach(function (z, i) {
            var nr = i + 1;
            z.querySelector('.fw-mzm-zeile-titel').textContent = ersetze(T.stufe, { n: nr });
            var weg = z.querySelector('.fw-mzm-weg');
            weg.setAttribute('aria-label', ersetze(T.stufe_weg, { n: nr }));
            weg.title = ersetze(T.stufe_weg, { n: nr });
        });
        W.querySelector('#mzm-panel-staffel').classList.toggle('leer', zeilen().length === 0);
    }
    function zeileNeu(ab, erh) {
        var z = el('div', 'fw-mzm-zeile'); z.setAttribute('role', 'listitem');
        var kopf = el('div', 'fw-mzm-zeile-kopf');
        kopf.appendChild(el('span', 'fw-mzm-zeile-titel fw-label'));
        var weg = el('button', 'fw-btn fw-knapp fw-leise fw-mzm-weg'); weg.type = 'button';
        var ikon = vorlageZeichen('loeschen'); if (ikon) weg.appendChild(ikon);
        weg.addEventListener('click', function () {
            z.remove(); nummerieren(); minAktualisieren(); angeklickt();
        });
        kopf.appendChild(weg);
        z.appendChild(kopf);

        var felder = el('div', 'fw-mzm-zeile-felder');
        var l1 = el('label', 'fw-mzm-feld'); l1.appendChild(el('span', null, T.ab));
        var i1 = el('input', 'fw-feld'); i1.type = 'date'; i1.name = 'staffel_ab'; i1.value = ab || '';
        l1.appendChild(i1);
        var l2 = el('label', 'fw-mzm-feld'); l2.appendChild(el('span', null, T.plus_chf));
        var i2 = el('input', 'fw-feld fw-num'); i2.type = 'number'; i2.step = '0.01'; i2.name = 'staffel_erhoehung';
        i2.inputMode = 'decimal'; i2.value = erh || '';
        l2.appendChild(i2);
        felder.appendChild(l1); felder.appendChild(l2);
        z.appendChild(felder);

        var neu = el('p', 'fw-mzm-neu'); neu.appendChild(document.createTextNode(T.neu_vor + ' '));
        var out = el('output', null, '—'); out.setAttribute('aria-live', 'off');
        neu.appendChild(out);
        z.appendChild(neu);
        z.appendChild(el('div', 'fw-mzm-zeile-fehler'));

        [i1, i2].forEach(function (i) {
            i.addEventListener('input', function () { minAktualisieren(); angeklickt(); });
        });
        if ($('mzm-panel-staffel').classList.contains('hidden')) { i1.disabled = true; i2.disabled = true; }
        $('mzm-staffel-zeilen').appendChild(z);
        nummerieren(); minAktualisieren();
        return z;
    }
    function stufenSetzen(liste) {
        $('mzm-staffel-zeilen').textContent = '';
        (liste || []).forEach(function (s) { zeileNeu(s.ab, s.erhoehung); });
        nummerieren(); minAktualisieren();
    }
    // `min` der Datumsfelder: Vorstufe plus ein Jahr. Vorstufe einer Zeile ist die späteste ANDERE Zeile,
    // die vor ihr liegt, sonst der Mietbeginn — unabhängig von der Reihenfolge der Eingabe, wie die Regel.
    function minAktualisieren() {
        var beginn = wert('s_beginn');
        var alle = zeilen().map(function (z) { return zeilenFelder(z).ab; });
        alle.forEach(function (feld) {
            var eigen = feld.value, vor = '';
            alle.forEach(function (anderes) {
                if (anderes === feld || !anderes.value) return;
                if (eigen ? anderes.value < eigen : true) { if (anderes.value > vor) vor = anderes.value; }
            });
            var grund = vor || beginn;
            if (grund) feld.min = plusJahr(grund, 1); else feld.removeAttribute('min');
        });
    }
    function generieren() {
        var hinweis = $('mzm-gen-hinweis'); hinweis.textContent = '';
        var beginn = wert('s_beginn');
        var b = bruch(wert('mzm-gen-betrag'));
        var anzahl = parseInt(wert('mzm-gen-anzahl'), 10);
        if (!beginn) { hinweis.textContent = T.gen_beginn; return; }
        if (!b || b.n <= 0n) { hinweis.textContent = T.gen_betrag; $('mzm-gen-betrag').focus(); return; }
        if (!(anzahl >= 1 && anzahl <= K.stufen_max)) {
            hinweis.textContent = ersetze(T.gen_anzahl, { max: K.stufen_max }); $('mzm-gen-anzahl').focus(); return;
        }
        var betrag = chfText(wert('mzm-gen-betrag')).replace(/'/g, '');
        var liste = [], vor = beginn;
        for (var i = 0; i < anzahl; i++) { vor = plusJahr(vor, 1); liste.push({ ab: vor, erhoehung: betrag }); }
        stufenSetzen(liste);
        angeklickt();
    }
    // Objekt-Staffelvorlage: absolute Nettobeträge → Erhöhungen in CHF, gerechnet ab dem Netto im Mietzinsfeld.
    function vorlage(plan) {
        var start = bruch(wert('s_netto'));
        var vorCents = start ? rundeHalbHoch(start.n * 100n, start.d) : 0n;
        var liste = (plan || []).map(function (s) {
            var cents = BigInt(Math.round(Number(s.netto) * 100));
            var erh = cents - vorCents; vorCents = cents;
            return { ab: s.ab, erhoehung: chfCents(erh).replace(/'/g, '') };
        });
        stufenSetzen(liste);
    }

    // ── Modellwechsel ───────────────────────────────────────────────────────────────────────────
    var INDEX_STANDARD = { s_weitergabe: '100', s_intervall: '12' };
    function indexHatDaten() {
        return !!(wert('s_lik') || wert('s_lik_stand') ||
                  wert('s_weitergabe') !== INDEX_STANDARD.s_weitergabe || wert('s_intervall') !== INDEX_STANDARD.s_intervall);
    }
    function indexRaeumen() {
        ['s_lik', 's_lik_stand'].forEach(function (id) { var e = $(id); e.value = ''; delete e.dataset.manuell; });
        Object.keys(INDEX_STANDARD).forEach(function (id) { $(id).value = INDEX_STANDARD[id]; });
    }
    function panelSetzen(m) {
        [['mzm-panel-staffel', 'staffel'], ['mzm-panel-index', 'index']].forEach(function (p) {
            var panel = $(p[0]), aktiv = (m === p[1]);
            panel.classList.toggle('hidden', !aktiv);
            panel.querySelectorAll('input, select, textarea, button').forEach(function (f) {
                if (f.matches('[data-mzm-immer]')) return;
                f.disabled = !aktiv;
            });
        });
        // Beschriftung der Kacheln: die gewählte trägt den Akzent
        W.querySelectorAll('.fw-mzm-kachel').forEach(function (k) {
            k.classList.toggle('akzent', k.querySelector('input').checked);
        });
        $('mzm-ampel').classList.toggle('hidden', m === 'fest');
    }
    function rueckmeldung(text) {
        var r = $('mzm-rueck');
        r.textContent = text || '';
        r.classList.toggle('hidden', !text);
        clearTimeout(rueckTimer);
        if (text) rueckTimer = setTimeout(function () { r.textContent = ''; r.classList.add('hidden'); }, 9000);
    }
    function setzeModell(m, still) {
        // «alt» ist das zuletzt angewandte Modell: Beim `change` des Radios steht das neue schon als gewählt.
        var alt = angewandt;
        var r = W.querySelector('input[name="mietzins_modell"][value="' + m + '"]');
        if (!r) return;
        r.checked = true;
        angewandt = m;
        if (alt !== m) {
            var meldungen = [];
            if (alt === 'staffel' && zeilen().some(inhaltZeile)) { meldungen.push(T.rueck_staffel); }
            if (alt === 'index' && indexHatDaten()) { meldungen.push(T.rueck_index); }
            // Das andere Modell räumen: Es dürfen keine Daten des anderen Modells gesendet werden.
            if (alt === 'staffel') stufenSetzen([]);
            if (alt === 'index') indexRaeumen();
            if (!still) rueckmeldung(meldungen.join(' · '));
        }
        panelSetzen(m);
        if (m === 'staffel' && !zeilen().length) zeileNeu('', '');
        if (m !== 'staffel' && zeilen().length) stufenSetzen([]);
        minAktualisieren();
        planen();
    }

    // ── Prüfung am Server ───────────────────────────────────────────────────────────────────────
    function parameter() {
        var m = modell(), q = new URLSearchParams();
        q.set('modell', m);
        if (wert('s_beginn')) q.set('beginn', wert('s_beginn'));
        var unbefristet = $('unbefristet').checked;
        q.set('ist_befristet', unbefristet ? '0' : '1');
        if (!unbefristet && wert('s_ende')) q.set('ende', wert('s_ende'));
        if (unbefristet && wert('s_verzicht')) q.set('verzicht_bis', wert('s_verzicht'));
        if (wert('s_netto')) q.set('netto', wert('s_netto'));
        if (W.dataset.zeitplan === '1') q.set('hat_zeitplan', '1');
        if (m === 'staffel') {
            zeilen().forEach(function (z) {
                var f = zeilenFelder(z);
                q.append('staffel_ab', f.ab.value); q.append('staffel_erhoehung', f.erh.value);
            });
        }
        if (m === 'index') {
            if (wert('s_lik')) q.set('basis_lik_punkte', wert('s_lik'));
            if (wert('s_lik_stand')) q.set('basis_lik_stand', wert('s_lik_stand'));
            if (wert('s_weitergabe')) q.set('index_weitergabe_prozent', wert('s_weitergabe'));
            if (wert('s_intervall')) q.set('index_intervall_monate', wert('s_intervall'));
        }
        return q;
    }
    function planen() {
        if (!W) return;
        startAnzeigen();
        minAktualisieren();
        beispiel();
        clearTimeout(timer);
        if (modell() === 'fest') {
            seq++; if (abbruch) abbruch.abort();
            zustand.antwort = null; zustand.nichtErreichbar = false;
            anzeigen(null);
            return;
        }
        timer = setTimeout(pruefen, 160);
    }
    function pruefen() {
        var mein = ++seq;
        if (abbruch) abbruch.abort();
        abbruch = typeof AbortController === 'function' ? new AbortController() : null;
        fetch(K.url + '?' + parameter().toString(), {
            credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' },
            signal: abbruch ? abbruch.signal : undefined
        }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (a) {
                if (mein !== seq) return;
                zustand.antwort = a; zustand.nichtErreichbar = false;
                anzeigen(a);
            }).catch(function (e) {
                if (mein !== seq || (e && e.name === 'AbortError')) return;
                // Unerreichbar ist keine Sperre: Der Server prüft beim Speichern ohnehin.
                zustand.antwort = null; zustand.nichtErreichbar = true;
                anzeigen(null);
            });
    }

    // ── Anzeige ─────────────────────────────────────────────────────────────────────────────────
    function startAnzeigen() {
        $('mzm-start').textContent = 'CHF ' + chfText(wert('s_netto'));
    }
    function fixKnopf(fix) {
        var b = el('button', 'fw-btn fw-knapp fw-rand-marke', fix.label); b.type = 'button';
        b.addEventListener('click', function () { fixAnwenden(fix); });
        return b;
    }
    var FELD_ID = {
        ende: 's_ende', vermieter_kuendigungsverzicht_bis: 's_verzicht', basis_lik_punkte: 's_lik',
        basis_lik_stand: 's_lik_stand', index_weitergabe_prozent: 's_weitergabe', index_intervall_monate: 's_intervall'
    };
    function fixAnwenden(fix) {
        var f = fix.feld, ziel = null;
        if (f === 'staffelstufen') {
            stufenSetzen(fix.wert || []);
        } else if (f === 'staffel_ab') {
            var z = zeilen()[fix.zeile];
            if (z) { ziel = zeilenFelder(z).ab; ziel.value = fix.wert; }
        } else if (FELD_ID[f]) {
            ziel = $(FELD_ID[f]);
            if (!ziel || ziel.disabled) return;
            ziel.value = fix.wert;
        }
        // `input` auslösen: Vorschau und Prüfung folgen wie bei einer Eingabe
        if (ziel) ziel.dispatchEvent(new Event('input', { bubbles: true }));
        else angeklickt();
        minAktualisieren();
    }
    function ikonFuer(stufe) { return vorlageZeichen(stufe === 'sperre' ? 'kritisch' : 'hinweis'); }

    function meldung(klasse, text, artikel, fix, ikon) {
        var d = el('div', 'fw-hinweis ' + klasse);
        var hi = el('span', 'fw-hi'); if (ikon) hi.appendChild(ikon); d.appendChild(hi);
        var ht = el('div', 'fw-ht fliess');
        ht.appendChild(document.createTextNode(text));
        if (artikel) { var a = el('span', 'fw-mzm-artikel', ' ' + artikel); ht.appendChild(a); }
        if (fix) { var wrap = el('div', 'fw-mzm-fix'); wrap.appendChild(fixKnopf(fix)); ht.appendChild(wrap); }
        d.appendChild(ht);
        return d;
    }
    function ampelZeichnen(a, beginnFehlt) {
        var box = $('mzm-ampel'), chip = $('mzm-ampel-chip'), text = $('mzm-ampel-text'), fix = $('mzm-ampel-fix');
        fix.textContent = '';
        box.classList.remove('gut', 'krit', 'offen');
        if (modell() === 'fest') return;
        var dauer = a && a.befunde.filter(function (b) { return b.regel === 'index_dauer' || b.regel === 'staffel_dauer'; })[0];
        if (beginnFehlt) {
            box.classList.add('offen'); chip.className = 'fw-chip fw-dot fw-info'; chip.textContent = T.ampel_offen;
            text.textContent = T.beginn_fehlt;
        } else if (!a) {
            box.classList.add('offen'); chip.className = 'fw-chip fw-dot fw-mut';
            chip.textContent = zustand.nichtErreichbar ? T.ampel_unbekannt : T.ampel_laedt;
            text.textContent = zustand.nichtErreichbar ? T.nicht_erreichbar : '';
        } else if (dauer) {
            box.classList.add('krit'); chip.className = 'fw-chip fw-dot fw-crit'; chip.textContent = T.ampel_nok;
            text.textContent = dauer.text;
            if (dauer.artikel) text.appendChild(el('span', 'fw-mzm-artikel', ' ' + dauer.artikel));
            if (dauer.fix) fix.appendChild(fixKnopf(dauer.fix));
        } else {
            box.classList.add('gut'); chip.className = 'fw-chip fw-dot fw-good'; chip.textContent = T.ampel_ok;
            text.textContent = ersetze(T.ampel_ok_text, {
                bis: dstr(a.abgeleitet.fest_bis), soll: dstr(a.abgeleitet.mindest_ende), jahre: K.jahre[modell()]
            });
        }
    }
    var BLEIBT_IN_LISTE_NICHT = { index_dauer: 1, staffel_dauer: 1, index_anpassung: 1, staffel_mitteilung: 1 };
    function befundeZeichnen(a) {
        var liste = $('mzm-befunde'); liste.textContent = '';
        if (!a) return;
        a.befunde.forEach(function (b) {
            if (BLEIBT_IN_LISTE_NICHT[b.regel] || b.zeile != null) return;
            liste.appendChild(meldung(b.stufe === 'sperre' ? 'crit' : 'info', b.text, b.artikel, b.fix, ikonFuer(b.stufe)));
        });
    }
    function zeilenZeichnen(a) {
        var rows = zeilen();
        // abgeleitete Stufen (nach Datum sortiert, nur vollständige Zeilen) den Zeilen zuordnen
        var frei = a ? a.abgeleitet.stufen.slice() : [];
        var neuWert = rows.map(function (z) {
            var f = zeilenFelder(z), ab = f.ab.value, e = bruch(f.erh.value);
            if (!a || !ab || !e) return null;
            for (var i = 0; i < frei.length; i++) {
                var s = frei[i], se = bruch(s.erhoehung);
                if (s.ab === ab && se && se.n * e.d === e.n * se.d) { frei.splice(i, 1); return s.neu; }
            }
            return null;
        });
        rows.forEach(function (z, i) {
            var out = z.querySelector('output');
            out.textContent = neuWert[i] != null ? chfText(neuWert[i]) : '—';
            var kasten = z.querySelector('.fw-mzm-zeile-fehler'); kasten.textContent = '';
            var f = zeilenFelder(z);
            [f.ab, f.erh].forEach(function (x) { x.removeAttribute('aria-invalid'); x.removeAttribute('aria-describedby'); });
            var fehler = a ? a.befunde.filter(function (b) { return b.zeile === i; }) : [];
            fehler.forEach(function (b, k) {
                var p = el('div', 'fw-mzm-zeilenbefund'); p.id = 'mzm-z' + i + '-' + k;
                p.appendChild(el('p', 'fw-feldfehler', b.text + (b.artikel ? ' (' + b.artikel + ')' : '')));
                if (b.fix) p.appendChild(fixKnopf(b.fix));
                kasten.appendChild(p);
                var ziel = b.feld === 'staffel_erhoehung' ? f.erh : (b.feld === 'staffel_ab' ? f.ab : null);
                (ziel ? [ziel] : [f.ab, f.erh]).forEach(function (x) {
                    if (b.stufe === 'sperre') { x.setAttribute('aria-invalid', 'true'); x.setAttribute('aria-describedby', p.id); }
                });
            });
            z.toggleAttribute('data-fehler', fehler.some(function (b) { return b.stufe === 'sperre'; }));
        });
    }
    // Felder, die ein Befund meint, bekommen aria-invalid (nur von hier gesetzt, nur hier entfernt)
    function felderMarkieren(a) {
        document.querySelectorAll('[data-mzm-markiert]').forEach(function (e) {
            e.removeAttribute('aria-invalid'); e.removeAttribute('aria-describedby'); e.removeAttribute('data-mzm-markiert');
        });
        if (!a) return;
        a.befunde.forEach(function (b) {
            if (b.stufe !== 'sperre' || b.zeile != null || !FELD_ID[b.feld]) return;
            var e = $(FELD_ID[b.feld]);
            if (e && !e.disabled) { e.setAttribute('aria-invalid', 'true'); e.setAttribute('data-mzm-markiert', '1'); e.setAttribute('aria-describedby', 'mzm-befunde'); }
        });
    }
    function basisVorschlag(a) {
        var hin = $('mzm-vorschlag'), knopf = $('mzm-vorschlag-knopf');
        hin.textContent = ''; knopf.classList.add('hidden');
        if (modell() !== 'index' || !a || !wert('s_beginn')) return;
        var v = a.abgeleitet.basis_lik;
        if (!v || !v.punkte || !v.stand) { hin.textContent = T.vorschlag_keiner; return; }
        hin.textContent = ersetze(T.vorschlag, { punkte: v.punkte, stand: mstr(v.stand) });
        // Vorbelegen nur, solange niemand die Felder selbst angefasst hat
        var gefuellt = false;
        [['s_lik', v.punkte], ['s_lik_stand', v.stand]].forEach(function (p) {
            var e = $(p[0]);
            if (!e.dataset.manuell && e.value !== p[1]) { e.value = p[1]; gefuellt = true; }
        });
        knopf.classList.toggle('hidden', wert('s_lik') === v.punkte && wert('s_lik_stand') === v.stand);
        knopf.onclick = function () {
            $('s_lik').value = v.punkte; $('s_lik_stand').value = v.stand;
            delete $('s_lik').dataset.manuell; delete $('s_lik_stand').dataset.manuell;
            angeklickt();
        };
        if (gefuellt) angeklickt();
    }

    // Beispielrechnung (nur Anzeige): neu = Netto × (1 + (LIK − Basis) / Basis × Weitergabe), auf 5 Rappen.
    // Gleiche Rechnung und Rundung wie mietrecht.index_anpassung_vorschlag / runde_mietzins.
    function beispiel() {
        var p = $('mzm-beispiel'); p.textContent = '';
        if (modell() !== 'index') { p.classList.add('hidden'); return; }
        var netto = bruch(wert('s_netto')), basis = bruch(wert('s_lik')), w = bruch(wert('s_weitergabe')), akt = bruch(String(K.aktueller_lik || ''));
        if (!netto || !basis || !w || !akt || basis.n <= 0n || netto.n < 0n) { p.classList.add('hidden'); return; }
        // faktor = (ad·bn·wd·100 + (an·bd − bn·ad)·wn) / (ad·bn·wd·100)
        var diff = akt.n * basis.d - basis.n * akt.d;
        var fz = akt.d * basis.n * w.d * 100n + diff * w.n, fn = akt.d * basis.n * w.d * 100n;
        var einheiten = rundeHalbHoch(20n * netto.n * fz, netto.d * fn);   // Vielfache von 5 Rappen
        if (einheiten < 0n) { p.classList.add('hidden'); return; }
        var neuCents = einheiten * 5n;
        var altCents = rundeHalbHoch(netto.n * 100n, netto.d);
        p.textContent = ersetze(neuCents === altCents ? T.beispiel_gleich : T.beispiel,
            { lik: String(K.aktueller_lik), neu: chfCents(neuCents), alt: chfCents(altCents) });
        p.classList.remove('hidden');
    }

    // ── Sperre ──────────────────────────────────────────────────────────────────────────────────
    function sperreSetzen(grund, weitere) {
        var radio = W.querySelector('input[name="mietzins_modell"]:checked');
        W.querySelectorAll('input[name="mietzins_modell"]').forEach(function (r) { r.setCustomValidity(''); });
        if (radio && grund) radio.setCustomValidity(grund);
        zustand.sperre = !!grund; zustand.grund = grund || ''; zustand.weitere = weitere || 0;
        knoepfe();
    }
    function nachMietzinsSchritt() {
        var s = zustand.schritt, r = W.closest('[data-schritt]');
        if (!s || !r) return false;
        return s === r || !!(r.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING);
    }
    function knoepfe() {
        var block = zustand.sperre && nachMietzinsSchritt();
        var weiter = A.querySelector('[data-assistent-weiter]');
        if (weiter) { weiter.disabled = block; weiter.setAttribute('aria-disabled', block ? 'true' : 'false'); }
        A.querySelectorAll('[data-assistent-absenden]').forEach(function (b) {
            b.disabled = block; b.setAttribute('aria-disabled', block ? 'true' : 'false');
        });
        var fuss = $('mzm-fuss');
        fuss.classList.toggle('hidden', !block);
        if (block) {
            var t = fuss.querySelector('.fw-mzm-fuss-text');
            t.textContent = ersetze(T.fuss_gesperrt, { grund: zustand.grund }) +
                (zustand.weitere ? ' ' + ersetze(T.fuss_weitere, { n: zustand.weitere }) : '');
        }
    }

    function anzeigen(a) {
        var m = modell();
        var beginnFehlt = m !== 'fest' && !wert('s_beginn');
        ampelZeichnen(a, beginnFehlt);
        befundeZeichnen(a);
        zeilenZeichnen(a);
        felderMarkieren(a);
        basisVorschlag(a);
        beispiel();
        var sperren = a ? a.befunde.filter(function (b) { return b.stufe === 'sperre'; }) : [];
        if (m === 'fest') { sperreSetzen('', 0); return; }
        if (beginnFehlt) { sperreSetzen(T.beginn_fehlt, 0); return; }
        if (sperren.length) sperreSetzen(sperren[0].text, sperren.length - 1);
        else sperreSetzen('', 0);
    }

    function zusammenfassung() {
        var m = modell(), z = [[T.zus_modell, T.modelle[m]]];
        if (m === 'fest') return z;
        var a = zustand.antwort;
        if (a && a.abgeleitet.fest_bis) z.push([T.zus_fest_bis, dstr(a.abgeleitet.fest_bis)]);
        if (m === 'staffel') {
            zeilen().forEach(function (zeile, i) {
                var f = zeilenFelder(zeile);
                if (f.ab.value && f.erh.value) {
                    z.push([ersetze(T.stufe, { n: i + 1 }), dstr(f.ab.value) + ' · + CHF ' + chfText(f.erh.value) +
                        ' → CHF ' + zeile.querySelector('output').textContent]);
                }
            });
        } else {
            z.push([T.zus_basis, wert('s_lik') + ' · ' + mstr(wert('s_lik_stand'))]);
            z.push([T.zus_weitergabe, wert('s_weitergabe') + ' %']);
        }
        return z;
    }

    function init(opt) {
        W = $('mzm');
        if (!W) return;
        A = W.closest('.fw-assistent');
        var cfg = JSON.parse($('mzm-config').textContent);
        K = cfg; T = cfg.texte;
        geaendert = opt && opt.geaendert;
        W.querySelectorAll('input[name="mietzins_modell"]').forEach(function (r) {
            r.addEventListener('change', function () { setzeModell(r.value); angeklickt(); });
        });
        ['s_lik', 's_lik_stand'].forEach(function (id) {
            $(id).addEventListener('input', function () {
                if (this.value) this.dataset.manuell = '1'; else delete this.dataset.manuell;
            });
        });
        // Felder anderer Schritte, von denen die Prüfung abhängt
        ['s_beginn', 's_ende', 's_verzicht', 's_netto', 's_lik', 's_lik_stand', 's_weitergabe', 's_intervall'].forEach(function (id) {
            var e = $(id); if (e) e.addEventListener('input', function () { planen(); });
        });
        var un = $('unbefristet'); if (un) un.addEventListener('change', planen);
        $('mzm-gen-knopf').addEventListener('click', generieren);
        $('mzm-zu-laufzeit').addEventListener('click', function () {
            var ziel = $('unbefristet').checked ? $('s_verzicht') : $('s_ende');
            if (A.fwAssistent && A.fwAssistent.zeigeFeld(ziel)) return;
            ziel.focus();
        });
        $('mzm-stufe-neu').addEventListener('click', function () { zeileNeu('', '').querySelector('input').focus(); angeklickt(); });
        $('mzm-fuss').querySelector('.fw-mzm-fuss-text').addEventListener('click', function () {
            var r = W.querySelector('input[name="mietzins_modell"]:checked');
            if (r && A.fwAssistent && A.fwAssistent.zeigeFeld(r)) return;
            if (r) r.focus();
        });
        A.addEventListener('fw-assistent:zeige', function (e) { zustand.schritt = e.detail.schritt; knoepfe(); });
        angewandt = modell();
        panelSetzen(modell());
        nummerieren();
        startAnzeigen();
        planen();
    }

    window.fwMzm = {
        init: init, planen: planen, setzeModell: setzeModell, stufenSetzen: stufenSetzen, vorlage: vorlage,
        modell: modell, zusammenfassung: zusammenfassung,
        // für die Tests im Browser
        _zustand: zustand, _beispiel: beispiel
    };
})();
