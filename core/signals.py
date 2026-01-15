import logging
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.mail import EmailMessage, send_mail
from django.conf import settings
from .models import SchadenMeldung

# Logger aktivieren (hilft bei der Fehlersuche im Terminal)
logger = logging.getLogger(__name__)

@receiver(pre_save, sender=SchadenMeldung)
def check_handwerker_assignment(sender, instance, **kwargs):
    """
    Prüft VOR dem Speichern, ob sich der Handwerker geändert hat.
    """
    # Nur bei existierenden Einträgen prüfen (nicht beim allerersten Erstellen)
    if instance.id:
        try:
            old_instance = SchadenMeldung.objects.get(id=instance.id)

            # WICHTIG: Das Feld heisst jetzt 'handwerker' (nicht beauftragter_handwerker)
            # Wir prüfen: Gibt es einen Handwerker? Und ist er NEU zugewiesen?
            if instance.handwerker and instance.handwerker != old_instance.handwerker:
                trigger_handwerker_workflow(instance)

        except SchadenMeldung.DoesNotExist:
            pass
        except Exception as e:
            # Fängt alle Fehler ab, damit der Admin nicht abstürzt!
            print(f"!!! FEHLER in signals.py: {e}")
            logger.error(f"Fehler beim Handwerker-Check: {e}")

def trigger_handwerker_workflow(meldung):
    """
    Versendet die E-Mails. Fehler werden hier abgefangen.
    """
    try:
        handwerker = meldung.handwerker

        # Sicherheits-Check: Hat der Handwerker überhaupt eine E-Mail?
        if not handwerker or not handwerker.email:
            print(f"Abbruch: Handwerker {handwerker} hat keine E-Mail.")
            return

        # ---------------------------------------------------------
        # A) MAIL AN HANDWERKER
        # ---------------------------------------------------------
        subject_hw = f"Auftrag: {meldung.liegenschaft} - {meldung.titel}"
        message_hw = f"""Grüezi {handwerker.firma},

Bitte beheben Sie folgenden Schaden:

Ort: {meldung.liegenschaft}
Schaden: {meldung.titel}
Beschreibung: {meldung.beschreibung}

--- KONTAKT MIETER ---
Telefon: {meldung.mieter_telefon}
E-Mail: {meldung.mieter_email}
Zutritt: {meldung.get_zutritt_display()}

Bitte kontaktieren Sie den Mieter direkt für einen Termin.
"""

        email_hw = EmailMessage(
            subject_hw,
            message_hw,
            settings.DEFAULT_FROM_EMAIL,
            [handwerker.email]
        )

        # Foto anhängen, falls vorhanden
        if meldung.foto:
            try:
                email_hw.attach_file(meldung.foto.path)
            except Exception as file_error:
                print(f"Konnte Foto nicht anhängen: {file_error}")

        # Senden
        email_hw.send(fail_silently=False)
        print(f"-> E-Mail an Handwerker ({handwerker.email}) erfolgreich versendet.")

        # ---------------------------------------------------------
        # B) MAIL AN MIETER
        # ---------------------------------------------------------
        if meldung.mieter_email:
            send_mail(
                f"Update zu Ihrer Meldung: {meldung.titel}",
                f"Grüezi,\n\nWir haben die Firma {handwerker.firma} beauftragt.\nDiese wird sich bezüglich eines Termins bei Ihnen melden.\n\nFreundliche Grüsse\nIhre Verwaltung",
                settings.DEFAULT_FROM_EMAIL,
                [meldung.mieter_email],
                fail_silently=True
            )
            print("-> Info-Mail an Mieter versendet.")

    except Exception as e:
        # Hier landet jeder Fehler (SMTP, falsches Passwort etc.)
        # Die Seite stürzt NICHT ab, aber Sie sehen den Fehler im Server-Log
        print(f"!!! CRITICAL MAIL ERROR: {e}")
        logger.error(f"Mailversand gescheitert: {e}")