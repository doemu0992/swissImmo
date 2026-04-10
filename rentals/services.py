# rentals/services.py
from decimal import Decimal
from .models import Dokument

def berechne_mietpotenzial(vertrag, aktuell_ref, aktuell_lik, allg_kosten_pct=Decimal('0.00')):
    """
    Berechnet das Erhöhungs- oder Senkungspotenzial nach Schweizer Mietrecht.
    Inklusive Referenzzinssatz, Teuerung (LIK) und allgemeiner Kostensteigerung.
    """
    if not vertrag.basis_referenzzinssatz or not vertrag.basis_lik_punkte:
        return None

    basis_ref = Decimal(str(vertrag.basis_referenzzinssatz))
    curr_ref = Decimal(str(aktuell_ref))
    basis_lik = Decimal(str(vertrag.basis_lik_punkte))
    curr_lik = Decimal(str(aktuell_lik))
    netto_miete = Decimal(str(vertrag.netto_mietzins))

    # --- 1. REFERENZZINSSATZ ---
    zins_delta = curr_ref - basis_ref
    steps = int(zins_delta / Decimal('0.25'))
    zins_prozent = Decimal('0.00')

    if steps > 0:
        zins_prozent = Decimal(steps) * Decimal('3.00')
    elif steps < 0:
        abs_steps = abs(steps)
        zins_prozent = Decimal(abs_steps) * Decimal('-2.91')

    # --- 2. TEUERUNG (LIK) ---
    lik_prozent = Decimal('0.00')
    if curr_lik > basis_lik:
        teuerung = (curr_lik - basis_lik) / basis_lik
        lik_prozent = teuerung * Decimal('100') * Decimal('0.4')

    # --- 3. ALLGEMEINE KOSTENSTEIGERUNG ---
    kosten_prozent = Decimal(str(allg_kosten_pct))

    # --- 4. ZUSAMMENFASSUNG ---
    total_prozent = zins_prozent + lik_prozent + kosten_prozent

    faktor = 1 + (total_prozent / Decimal('100'))
    neue_miete = netto_miete * faktor
    differenz_chf = neue_miete - netto_miete

    action = 'OK'
    if total_prozent > 0.5:
        action = 'UP'
    elif total_prozent < -0.5:
        action = 'DOWN'

    return {
        'mieter': f"{vertrag.mieter}",
        'objekt': str(vertrag.einheit),
        'aktuell_chf': round(netto_miete, 2),
        'neu_chf': round(neue_miete, 2),
        'delta_chf': round(differenz_chf, 2),
        'delta_prozent': round(total_prozent, 2),
        'details_zins': f"{zins_prozent}% (Ref: {basis_ref} -> {curr_ref})",
        'details_lik': f"{round(lik_prozent, 2)}% (Index: {basis_lik} -> {curr_lik})",
        'details_kosten': f"{kosten_prozent}% (Allg. Kostensteigerung)",
        'action': action
    }


def archiviere_vertrag_wenn_unterzeichnet(vertrag):
    """
    Prüft, ob der Vertrag unterzeichnet ist und legt bei Bedarf
    automatisch ein Archiv-Dokument an.
    Gibt True zurück, wenn ein neues Dokument erstellt wurde, sonst False.
    """
    if vertrag.sign_status == 'unterzeichnet' and vertrag.pdf_datei:
        exists = Dokument.objects.filter(vertrag=vertrag, kategorie='vertrag').exists()

        if not exists:
            Dokument.objects.create(
                titel=f"Mietvertrag {vertrag.mieter}",
                kategorie='vertrag',
                vertrag=vertrag,
                mieter=vertrag.mieter,
                einheit=vertrag.einheit,
                datei=vertrag.pdf_datei
            )
            return True

    return False