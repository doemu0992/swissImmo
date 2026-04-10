# crm/forms.py
from django import forms
from .models import Mieter

class MieterForm(forms.ModelForm):
    class Meta:
        model = Mieter
        fields = ['is_company', 'firma', 'anrede', 'vorname', 'nachname', 'email', 'telefon', 'strasse', 'plz', 'ort']
        widgets = {
            # Checkbox für AlpineJS präparieren
            'is_company': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500 cursor-pointer', 'x-model': 'isCompany'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'is_company':
                field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'