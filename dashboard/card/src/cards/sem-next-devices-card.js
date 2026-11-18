/**
 * SEM Next · Devices (#1321)
 *
 * One list, one order. Every device the load manager knows — chargers,
 * the battery, every load — is one card with the same anatomy: handle ·
 * rank · icon + name + state pill · live kW · ⚙ · verdict, then a body
 * per type (util/next-devices-charger.js, -battery.js, -load.js). The
 * rank is the position; Reorder mode moves cards by drag or ▲▼ and
 * writes the order on Done with update_device_priorities. Above the
 * list: Surplus and peak, with the peak limit and its slot budget.
 *
 * Every number comes from an SEM entity; a missing one leaves its row
 * out. Observer mode disables every control.
 *
 * Config:
 *   type: custom:sem-next-devices-card
 */

import { effectivePlan, planRuns, nextRun } from '../util/plan-facts.js';
import { SEMNextBase, html, css, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { haDefined, ensureHaElements } from '../util/ha-elements.js';
import { PEAK_KW, PEAK_TEXT, peakQuestion, peakWrites } from '../util/peak-questions.js';
import { semDefineCard } from '../base/sem-shared.js';
import { repeat } from 'lit/directives/repeat.js';
import { moveToIndex, computeDropIndex } from '../util/drag-reorder.js';
import { slotStatus, isUncapped } from '../util/peak-slot.js';
import { downloadBase64 } from '../util/download.js';
import {
    ENTITY_DOMAINS, controlToFormValues, formValuesToServiceData, buildLoadConfigModalHTML,
    readFormValues, findDeviceForConfig,
} from './load-config-modal.js';
import { deviceRows, statePill, surplusInUse, ratedKey, swap, priorityPayload, verdictKey, unmanagedLoads, registerPayload, entityOptions, SWITCH_DOMAINS, defaultOpen, PHONE_MAX_PX, OPEN_CHARGE_PLAN_KEY, CHARGER_PREFIX } from '../util/next-devices.js';
import { chargerBody } from '../util/next-devices-charger.js';
import { batteryBody } from '../util/next-devices-battery.js';
import { loadBody } from '../util/next-devices-load.js';
import { wouldFor, wouldList, wouldLine } from '../util/why-rows.js';

const DOMAIN = 'solar_energy_management';
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const HOLD_MS = 15000;

const IDS = [
    'sensor.sem_controllable_devices_count', 'sensor.sem_energy_plan', 'sensor.sem_charging_state',
    'sensor.sem_surplus_total_w', 'sensor.sem_surplus_distributable_w', 'sensor.sem_surplus_allocated_w',
    'sensor.sem_surplus_unallocated_w', 'sensor.sem_surplus_active_devices', 'sensor.sem_surplus_total_devices',
    'sensor.sem_consecutive_peak_15min', 'sensor.sem_target_peak_limit', 'sensor.sem_peak_margin',
    'sensor.sem_current_vs_peak_percentage', 'sensor.sem_monthly_consecutive_peak', 'sensor.sem_available_load_reduction',
    'sensor.sem_load_management_recommendation', 'sensor.sem_load_management_status',
    'sensor.sem_battery_soc', 'sensor.sem_battery_power', 'sensor.sem_battery_status', 'sensor.sem_battery_spendable_kwh',
    'sensor.sem_battery_dynamic_floor_pct', 'sensor.sem_battery_charge_pacing', 'sensor.sem_battery_measured_capacity_kwh',
    'sensor.sem_battery_capacity_drift_pct', 'sensor.sem_diag_battery_capacity', 'sensor.sem_battery_health_score',
    'sensor.sem_battery_cycles_estimated', 'sensor.sem_battery_temperature', 'sensor.sem_daily_battery_charge_energy',
    'sensor.sem_daily_battery_discharge_energy', 'sensor.sem_forecast_source', 'sensor.sem_forecast_trust_d1',
    'sensor.sem_forecast_trust_d2', 'sensor.sem_tariff_current_export_rate', 'sensor.sem_vehicle_soc',
    'sensor.sem_heat_pump_sg_ready_state', 'sensor.sem_heat_pump_mode', 'binary_sensor.sem_heat_pump_solar_boost',
    'sensor.sem_heat_pump_cost_of_heat', 'sensor.sem_lifetime_ev_energy', 'sensor.sem_lifetime_ev_cost',
    'sensor.sem_lifetime_ev_solar_share', 'sensor.sem_lifetime_ev_sessions',
    'select.sem_battery_mode', 'select.sem_pause_duration',
    'number.sem_battery_buffer_soc', 'number.sem_battery_priority_soc', 'number.sem_battery_auto_start_soc',
    'number.sem_battery_assist_max_power', 'number.sem_battery_assist_min_surplus', 'number.sem_battery_capacity',
    'number.sem_legionella_target_temp', 'number.sem_legionella_interval_hours', 'number.sem_heat_pump_boost_offset',
    'switch.sem_battery_may_assist_ev', 'switch.sem_battery_may_export', 'switch.sem_battery_charge_pacing_enabled',
];
const CHARGER_ENTITIES = [
    ['sensor', 'power'], ['sensor', 'commanded_current'], ['sensor', 'daily_energy'], ['sensor', 'session_energy'],
    ['sensor', 'session_energy_external'], ['sensor', 'session_solar_share'], ['sensor', 'vehicle_soc'], ['sensor', 'estimated_soc'],
    ['sensor', 'flow_solar_to_ev_energy'], ['sensor', 'flow_grid_to_ev_energy'], ['sensor', 'flow_battery_to_ev_energy'],
    ['select', 'charge_mode'], ['select', 'ev_target_type'], ['select', 'phase_mode'], ['time', 'target_time'],
    ['number', 'daily_ev_target'], ['number', 'daily_ev_target_max'], ['number', 'target_soc'], ['number', 'target_soc_max'],
    ['number', 'ev_battery_capacity_kwh'], ['number', 'minimum_current'], ['number', 'maximum_current'],
    ['number', 'ev_kwh_per_100km'], ['number', 'ev_phases'], ['button', 'pause_charging'], ['binary_sensor', 'connected'],
];

const OPEN_KEY = 'sem-next-devices-open';
function readOpen() {
    try { const v = JSON.parse(window.localStorage.getItem(OPEN_KEY) || 'null'); return v && typeof v === 'object' ? v : {}; } catch (e) { return {}; }
}
function writeOpen(map) {
    try { window.localStorage.setItem(OPEN_KEY, JSON.stringify(map)); } catch (e) { /* private window: nothing kept */ }
}

/** (#1321) "Normal" and "Normal operation" say one thing: show the longer once. */
function sameWords(a, b) {
    const x = String(a || '').trim().toLowerCase(), y = String(b || '').trim().toLowerCase();
    return !!x && !!y && (y.startsWith(x) || x.startsWith(y));
}

const devicesCss = css`
    .addform { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; margin-top: 6px; }
    .addform label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--n-fg2); }
    .addform input.txt { max-width: none; }
    .addform ha-textfield { max-width: none; }
    .addform .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .addform .acts { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
    ha-entity-picker { display: block; }
    .grid { align-items: start; grid-template-columns: minmax(0, 1fr); }
    .dev.folded .body { display: none; }
    .dev .would { margin: 2px 0 6px 40px; }
    .dev.folded .head { margin-bottom: 0; }
    .dev .fold { border: 0; background: none; color: var(--n-fg3); cursor: pointer; padding: 4px; border-radius: 8px; display: inline-flex; }
    .dev .fold ha-icon { transition: transform .15s; }
    .dev:not(.folded) .fold ha-icon { transform: rotate(180deg); }
    .reorder .dev .fold { display: none; }
    .dev .name.tap { cursor: pointer; }
    .period button.pill { border: 0; cursor: pointer; }
    .grid.reorder { grid-template-columns: 1fr; }
    .dev.dragging { opacity: .95; z-index: 20; position: relative; outline: 2px solid var(--n-accent); cursor: grabbing; }
    .dev.drop-above { box-shadow: 0 -3px 0 0 var(--n-accent); }
    .dev.drop-below { box-shadow: 0 3px 0 0 var(--n-accent); }
    .dev .live { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .edit { display: inline-flex; gap: 4px; align-items: center; flex-wrap: wrap; }
    .edit input[type="number"] { width: 84px; }
    .days { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 0; border-top: 1px solid var(--n-line); }
    .dayin { display: flex; flex-direction: column; font-size: 11px; color: var(--n-fg3); gap: 2px; }
    .dayin input { max-width: 96px; padding: 2px 6px; }
    .days .help { flex: 1 0 100%; margin: 0; }
    .banner { display: flex; gap: 10px; align-items: flex-start; background: var(--n-card2); border-radius: 8px; padding: 10px 12px; margin: 0 0 12px; }
    .banner ha-icon { color: var(--n-warn); }
    .banner.bad ha-icon { color: var(--n-bad); }
`;

class SEMNextDevicesCard extends SEMNextBase {
    static get styles() { return [nextCss, devicesCss]; }
    static get properties() {
        return { ...super.properties, _reorder: { state: true }, _open: { state: true }, _adding: { state: true }, _addForm: { state: true }, _addBusy: { state: true }, _tick: { state: true } };
    }

    constructor() {
        super();
        this._reorder = false;
        this._open = readOpen();
        this._adding = false;
        this._addForm = {};
        this._addBusy = false;
        this._tick = 0;
        this._work = null;      // the rows while reordering
        this._held = null;      // the order just written, until the sensor has it
        this._holdUntil = 0;
        this._sess = {};
        this._sessWatch = {};
        this._depOpen = {};
        this._batteries = [];
    }

    // ── reactivity ──
    _watchIds() {
        const ids = [...super._watchIds(), ...IDS];
        const st = this._hass?.states || {};
        for (const cid of this._chargers) {
            for (const [dom, s] of CHARGER_ENTITIES) {
                const id = dom + '.sem_charger_' + cid + '_' + s;
                if (st[id]) ids.push(id);
            }
        }
        const devices = this._attrs('sensor.sem_controllable_devices_count').devices || {};
        for (const info of Object.values(devices)) {
            if (!info) continue;
            for (const id of [info.power_entity, info.switch_entity, info.control && info.control.entity,
                info.goals && info.goals.stop_entity, info.goals && info.goals.comfort_entity]) {
                if (id && st[id]) ids.push(id);
            }
        }
        const bats = [];
        for (const id of Object.keys(st)) {
            const m = id.match(/^select\.sem_battery_(b\d+)_mode$/);
            if (m) bats.push(m[1]);
        }
        bats.sort();
        this._batteries = bats;
        for (const bid of bats) {
            ids.push('select.sem_battery_' + bid + '_mode', 'number.sem_battery_' + bid + '_reserve_soc',
                'number.sem_battery_' + bid + '_capacity_kwh');
            for (const s of ['soc', 'power', 'status']) if (st['sensor.sem_battery_' + bid + '_' + s]) ids.push('sensor.sem_battery_' + bid + '_' + s);
        }
        for (const id of ['sensor.sem_energy_plan', 'number.sem_battery_reserve_soc']) if (st[id]) ids.push(id);
        return ids;
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (this._drag) this._dragEnd({ type: 'pointercancel' });
    }

    updated(changed) {
        super.updated(changed);
        this._watchSessions();
        this._afterRender();
    }

    // ── rows ──
    _rowsNow() {
        if (this._reorder && this._work) return this._work;
        if (this._held && Date.now() < this._holdUntil) return this._held;
        this._held = null;
        const devices = this._attrs('sensor.sem_controllable_devices_count').devices || {};
        const st = this._hass?.states || {};
        const rows = deviceRows(devices, this._chargers, {
            hasBattery: this._has('sensor.sem_battery_soc'),
            chargerName: (cid) => this._chargerName(cid),
            loadName: (id, info) => this._loadName(id, info),
            states: st,
        });
        for (const r of rows) {
            if (r.type === 'charger') { r.name = this._chargerName(r.cid); r.icon = 'mdi:ev-station'; continue; }
            if (r.type === 'battery') { r.name = r.name || this._t('next_src_battery'); continue; }
            for (const id of [r.controlEntity, r.powerEntity]) {
                const ic = id && st[id] && st[id].attributes && st[id].attributes.icon;
                if (ic) { r.icon = ic; break; }
            }
        }
        return rows;
    }

    /**
     * The next planned start for a plan id (ev:<cid> · battery · load:<id>), as HH:MM, or ''.
     * Several ids: the earliest of them (a heater's run-time block and its Keep at block).
     */
    _plannedAt(...planIds) {
        // (#1321) the same plan every screen reads; tomorrow's hour says tomorrow
        const plan = effectivePlan(this._attrs('sensor.sem_energy_plan'));
        // the next run, not the next change of watts inside one that is under way
        const now = Date.now();
        const want = new Set(planIds.map(String));
        const next = nextRun(planRuns(plan, (id) => want.has(id), now), now);
        return next ? this._clockDay(next.s) : '';
    }

    /** The pill's words: the state, then why when the engine names a cause. */
    _pillText(pill) {
        const text = this._tf(pill.key, pill.params);
        return pill.why ? text + ' · ' + this._t(pill.why) : text;
    }

    _live(row) {
        const cs = this._attrs('sensor.sem_charging_state');
        if (row.type === 'charger') {
            const cid = row.cid;
            const modeId = this._chargerEntity('select', cid, 'charge_mode');
            const modeAttrs = modeId ? this._attrs(modeId) : {};
            const paused = modeId && this._str(modeId) === 'off' && !!modeAttrs.paused_until;
            const connId = this._chargerEntity('binary_sensor', cid, 'connected');
            return {
                powerW: this._powerW('sensor.sem_charger_' + cid + '_power'),
                amps: this._num('sensor.sem_charger_' + cid + '_commanded_current'),
                paused, pausedUntil: paused ? this._hhmm(modeAttrs.paused_until) : '',
                plannedAt: this._plannedAt('ev:' + cid),
                connected: connId ? this._str(connId) === 'on' : null,
            };
        }
        if (row.type === 'battery') {
            const boost = cs.battery_boost || null;
            return {
                powerW: this._powerW('sensor.sem_battery_power'),
                status: this._str('sensor.sem_battery_status'),
                boost: !!(boost && boost.active),
                mode: this._str('select.sem_battery_mode'),
            };
        }
        const parent = row.blockedBy ? this._rowsNow().find((r) => r.id === row.blockedBy) : null;
        return {
            powerW: row.powerEntity ? this._powerW(row.powerEntity) : null,
            plannedAt: this._plannedAt('load:' + row.id, 'comfort:' + row.id),
            sunW: this._powerW('sensor.sem_solar_power'),
            fmtTemp: (c) => this._temp(c),
            parentName: parent ? parent.name : '',
        };
    }

    // ── services ──
    _svc(service, data) {
        if (!this._hass) return Promise.resolve();
        return this._call(DOMAIN, service, data, undefined, false).catch((err) => this._showError(err));
    }

    _dev(deviceId, property, value) {
        return this._svc('update_device_config', { device_id: deviceId, property, value });
    }

    _showError(err) { this._failed(err); }

    _setTime(id, value) {
        if (!value) return;
        this._callService('time', 'set_value', { entity_id: id, time: value.length === 5 ? value + ':00' : value });
    }

    /** Every row on this screen puts its sub line under the label, as HA's settings rows do. */
    _row(icon, text, value, sub, o = {}) { return super._row(icon, text, value, sub, { help: true, ...o }); }

    // ── editable values (#1321): the value shows as plain text in its row; a tap opens the one edit dialog ──
    /** A value that opens its editor; `editor()` gives the dialog's spec, `o.label` its title. */
    _inline(key, text, editor, o = {}) {
        // the dialog is named after the row the value sits in
        const open = (e) => {
            const row = e && e.currentTarget && e.currentTarget.closest ? e.currentTarget.closest('.row') : null;
            const title = o.label || (row && row.querySelector('.t') ? row.querySelector('.t').textContent.trim() : '');
            this._editDialog({ title, ...editor() });
        };
        return this._vbtn(text, open, { disabled: !!o.disabled });
    }

    _numEdit(key, { value, min, max, step, unit, onCommit }) {
        return { kind: 'number', value, min, max, step, unit, onCommit };
    }

    /** (#1081) One text box. */
    _textEdit(key, { value, placeholder, onCommit }) {
        return { kind: 'text', value: value || '', placeholder, onCommit };
    }

    _selEdit(key, { value, options, onCommit }) {
        return { kind: 'select', value, options: (options || []).map((o) => ({ value: o.key, label: o.label })), onCommit };
    }

    _timeEdit(key, { value, onCommit }) {
        return { kind: 'time', value: value || '', onCommit };
    }

    /** Two numbers (At least · Up to) in one dialog. */
    _pairEdit(key, { a, b, unit, onCommit }) {
        return { kind: 'pair', a, b, unit, onCommit };
    }

    /** "{a} and {b}" with templates in the slots. */
    _sentence(text, parts) {
        const s = String(text || '');
        const re = /\{(\w+)\}/g;
        const out = [];
        let last = 0, m;
        while ((m = re.exec(s))) {
            if (m.index > last) out.push(s.slice(last, m.index));
            out.push(parts && (m[1] in parts) ? parts[m[1]] : m[0]);
            last = m.index + m[0].length;
        }
        if (last < s.length) out.push(s.slice(last));
        return html`${out}`;
    }

    _dayName(i) {
        try {
            return new Intl.DateTimeFormat(this._hass?.language || 'en', { weekday: 'short', timeZone: 'UTC' })
                .format(new Date(Date.UTC(2024, 0, 1 + i, 12)));
        } catch (e) { return ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][i]; }
    }

    _toggleDep(cid) {
        this._depOpen = { ...this._depOpen, [cid]: !this._depOpen[cid] };
        this._tick++;
    }

    // ── sessions (this month row + the .xlsx) ──
    _watchSessions() {
        if (!this._hass) return;
        for (const cid of this._chargers) {
            const conn = this._str('binary_sensor.sem_charger_' + cid + '_connected');
            const sess = this._num('sensor.sem_charger_' + cid + '_session_energy') || 0;
            const prev = this._sessWatch[cid];
            this._sessWatch[cid] = { conn, sess };
            const ended = prev && ((prev.conn === 'on' && conn === 'off') || (prev.sess > 0 && sess === 0));
            if (!prev || ended) this._loadSessions(cid);
        }
    }

    async _loadSessions(cid) {
        const st = this._sess[cid];
        if ((st && st.loading) || !this._hass?.callWS) return;
        this._sess = { ...this._sess, [cid]: { ...(st || {}), loading: true } };
        let rows = [];
        try {
            const res = await this._hass.callWS({ type: DOMAIN + '/session_history', charger_id: cid });
            rows = Array.isArray(res?.rows) ? res.rows : [];
        } catch (_err) { rows = []; }
        this._sess = { ...this._sess, [cid]: { loading: false, rows } };
        this._tick++;
    }

    async _downloadXlsx(cid) {
        if (!this._hass?.callWS) return;
        try {
            const res = await this._hass.callWS({ type: DOMAIN + '/session_history/xlsx', charger_id: cid });
            if (res?.base64) downloadBase64(res.filename || 'sem-sessions.xlsx', res.base64, XLSX_MIME);
        } catch (err) { this._showError(err); }
    }

    // ── add a device ──
    async _toggleAdd() {
        this._adding = !this._adding;
        if (this._adding) {
            this._addForm = {};
            await this._ensureEntityPicker();
            this.requestUpdate();
        }
    }

    /** An entity field: HA's picker when it is loaded, else a text box with the matching ids to choose from. */
    _entityField(value, domains, onChange, o = {}) {
        if (customElements.get('ha-entity-picker')) {
            return html`<ha-entity-picker .hass=${this._hass} .value=${value || ''} .includeDomains=${domains}
                .entityFilter=${o.filter || undefined} .label=${o.label || ''} allow-custom-entity
                @value-changed=${(e) => onChange(String(e.detail?.value || ''))}></ha-entity-picker>`;
        }
        const listId = 'ents-' + domains.join('-') + (o.filter ? '-f' : '');
        const ids = entityOptions(this._hass?.states, domains, o.filter);
        // a native input: a datalist only attaches to one
        return html`<input class="txt" list=${listId} .value=${value || ''} placeholder=${o.label || ''}
            @change=${(e) => onChange(e.target.value.trim())}>
            <datalist id=${listId}>${ids.map((id) => html`<option value=${id}></option>`)}</datalist>`;
    }

    /** An entity editor: the dialog's picker; an empty choice clears. */
    _entEdit(key, { value, domains, filter, onCommit }) {
        return { kind: 'entity', value, domains, filter, allowClear: true, onCommit };
    }

    _setAdd(field, value) { this._addForm = { ...this._addForm, [field]: value }; }

    async _submitAdd(rows) {
        const { data, error } = registerPayload(this._addForm, rows);
        if (error) { this._toast(this._t(error), true); return; }
        this._addBusy = true;
        try {
            await this._call(DOMAIN, 'register_surplus_device', data, undefined, false);
            this._toast(this._tf('next_add_done', { name: data.name }));
            this._adding = false;
            this._addForm = {};
        } catch (err) {
            this._failed(err);
        } finally {
            this._addBusy = false;
        }
    }

    _addSheet(rows) {
        const t = (k) => this._t(k);
        const dis = this._addBusy;
        const f = this._addForm || {};
        const loose = unmanagedLoads(rows);
        const known = loose.length
            ? html`<div class="rows">${loose.map((r) => {
                const w = r.powerEntity ? this._powerW(r.powerEntity) : null;
                return this._row('mdi:power-plug-outline', r.name,
                    this._btn(t('next_add_control_it'), () => this._showConfigureModal(r.id, r.name), { small: true }),
                    w === null ? t('next_add_measured_only') : this._kw(w) + ' · ' + t('next_add_measured_only'));
            })}</div>`
            : html`<p class="help">${t('next_add_none_loose')}</p>`;
        const form = html`<div class="addform">
            <label>${t('next_add_name')}${this._input({ cls: 'txt', value: f.name || '', onInput: (e) => this._setAdd('name', e.target.value) })}</label>
            <label>${t('next_add_switch')}${this._entityField(f.entity, SWITCH_DOMAINS, (v) => this._setAdd('entity', v))}</label>
            <label>${t('next_add_power_sensor')}${this._entityField(f.power, ['sensor'], (v) => this._setAdd('power', v),
                { filter: (st) => ['W', 'kW'].includes(st?.attributes?.unit_of_measurement) })}</label>
            <div class="two">
                <label>${t('next_add_rated')}${this._input({ cls: 'txt', type: 'number', min: 0, step: 50, value: f.rated || '', onInput: (e) => this._setAdd('rated', e.target.value) })}</label>
                <label>${t('next_priority')}${this._input({ cls: 'txt', type: 'number', min: 1, max: 10, step: 1, value: f.priority || '',
                    placeholder: String(Math.min(10, rows.length + 1)), onInput: (e) => this._setAdd('priority', e.target.value) })}</label>
            </div>
            <p class="help">${t('next_add_starts_off')}</p>
            <div class="acts">
                ${this._btn(t('next_cancel'), () => this._toggleAdd(), { ghost: true })}
                ${this._btn(t('next_add_btn'), () => this._submitAdd(rows), { primary: true, icon: 'mdi:plus', disabled: dis })}
            </div></div>`;
        return this._sec(t('next_add_device'), html`
            <p class="help">${t('next_add_energy_help')} ${this._link(t('next_add_open_energy'), () => this._go('/config/energy'))}</p>
            <h4 class="sm muted">${t('next_add_measured_title')}</h4>
            ${known}
            <h4 class="sm muted">${t('next_add_new_title')}</h4>
            ${form}`);
    }

    // ── fold ──
    /** Chargers and batteries start open, loads folded; a tap is remembered. */
    _isOpen(row) {
        if (this._all) return true;
        const v = this._open[row.id];
        return v === undefined ? defaultOpen(row.type, this._narrow()) : !!v;
    }

    /** (#1321) A phone-width screen: every card starts folded there. */
    _narrow() {
        try { return !!(window.matchMedia && window.matchMedia(`(max-width: ${PHONE_MAX_PX}px)`).matches); } catch (e) { return false; }
    }

    /** (#1321) Open a charger's card at its charge plan, e.g. from the Plan screen. */
    _openChargePlan(cid) {
        this._open = { ...this._open, [CHARGER_PREFIX + cid]: true };
        writeOpen(this._open);
        this._depOpen = { ...this._depOpen, [cid]: true };
        this._scrollTo = CHARGER_PREFIX + cid;
        this._tick++;
    }

    /** A charge plan another screen asked for, read once. */
    _takeOpenRequest() {
        let cid = null;
        try { cid = window.sessionStorage.getItem(OPEN_CHARGE_PLAN_KEY); if (cid) window.sessionStorage.removeItem(OPEN_CHARGE_PLAN_KEY); } catch (e) { cid = null; }
        if (cid) this._openChargePlan(cid);
    }

    _afterRender() {
        if (this._chargers && this._chargers.length && !this._openTaken) { this._openTaken = true; this._takeOpenRequest(); }
        if (this._scrollTo) {
            const el = this.renderRoot && this.renderRoot.querySelector(`[data-id="${this._scrollTo}"]`);
            if (el) { this._scrollTo = null; el.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
        }
    }

    _toggleOpen(row) {
        this._open = { ...this._open, [row.id]: !this._isOpen(row) };
        writeOpen(this._open);
    }

    _setAllOpen(rows, open) {
        const next = { ...this._open };
        for (const r of rows) next[r.id] = open;
        this._open = next;
        writeOpen(next);
    }

    // ── reorder ──
    _toggleReorder() {
        if (this._reorder) {
            const rows = this._work || [];
            this._reorder = false;
            this._work = null;
            this._held = rows;
            this._holdUntil = Date.now() + HOLD_MS;
            this._svc('update_device_priorities', priorityPayload(rows));
        } else {
            this._work = this._rowsNow();
            this._reorder = true;
        }
    }

    async _move(id, dir) {
        if (!this._reorder || !this._work) return;
        this._work = swap(this._work, id, dir);
        this._tick++;
        await this.updateComplete;
        const el = this.renderRoot.querySelector('.dev[data-id="' + id + '"] [data-mv="' + dir + '"]');
        if (el && el.focus) el.focus();
    }

    _dragStart(e, id) {
        if (!this._reorder || !this._work) return;
        if (e.button != null && e.button !== 0) return;
        const dev = this._work.find((d) => d.id === id);
        if (!dev || (dev.dependsOn || []).length) return;
        e.preventDefault();
        const handle = e.currentTarget;
        const row = handle.closest('.dev');
        const rows = Array.from(this.renderRoot.querySelectorAll('.grid .dev'));
        if (!row || !rows.length) return;
        const centres = rows.map((r) => { const b = r.getBoundingClientRect(); return b.top + b.height / 2; });
        const fromIndex = rows.indexOf(row);
        this._drag = { id, handle, row, rows, centres, y0: e.clientY, fromIndex, dropIndex: fromIndex, pointerId: e.pointerId };
        row.classList.add('dragging');
        try { handle.setPointerCapture(e.pointerId); } catch (_) { /* no capture */ }
        this._dragMoveBound = this._dragMoveBound || this._dragMove.bind(this);
        this._dragEndBound = this._dragEndBound || this._dragEnd.bind(this);
        window.addEventListener('pointermove', this._dragMoveBound);
        window.addEventListener('pointerup', this._dragEndBound);
        window.addEventListener('pointercancel', this._dragEndBound);
    }

    _dragMove(e) {
        const d = this._drag;
        if (!d) return;
        e.preventDefault();
        d.row.style.transform = 'translateY(' + (e.clientY - d.y0) + 'px)';
        const idx = computeDropIndex(d.centres, d.fromIndex, e.clientY);
        if (idx !== d.dropIndex) {
            d.dropIndex = idx;
            d.rows.forEach((r) => r.classList.remove('drop-above', 'drop-below'));
            const target = d.rows[idx < d.fromIndex ? idx : idx + 1];
            if (target && target !== d.row) target.classList.add('drop-above');
            else if (d.rows[d.rows.length - 1]) d.rows[d.rows.length - 1].classList.add('drop-below');
        }
    }

    _dragEnd(e) {
        const d = this._drag;
        if (!d) return;
        window.removeEventListener('pointermove', this._dragMoveBound);
        window.removeEventListener('pointerup', this._dragEndBound);
        window.removeEventListener('pointercancel', this._dragEndBound);
        try { d.handle.releasePointerCapture(d.pointerId); } catch (_) { /* no capture */ }
        d.row.style.transform = '';
        d.row.classList.remove('dragging');
        d.rows.forEach((r) => r.classList.remove('drop-above', 'drop-below'));
        this._drag = null;
        if (e.type !== 'pointercancel' && d.dropIndex !== d.fromIndex && this._work) {
            this._work = moveToIndex(this._work, d.id, d.dropIndex);
            this._tick++;
        }
    }

    // ── configure dialog (the classic Load Priority card's, unchanged in behaviour) ──
    async _ensureEntityPicker() {
        await ensureHaElements(['ha-entity-picker', 'ha-dialog'], 3000);
    }

    async _showConfigureModal(deviceId, deviceName) {
        const dev = findDeviceForConfig(this._rowsNow(), deviceId);
        const energySensor = dev?.energySensor || '';
        const values = controlToFormValues(dev?.control);
        const hasManual = dev?.control?.discovered_via === 'manual_mapping';
        await this._ensureEntityPicker();
        const isLoad = dev && dev.type === 'load';
        // (#1321) one dialog helper in the base: ha-dialog or the plain overlay, Escape, focus back
        const { el: overlay, close } = this._dialog({
            id: 'sem-config-modal', title: `${this._t('configure_device')}: ${deviceName}`,
            build: (useDialog) => buildLoadConfigModalHTML({
                deviceName, values, t: (k) => this._t(k), hasManual,
                behindRelay: isLoad ? !!dev.behindRelay : null,
                inUse: !hasManual && !values.entity ? (dev?.controlEntity || '') : '',
                dialog: useDialog, textfield: haDefined('ha-textfield'),
            }),
        });
        const typeSel = overlay.querySelector('#cfg-type');
        const entityGroup = overlay.querySelector('#cfg-entity-group');
        const serviceGroup = overlay.querySelector('#cfg-service-group');
        const entityInput = overlay.querySelector('#cfg-entity');
        const errDiv = overlay.querySelector('.cfg-error');
        const showError = (msg) => { errDiv.textContent = msg; errDiv.style.display = 'block'; };
        let picker = null;
        if (customElements.get('ha-entity-picker')) {
            picker = document.createElement('ha-entity-picker');
            picker.hass = this._hass;
            picker.allowCustomEntity = true;
            picker.value = entityInput.value;
            picker.includeDomains = ENTITY_DOMAINS[typeSel.value];
            picker.style.cssText = 'display:block;margin:6px 0 12px';
            picker.addEventListener('value-changed', (e) => { entityInput.value = e.detail.value || ''; });
            entityInput.style.display = 'none';
            entityInput.parentNode.insertBefore(picker, entityInput);
        }
        const applyType = () => {
            const isService = typeSel.value === 'service';
            entityGroup.style.display = isService ? 'none' : 'block';
            serviceGroup.style.display = isService ? 'block' : 'none';
            if (picker && !isService) picker.includeDomains = ENTITY_DOMAINS[typeSel.value];
        };
        typeSel.addEventListener('change', applyType);
        const relay = overlay.querySelector('#cfg-relay');
        if (relay && dev) {
            // (#1321) one tap only asks: the switch and the device change on the confirm
            relay.addEventListener('click', () => {
                const on = !relay.classList.contains('on');
                this._askFirst(this._t('cfg_behind_operator_relay'), () => {
                    relay.classList.toggle('on', on);
                    relay.setAttribute('aria-checked', String(on));
                    this._dev(dev.id, 'behind_operator_relay', String(on));
                }, { body: this._t('next_confirm_relay'), okLabel: this._t('next_yes') });
            });
        }
        overlay.querySelector('#cfg-cancel').addEventListener('click', () => close());
        const removeBtn = overlay.querySelector('#cfg-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                this._askFirst(removeBtn.textContent.trim(), () => this._call(DOMAIN, 'remove_device_control_mapping', { energy_sensor: energySensor })
                    .then(() => close()).catch((err) => showError(err.message)), { body: this._t('next_confirm_clear_mapping') });
            });
        }
        overlay.querySelector('#cfg-save').addEventListener('click', () => {
            const formVals = readFormValues(overlay);
            if (picker) formVals.entity = (picker.value || '').trim();
            let data;
            try { data = formValuesToServiceData(energySensor, formVals); } catch (err) { showError(this._t(err.message)); return; }
            this._call(DOMAIN, 'set_device_control_mapping', data)
                .then(() => close()).catch((err) => showError(err.message));
        });
    }

    // ── Surplus and peak ──
    /** The peak sensors publish kW; the formatters take W. A sensor that says W stays W. */
    _kwSensorW(id) {
        const v = this._num(id);
        if (v === null) return null;
        return (this._unitOf(id) || '').toLowerCase() === 'w' ? v : v * 1000;
    }

    /** Measured watts of the running devices, capped at the house; see surplusInUse. */
    _inUse(rows, surplusW = null) {
        return surplusInUse(rows, (r) => this._live(r).powerW, this._powerW('sensor.sem_home_consumption_power'), surplusW);
    }

    _surplus(rows) {
        const t = (k) => this._t(k);
        const peakE = this._hass.states['sensor.sem_target_peak_limit'];
        const total = this._num('sensor.sem_surplus_total_w');
        const given = this._num('sensor.sem_surplus_allocated_w'), free = this._num('sensor.sem_surplus_unallocated_w');
        const active = this._num('sensor.sem_surplus_active_devices'), totalN = this._num('sensor.sem_surplus_total_devices');
        const peakW = this._kwSensorW('sensor.sem_consecutive_peak_15min');
        const limitW = this._kwSensorW('sensor.sem_target_peak_limit');
        const limit = limitW === null ? null : limitW / 1000;
        const uncapped = isUncapped(peakE);
        const marginW = this._kwSensorW('sensor.sem_peak_margin');
        const tiles = [];
        if (total !== null) {
            // (#1321) "in use" counts measured power only: a switch's configured size is an estimate, shown apart
            // …never more than the house draws; a sensor that reads more than the house is named
            const use = this._inUse(rows, total);
            const nums = { given: this._fmtKw(use.measuredW), est: this._fmtKw(use.estW), free: this._fmtKw(use.leftW ?? 0) };
            const base = given === null && free === null ? ''
                : this._tf(use.leftW === null ? (use.estW > 0 ? 'next_given_est' : 'next_given_only') : use.estW > 0 ? 'next_given_free_est' : 'next_given_free', nums);
            const who = use.names.length && use.names.length <= 2 ? this._tf('next_in_use_by', { names: use.names.join(', ') }) : '';
            const bad = use.over.length ? this._tf('next_sensor_over_house', { names: use.over.join(', ') }) : '';
            const sub = [base, who, bad].filter(Boolean).join(' · ');
            tiles.push({ label: t('next_surplus'), value: this._fmtKw(total), unit: 'kW', sub });
        }
        if (active !== null || totalN !== null) {
            tiles.push({ label: t('next_active'), value: active === null ? '—' : Math.round(active), unit: totalN === null ? '' : this._tf('next_of_n', { n: Math.round(totalN) }),
                sub: t('next_active_sub') });
        }
        if (peakE) {
            tiles.push({ label: t('next_peak'), value: this._fmtKw(peakW), unit: uncapped ? t('uncapped') : this._tf('next_of_kw', { kw: this._fmtKw(limitW) }),
                // (#1321) a phone tile is a third of the width: the margin alone, not three lines
                sub: uncapped || marginW === null ? t('next_15min') : this._tf(this._narrow() ? 'next_margin_short' : 'next_15min_margin', { kw: this._fmtKw(marginW) }) });
        }
        if (!tiles.length) return nothing;
        const pctSensor = this._num('sensor.sem_current_vs_peak_percentage');
        const pct = uncapped ? 0 : (pctSensor !== null ? pctSensor : (limitW && peakW !== null ? (peakW / limitW) * 100 : 0));
        const dis = false;   // (#1321) the peak limit is SEM's own setting: editable while watching
        const peakRows = [];
        const sent = [];
        if (peakE) {
            // (#1354) the peak limit is ONE question, the same model as the classic card
            const q = peakQuestion({ unlimited: uncapped, limitKw: limit });
            const send = (limited, kw) => {
                const w = peakWrites(limited, kw);
                this._svc('update_target_peak', { target_peak_limit: w.target_peak_limit ?? q.kw, peak_limit_unlimited: w.peak_limit_unlimited });
            };
            // a limit that is not read shows no number (no fallback in its place)
            // (#1321) a switch (limit on or off) and, when on, its level as the next row
            peakRows.push(this._setRow({ label: this._lbl('next_peak_limit'), help: t(q.limited ? PEAK_TEXT.sub : PEAK_TEXT.subNone),
                disabled: dis || limit === null, toggle: { on: q.limited, onChange: (on) => send(!!on, q.kw) } }));
            if (q.limited) {
                peakRows.push(this._setRow({ label: this._lbl('next_row_peak_level'), value: limit === null ? '—' : this._kw(q.kw * 1000), disabled: dis,
                    onTap: () => this._editDialog({ title: this._lbl('next_row_peak_level'), kind: 'number', value: q.kw,
                        min: PEAK_KW.min, max: PEAK_KW.max, step: PEAK_KW.slider, unit: 'kW', onCommit: (v) => send(true, v) }) }));
            }
            const slot = uncapped ? null : slotStatus({ targetKw: limit, usedKwh: peakE.attributes?.peak_slot_used_kwh, allowedW: peakE.attributes?.peak_slot_allowed_w });
            if (slot) sent.push(this._tf('next_sent_slot', { used: this._fmt(slot.usedKwh, 2), budget: this._fmt(slot.budgetKwh, 2) }));
        }
        const month = this._kwSensorW('sensor.sem_monthly_consecutive_peak');
        if (month !== null) sent.push(this._tf('next_sent_month_peak', { kw: this._kw(month) }));
        const shed = this._kwSensorW('sensor.sem_available_load_reduction');
        // (#1371) only what SEM could really shed: nothing is said when that
        // is nothing (load management off), and a device in mode Off is not counted
        if (shed !== null && shed > 0) sent.push(this._tf('next_sent_can_shed', { kw: this._kw(shed), n: rows.filter((r) => r.type === 'load' && r.hasControlHandle && r.isControllable && r.mergedMode !== 'off').length }));
        // (#1321) "warning" is the engine's low warning level: say it only when the peak is near the limit
        const calm = this._str('sensor.sem_load_management_status') === 'warning' && !uncapped && pct !== null && pct < 80;
        const status = calm ? '' : this._valLabel('load_management_status');
        const recRaw = calm ? '' : this._str('sensor.sem_load_management_recommendation');
        const rec = recRaw ? (this._t(recRaw === 'Monitor - approaching peak limit' ? 'next_peak_close' : recRaw) || recRaw) : '';
        const lm = this._attrs('sensor.sem_load_management_status');
        const op = lm.shed_signal_active === true ? this._tf('operator_limit_banner', {
            kw: typeof lm.shed_signal_cap_kw === 'number' ? this._fmt(lm.shed_signal_cap_kw, 1) : '—',
            time: lm.shed_signal_since ? this._hhmm(lm.shed_signal_since) : '—' }) : '';
        return this._sec(t('next_surplus_peak'), html`
            ${op ? html`<div class="banner">${this._icon('mdi:transmission-tower-export')}<div class="sm">${op}</div></div>` : nothing}
            ${this._tiles(tiles, { three: true, stack: this._narrow() })}
            ${peakE && !uncapped ? html`<div style="margin:10px 0 6px">${this._track(pct, C.grid)}</div>` : nothing}
            ${peakRows.length ? html`<div class="rows">${peakRows}</div>` : nothing}
            ${sent.length ? html`<p class="sent">${sent.map((s, i) => html`${i ? ' ' : ''}${s}`)}</p>` : nothing}
            ${status || rec ? html`<p class="help">${sameWords(status, rec) ? rec : html`${status}${status && rec ? ' · ' : ''}${rec}`}</p>` : nothing}`, { cls: 'span2' });
    }

    // ── one device card ──
    _shell(row, i) {
        const t = (k) => this._t(k);
        const live = this._live(row);
        const pill = statePill(row, live);
        const color = row.type === 'charger' ? C.ev : row.type === 'battery' ? C.battery_out : C.home;
        const w = live.powerW;
        const liveText = row.type === 'battery' && w !== null
            ? (w < 0 ? '−' : '') + this._kw(Math.abs(w))
            : (w !== null && (row.type !== 'load' || w > 10 || row.isOn) ? this._kw(w)
                : (row.rating > 0 ? html`<span class="dim">${this._tf(ratedKey(row, w), { kw: this._kw(row.rating) })}</span>` : (w === null ? '' : this._kw(w))));
        const dis = this._obs();
        const open = !this._reorder && this._isOpen(row);
        const body = !open ? nothing
            : row.type === 'charger' ? chargerBody(this, row) : row.type === 'battery' ? batteryBody(this, row) : loadBody(this, row);
        const locked = (row.dependsOn || []).length > 0;
        // (#1321) watch-only: the same "would ..." line System shows, one helper
        const dec = this._obs() ? wouldFor(row, wouldList(this._attrs('switch.sem_observer_mode'))) : null;
        const would = dec ? wouldLine(dec, (k) => this._t(k)) : '';
        const toggle = () => { if (!this._reorder) this._toggleOpen(row); };
        return html`<ha-card class="card dev ${open ? '' : 'folded'}" data-id=${row.id} style="--c:${color}">
            <div class="head">
                <span class="handle" title=${locked ? t('locked_under_parent') : t('drag_to_reorder')}
                    @pointerdown=${locked ? nothing : (e) => this._dragStart(e, row.id)}>${this._icon(locked ? 'mdi:subdirectory-arrow-right' : 'mdi:drag-vertical')}</span>
                <span class="rank" title=${t('next_priority')}>${i + 1}</span>
                <div class="name tap" role="button" tabindex="0" aria-expanded=${open ? 'true' : 'false'} @click=${toggle}
                    @keydown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } }}>${this._icon(row.icon)}<span title=${row.name}>${row.name}</span>${this._pill(this._pillText(pill), pill.cls)}</div>
                <span class="live muted sm">${liveText}</span>
                ${row.type === 'load' && !row.lockedByOperator ? this._pill(t(verdictKey(row)), '', { icon: 'mdi:hand-back-left-outline' }) : nothing}
                <div class="arrows">
                    <button type="button" data-mv="-1" aria-label=${t('move_up')} ?disabled=${locked} @click=${() => this._move(row.id, -1)}>${this._icon('mdi:arrow-up')}</button>
                    <button type="button" data-mv="1" aria-label=${t('move_down')} ?disabled=${locked} @click=${() => this._move(row.id, 1)}>${this._icon('mdi:arrow-down')}</button>
                </div>
                ${row.type === 'load' ? html`<button type="button" class="gear" aria-label=${t('configure')} @click=${() => this._showConfigureModal(row.id, row.name)}>${this._icon('mdi:cog-outline')}</button>` : nothing}
                <button type="button" class="fold" aria-expanded=${open ? 'true' : 'false'} aria-label=${t(open ? 'next_fold_device' : 'next_open_device')}
                    @click=${toggle}>${this._icon('mdi:chevron-down')}</button>
            </div>
            ${would ? html`<div class="would xs dim">${would}</div>` : nothing}
            ${open ? html`<div class="body">${body}</div>` : nothing}</ha-card>`;
    }

    render() {
        if (!this._hass) return nothing;
        const t = (k) => this._t(k);
        const rows = this._rowsNow();
        const n = rows.length;
        const main = n === 0 ? t('next_dev_none')
            : n === 1 ? this._tf('next_dev_lead_one', { first: rows[0].name })
            : this._tf('next_dev_lead2', { n, first: rows[0].name, last: rows[n - 1].name });
        const sub = n ? t('next_dev_lead2_sub') : t('next_no_loads');
        const dis = this._obs();
        const toolbar = html`<div class="period">
            ${this._btn(this._reorder ? t('next_done_btn') : t('next_reorder'), () => this._toggleReorder(),
                { primary: this._reorder, icon: this._reorder ? 'mdi:check' : 'mdi:swap-vertical', disabled: n < 2 })}
            <button type="button" class="pill" aria-expanded=${this._adding ? 'true' : 'false'} @click=${() => this._toggleAdd()}>${this._icon(this._adding ? 'mdi:close' : 'mdi:plus', 's')}${t(this._adding ? 'next_cancel' : 'next_add_device')}</button>
            ${!this._reorder && !this._all && n > 1 ? (() => {
                const allOpen = rows.every((r) => this._isOpen(r));
                return html`<button type="button" class="pill" @click=${() => this._setAllOpen(rows, !allOpen)}>${this._icon(allOpen ? 'mdi:unfold-less-horizontal' : 'mdi:unfold-more-horizontal', 's')}${t(allOpen ? 'next_fold_all' : 'next_open_all')}</button>`;
            })() : nothing}
            ${this._reorder ? html`<span class="dim sm">${t('next_reorder_hint')}</span>` : nothing}
            ${dis ? html`<span class="dim sm">${t('next_observing_hint')}</span>` : nothing}
        </div>`;
        return this._frame({ main, sub }, html`
            ${toolbar}
            <div class="grid ${this._reorder ? 'reorder' : ''}">
                ${this._adding && !this._reorder ? this._addSheet(rows) : nothing}
                ${this._surplus(rows)}
                ${repeat(rows, (r) => r.id, (r, i) => this._shell(r, i))}
            </div>`);
    }

    getCardSize() { return 8 + this._chargers.length * 4; }
}

semDefineCard('sem-next-devices-card', SEMNextDevicesCard, {
    type: 'sem-next-devices-card',
    name: 'SEM · Devices',
    description: 'Every charger, battery and load in one card shape: status, mode, targets, today, next, one change',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-devices-card',
    preview: true,
});
