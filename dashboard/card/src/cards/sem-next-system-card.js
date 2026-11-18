/**
 * SEM Next · System (#1321)
 *
 * Health first: how fresh every source is, the setup check, the hardware,
 * what is unavailable, the version, with Copy diagnostics, Diagnose and
 * the observer switch (behind a confirm step: the test rigs share real
 * hardware). Then what SEM held back. Then the settings as seven groups: a
 * short summary sentence, then Home Assistant settings rows (label, value;
 * tap a row, a dialog opens with the right control; a boolean is a switch on
 * the row). Changes wait in a pending map and go
 * out together from the sticky Apply bar: entities directly, options in
 * one set_option call. Entity fields use HA's own entity picker, filtered
 * like the classic setup card's picker for the same option. Chargers are
 * added and removed here; the setup check and the detected-hardware report
 * open in place (`_setupPanel`), never on the classic dashboard.
 *
 * Config:
 *   type: custom:sem-next-system-card
 */

import { OPEN_PANEL_KEY, takeStored, readChecklist } from '../util/setup-checklist.js';
import { SEMNextBase, html, css, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import './sem-next-setup-panel.js';
import { sourceRows, ageLabel, freshness, SOURCE_ROWS, sourceEntityOf } from '../util/next-freshness.js';
import { recordReason, deviceName, actionWords } from '../util/why-rows.js';
import { gridReading } from '../util/next-format.js';
import { entityName } from '../util/next-names.js';
import { MISSING } from '../util/missing-value.js';
import { groups, applyPlan, pendingKey, navTarget, slotText, sentenceText, rowText, setupItems, loadSources, unavailableCount,
         reserveIds, pvStrings, chargerSkeleton, FILTER_CLASSES } from '../util/next-settings.js';
import { isPowerEntity, isCo2IntensityEntity, isOutdoorTemperatureCandidate } from '../util/detect-rows.js';

const HA_SETTINGS = '/config/integrations/integration/solar_energy_management';
const ENTITY_FILTERS = { power: isPowerEntity, co2_intensity: isCo2IntensityEntity, outdoor_temperature: isOutdoorTemperatureCandidate };

const DIAG_IDS = ['sensor.sem_diag_version', 'sensor.sem_diag_grid_mode', 'sensor.sem_diag_grid_sign',
                  'sensor.sem_diag_battery_sign', 'sensor.sem_diag_charger_count', 'sensor.sem_diag_charger_control',
                  'sensor.sem_diag_battery_capacity', 'sensor.sem_diag_update_interval', 'sensor.sem_diag_sensors_unavailable',
                  'sensor.sem_diag_inputs_degraded', 'sensor.sem_diag_ed_config', 'sensor.sem_energy_plan',
                  'sensor.sem_charging_state', 'sensor.sem_controllable_devices_count', 'sensor.sem_tariff_provider',
                  'binary_sensor.sem_heat_pump_registered'];

// Every entity a sentence can bind to (the per-charger, per-battery and
// per-load ids are added in _watchIds).
const SETTING_IDS = ['number.sem_electricity_import_rate', 'number.sem_electricity_export_rate', 'number.sem_demand_charge_rate',
                     'number.sem_cheap_price_threshold', 'number.sem_expensive_price_threshold',
                     'switch.sem_export_guard_enabled', 'number.sem_export_guard_engage_s', 'number.sem_export_guard_release_s',
                     'switch.sem_export_guard_override_external',
                     'number.sem_battery_priority_soc', 'number.sem_battery_buffer_soc', 'number.sem_battery_auto_start_soc',
                     'switch.sem_forecast_spending_enabled', 'switch.sem_battery_charge_pacing_enabled',
                     'switch.sem_battery_may_export', 'switch.sem_battery_may_assist_ev',
                     'number.sem_battery_max_discharge_power', 'number.sem_battery_morning_drain_floor_soc',
                     'switch.sem_battery_house_sink_enabled', 'number.sem_battery_assist_max_power',
                     'number.sem_battery_assist_min_surplus', 'number.sem_ev_enable_delay_seconds',
                     'number.sem_ev_disable_delay_seconds', 'number.sem_heat_pump_boost_offset',
                     'number.sem_hot_water_solar_target', 'number.sem_legionella_target_temp',
                     'number.sem_legionella_interval_hours', 'number.sem_system_size_kwp', 'select.sem_hints',
                     'number.sem_update_interval', 'switch.sem_ev_morning_window_enabled',
                     'number.sem_ev_morning_window_hours', 'number.sem_night_start_offset_min',
                     'number.sem_night_latest_end', 'switch.sem_vacation_mode', 'switch.sem_simulation_tab',
                     'number.sem_minimum_solar_power', 'number.sem_regulation_offset'];

const CHARGER_SUFFIXES = ['ev_phases', 'minimum_current', 'maximum_current', 'ev_battery_capacity_kwh', 'ev_kwh_per_100km'];

const FRESH_LOOK = {
    next_src_solar: { icon: 'mdi:white-balance-sunny', color: C.solar },
    next_src_grid: { icon: 'mdi:transmission-tower', color: C.grid },
    next_src_battery: { icon: 'mdi:battery-charging', color: C.battery_out },
    next_src_car: { icon: 'mdi:car-electric', color: C.ev },
    next_src_forecast: { icon: 'mdi:weather-sunny', color: C.solar },
    next_src_price: { icon: 'mdi:cash', color: C.fg2 },
};

const cardCss = css`
    .val.dirty { color: var(--n-accent); text-decoration-color: var(--n-accent); text-decoration-style: solid; }
    .sent .edit { display: inline-flex; align-items: center; gap: 4px; vertical-align: baseline; }
    .sent input, .sent select, .help input, .help select { font-size: var(--ha-font-size-s, 13px); padding: 2px 6px; max-width: 130px; min-height: 28px; }
    .sent .ro { font-weight: 500; color: var(--n-fg); }
    .fresh .tile .xs.warn { color: var(--n-warn); }
    .fresh .tile .xs.bad { color: var(--n-bad); }
    .fresh .tile .dim { overflow-wrap: anywhere; }
    .confirm { display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 13px; }
    .ct .lnk.ic { padding: 2px 4px; }
    .ct .lnk.ic ha-icon { color: var(--n-fg3); }
    .sent .edit.pick, .help .edit.pick { display: inline-flex; min-width: min(320px, 100%); max-width: 100%; vertical-align: middle; }
    .edit.pick ha-entity-picker { flex: 1; min-width: 0; }
    .chlist { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 6px; }
`;

class SEMNextSystemCard extends SEMNextBase {
    static get styles() { return [nextCss, cardCss]; }

    static get properties() {
        return {
            ...super.properties,
            _pending: { state: true },
            _options: { state: true },
            _applying: { state: true },
            _confirmObs: { state: true },
            _diagBusy: { state: true },
            _panel: { state: true },
            _showSources: { state: true },
            _chargerBusy: { state: true },
            _confirmRemove: { state: true },
        };
    }

    constructor() {
        super();
        this._pending = {};
        this._options = null;
        this._entryId = '';
        this._applying = false;
        this._confirmObs = false;
        this._diagBusy = false;
        this._optionsAsked = false;
        // (#1379) the Home checklist can open the setup check directly
        this._panel = takeStored(OPEN_PANEL_KEY);
        this._chargerBusy = false;
        this._confirmRemove = '';
    }

    // (#1379) a Home checklist tap while this screen is already built
    connectedCallback() {
        super.connectedCallback();
        this._onRoute = () => setTimeout(() => { const p = takeStored(OPEN_PANEL_KEY); if (p) this._panel = p; }, 0);
        window.addEventListener('location-changed', this._onRoute);
    }
    disconnectedCallback() {
        window.removeEventListener('location-changed', this._onRoute);
        super.disconnectedCallback();
    }

    set hass(hass) {
        super.hass = hass;
        if (hass && !this._optionsAsked) {
            this._optionsAsked = true;
            this._loadOptions();
        }
    }
    get hass() { return this._hass; }


    _watchIds() {
        const states = this._hass?.states || {};
        const per = [];
        for (const cid of this._chargers) for (const s of CHARGER_SUFFIXES) per.push(`number.sem_charger_${cid}_${s}`);
        return [...super._watchIds(), ...DIAG_IDS, ...SETTING_IDS, ...per, ...reserveIds(states),
                ...SOURCE_ROWS.map((r) => r.entity), ...loadSources(states).map((l) => l.entity)];
    }

    // ── options (the integration's own dict, for the slots no entity carries) ──

    async _loadOptions() {
        if (!this._hass) return;
        try {
            const resp = await this._call('solar_energy_management', 'get_config', {},
                undefined, undefined, true);
            const cfg = resp?.response?.config;
            if (cfg && typeof cfg === 'object') this._options = cfg;
            if (resp?.response?.entry_id) this._entryId = resp.response.entry_id;
        } catch (err) {
            console.warn('[sem-next-system-card] get_config failed', err);
        }
    }

    _say(text, ms = 2500, bad = false) { this._toast(text, bad, ms); }

    // ── health ──

    _inputsDegraded() {
        const s = String(this._str('sensor.sem_diag_inputs_degraded') || '').toLowerCase();
        return s === 'true' || s === 'on';
    }

    /** [{key, name, entity, state, age, icon, color}] for the tiles and the lead. */
    _freshRows() {
        const states = this._hass.states;
        const now = Date.now();
        const ed = states['sensor.sem_diag_ed_config']?.attributes?.energy_dashboard;
        const rows = sourceRows(states, now).map((r) => ({ ...r, name: this._t(r.key), src: sourceEntityOf(r.key, ed), ...FRESH_LOOK[r.key] }));
        for (const l of loadSources(states, this._hass)) {
            const e = states[l.entity];
            rows.push({ key: l.id, name: l.name, entity: l.entity, src: l.entity, state: freshness(e, now), age: null,
                        icon: 'mdi:power-plug', color: C.home, load: true });
        }
        return rows;
    }

    /** The value and status words of one source, as the old tile said them. */
    _freshLine(r) {
        const txt = r.state === 'ok' || r.state === 'old' ? (ageLabel(r.age) || this._t('next_fresh_ok'))
            : r.state === 'missing' ? this._t(r.load ? 'next_no_power_reading' : 'next_no_reading') : this._t('next_fresh_' + r.state);
        const st = this._hass.states[r.entity];
        const g = r.key === 'next_src_grid' ? gridReading(st?.state) : null;
        // the grid reads as Now says it: a size and import or export, not a signed number
        const val = g ? `${this._fmt(g.watts, 0)} W${g.dir ? ' ' + this._t(g.dir === 'import' ? 'next_import' : 'next_export').toLowerCase() : ''}`
            : !st ? '' : (typeof this._hass.formatEntityState === 'function' ? this._hass.formatEntityState(st)
            : `${st.state}${st.attributes?.unit_of_measurement ? ' ' + st.attributes.unit_of_measurement : ''}`);
        return { value: val ? `${val} · ${txt}` : txt, cls: r.state === 'old' || r.state === 'missing' ? 'warn' : 'bad' };
    }

    _sourceRow(r) {
        const { value, cls } = this._freshLine(r);
        const srcName = r.src ? entityName(this._hass, r.src) : '';
        const sub = srcName && srcName.toLowerCase() !== String(r.name).toLowerCase() ? srcName : '';
        const open = () => this._moreInfo(r.src && this._hass.states[r.src] ? r.src : r.entity);
        return this._row(r.icon, r.name, html`<span class="${r.state === 'ok' ? '' : cls}">${value}</span>`, sub, { color: r.color, onClick: open, cls: 'ell' });
    }

    /**
     * (#1321) One row says how the sources are doing (tap for the list); only a
     * source with a problem gets a row of its own. HA's own pattern for a healthy list.
     */
    _freshSummary(rows) {
        const bad = rows.filter((r) => r.state !== 'ok');
        const okN = rows.length - bad.length;
        const label = bad.length ? this._tf('next_n_sources_ok', { n: okN }) : this._tf('next_all_sources_ok', { n: rows.length });
        const open = !!this._showSources;
        return html`<div class="rows">
            ${bad.map((r) => this._sourceRow(r))}
            ${okN || !bad.length ? this._row(bad.length ? 'mdi:check-circle-outline' : 'mdi:check-circle', label,
                html`<ha-icon icon="${open ? 'mdi:chevron-up' : 'mdi:chevron-down'}"></ha-icon>`, '',
                { color: C.good, onClick: () => { this._showSources = !open; } }) : nothing}
            ${open ? rows.filter((r) => r.state === 'ok').map((r) => this._sourceRow(r)) : nothing}</div>`;
    }

    _setupRow() {
        const items = setupItems(this._hass.states, this._options);
        const counted = items.filter((i) => !i.optional);
        const done = counted.filter((i) => i.done).length;
        const value = done === counted.length ? this._t('config_setup_done')
            : this._tf('config_setup_progress', { done, total: counted.length });
        const grid = this._valLabel('diag_grid_sign');
        const batt = this._valLabel('diag_battery_sign');
        // (#1321) the Now screen's checklist counts the same things to check: the required steps are the value, the checks ride beside it
        const checks = readChecklist(this._hass.states)?.repairs?.count || 0;
        const checkText = checks === 1 ? this._t('setup_check_one') : (checks ? this._tf('setup_check_n', { n: checks }) : '');
        const sub = [grid ? `${this._t('next_grid_sign')} ${grid}` : '', batt ? `${this._t('next_battery_sign')} ${batt}` : '', checkText].filter(Boolean).join(' · ');
        return this._row('mdi:check-decagram', this._t('next_setup_check'), value, sub, { onClick: () => this._togglePanel('setup') });
    }

    _hardwareRow() {
        const count = this._str('sensor.sem_diag_charger_count');
        const control = this._valLabel('diag_charger_control');
        const cap = this._num('sensor.sem_diag_battery_capacity');
        const report = this._attrs('sensor.sem_diag_charger_control').detection_report || null;
        const unmapped = report ? (report.near_misses || []).length : null;
        const strings = pvStrings(this._hass.states).length;
        const value = [count !== '' ? this._tf('next_chargers_n', { n: count }) : '', control].filter(Boolean).join(' · ') || MISSING;
        const sub = [
            strings ? this._tf('next_strings', { n: strings }) : '',
            cap !== null && cap > 0 ? this._tf('next_batt_cap', { kwh: this._fmt(cap, 1) }) : '',
            // only what needs a look: unmapped devices; the grid wiring is in the settings
            unmapped ? this._tf('next_unmapped', { n: unmapped }) : '',
        ].filter(Boolean).join(' · ');
        return this._row('mdi:radar', this._t('next_hardware'), value, sub, { onClick: () => this._togglePanel('hardware') });
    }

    _togglePanel(kind) { this._panel = this._panel === kind ? '' : kind; }

    /** Mount point for the setup check ('setup') and the detected-hardware review ('hardware'). */
    _setupPanel(kind) {
        return html`<sem-next-setup-panel .hass=${this._hass} .kind=${kind === 'setup' ? 'check' : kind}
            @sem-next-close=${() => { this._panel = ''; }}></sem-next-setup-panel>`;
    }

    _unavailableRow() {
        const { n, m } = unavailableCount(this._hass.states);
        const value = n === null ? MISSING : this._tf('next_n_of_m', { n, m });
        const sub = this._inputsDegraded() ? this._t('next_inputs_degraded') : '';
        return this._row('mdi:lan-disconnect', this._t('next_unavailable'), value, sub,
                         { onClick: () => this._moreInfo('sensor.sem_diag_sensors_unavailable') });
    }

    _versionRow() {
        const ver = this._str('sensor.sem_diag_version');
        const ha = this._hass.config?.version || '';
        const every = this._num('number.sem_update_interval') ?? this._num('sensor.sem_diag_update_interval');
        const sub = [ha ? `HA ${ha}` : '', every !== null ? this._tf('next_every_s', { s: Math.round(every) }) : ''].filter(Boolean).join(' · ');
        return this._row('mdi:new-box', this._t('version'), ver || MISSING, sub, { onClick: () => this._moreInfo('sensor.sem_diag_version') });
    }

    /** (#1321) Observer mode changes what SEM does, so it is a switch row, not a tool button. */
    updated(changed) {
        super.updated(changed);
        // (#1321) the confirm opens under the switch: the keyboard goes to its first button
        if (this._confirmObs && !this._confirmFocused) {
            this._confirmFocused = true;
            const b = this.renderRoot?.querySelector?.('.confirm ha-button, .confirm button');
            if (b && typeof b.focus === 'function') b.focus();
        } else if (!this._confirmObs) this._confirmFocused = false;
    }

    _observerRow() {
        const obs = this._obs();
        const confirm = this._confirmObs
            ? html`<div class="confirm">${this._alert('warning', '', this._t(obs ? 'next_obs_confirm_off' : 'next_obs_confirm_on'), html`
                ${this._btn(this._t('next_yes'), () => { this._confirmObs = false; this._toggleSwitch('switch.sem_observer_mode'); }, { small: true, primary: true })}
                ${this._btn(this._t('next_cancel'), () => { this._confirmObs = false; }, { small: true, ghost: true })}`)}</div>` : nothing;
        return html`${this._row('mdi:eye-outline', this._t('next_observer'),
            this._switch(obs, () => { this._confirmObs = true; }, { label: this._t('next_observer') }), this._t('next_observer_sub'))}${confirm}`;
    }

    _health(rows) {
        return this._sec(this._t('next_health'), html`
            ${this._freshSummary(rows)}
            <div class="rows" style="margin-top:8px">${this._setupRow()}${this._panel === 'setup' ? this._setupPanel('setup') : nothing}${this._hardwareRow()}${this._panel === 'hardware' ? this._setupPanel('hardware') : nothing}${this._unavailableRow()}${this._versionRow()}${this._observerRow()}</div>
            <div class="btns" style="margin-top:10px">
                ${this._btn(this._t('copy_diagnostics'), () => this._copyDiagnostics(), { small: true, ghost: true, icon: 'mdi:content-copy' })}
                ${this._btn(this._t('config_diagnose'), () => this._diagnose('all'), { small: true, ghost: true, icon: 'mdi:stethoscope', disabled: this._diagBusy })}
                ${this._btn(this._t('config_open_ha_settings'), () => this._go(HA_SETTINGS), { small: true, ghost: true, icon: 'mdi:cog-outline' })}
            </div>
`, { cls: 'span2' });
    }

    /** A charger by the name the user knows; the rest by their own name, else their kind (a second one numbered). */
    _refusedName(r, t, rows) {
        const cid = r.kind === 'charger' ? String(r.device_id || '').replace(/^ev:/, '') : '';
        if (cid && this._chargers.includes(cid)) return this._chargerName(cid);
        const kind = r.device_kind || r.kind;
        // (#1321) a load is named as the Devices screen names it
        const info = kind === 'load' ? (this._attrs('sensor.sem_controllable_devices_count').devices || {})[String(r.device_id || '')] : null;
        if (info) return this._loadName(String(r.device_id), info);
        return deviceName(r, t, rows.filter((x) => (x.device_kind || x.kind) === kind).length > 1);
    }

    _refused() {
        const attrs = this._attrs('switch.sem_observer_mode');
        const obs = this._obs();
        // withheld_commands is { device_id: [ {service, data, …}, … ] } — one row per call.
        const withheld = Object.entries(attrs.withheld_commands || {}).flatMap(([dev, cmds]) =>
            (Array.isArray(cmds) ? cmds : [cmds]).filter((c) => c && typeof c === 'object').map((c) => ({
                ...c, name: c.name || dev, device_id: c.device_id || dev,
                action: c.action || c.service || '',
            })));
        const would = Object.values(attrs.would_decisions || {}).filter((d) => d && d.action && d.action !== 'idle');
        const rows = obs ? would : withheld;
        const t = (k) => this._t(k);
        const body = rows.length
            ? html`<div class="rows">${rows.slice(0, 8).map((r) => this._row('mdi:hand-back-left-outline',
                `${this._refusedName(r, t, rows)}${r.action ? ' · ' + actionWords(r.action, t) : ''}`,
                Number.isFinite(Number(r.power_w)) ? this._kw(Number(r.power_w)) : '',
                recordReason(r, this._hass.states, t)))}</div>`
            : html`<div class="hint">${obs ? this._t('next_would_none') : this._t('next_refused_none')}</div>`;
        return this._sec(obs ? this._t('next_would_do') : this._t('next_held_back'), body);
    }

    // ── settings as sentences ──

    _ctx() {
        const services = this._hass.services || {};
        const notifyServices = [];
        for (const n of Object.keys(services.notify || {})) notifyServices.push({ value: n, label: 'notify.' + n });
        for (const n of Object.keys(services.rest_command || {})) notifyServices.push({ value: n, label: 'rest_command.' + n });
        return {
            options: this._options,
            currency: this._currency(),
            chargers: this._chargerList(),
            labels: {
                control: this._valLabel('diag_charger_control'),
                // (#1321) "from Custom" says nothing: a custom source names no provider
                provider: /^custom$/i.test(this._str('sensor.sem_tariff_provider')) ? '' : (this._valLabel('tariff_provider') || this._str('sensor.sem_tariff_provider')),
                gridSign: this._valLabel('diag_grid_sign'),
                battSign: this._valLabel('diag_battery_sign'),
            },
            notifyServices,
        };
    }

    /** Chargers from the options (a new one has no entities yet) and from SEM's entities. */
    _chargerList() {
        const out = [];
        const seen = new Set();
        for (const c of (this._options?.ev_chargers || [])) {
            if (!c || !c.id || seen.has(c.id)) continue;
            seen.add(c.id);
            out.push({ cid: c.id, name: this._chargers.includes(c.id) ? this._chargerName(c.id) : (c.name || c.id) });
        }
        for (const cid of this._chargers) {
            if (seen.has(cid)) continue;
            seen.add(cid);
            out.push({ cid, name: this._chargerName(cid) });
        }
        return out;
    }

    /** (#1321) A setting row: label left, value right; a tap opens the right control, a boolean is a switch. */
    _slotRow(r) {
        const slot = r.slot;
        const t = (k) => this._t(k);
        const dis = false;   // (#1321) SEM's own settings stay editable while it only watches
        if (slot.kind === 'action') {
            const go = slot.nav ? () => this._go(navTarget(window.location.pathname, slot.action)) : () => this._askAction(slot, r.label);
            // (#1321) a sign row shows its direction now; a tap only opens the question
            return this._setRow({ label: r.label, value: slot.nav ? '' : this._actionValue(slot, t), more: r.more, onTap: go, disabled: dis && !slot.nav });
        }
        // (#1321) no help line under any row: it sits in the row's dialog
        if (slot.ro || slot.kind === 'text' && !pendingKey(slot)) {
            return this._setRow({ label: r.label, value: slot.value, more: r.more, ro: true });
        }
        const key = pendingKey(slot);
        const pend = this._pending[key];
        const value = pend ? pend.value : slot.value;
        const base = { label: r.label, more: r.more, dirty: !!pend, disabled: dis };
        if (slot.kind === 'switch') {
            return this._setRow({ ...base, toggle: { on: !!value, onChange: (v) => this._stage(slot, v) } });
        }
        // the peak limit is a switch (limit or none); its level is the next row
        if (slot.peak) {
            return this._setRow({ ...base, toggle: { on: value === 'limit', onChange: (on) => this._stage(slot, on ? 'limit' : 'none') } });
        }
        return this._setRow({ ...base, value: slotText(slot, t, value, this._hass), onTap: () => this._openEdit(slot, r.label, value, r.help) });
    }

    /** The edit dialog for a slot: its kind picks the control, the commit stages the change. */
    _editSpec(slot, label, value) {
        const t = (k) => this._t(k);
        const stage = (v) => this._stage(slot, v);
        const base = { title: label, value, onCommit: stage };
        if (slot.kind === 'entity') {
            const dc = slot.deviceClass;
            return { ...base, kind: 'entity', allowClear: true, domains: slot.domains || undefined,
                deviceClasses: dc && !FILTER_CLASSES.has(dc) ? [dc] : undefined, filter: dc ? ENTITY_FILTERS[dc] : undefined };
        }
        if (slot.kind === 'select') {
            const options = (slot.options || []).map((o) => ({ value: o.value, label: o.labelKey ? t(o.labelKey) : String(o.label ?? o.value) }));
            return { ...base, kind: 'select', options };
        }
        if (slot.kind === 'number') {
            return { ...base, kind: 'number', min: slot.min, max: slot.max, step: slot.step || 1, unit: slot.unit };
        }
        return { ...base, kind: 'text', placeholder: slot.placeholder };
    }

    _openEdit(slot, label, value, help = '') {
        this._editDialog({ ...this._editSpec(slot, label, value), ...(help ? { help } : {}) });
    }

    _stage(slot, raw) {
        const key = pendingKey(slot);
        if (!key) return;
        let v = raw;
        if (slot.kind === 'number') { v = Number(raw); if (raw === '' || !Number.isFinite(v)) return; }
        if (slot.kind === 'switch') v = !!raw;
        const same = slot.kind === 'number' ? Number(slot.value) === v : String(slot.value) === String(v);
        const p = { ...this._pending };
        if (same) delete p[key]; else p[key] = { slot, value: v };
        this._pending = p;
    }

    _group(g) {
        const n = g.count || 0;
        const extra = html`<button type="button" class="lnk ic" aria-label="${this._t('config_diagnose')}" title="${this._t('config_diagnose')}"
            ?disabled=${this._diagBusy} @click=${() => this._diagnose(g.diagnoseSection)}>${this._icon('mdi:stethoscope', 's')}</button>`;
        const t = (k) => this._t(k);
        const summary = sentenceText(g.sentence, t, this._hass, (s) => {
            const p = this._pending[pendingKey(s)];
            return p ? p.value : s.value;
        });
        return this._sec(this._t(g.titleKey), html`
            ${summary ? html`<p class="sent">${summary}</p>` : nothing}
            ${g.key === 'chargers' ? this._chargerTools() : nothing}
            <div class="rows">${(g.rows || []).map((r) => this._slotRow(r))}</div>
            ${n ? html`<p class="help app-not-all">${this._tf('config_more_in_all', { n })}</p>` : nothing}`,
            { cls: 'group', extra });
    }

    // ── chargers: add and remove (classic _addCharger / _removeCharger) ──

    _chargerTools() {
        const dis = this._chargerBusy || this._applying || !this._options;
        const list = this._chargerList();
        const t = (k) => this._t(k);
        const removeFor = (c) => (this._confirmRemove === c.cid
            ? html`<span class="confirm">${t('config_ev_remove_confirm')} <b>${c.name}</b>
                ${this._btn(t('next_yes'), () => this._removeCharger(c.cid), { small: true, primary: true, disabled: dis })}
                ${this._btn(t('next_cancel'), () => { this._confirmRemove = ''; }, { small: true, ghost: true })}</span>`
            : this._btn(t('config_ev_remove') + ' ' + c.name, () => { this._confirmRemove = c.cid; }, { small: true, ghost: true, icon: 'mdi:delete-outline', disabled: dis }));
        return html`<div class="chlist">
            ${this._btn(t('config_ev_add_charger'), () => this._addCharger(), { small: true, icon: 'mdi:plus', disabled: dis })}
            ${list.length ? html`<span data-more>${list.map(removeFor)}</span>` : nothing}
        </div>`;
    }

    async _setOptions(options) {
        await this._call('solar_energy_management', 'set_option',
            { options, ...(this._entryId ? { entry_id: this._entryId } : {}) }, undefined, false);
    }

    async _addCharger() {
        if (this._chargerBusy || !this._options) return;
        const charger = chargerSkeleton(this._options.ev_chargers, this._chargers, this._t('config_ev_new_charger'));
        this._chargerBusy = true;
        try {
            // One skeleton: the backend merges ev_chargers by id, so the siblings stay.
            await this._setOptions({ ev_chargers: [charger] });
            await this._loadOptions();
            this._say(this._t('config_saved'));
        } catch (err) {
            console.error('[sem-next-system-card] add charger failed', err);
            this._say(err?.message || this._t('next_apply_failed'), 8000, true);
        } finally {
            this._chargerBusy = false;
        }
    }

    async _removeCharger(cid) {
        if (this._chargerBusy || !cid) return;
        this._chargerBusy = true;
        this._confirmRemove = '';
        try {
            await this._call('solar_energy_management', 'remove_charger', { charger_id: cid }, undefined, false);
            const p = { ...this._pending };
            for (const k of Object.keys(p)) if (k.startsWith(`opt:ev_chargers:${cid}:`)) delete p[k];
            this._pending = p;
            await this._loadOptions();
            this._say(this._t('config_saved'));
        } catch (err) {
            console.error('[sem-next-system-card] remove charger failed', err);
            this._say(err?.message || this._t('next_apply_failed'), 8000, true);
        } finally {
            this._chargerBusy = false;
        }
    }

    // ── apply ──

    _applyBar() {
        const n = Object.keys(this._pending).length;
        if (!n && !this._applying) return nothing;
        const plan = applyPlan(this._pending, this._hass.states);
        const text = this._applying ? this._t('config_applying')
            : this._tf('next_changes_waiting', { n }) + (plan.reload ? ' · ' + this._t('next_reloads') : '');
        return html`<div class="apply"><span>${text}</span>
            ${this._btn(this._t('config_discard'), () => this._discard(), { ghost: true, disabled: this._applying })}
            ${this._btn(this._t('config_apply'), () => this._apply(), { primary: true, disabled: this._applying })}</div>`;
    }

    _discard() { this._pending = {}; }

    async _apply() {
        if (this._applying || !Object.keys(this._pending).length || !this._hass) return;
        this._applying = true;
        const plan = applyPlan(this._pending, this._hass.states);
        try {
            for (const w of plan.entityWrites) await this._call(w.domain, w.service, w.data, undefined, false);
            if (Object.keys(plan.options).length) {
                await this._call('solar_energy_management', 'set_option',
                    { options: plan.options, ...(this._entryId ? { entry_id: this._entryId } : {}) }, undefined, false);
            }
            for (const edit of plan.listEdits || []) await this._setOptions(edit);
            this._pending = {};
            this._say(this._t('config_saved'));
            await this._loadOptions();
        } catch (err) {
            console.error('[sem-next-system-card] apply failed', err);
            this._say(err?.message || this._t('next_apply_failed'), 8000, true);
        } finally {
            this._applying = false;
        }
    }

    // ── one-shot actions ──

    /** What the row reads: the direction a sign is read in now, else the verb. */
    _actionValue(slot, t) {
        const sensor = { flip_grid_sign: 'diag_grid_sign', flip_battery_sign: 'diag_battery_sign' }[slot.action];
        if (!sensor) return rowText(t(slot.labelKey));
        const raw = this._str('sensor.sem_' + sensor);
        if (!raw) return MISSING;
        return t(/negated|inverted/i.test(raw) ? 'sign_negated' : 'normal');
    }

    /** (#1321) No action runs on a tap: the question comes first, only its confirm button calls the service. */
    _askAction(slot, label) {
        const flip = slot.action === 'flip_grid_sign' ? 'next_flip_grid_body' : slot.action === 'flip_battery_sign' ? 'next_flip_battery_body' : '';
        const run = () => this._action(slot.action);
        if (flip) this._confirmDo({ title: label, body: this._t(flip), okLabel: this._t('next_flip_ok'), run });
        else this._askFirst(label, run, { body: this._t({ reset_sign_detection: 'next_confirm_reset_sign', purge_status_history: 'next_confirm_cleanup' }[slot.action] || 'next_confirm_body') });
    }

    async _action(name) {
        if (!this._hass) return;
        try {
            if (name === 'flip_grid_sign' || name === 'flip_battery_sign') {
                const res = await this._call('solar_energy_management', name, {}, undefined, false, true);
                const payload = res && res.response ? res.response : res;
                const ok = await this._writeClipboard(JSON.stringify(payload || {}, null, 2), true);
                this._say(this._t(ok ? 'sign_flipped_copied' : 'sign_flipped'), 6000);
            } else if (name === 'reset_sign_detection') {
                await this._call('solar_energy_management', 'reset_sign_detection', {}, undefined, false);
                this._say(this._t('sign_relearn_started'), 4000);
            } else if (name === 'purge_status_history') {
                await this._call('solar_energy_management', 'purge_status_history', {}, undefined, false);
                this._say(this._t('next_done'));
            }
        } catch (err) {
            console.error('[sem-next-system-card] action failed', name, err);
            this._say(err?.message || this._t('next_apply_failed'), 8000, true);
        }
    }

    async _diagnose(section) {
        if (!this._hass || this._diagBusy) return;
        this._diagBusy = true;
        try {
            const resp = await this._call('solar_energy_management', 'diagnose',
                { section: section || 'all' }, undefined, false, true);
            const payload = resp?.response || resp;
            await this._writeClipboard(JSON.stringify(payload, null, 2));
        } catch (err) {
            console.error('[sem-next-system-card] diagnose failed', err);
            this._say(err?.message || this._t('copy_failed'), 8000, true);
        } finally {
            this._diagBusy = false;
        }
    }

    // The classic System card's text (sem-system-card.js): support reads SEM's own words.
    _copyDiagnostics() {
        const v = (id) => this._str(id) || '—';
        const cap = this._num('sensor.sem_diag_battery_capacity');
        const capStr = cap !== null && cap > 0 ? cap.toFixed(1) : '—';
        const header = `SEM ${v('sensor.sem_diag_version')} | Grid: ${v('sensor.sem_diag_grid_mode')} | Chargers: ${v('sensor.sem_diag_charger_count')} (${v('sensor.sem_diag_charger_control')}) | Battery: ${capStr}kWh | Unavailable: ${this._str('sensor.sem_diag_sensors_unavailable') || MISSING}`;
        const ed = this._attrs('sensor.sem_diag_ed_config').energy_dashboard;
        let edBlock;
        if (ed) {
            const x = (y) => y || '—';
            edBlock = `Solar:   pwr=${x(ed.solar?.power)} [${x(ed.solar?.power_source)}]  energy=${x(ed.solar?.energy)}\n`
                + `Grid:    pwr=${x(ed.grid?.power)} [${x(ed.grid?.power_source)}]  imp=${x(ed.grid?.import_energy)}  exp=${x(ed.grid?.export_energy)}\n`
                + `Battery: pwr=${x(ed.battery?.power)} [${x(ed.battery?.power_source)}]  chg=${x(ed.battery?.charge_energy)}  dis=${x(ed.battery?.discharge_energy)}`;
        } else {
            edBlock = `Config: ${v('sensor.sem_diag_ed_config')}`;
        }
        this._writeClipboard(`${header}\n${edBlock}`);
    }

    /** Modern clipboard first, the legacy textarea path on plain HTTP (#285). */
    async _writeClipboard(text, quiet = false) {
        const done = (ok) => { if (!quiet) this._say(this._t(ok ? 'copied' : 'copy_failed'), ok ? 2500 : 8000, !ok); return ok; };
        if (navigator?.clipboard?.writeText && window.isSecureContext !== false) {
            try { await navigator.clipboard.writeText(text); return done(true); } catch (err) { /* fall through */ }
        }
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.left = '0';
            ta.style.width = '1px'; ta.style.height = '1px'; ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus(); ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return done(!!ok);
        } catch (err) {
            console.error('[sem-next-system-card] clipboard fallback threw', err);
            return done(false);
        }
    }

    // ── render ──

    render() {
        if (!this._hass) return nothing;
        const rows = this._freshRows();
        const bad = rows.filter((r) => r.state !== 'ok').length + (this._inputsDegraded() ? 1 : 0);
        const main = bad ? this._tf('next_sys_lead_bad', { n: bad }) : this._t('next_sys_lead_ok');
        const sub = this._t('next_sys_sub');
        const t = (k) => this._t(k);
        const gs = groups(this._hass.states, t, this._ctx());
        return this._frame({ main, sub }, html`<div class="grid">
                ${this._health(rows)}
                ${this._refused()}
                ${gs.map((g) => this._group(g))}
            </div>
            ${this._applyBar()}`);
    }
}

semDefineCard('sem-next-system-card', SEMNextSystemCard, {
    type: 'sem-next-system-card',
    name: 'SEM · System',
    description: 'Health first: source freshness, setup check, what SEM held back, and every setting as a sentence',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-system-card',
    preview: true,
});
