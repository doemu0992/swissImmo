from decimal import Decimal

def berechne_mietpotenzial(vertrag, aktuell_ref, aktuell_lik):
    """
    Berechnet das Erhöhungs- oder Senkungspotenzial nach Schweizer Mietrecht.
    Rückgabe: Dictionary mit allen Details.
    """

    # Sicherheitscheck: Wenn Basisdaten im Vertrag fehlen, können wir nicht rechnen
    if not vertrag.basis_referenzzinssatz or not vertrag.basis_lik_punkte:
        return None

    # Alles in Decimal umwandeln für präzises Rechnen (Wichtig bei Geld!)
    basis_ref = Decimal(str(vertrag.basis_referenzzinssatz))
    curr_ref = Decimal(str(aktuell_ref))

    basis_lik = Decimal(str(vertrag.basis_lik_punkte))
    curr_lik = Decimal(str(aktuell_lik))

    netto_miete = Decimal(str(vertrag.netto_mietzins))

    # --- 1. REFERENZZINSSATZ ---
    # Regel:
    # Erhöhung: +0.25% Zins = +3.00% Miete
    # Senkung:  -0.25% Zins = -2.91% Miete

    zins_delta = curr_ref - basis_ref
    steps = int(zins_delta / Decimal('0.25'))

    zins_prozent = Decimal('0.00')

    if steps > 0:
        zins_prozent = Decimal(steps) * Decimal('3.00')
    elif steps < 0:
        # Bei Senkung rechnen wir mit positiven Schritten für die Formel
        abs_steps = abs(steps)
        zins_prozent = Decimal(abs_steps) * Decimal('-2.91')

    # --- 2. TEUERUNG (LIK) ---
    # Regel: 40% der Teuerung darf auf die Miete geschlagen werden.
    # Formel: ((Neu - Alt) / Alt) * 100 * 0.4

    lik_prozent = Decimal('0.00')

    # Nur wenn der Index gestiegen ist, gibt es einen Aufschlag.
    # (Deflation wird im Mietrecht meist ignoriert oder separat behandelt)
    if curr_lik > basis_lik:
        teuerung = (curr_lik - basis_lik) / basis_lik
        lik_prozent = teuerung * Decimal('100') * Decimal('0.4')

    # --- 3. ZUSAMMENFASSUNG ---
    total_prozent = zins_prozent + lik_prozent

    # Neue Miete berechnen
    faktor = 1 + (total_prozent / Decimal('100'))
    neue_miete = netto_miete * faktor

    differenz_chf = neue_miete - netto_miete

    # Entscheidung: Was tun?
    action = 'OK'
    if total_prozent > 0.5:
        action = 'UP' # Erhöhung möglich
    elif total_prozent < -0.5:
        action = 'DOWN' # Senkungsanspruch des Mieters

    return {
        'mieter': f"{vertrag.mieter}",
        'objekt': str(vertrag.einheit),
        'aktuell_chf': round(netto_miete, 2),
        'neu_chf': round(neue_miete, 2),
        'delta_chf': round(differenz_chf, 2),
        'delta_prozent': round(total_prozent, 2),
        'details_zins': f"{zins_prozent}% (Ref: {basis_ref} -> {curr_ref})",
        'details_lik': f"{round(lik_prozent, 2)}% (Index: {basis_lik} -> {curr_lik})",
        'action': action
    }