/* Zahlungs-Cockpit V12 (26.10.2026): Reiter der Arbeitslisten, Sammelauswahl,
 * und der Assistent «Zahlung aufteilen» (Split-Screen).
 *
 * Alles ist Zugabe: Ohne JavaScript stehen die Listen untereinander, und der
 * Assistent ist ein normales Formular (Beträge eintippen, Rest wählen,
 * speichern). Der Server prüft jede Zuteilung selbst — hier wird nur
 * angezeigt, gerechnet und vorgeschlagen.
 */
(function () {
    'use strict';

    function chf(n) {
        var s = (Math.round(n * 100) / 100).toFixed(2).split('.');
        return s[0].replace(/\B(?=(\d{3})+(?!\d))/g, '’') + '.' + s[1];
    }
    function zahl(s) {
        var t = String(s || '').replace(/[\s'’]/g, '').replace(',', '.');
        var n = parseFloat(t);
        return isNaN(n) ? 0 : Math.round(n * 100) / 100;
    }

    /* ---------- Reiter der Arbeitslisten ---------- */
    function spuren() {
        var leiste = document.querySelector('[data-spuren]');
        if (!leiste) return;
        var inhalte = document.querySelectorAll('[data-spur-inhalt]');
        function zeige(name, merken) {
            inhalte.forEach(function (s) { s.classList.toggle('aus', s.getAttribute('data-spur-inhalt') !== name); });
            leiste.querySelectorAll('[data-spur]').forEach(function (a) {
                var an = a.getAttribute('data-spur') === name;
                a.classList.toggle('hier', an);
                if (an) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
            });
            if (merken && window.history && history.replaceState) {
                var url = new URL(window.location.href);
                url.searchParams.set('spur', name);
                history.replaceState(null, '', url.pathname + url.search + '#spuren');
            }
        }
        document.addEventListener('click', function (e) {
            var a = e.target.closest && e.target.closest('[data-spur], [data-spur-link]');
            if (!a) return;
            e.preventDefault();
            zeige(a.getAttribute('data-spur') || a.getAttribute('data-spur-link'), true);
            if (a.hasAttribute('data-spur-link')) leiste.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        zeige(leiste.getAttribute('data-start') || 'klaerung', false);
    }

    /* ---------- Sammelauswahl (Zahlungen eines Absenders) ---------- */
    function sammel() {
        var kaesten = function () { return document.querySelectorAll('input[name="zahlung_ids"]'); };
        var anzeige = document.querySelector('[data-anzahl]');
        var alle = document.querySelector('[data-alle]');
        if (!kaesten().length) return;
        function zaehlen() {
            var n = document.querySelectorAll('input[name="zahlung_ids"]:checked').length;
            if (anzeige) anzeige.textContent = anzeige.textContent.replace(/^\d+/, String(n));
            if (alle) alle.checked = n > 0 && n === kaesten().length;
        }
        document.addEventListener('change', function (e) {
            if (e.target.name === 'zahlung_ids') zaehlen();
            if (e.target.hasAttribute && e.target.hasAttribute('data-alle')) {
                kaesten().forEach(function (k) { k.checked = e.target.checked; });
                zaehlen();
            }
        });
        // «alle von diesem Absender» — der eigentliche Zeitgewinn, wenn ein
        // Dauerauftrag über Monate ungeklärt liegen geblieben ist.
        document.addEventListener('click', function (e) {
            var btn = e.target.closest && e.target.closest('[data-alle-von]');
            if (!btn) return;
            var name = btn.getAttribute('data-alle-von');
            kaesten().forEach(function (k) { if (k.getAttribute('data-zahler') === name) k.checked = true; });
            zaehlen();
        });
        zaehlen();
    }

    /* ---------- Sofort speichern (Verwendung eines Guthabens) ---------- */
    function sofort() {
        document.querySelectorAll('form[data-sofort]').forEach(function (f) {
            f.querySelectorAll('[data-ohne-js]').forEach(function (b) { b.classList.add('aus'); });
            f.addEventListener('change', function () { f.submit(); });
        });
    }

    /* ---------- Assistent «Zahlung aufteilen» ---------- */
    function split() {
        var form = document.querySelector('form[data-split]');
        if (!form) return;
        form.classList.add('an');
        var betrag = zahl(form.getAttribute('data-betrag'));
        var parkKonto = form.getAttribute('data-park') || '1190';
        var bankKonto = function () {
            var s = form.querySelector('select[name="bank_konto"]');
            return s ? s.value : '1020';
        };
        var zugeteiltEl = form.querySelector('[data-zugeteilt]');
        var restEl = form.querySelector('[data-rest]');
        var balken = form.querySelector('[data-balken]');
        var restWahl = form.querySelector('[data-rest-wahl]');
        var absenden = form.querySelector('[data-split-absenden]');
        var meldung = form.querySelector('[data-split-meldung]');
        var pruefung = form.querySelector('[data-pruefung]');
        var t = function (k) { return form.getAttribute('data-t-' + k) || ''; };

        function teile() { return form.querySelectorAll('input[data-teil]'); }

        // «als Guthaben von»: jeder Mieter, der in den Treffern steht, ist wählbar.
        function guthabenMieter() {
            var sel = form.querySelector('select[name="rest_vertrag"]');
            if (!sel) return;
            form.querySelectorAll('[data-vertrag]').forEach(function (g) {
                var id = g.getAttribute('data-vertrag');
                if (!id || sel.querySelector('option[value="' + id + '"]')) return;
                var o = document.createElement('option');
                o.value = id;
                o.textContent = g.getAttribute('data-mieter');
                sel.appendChild(o);
            });
            var leer = sel.querySelector('option[value=""]');
            if (leer && sel.options.length > 1) leer.remove();
        }

        function rechnen() {
            var summe = 0, zuViel = false, zeilen = [];
            teile().forEach(function (inp) {
                var b = zahl(inp.value), offen = zahl(inp.getAttribute('data-offen'));
                var karte = inp.closest('[data-posten]');
                var falsch = b < 0 || b > offen + 0.001;
                inp.setAttribute('aria-invalid', falsch ? 'true' : 'false');
                if (karte) karte.classList.toggle('gewaehlt', b > 0 && !falsch);
                if (falsch) zuViel = true;
                if (b > 0) {
                    summe += b;
                    zeilen.push([parkKonto + ' → 1100', b, inp.getAttribute('data-text') || '']);
                }
            });
            summe = Math.round(summe * 100) / 100;
            var rest = Math.round((betrag - summe) * 100) / 100;
            if (zugeteiltEl) zugeteiltEl.textContent = chf(summe);
            if (restEl) {
                restEl.textContent = chf(rest);
                restEl.classList.toggle('fw-kritisch', rest < 0);
                restEl.classList.toggle('fw-good', rest === 0);
            }
            if (balken) balken.value = betrag > 0 ? Math.min(100, Math.round(summe / betrag * 100)) : 0;
            if (restWahl) restWahl.classList.toggle('aus', rest <= 0);
            var ziel = (form.querySelector('input[name="rest_ziel"]:checked') || {}).value || 'offen';
            if (rest > 0) {
                if (ziel === 'guthaben') {
                    var sel = form.querySelector('select[name="rest_vertrag"]');
                    var name = sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent.trim() : '';
                    zeilen.push([(parkKonto === '2030' ? '2030' : parkKonto + ' → 2030'), rest, t('guthaben') + ' ' + name]);
                } else if (ziel === 'zurueck') {
                    zeilen.push([parkKonto + ' → ' + bankKonto(), rest, t('zurueck')]);
                } else {
                    zeilen.push(['1190', rest, t('offen')]);
                }
            }
            var fehler = '';
            if (zuViel) fehler = t('zuviel');
            else if (rest < 0) fehler = t('ueber');
            else if (summe === 0 && (rest <= 0 || ziel === 'offen')) fehler = t('nichts');
            if (meldung) { meldung.textContent = fehler; meldung.classList.toggle('aus', !fehler); }
            if (absenden) absenden.disabled = !!fehler;
            if (pruefung) {
                pruefung.innerHTML = '';
                zeilen.forEach(function (z) {
                    var li = document.createElement('li');
                    var k = document.createElement('span'); k.className = 'fw-mono'; k.textContent = z[0];
                    var b = document.createElement('b'); b.textContent = 'CHF ' + chf(z[1]);
                    var x = document.createElement('span'); x.textContent = z[2];
                    li.appendChild(k); li.appendChild(b); li.appendChild(x);
                    pruefung.appendChild(li);
                });
            }
        }

        // Antippen von «offen» übernimmt den offenen Betrag — höchstens, was
        // von der Zahlung noch übrig ist.
        function fuellen(inp) {
            var offen = zahl(inp.getAttribute('data-offen'));
            var andere = 0;
            teile().forEach(function (x) { if (x !== inp) andere += zahl(x.value); });
            var frei = Math.max(0, Math.round((betrag - andere) * 100) / 100);
            var b = Math.min(offen, frei);
            inp.value = b > 0 ? b.toFixed(2) : '';
            rechnen();
            if (b > 0) inp.focus();
        }

        form.addEventListener('input', rechnen);
        form.addEventListener('change', rechnen);
        form.addEventListener('click', function (e) {
            var v = e.target.closest && e.target.closest('[data-voll]');
            if (v) {
                e.preventDefault();
                var inp = v.closest('[data-posten]').querySelector('input[data-teil]');
                if (zahl(inp.value) > 0) { inp.value = ''; rechnen(); } else fuellen(inp);
            }
        });

        // Drag & Drop am Desktop: den Zahlungs-Chip auf einen Posten ziehen.
        var chip = form.querySelector('[data-zahlung-chip]');
        if (chip) {
            chip.setAttribute('draggable', 'true');
            chip.addEventListener('dragstart', function (e) {
                e.dataTransfer.setData('text/plain', 'zahlung');
                e.dataTransfer.effectAllowed = 'copy';
                form.classList.add('zieht');
            });
            chip.addEventListener('dragend', function () { form.classList.remove('zieht'); });
        }
        form.addEventListener('dragover', function (e) {
            var k = e.target.closest && e.target.closest('[data-posten]');
            if (!k) return;
            e.preventDefault();
            form.querySelectorAll('[data-posten].ziel').forEach(function (x) { if (x !== k) x.classList.remove('ziel'); });
            k.classList.add('ziel');
        });
        form.addEventListener('dragleave', function (e) {
            var k = e.target.closest && e.target.closest('[data-posten]');
            if (k && !k.contains(e.relatedTarget)) k.classList.remove('ziel');
        });
        form.addEventListener('drop', function (e) {
            var k = e.target.closest && e.target.closest('[data-posten]');
            if (!k) return;
            e.preventDefault();
            k.classList.remove('ziel');
            form.classList.remove('zieht');
            fuellen(k.querySelector('input[data-teil]'));
        });

        // Suche ohne Neuladen: Treffer ersetzen, gewählte Posten behalten.
        var suche = document.querySelector('form[data-suche]');
        var treffer = form.querySelector('[data-treffer]');
        var gewaehlt = form.querySelector('[data-gewaehlt]');
        if (suche && treffer && window.fetch) {
            suche.addEventListener('submit', function (e) {
                e.preventDefault();
                // Das Suchfeld steht im Assistenten und gehört über das
                // form-Attribut zum Suchformular (Formulare lassen sich nicht schachteln).
                var feld = document.querySelector('[form="' + suche.id + '"][name="q"]') || suche.querySelector('[name="q"]');
                var q = feld ? feld.value : '';
                var url = new URL(window.location.href);
                url.searchParams.set('q', q);
                url.searchParams.set('fragment', '1');
                treffer.setAttribute('aria-busy', 'true');
                fetch(url.toString(), { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
                    .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
                    .then(function (html) {
                        // Gewählte Posten wandern nach «Ausgewählt», damit eine neue
                        // Suche keine Zuteilung verwirft.
                        teile().forEach(function (inp) {
                            if (zahl(inp.value) > 0 && gewaehlt && !gewaehlt.contains(inp)) {
                                gewaehlt.appendChild(inp.closest('[data-posten]'));
                            }
                        });
                        if (gewaehlt) gewaehlt.closest('[data-gewaehlt-block]').classList.toggle('aus', !gewaehlt.children.length);
                        treffer.innerHTML = html;
                        var schon = {};
                        if (gewaehlt) gewaehlt.querySelectorAll('[data-posten]').forEach(function (k) { schon[k.getAttribute('data-posten')] = 1; });
                        treffer.querySelectorAll('[data-posten]').forEach(function (k) {
                            if (schon[k.getAttribute('data-posten')]) k.remove();
                        });
                        treffer.removeAttribute('aria-busy');
                        guthabenMieter();
                        rechnen();
                    })
                    .catch(function () { treffer.removeAttribute('aria-busy'); suche.submit(); });
            });
        }
        guthabenMieter();
        rechnen();
    }

    function start() {
        spuren();
        sammel();
        sofort();
        split();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
