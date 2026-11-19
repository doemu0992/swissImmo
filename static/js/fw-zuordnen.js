/* Dialog «Zahlung zuordnen» (UI-Zielbild). Zugabe: Ohne JavaScript bleibt der Link «Zuordnen / Aufteilen» zum Assistenten.
 * Der Server prüft jede Zuordnung selbst; hier werden nur Ziel-Adresse und Felder passend zum gewählten Weg gesetzt.
 *
 *   data-zuordnen="<id>"   Klick: Dialog für diese Zahlung öffnen (Angaben aus <script id="zuordnenDaten">)
 */
(function () {
    'use strict';
    var dlg = document.getElementById('fwZuordnen');
    var daten = document.getElementById('zuordnenDaten');
    if (!dlg || !daten || typeof dlg.showModal !== 'function') return;
    var D = {};
    try { D = JSON.parse(daten.textContent || '{}'); } catch (x) { D = {}; }

    var form = document.getElementById('fwZuordnenForm');
    var idFeld = document.getElementById('fwZuordnenId');
    var nextFeld = document.getElementById('fwZuordnenNext');
    var rechnung = document.getElementById('fwZuordnenRechnung');
    var vertrag = document.getElementById('fwZuordnenVertrag');
    var ok = document.getElementById('fwZuordnenOk');
    var aktuell = null;

    // Die Seite, die nach «Aufteilen» führt, steht in der Zeile selbst (Link), damit die Adresse nur einmal definiert ist.
    function weg() { return (form.querySelector('input[name="weg"]:checked') || {}).value || 'miete'; }

    function umstellen() {
        var w = weg();
        form.querySelectorAll('.fw-zopt').forEach(function (l) {
            l.classList.toggle('on', l.getAttribute('data-opt') === w);
        });
        rechnung.disabled = w !== 'miete';
        rechnung.required = w === 'miete';
        vertrag.disabled = w !== 'kaution' || !vertrag.options.length;
        vertrag.required = w === 'kaution';
        nextFeld.disabled = !(w === 'kaution' || w === 'back');
        form.removeAttribute('data-bestaetigen');
        if (w === 'miete') form.action = '/neu/bankabgleich/zuordnen/';
        else if (w === 'kaution') {
            form.action = '/neu/bankabgleich/zahlung/' + aktuell + '/kaution/';
            form.setAttribute('data-bestaetigen', form.getAttribute('data-text-kaution'));
        } else if (w === 'back') {
            form.action = '/neu/bankabgleich/guthaben/rueckerstatten/';
            form.setAttribute('data-bestaetigen', form.getAttribute('data-text-zurueck'));
        }
        ok.disabled = (w === 'kaution' && !vertrag.options.length);
    }

    function oeffnen(id) {
        var d = D[String(id)];
        if (!d) return;
        aktuell = String(id);
        idFeld.value = aktuell;
        document.getElementById('fwZuordnenSub').textContent =
            [d.zahler, 'CHF ' + d.betrag, 'Valuta ' + d.valuta].filter(Boolean).join(' · ');
        rechnung.value = d.rechnung ? String(d.rechnung) : '';
        while (vertrag.firstChild) vertrag.removeChild(vertrag.firstChild);
        (d.kaution || []).forEach(function (k) {
            var o = document.createElement('option');
            o.value = k.id; o.textContent = k.label; vertrag.appendChild(o);
        });
        form.querySelector('input[name="weg"][value="miete"]').checked = true;
        var nf = document.getElementById('fwZuordnenNotizForm');
        nf.action = '/neu/bankabgleich/zahlung/' + aktuell + '/notiz/';
        document.getElementById('fwZuordnenNotiz').value = d.notiz || '';
        umstellen();
        dlg.showModal();
    }

    document.addEventListener('click', function (e) {
        var t = e.target && e.target.closest ? e.target.closest('[data-zuordnen]') : null;
        if (t) { e.preventDefault(); oeffnen(t.getAttribute('data-zuordnen')); return; }
        if (e.target && e.target.id === 'fwZuordnenAbbrechen') dlg.close();
        // Klick auf den Hintergrund (ausserhalb der Karte) schliesst, wie bei den anderen Dialogen.
        if (e.target === dlg) dlg.close();
    });
    form.addEventListener('change', umstellen);
    form.addEventListener('submit', function (e) {
        if (weg() === 'split') {
            e.preventDefault();
            window.location = '/neu/bankabgleich/zahlung/' + aktuell + '/aufteilen/';
        }
    });
})();
