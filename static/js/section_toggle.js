// static/js/section_toggle.js

document.addEventListener('DOMContentLoaded', function() {

    // =====================================================================
    // 1. ZERSTÖRUNG DER INNENLIEGENDEN UNFOLD-RAHMEN (Globaler Clean-Look)
    // =====================================================================
    const readonlyBoxes = document.querySelectorAll('td .readonly');

    readonlyBoxes.forEach(box => {
        box.style.setProperty('border', 'none', 'important');
        box.style.setProperty('background', 'transparent', 'important');
        box.style.setProperty('background-color', 'transparent', 'important');
        box.style.setProperty('box-shadow', 'none', 'important');
        box.style.setProperty('padding', '0', 'important');
        box.classList.remove('bg-base-50', 'border', 'border-base-200', 'shadow-xs', 'bg-white', 'dark:bg-base-800');
    });

    const inlineCells = document.querySelectorAll('td.field-tabular');
    inlineCells.forEach(cell => {
        cell.style.setProperty('vertical-align', 'middle', 'important');
        cell.style.setProperty('padding-top', '1rem', 'important');
        cell.style.setProperty('padding-bottom', '1rem', 'important');
    });

    // =====================================================================
    // 2. GLOBALES INLINE-EDITING (Für alle Apps: CRM, Finanzen, Portfolio)
    // =====================================================================

    const realSaveBtn = document.querySelector('button[name="_save"], input[name="_save"]');
    if (realSaveBtn) {
        const bottomBar = realSaveBtn.closest('.submit-row') || realSaveBtn.closest('.sticky') || realSaveBtn.parentElement;
        if (bottomBar) {
            bottomBar.style.display = 'none';
        }
    }

    // FIX: Ignoriere explizit .map-fieldset UND .header-fieldset!
    const fieldsets = document.querySelectorAll('fieldset:not(.map-fieldset):not(.header-fieldset)');

    fieldsets.forEach(fieldset => {
        if (fieldset.closest('.inline-group') || fieldset.closest('.js-inline-admin-formset') || (fieldset.id && fieldset.id.includes('-group'))) {
            return;
        }

        const titleEl = fieldset.querySelector('h2');
        if (!titleEl) return;

        const formRowsContainer = document.createElement('div');
        formRowsContainer.className = 'edit-mode-container hidden';

        const rows = fieldset.querySelectorAll('.form-row');
        if (rows.length === 0) return;
        rows.forEach(row => formRowsContainer.appendChild(row));

        const readOnlyContainer = document.createElement('div');
        readOnlyContainer.className = 'view-mode-container grid grid-cols-1 lg:grid-cols-2 gap-6 py-4';

        rows.forEach(row => {
            const inputs = row.querySelectorAll('input, select, textarea, .readonly');
            const labels = row.querySelectorAll('label');

            inputs.forEach((input, index) => {
                if(input.type === 'hidden') return;

                let labelText = 'Feld';
                if (labels[index]) {
                    labelText = labels[index].innerText.replace('*', '').trim();
                } else if (input.closest('.form-row').querySelector('label')) {
                    labelText = input.closest('.form-row').querySelector('label').innerText.replace('*', '').trim();
                }

                let valueText = '-';
                if (input.classList.contains('readonly')) {
                    // FIX: Benutze innerHTML anstelle von innerText, um HTML/Badges nicht zu zerstören!
                    valueText = input.innerHTML.trim() || '-';
                } else if (input.tagName === 'SELECT') {
                    const selected = input.options[input.selectedIndex];
                    valueText = selected ? selected.text : '-';
                } else if (input.type === 'checkbox') {
                    valueText = input.checked ? 'Ja' : 'Nein';
                } else {
                    valueText = input.value || '-';
                }

                const valueDiv = document.createElement('div');
                valueDiv.innerHTML = `
                    <div class="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">${labelText}</div>
                    <div class="text-sm font-medium text-gray-900 dark:text-gray-100">${valueText}</div>
                `;
                readOnlyContainer.appendChild(valueDiv);
            });
        });

        titleEl.style.display = 'flex';
        titleEl.style.justifyContent = 'space-between';
        titleEl.style.alignItems = 'center';

        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.innerHTML = `
            <svg class="w-3.5 h-3.5 mr-1.5 inline-block" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
            Bearbeiten
        `;
        editBtn.className = 'text-xs text-blue-600 hover:text-blue-800 font-semibold px-3 py-1.5 rounded-md hover:bg-blue-50 transition-colors shadow-sm ring-1 ring-inset ring-blue-600/10 cursor-pointer flex items-center';
        titleEl.appendChild(editBtn);

        const actionButtons = document.createElement('div');
        actionButtons.className = 'flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100 hidden';
        actionButtons.innerHTML = `
            <button type="button" class="cancel-btn px-4 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors cursor-pointer">
                Abbrechen
            </button>
            <button type="button" class="save-btn px-5 py-2 text-sm font-bold rounded-lg shadow-sm transition-colors flex items-center gap-2 cursor-pointer" style="background-color: var(--si-primary) !important; color: #ffffff !important;">
                <svg class="w-4 h-4 inline-block" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                Speichern
            </button>
        `;
        formRowsContainer.appendChild(actionButtons);

        fieldset.appendChild(readOnlyContainer);
        fieldset.appendChild(formRowsContainer);

        const btnCancel = actionButtons.querySelector('.cancel-btn');
        const btnSave = actionButtons.querySelector('.save-btn');

        editBtn.addEventListener('click', (e) => {
            e.preventDefault();
            readOnlyContainer.classList.add('hidden');
            formRowsContainer.classList.remove('hidden');
            actionButtons.classList.remove('hidden');
            editBtn.classList.add('hidden');
        });

        btnCancel.addEventListener('click', (e) => {
            e.preventDefault();
            readOnlyContainer.classList.remove('hidden');
            formRowsContainer.classList.add('hidden');
            actionButtons.classList.add('hidden');
            editBtn.classList.remove('hidden');
        });

        btnSave.addEventListener('click', (e) => {
            e.preventDefault();
            btnSave.innerHTML = `
                <svg class="animate-spin w-4 h-4 mr-2 inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                Speichert...
            `;
            btnSave.style.opacity = '0.7';

            const targetContinueBtn = document.querySelector('button[name="_continue"], input[name="_continue"]');
            if(targetContinueBtn) {
                targetContinueBtn.click();
            } else {
                const form = document.querySelector('form');
                const continueInput = document.createElement('input');
                continueInput.type = 'hidden';
                continueInput.name = '_continue';
                continueInput.value = 'Speichern und weiter bearbeiten';
                form.appendChild(continueInput);
                form.submit();
            }
        });

        const hasError = fieldset.querySelector('ul.errorlist') !== null;
        if (hasError) {
            editBtn.click();
        }
    });
});