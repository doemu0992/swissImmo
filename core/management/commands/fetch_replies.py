from crm.models import Verwaltung
from tickets.models import SchadenMeldung, TicketNachricht

import imaplib
import email
import re
import os
import time
import html
from email.header import decode_header
from django.core.management.base import BaseCommand
from django.db import connections
from django.utils.html import strip_tags

class Command(BaseCommand):
    help = 'Holt Antworten von reply@immoswiss.app ab (Brechstangen-Methode)'

    def handle(self, *args, **options):
        self.stdout.write("🚀 Starte E-Mail-Abruf (Final Force Mode)...")

        while True:
            try:
                self.check_emails()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"💥 Kritischer Fehler im Loop: {e}"))

            for conn in connections.all():
                conn.close()

            self.stdout.write("💤 Warte 60 Sekunden...")
            time.sleep(60)

    def advanced_clean_body(self, html_content):
        if not html_content: return ""

        text = html_content

        # 1. PLATZHALTER EINFÜGEN (Die Brechstange)
        # Wir ersetzen alles, was wie ein Umbruch aussieht, durch ein eindeutiges Wort.

        placeholder = "[[ZEILENUMBRUCH]]"

        # <br> -> Platzhalter
        text = re.sub(r'<br\s*/?>', placeholder, text, flags=re.IGNORECASE)
        # </div>, </p>, </h1> -> Platzhalter
        text = re.sub(r'</(div|p|h[1-6]|table|tr|li|blockquote)>', placeholder, text, flags=re.IGNORECASE)
        # Block-Start -> Platzhalter (sicher ist sicher)
        text = re.sub(r'<(div|p|h[1-6]|table|tr|li|blockquote)[^>]*>', placeholder, text, flags=re.IGNORECASE)
        # Tabellenzellen -> Leerzeichen
        text = re.sub(r'<(td|th)[^>]*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'</(td|th)[^>]*>', ' ', text, flags=re.IGNORECASE)

        # 2. ALLES ANDERE HTML LÖSCHEN
        text = strip_tags(text)

        # 3. PLATZHALTER IN ECHTE UMBRÜCHE WANDELN
        text = text.replace(placeholder, "\n")

        # 4. Entities auflösen
        text = html.unescape(text)
        text = text.replace("\xa0", " ")

        # 5. ZITAT ABSCHNEIDEN
        cutoff_patterns = [
            r'ImmoSwiss Verwaltung\s+schrieb am',
            r'schrieb am.*?um.*?:',
            r'On\s+.*?wrote:',
            r'Am\s+.*?schrieb.*?:',
            r'-+Original\s+Message-+',
            r'From:\s+.*',
            r'Von:\s+.*',
            r'Gesendet von meinem iPhone',
            r'Sent from my iPhone'
        ]

        first_match_index = len(text)
        found = False

        for pattern in cutoff_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if match.start() < first_match_index:
                    first_match_index = match.start()
                    found = True
                    self.stdout.write(f"   ✂️ Schnitt bei: '{match.group()[:30]}...'")

        if found:
            text = text[:first_match_index]

        # 6. SAUBER MACHEN
        lines = [line.strip() for line in text.splitlines()]
        clean_text = ""
        for line in lines:
            if line:
                clean_text += line + "\n"
            else:
                # Max 1 Leerzeile
                if not clean_text.endswith("\n\n"):
                    clean_text += "\n"

        return clean_text.strip()

    def check_emails(self):
        IMAP_SERVER = "lx37.hoststar.hosting"
        EMAIL_USER = os.environ.get('EMAIL_REPLY_USER')
        EMAIL_PASS = os.environ.get('EMAIL_REPLY_PASSWORD')

        if not EMAIL_USER or not EMAIL_PASS:
            self.stdout.write(self.style.ERROR('❌ Fehler: Zugangsdaten fehlen in .env'))
            return

        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
            mail.login(EMAIL_USER, EMAIL_PASS)
            mail.select("inbox")

            status, messages = mail.search(None, 'UNSEEN')

            mail_ids = messages[0].split()
            if not mail_ids:
                print("   (Verbunden, keine ungelesenen Mails)")
                mail.close(); mail.logout()
                return

            self.stdout.write(self.style.SUCCESS(f"📨 {len(mail_ids)} neue Nachricht(en)!"))

            for i in mail_ids:
                try:
                    res, msg_data = mail.fetch(i, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])

                            subject = "Kein Betreff"
                            if msg["Subject"]:
                                decoded_list = decode_header(msg["Subject"])
                                parts = []
                                for content, encoding in decoded_list:
                                    if isinstance(content, bytes):
                                        parts.append(content.decode(encoding or "utf-8", errors="ignore"))
                                    else:
                                        parts.append(str(content))
                                subject = "".join(parts)

                            sender = msg.get("From", "Unbekannt")
                            self.stdout.write(f"🔎 Prüfe: {subject}")

                            match = re.search(r'Ticket #(\d+)', subject, re.IGNORECASE)

                            if match:
                                ticket_id = match.group(1)
                                try:
                                    ticket = SchadenMeldung.objects.get(id=ticket_id)

                                    raw_html = ""
                                    raw_text = ""

                                    if msg.is_multipart():
                                        for part in msg.walk():
                                            ctype = part.get_content_type()
                                            payload = part.get_payload(decode=True)
                                            if payload:
                                                decoded = payload.decode('utf-8', errors='ignore')
                                                if ctype == "text/html": raw_html = decoded
                                                elif ctype == "text/plain": raw_text = decoded
                                    else:
                                        payload = msg.get_payload(decode=True)
                                        if payload:
                                            decoded = payload.decode('utf-8', errors='ignore')
                                            if msg.get_content_type() == "text/html": raw_html = decoded
                                            else: raw_text = decoded

                                    content = raw_html if raw_html else raw_text

                                    if content:
                                        final_msg = self.advanced_clean_body(content)

                                        # --- DEBUGGING AUSGABE ---
                                        # Zeigt uns, ob Umbrüche (\n) WIRKLICH da sind
                                        print("---------------- VORSCHAU ----------------")
                                        print(final_msg)
                                        print("------------------------------------------")

                                        TicketNachricht.objects.create(
                                            ticket=ticket,
                                            absender_name=sender,
                                            typ='mail_antwort',
                                            nachricht=final_msg,
                                            gelesen=False
                                        )
                                        ticket.gelesen = False
                                        ticket.save()
                                        self.stdout.write(self.style.SUCCESS(f"✅ Importiert in Ticket #{ticket_id}"))
                                    else:
                                        self.stdout.write("⚠️ Inhalt leer.")

                                except SchadenMeldung.DoesNotExist:
                                    self.stdout.write(self.style.WARNING(f"⚠️ Ticket #{ticket_id} nicht gefunden."))
                                except Exception as db_err:
                                     self.stdout.write(self.style.ERROR(f"❌ DB Fehler: {db_err}"))
                            else:
                                self.stdout.write(f"ℹ️ Kein Ticket # gefunden")

                except Exception as inner_e:
                    self.stdout.write(self.style.ERROR(f"Fehler bei Mail: {inner_e}"))

            mail.close()
            mail.logout()

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Verbindungsfehler: {e}"))
