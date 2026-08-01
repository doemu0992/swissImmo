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


def uebernehme_aus_formular(obj, request, feld='unterschrift_bild'):
    """Verarbeitet das Unterschriftsfeld (fw/_unterschrift_feld.html) für ein
    Objekt mit ImageField `unterschrift_bild`.

    Drei Wege, in dieser Reihenfolge:
      1. `unterschrift_entfernen=1`  → Bild löschen
      2. `unterschrift_gezeichnet`   → direkt gezeichnete PNG (Data-URL)
      3. `unterschrift_bild`         → hochgeladene Datei

    Gibt True zurück, wenn sich etwas geändert hat. Das Objekt wird NICHT
    gespeichert — der Aufrufer ruft danach ohnehin obj.save() (dort läuft die
    Hintergrund-Transparenz).

    Die Data-URL wird über Pillow neu geschrieben statt roh gespeichert: so
    landet garantiert ein echtes PNG im Medienordner, egal was der Browser
    (oder jemand mit einem gefälschten POST) geschickt hat.
    """
    import base64
    import io

    from django.core.files.base import ContentFile

    P = request.POST
    if P.get('unterschrift_entfernen') == '1' and getattr(obj, feld, None):
        getattr(obj, feld).delete(save=False)
        setattr(obj, feld, None)
        return True

    roh = (P.get('unterschrift_gezeichnet') or '').strip()
    if roh.startswith('data:image/'):
        # Grössenlimit: ein gezeichnetes Feld liegt bei ~5–40 KB Base64.
        # 4 MB sind grosszügig und verhindern trotzdem einen aufgeblähten POST.
        if len(roh) > 4 * 1024 * 1024:
            return False
        try:
            _kopf, _, b64 = roh.partition(',')
            daten = base64.b64decode(b64, validate=True)
            from PIL import Image
            bild = Image.open(io.BytesIO(daten))
            bild.verify()                       # nur echte Bilddaten zulassen
            bild = Image.open(io.BytesIO(daten)).convert('RGBA')
            puffer = io.BytesIO()
            bild.save(puffer, format='PNG')
            # NUR zuweisen, nicht speichern: obj.save() schreibt die Datei danach
            # unter ihrem endgültigen Namen. Ein FieldFile.save() hier würde eine
            # zusätzliche, sofort verwaiste «unterschrift.png» hinterlassen.
            setattr(obj, feld, ContentFile(puffer.getvalue(), name='unterschrift.png'))
            return True
        except Exception:
            return False

    datei = request.FILES.get(feld)
    if datei:
        setattr(obj, feld, datei)
        return True
    return False
