"""Formularfelder, die mehrere Apps brauchen (Audit Etappe 2).

Bewusst NICHT in `core/forms.py`: Dort baut `SchadenForm` beim Import eine
mandantenabhängige Queryset — wer das Modul importiert, weckt sie.
"""
from django import forms


class SchweizerZahl(forms.DecimalField):
    """Nimmt Beträge so an, wie die Oberfläche sie zeigt: «CHF 1'250'000.50»,
    «4,5». Normalisiert wird erst beim Umwandeln (`_num`) — die ROHEINGABE
    bleibt im Formular, damit sie nach einem Fehler unverändert im Feld steht
    («etwa 80», nicht «etwa80»)."""

    def to_python(self, value):
        from core.views.fw._basis import _num
        if value not in self.empty_values:
            value = _num(value)
        return super().to_python(value)
