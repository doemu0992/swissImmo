# core/admin_base.py
#
# Der Unfold-Admin ist ab E2 ein reines Auskunfts- und Kontrollwerkzeug —
# kein zweiter Schreibpfad neben /neu/.
#
# Warum das mehr ist als Aufräumen: Solange der Admin schreiben kann, muss
# JEDE Mandanten-, Entitlement- und Fachregel ein zweites Mal implementiert
# werden, sonst umgeht man sie über /admin/. Der Admin sieht per Definition
# alle Objekte; ein schreibender Admin wäre in der Mehrmandanten-Welt der
# Phase 2 der direkte Weg, fremde Daten zu verändern. Lesend bleibt er
# nützlich (nachsehen, suchen, prüfen) und aus der Pflicht draussen.
#
# Geschrieben wird ausschliesslich über /neu/ — dort sitzen die Rollenprüfung
# (core/auth.py), die Fachlogik und der Audit-Trail (log_aktion). Das gilt
# auch für Benutzer und Rollen: /neu/benutzer/ deckt Anlegen, Rolle setzen
# und Löschen vollständig ab (fw_benutzer_form, fw_benutzer_loeschen).
#
# Verwendung — in jeder admin.py statt der Unfold-Basisklassen:
#
#     from core.admin_base import NurLesenModelAdmin, NurLesenTabularInline
#
#     @admin.register(Mieter)
#     class MieterAdmin(NurLesenModelAdmin):
#         ...
#
# Abgesichert ist das durch `AdminNurLesendTests` in core/tests.py: Der Test
# läuft über die tatsächliche Registrierung (`admin.site._registry`) samt
# aller Inlines. Ein neuer ModelAdmin, der versehentlich auf der schreibenden
# Unfold-Basisklasse sitzt, fällt dort auf — nicht erst im Betrieb.

from django.core.exceptions import PermissionDenied
from unfold.admin import ModelAdmin, StackedInline, TabularInline


class NurLesenMixin:
    """Entzieht einem ModelAdmin oder Inline jedes Schreibrecht.

    Eine Signatur für beide Fälle: `ModelAdmin.has_add_permission(request)`
    kennt kein `obj`, `InlineModelAdmin.has_add_permission(request, obj)`
    schon — der Vorgabewert `obj=None` deckt beide ab.

    `has_view_permission` wird bewusst NICHT angefasst. Djangos Vorgabe lässt
    Lesen zu, wenn der Benutzer das `view`- ODER das `change`-Recht hat; wer
    heute Zugriff hat, behält ihn also.
    """

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # --- Zweite Reihe -------------------------------------------------------
    # Die drei Rechte-Methoden genügen für Djangos Oberfläche. Diese beiden
    # fangen den Fall ab, dass jemand später eine davon lockert und dabei
    # übersieht, dass damit auch geschrieben werden kann. Sie kosten nichts,
    # solange der Admin lesend bleibt — sie werden dann nie erreicht.
    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Der Admin ist nur lesend (E2) — schreiben über /neu/.")

    def delete_model(self, request, obj):
        raise PermissionDenied("Der Admin ist nur lesend (E2) — löschen über /neu/.")


class NurLesenModelAdmin(NurLesenMixin, ModelAdmin):
    """Unfold-`ModelAdmin` ohne Schreibrechte."""


class NurLesenTabularInline(NurLesenMixin, TabularInline):
    """Unfold-`TabularInline` ohne Schreibrechte."""


class NurLesenStackedInline(NurLesenMixin, StackedInline):
    """Unfold-`StackedInline` ohne Schreibrechte."""
