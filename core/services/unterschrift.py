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
import logging
import os

from reportlab.lib.units import mm

logger = logging.getLogger(__name__)



def hat_sichtbare_tinte(bild):
    """True, wenn auf dem Bild überhaupt etwas zu sehen ist.

    Ein leeres Zeichenfeld liefert ein vollständig durchsichtiges PNG, ein
    abfotografiertes leeres Blatt ein weisses. Beides wurde bisher anstandslos
    gespeichert: Die App meldete «hinterlegt», die Vorschau blieb leer und der
    Brief ging unsigniert raus — ohne dass irgendwo ein Fehler auftauchte.
    Genau dieses Bild ist reproduziert worden. Darum wird hier geprüft, ob es
    dunkle, nicht durchsichtige Pixel gibt.
    """
    try:
        bild = bild.convert('RGBA')
        if bild.width * bild.height > 250_000:      # grosse Fotos verkleinern
            bild.thumbnail((500, 500))
        for r, g, b, a in bild.getdata():
            if a > 40 and (r < 200 or g < 200 or b < 200):
                return True
    except Exception:
        return True          # im Zweifel durchlassen, nie den Upload blockieren
    return False


def unterschrift_url(obj, feld='unterschrift_bild'):
    """URL der hinterlegten Unterschrift — leer, wenn sie nicht brauchbar ist.

    Die Vorlage leitet daraus sowohl die Vorschau als auch den Hinweis
    «hinterlegt» ab. Bisher genügte dafür der Datenbankeintrag. Fehlte die
    Datei auf dem Server oder war sie leer (durchsichtiges Canvas), behauptete
    die App eine Unterschrift, die weder in der Vorschau noch auf einem Brief
    je erschien. Darum hier beides prüfen.
    """
    bild = getattr(obj, feld, None) if obj else None
    if not bild:
        return ''
    try:
        if not bild.storage.exists(bild.name):
            return ''
        from PIL import Image
        with bild.open('rb') as f:
            if not hat_sichtbare_tinte(Image.open(f)):
                return ''
        return bild.url
    except Exception:
        return ''


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

    from django.contrib import messages
    from django.core.files.base import ContentFile

    def _leer_melden():
        try:
            messages.warning(request, "⚠️ Die Unterschrift war leer und wurde nicht "
                                      "gespeichert — bitte nochmals unterschreiben.")
        except Exception:
            pass                       # ohne Message-Framework (Tests) einfach still
        return False

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
            if not hat_sichtbare_tinte(bild):
                return _leer_melden()
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
        try:
            from PIL import Image
            datei.seek(0)
            if not hat_sichtbare_tinte(Image.open(datei)):
                return _leer_melden()
        except Exception:
            pass                       # kein lesbares Bild → Modell meldet es
        finally:
            try:
                datei.seek(0)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        setattr(obj, feld, datei)
        return True
    return False
