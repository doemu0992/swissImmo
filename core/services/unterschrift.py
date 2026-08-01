"""Digitale Unterschrift auf reportlab-Briefen.

Die Unterschrift lag bisher nur auf den Vertrags- und Formular-PDFs
(pdf_service, formular_fill, amtliche_formulare_so). Alle mit reportlab
gezeichneten Briefe — Mahnung mit Kündigungsandrohung, Mängelrüge,
Untermiete-Zustimmung, Kautionsbelege, Serienbrief, Schlussabrechnung —
zogen zwar eine Unterschriftslinie, liessen sie aber leer. Ein Brief, der
per Einschreiben rausgeht und eine Kündigung androht, gehört unterschrieben.

Dieses Modul ist die eine Stelle dafür: `unterschrift_zeichnen()` findet das
Bild, skaliert es proportional und setzt es über die Linie. Neue Briefe rufen
denselben Helfer auf, damit die Lücke nicht erneut entsteht.
"""
import os

from reportlab.lib.units import mm


def unterschrift_pfad(*kandidaten):
    """Erster Kandidat (Verwaltung/Mandant) mit einer vorhandenen Bilddatei.

    Die Reihenfolge gibt der Aufrufer vor: unterschreiben soll, wer unter der
    Linie steht. Fehlt die Datei auf der Platte (Medien nicht mitmigriert),
    wird der Kandidat übersprungen statt den Brief mit einem Fehler abzubrechen.
    """
    for k in kandidaten:
        if k is None:
            continue
        bild = getattr(k, 'unterschrift_bild', None) or getattr(k, 'unterschrift', None)
        if not bild:
            continue
        try:
            pfad = bild.path
        except (ValueError, NotImplementedError, AttributeError):
            continue
        if pfad and os.path.exists(pfad):
            return pfad
    return None


def unterschrift_zeichnen(c, x, y, *kandidaten, breite=42 * mm, max_hoehe=18 * mm):
    """Zeichnet die Unterschrift mit der unteren Kante auf `y` (= Linienhöhe).

    Gibt True zurück, wenn gezeichnet wurde — der Aufrufer kann dann z.B. den
    Hinweis «Dieses Schreiben wurde elektronisch erstellt» weglassen.
    """
    pfad = unterschrift_pfad(*kandidaten)
    if not pfad:
        return False
    try:
        from reportlab.lib.utils import ImageReader
        bild = ImageReader(pfad)
        bw, bh = bild.getSize()
        if not bw or not bh:
            return False
        h = breite * bh / bw
        if h > max_hoehe:          # proportional an die Höhe anpassen
            h = max_hoehe
            breite = h * bw / bh
        # +1 mm Luft, damit die Signatur auf der Linie sitzt und sie nicht verdeckt
        c.drawImage(bild, x, y + 1 * mm, width=breite, height=h,
                    mask='auto', preserveAspectRatio=True, anchor='sw')
        return True
    except Exception:
        # Ein defektes Bild darf nie den ganzen Brief verhindern.
        return False
