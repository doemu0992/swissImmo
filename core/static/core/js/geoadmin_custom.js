/**
 * GeoAdmin Search Script
 * Dateiname: geoadmin_custom.js
 * Version: Standalone (Kein Import, damit Django Admin nicht abstürzt)
 */

console.log("GeoAdmin Script: RELOADED geladen.");

// Kleine Hilfsfunktion direkt hier drin (statt Import)
const Units = {
    formatArea: function(val) {
        return val ? val + " m²" : "";
    }
};

document.addEventListener('DOMContentLoaded', function() {

    const el = {
        strasse: document.getElementById('id_strasse'),
        plz: document.getElementById('id_plz'),
        ort: document.getElementById('id_ort'),
        kanton: document.getElementById('id_kanton'),
        egid: document.getElementById('id_egid')
    };

    if (!el.strasse) {
        console.warn("Feld 'id_strasse' nicht gefunden.");
        return;
    }

    // Schwebendes Menü erstellen
    const results = document.createElement('div');
    results.style.cssText = `
        position: absolute;
        background: white;
        border: 2px solid #00bcd4;
        z-index: 999999;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        display: none;
        max-height: 300px;
        overflow-y: auto;
        font-family: Roboto, sans-serif;
        font-size: 13px;
        color: #333;
    `;
    document.body.appendChild(results);

    function positionMenu() {
        const rect = el.strasse.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        results.style.top = (rect.bottom + scrollTop) + 'px';
        results.style.left = (rect.left + scrollLeft) + 'px';
        results.style.width = rect.width + 'px';
    }

    el.strasse.addEventListener('input', function() {
        const val = el.strasse.value;
        if (val.length < 3) { results.style.display = 'none'; return; }

        positionMenu();

        fetch(`https://api3.geo.admin.ch/rest/services/api/SearchServer?searchText=${encodeURIComponent(val)}&type=locations&origins=address&limit=10`)
            .then(r => r.json())
            .then(data => {
                results.innerHTML = '';
                if (!data.results || data.results.length === 0) {
                    results.style.display = 'none';
                    return;
                }
                results.style.display = 'block';

                data.results.forEach(item => {
                    const a = item.attrs;
                    const label = a.label.replace(/<[^>]*>?/gm, '');

                    // EGID holen
                    let rawEgid = null;
                    if (a.egid) rawEgid = a.egid;
                    else if (a.featureId) rawEgid = a.featureId.toString().split('_')[0];
                    else if (item.featureId) rawEgid = item.featureId.toString().split('_')[0];

                    const rawKanton = a.kantone || a.kanton || "";

                    // Anzeige bauen
                    const row = document.createElement('div');
                    row.style.cssText = 'padding:10px; cursor:pointer; border-bottom:1px solid #eee;';
                    row.onmouseover = function() { this.style.backgroundColor = '#e0f7fa'; };
                    row.onmouseout = function() { this.style.backgroundColor = 'white'; };

                    row.innerHTML = `<strong>${label}</strong><br><span style="color:#666">EGID: ${rawEgid || "?"} | Kt: ${rawKanton}</span>`;

                    row.onclick = function() {
                        // Adresse parsen
                        const match = label.match(/^(.*?)\s*[,\s]\s*(\d{4})\s+(.*)$/);
                        if (match) {
                            el.strasse.value = match[1].replace(/,$/, '').trim();
                            if (el.plz) el.plz.value = match[2];
                            if (el.ort) el.ort.value = match[3];
                        } else {
                            el.strasse.value = label;
                        }

                        // WICHTIG: EGID setzen!
                        if (el.egid && rawEgid) el.egid.value = rawEgid;
                        if (el.kanton && rawKanton) el.kanton.value = rawKanton.toUpperCase();

                        results.style.display = 'none';
                    };
                    results.appendChild(row);
                });
            })
            .catch(err => console.error("API Fehler:", err));
    });

    // Menü schließen bei Klick daneben
    document.addEventListener('click', function(e) {
        if (e.target !== el.strasse && e.target !== results && !results.contains(e.target)) {
            results.style.display = 'none';
        }
    });
});