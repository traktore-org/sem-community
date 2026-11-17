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

/**
 * Resolve the load-device row a "Configure" action targets. Rows MUST be
 * matched by their UNIQUE `id`, never by `energySensor`: the latter is
 * null/'' for every device without an Energy-Dashboard energy counter
 * (service-registered loads, direct heat-pump/hot-water, the battery row), so
 * an energySensor lookup collides all such rows onto the first empty-key
 * device and opens a sibling's control in the config card (#621). Pure.
 *
 * @param {Array<{id:string}>} devices
 * @param {string} deviceId
 * @returns {object|null} the matching device row, or null
 */
export function findDeviceForConfig(devices, deviceId) {
    return (devices || []).find((d) => d.id === deviceId) || null;
}

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

// (#1321) HA's theme variables only: the box follows the light and dark theme.
const FIELD_STYLE =
    'width:100%;padding:8px;margin:6px 0 12px;border-radius:4px 4px 0 0;border:0;border-bottom:1px solid var(--secondary-text-color);background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit;box-sizing:border-box';
const LABEL_STYLE = 'font-size:var(--ha-font-size-s,12px);color:var(--secondary-text-color)';
const NOTE_STYLE = 'font-size:var(--ha-font-size-s,12px);color:var(--secondary-text-color);margin:-6px 0 12px;max-width:340px';

/**
 * Build the modal's inner HTML (the dialog box). Pure → returns a string so
 * the pre-fill wiring is unit-testable (the #219 regression: the form must
 * carry the saved values, not open blank).
 *
 * @param {string} deviceName
 * @param {object} values  from controlToFormValues()
 * @param {(key:string)=>string} t  translate fn
 * @param {boolean} hasManual  show the "Remove mapping" button (manual mapping set)
 * @param {string} inUse  (#1145) the entity SEM already drives from the Configuration
 *   tab; named above the empty form so it does not read as "nothing set"
 */
/** (#1341) The longest name a load may be given — the backend's cap. */
export const LOAD_NAME_MAX = 60;

/**
 * (#1341) A typed load name as it is saved: one line, trimmed, capped.
 * Empty means "no own name" and brings the automatic name back.
 */
export function cleanLoadName(raw) {
    return String(raw == null ? '' : raw).replace(/\s+/g, ' ').trim().slice(0, LOAD_NAME_MAX).trim();
}

export function buildLoadConfigModalHTML({ deviceName, values, t, hasManual = false, behindRelay = null, inUse = '', ownName = null, autoName = '', dialog = false, textfield = false }) {
    const v = values;
    const isService = v.type === 'service';
    const opt = (val, label) =>
        `<option value="${val}" ${v.type === val ? 'selected' : ''}>${label}</option>`;
    // ha-textfield when HA has it, else a native input in HA's look
    const field = (id, type, value, extra = '') => (textfield
        ? `<ha-textfield id="${id}" type="${type}" value="${escapeHtml(value)}" ${extra} style="display:block;margin:6px 0 12px"></ha-textfield>`
        : `<input id="${id}" type="${type}" ${extra} value="${escapeHtml(value)}" style="${FIELD_STYLE}">`);
    const label = (text) => `<label style="${LABEL_STYLE}">${text}</label>`;
    const btn = (id, text, slot, kind) => (dialog
        ? `<ha-button id="${id}" slot="${slot}" appearance="${kind}">${text}</ha-button>`
        : `<button id="${id}" style="padding:0 16px;min-height:36px;border-radius:20px;border:0;cursor:pointer;font:inherit;${kind === 'filled'
            ? 'background:var(--primary-color);color:var(--text-primary-color)'
            : 'background:transparent;color:var(--primary-color)'}">${text}</button>`);
    const form = `
            ${inUse ? `<div class="cfg-in-use" style="${LABEL_STYLE};margin-bottom:12px">${escapeHtml(t('cfg_in_use_hint').replace(/\{entity\}/g, inUse))}</div>` : ''}
            ${ownName === null ? '' : `
            ${label(t('cfg_own_name'))}
            ${field('cfg-name', 'text', ownName, `maxlength="${LOAD_NAME_MAX}" placeholder="${escapeHtml(autoName)}"`)}
            <div style="${NOTE_STYLE}">${t('cfg_own_name_hint')}</div>`}
            ${label(t('control_type'))}
            <select id="cfg-type" style="${FIELD_STYLE}">
                ${opt('switch', t('mode_switch'))}
                ${opt('current', t('mode_current'))}
                ${opt('input_boolean', t('mode_input_boolean'))}
                ${opt('service', t('mode_service'))}
            </select>
            <div id="cfg-entity-group" style="display:${isService ? 'none' : 'block'}">
                ${label(t('control_entity'))}
                ${field('cfg-entity', 'text', v.entity, 'placeholder="switch.example"')}
            </div>
            <div id="cfg-service-group" style="display:${isService ? 'block' : 'none'}">
                ${label(t('svc_service'))}
                ${field('cfg-service', 'text', v.service, 'placeholder="keba.set_current"')}
                ${label(t('svc_param'))}
                ${field('cfg-param', 'text', v.param, 'placeholder="current"')}
                <div style="display:flex;gap:8px">
                    <div style="flex:1">
                        ${label(t('svc_shed_value'))}
                        ${field('cfg-shed', 'number', v.shed_value)}
                    </div>
                    <div style="flex:1">
                        ${label(t('svc_restore_value'))}
                        ${field('cfg-restore', 'number', v.restore_value)}
                    </div>
                </div>
            </div>
            ${behindRelay === null ? '' : `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 2px">
                <span>${t('cfg_behind_operator_relay')}</span>
                <span id="cfg-relay" role="switch" aria-checked="${behindRelay ? 'true' : 'false'}" class="${behindRelay ? 'on' : ''}"
                      style="cursor:pointer"></span>
            </div>
            <div style="${NOTE_STYLE};margin-top:0">${t('cfg_help_behind_operator_relay')}</div>
            <style>
                #cfg-relay { width:36px;height:14px;border-radius:7px;background:color-mix(in srgb,var(--secondary-text-color) 45%,transparent);position:relative;display:inline-block;flex:none;transition:background .15s }
                #cfg-relay::after { content:'';position:absolute;left:0;top:-3px;width:20px;height:20px;border-radius:50%;background:var(--secondary-text-color);transition:left .15s,background .15s }
                #cfg-relay.on { background:color-mix(in srgb,var(--primary-color) 50%,transparent) }
                #cfg-relay.on::after { left:16px;background:var(--primary-color) }
            </style>`}
            <div class="cfg-error" style="color:var(--error-color);font-size:var(--ha-font-size-m,14px);margin:4px 0 8px;display:none"></div>`;
    const actions = `${hasManual ? btn('cfg-remove', t('clear_mapping'), 'secondaryAction', 'plain') : ''}
        ${btn('cfg-cancel', t('cancel'), 'secondaryAction', 'plain')}
        ${btn('cfg-save', t('save'), 'primaryAction', 'filled')}`;
    if (dialog) return `${form}${actions}`;
    return `
        <div style="background:var(--card-background-color);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color);padding:24px;min-width:320px;max-width:90vw;color:var(--primary-text-color)">
            <div style="font-weight:var(--ha-font-weight-medium,500);font-size:var(--ha-font-size-l,16px);margin-bottom:16px">${t('configure_device')}: ${escapeHtml(deviceName)}</div>
            ${form}
            <div style="display:flex;gap:8px;align-items:center">${hasManual ? btn('cfg-remove', t('clear_mapping'), '', 'plain') : ''}
                <div style="flex:1"></div>
                ${btn('cfg-cancel', t('cancel'), '', 'plain')}
                ${btn('cfg-save', t('save'), '', 'filled')}
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
