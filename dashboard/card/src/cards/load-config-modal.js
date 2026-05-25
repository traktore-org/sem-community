/**
 * Pure helpers for the load-device "Configure" modal (#219).
 *
 * No DOM / Lit / hass dependencies so they can be unit-tested headlessly
 * (see dashboard/card/test/load-config-modal.test.js). The card
 * (sem-load-priority-card.js) wires these into the actual overlay + the
 * ha-entity-picker.
 *
 * The four control types mirror what auto-discovery emits and what
 * load_management.py sheds/restores: switch, current, input_boolean, service.
 */

export const CONTROL_TYPES = ['switch', 'current', 'input_boolean', 'service'];

// Entity-picker domain filter per (entity-based) control type.
export const ENTITY_DOMAINS = {
    switch: ['switch'],
    current: ['number', 'input_number'],
    input_boolean: ['input_boolean'],
};

export function escapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * Saved `control` dict (from the device's sensor attributes) → flat form
 * values with sane defaults. Pure.
 */
export function controlToFormValues(control) {
    const c = control || {};
    const type = CONTROL_TYPES.includes(c.type) ? c.type : 'switch';
    return {
        type,
        entity: c.entity || '',
        service: c.service || '',
        param: c.param || 'current',
        shed_value: c.shed_value != null ? c.shed_value : 0,
        restore_value: c.restore_value != null ? c.restore_value : 16,
    };
}

/**
 * Flat form values → service-call data for `set_device_control_mapping`.
 * Pure. Throws Error(<translation_key>) on validation failure so the caller
 * can render a localized message.
 */
export function formValuesToServiceData(energySensor, v) {
    const type = CONTROL_TYPES.includes(v.type) ? v.type : 'switch';
    if (type === 'service') {
        if (!v.service) throw new Error('mapping_service_required');
        return {
            energy_sensor: energySensor,
            control_type: 'service',
            service: v.service,
            param: v.param || 'current',
            shed_value: Number(v.shed_value),
            restore_value: Number(v.restore_value),
        };
    }
    if (!v.entity) throw new Error('mapping_entity_required');
    return {
        energy_sensor: energySensor,
        control_type: type,
        control_entity: v.entity,
    };
}

const FIELD_STYLE =
    'width:100%;padding:8px;margin:6px 0 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:inherit;box-sizing:border-box';

/**
 * Build the modal's inner HTML (the dialog box). Pure → returns a string so
 * the pre-fill wiring is unit-testable (the #219 regression: the form must
 * carry the saved values, not open blank).
 *
 * @param {string} deviceName
 * @param {object} values  from controlToFormValues()
 * @param {(key:string)=>string} t  translate fn
 */
export function buildLoadConfigModalHTML({ deviceName, values, t }) {
    const v = values;
    const isService = v.type === 'service';
    const opt = (val, label) =>
        `<option value="${val}" ${v.type === val ? 'selected' : ''}>${label}</option>`;
    return `
        <div style="background:var(--card-background-color,#1e1e2e);border-radius:12px;padding:24px;min-width:320px;max-width:90vw;color:var(--primary-text-color,#e0e0e0)">
            <div style="font-weight:700;margin-bottom:16px">${t('configure_device')}: ${escapeHtml(deviceName)}</div>
            <label style="font-size:13px;opacity:0.7">${t('control_type')}</label>
            <select id="cfg-type" style="${FIELD_STYLE}">
                ${opt('switch', t('mode_switch'))}
                ${opt('current', t('mode_current'))}
                ${opt('input_boolean', t('mode_input_boolean'))}
                ${opt('service', t('mode_service'))}
            </select>
            <div id="cfg-entity-group" style="display:${isService ? 'none' : 'block'}">
                <label style="font-size:13px;opacity:0.7">${t('control_entity')}</label>
                <input id="cfg-entity" type="text" placeholder="switch.example" value="${escapeHtml(v.entity)}" style="${FIELD_STYLE}">
            </div>
            <div id="cfg-service-group" style="display:${isService ? 'block' : 'none'}">
                <label style="font-size:13px;opacity:0.7">${t('svc_service')}</label>
                <input id="cfg-service" type="text" placeholder="keba.set_current" value="${escapeHtml(v.service)}" style="${FIELD_STYLE}">
                <label style="font-size:13px;opacity:0.7">${t('svc_param')}</label>
                <input id="cfg-param" type="text" placeholder="current" value="${escapeHtml(v.param)}" style="${FIELD_STYLE}">
                <div style="display:flex;gap:8px">
                    <div style="flex:1">
                        <label style="font-size:13px;opacity:0.7">${t('svc_shed_value')}</label>
                        <input id="cfg-shed" type="number" value="${escapeHtml(v.shed_value)}" style="${FIELD_STYLE}">
                    </div>
                    <div style="flex:1">
                        <label style="font-size:13px;opacity:0.7">${t('svc_restore_value')}</label>
                        <input id="cfg-restore" type="number" value="${escapeHtml(v.restore_value)}" style="${FIELD_STYLE}">
                    </div>
                </div>
            </div>
            <div class="cfg-error" style="color:#f44336;font-size:13px;margin:4px 0 8px;display:none"></div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button id="cfg-cancel" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:rgba(255,255,255,0.1);color:inherit">${t('cancel')}</button>
                <button id="cfg-save" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:#4caf50;color:white">${t('save')}</button>
            </div>
        </div>`;
}

/** Read current form values out of a modal root element. Thin DOM read. */
export function readFormValues(root) {
    const get = (id) => root.querySelector('#' + id);
    return {
        type: get('cfg-type')?.value || 'switch',
        entity: (get('cfg-entity')?.value || '').trim(),
        service: (get('cfg-service')?.value || '').trim(),
        param: (get('cfg-param')?.value || '').trim() || 'current',
        shed_value: get('cfg-shed')?.value,
        restore_value: get('cfg-restore')?.value,
    };
}
