"""LIK-Hilfsfunktionen: einheitliche Beschriftung mit Basis + Stand-Monat.

Der Landesindex der Konsumentenpreise (LIK) wird auf einer Basis geführt
(aktuell «Dezember 2020 = 100»). Für die Teuerungsberechnung bei
Mietzinsanpassungen müssen der alte und der neue LIK-Wert auf DERSELBEN Basis
stehen, und auf dem amtlichen Formular müssen Basis + Stand-Monat ausgewiesen
werden (Art. 269a lit. b OR / VMWG)."""

_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]


def stand_label(stand):
    """DateField -> 'August 2024' (oder '' wenn None)."""
    if not stand:
        return ""
    try:
        return f"{_MONATE[stand.month - 1]} {stand.year}"
    except Exception:
        return ""


def lik_bezeichnung(punkte, basis="Dezember 2020", stand=None):
    """'107,2 Punkte · Basis Dezember 2020 · Stand August 2024'."""
    if punkte is None:
        return "—"
    try:
        p = f"{float(punkte):.1f}".replace('.', ',')
    except Exception:
        p = str(punkte)
    teile = [f"{p} Punkte"]
    if basis:
        teile.append(f"Basis {basis}")
    s = stand_label(stand)
    if s:
        teile.append(f"Stand {s}")
    return " · ".join(teile)


def vertrag_lik_context(vertrag, verwaltung=None):
    """Einheitliche LIK-Angaben eines Vertrags für alle Ansichten/PDFs.

    Gibt {lik_basis, lik_stand, lik_stand_label, lik_pkt, lik_voll} zurück.
    - Basis: `Verwaltung.lik_basis` (Default «Dezember 2020»)
    - Stand: `Vertrag.basis_lik_stand`, sonst `Verwaltung.aktueller_lik_stand`
    - Punkte: `Vertrag.basis_lik_punkte` (Schweizer Format mit Komma)
    """
    basis = (getattr(verwaltung, 'lik_basis', None) or "Dezember 2020")
    stand = getattr(vertrag, 'basis_lik_stand', None) or getattr(verwaltung, 'aktueller_lik_stand', None)
    punkte = getattr(vertrag, 'basis_lik_punkte', None)
    try:
        pkt = f"{float(punkte):.1f}".replace('.', ',') if punkte is not None else "—"
    except Exception:
        pkt = str(punkte)
    return {
        'lik_basis': basis,
        'lik_stand': stand,
        'lik_stand_label': stand_label(stand),
        'lik_pkt': pkt,
        'lik_voll': lik_bezeichnung(punkte, basis=basis, stand=stand),
    }
