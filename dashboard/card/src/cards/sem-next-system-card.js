/**
 * SEM Next · System (#1321)
 *
 * Health first: how fresh every source is, the setup check, the hardware,
 * what is unavailable, the version, with Copy diagnostics, Diagnose and
 * the observer switch (behind a confirm step: the test rigs share real
 * hardware). Then what SEM held back. Then the settings as seven sentences;
 * tap a value, it becomes a control; changes wait in a pending map and go
 * out together from the sticky Apply bar: entities directly, options in
 * one set_option call. Entity fields use HA's own entity picker, filtered
 * like the classic setup card's picker for the same option. Chargers are
 * added and removed here; the setup check and the detected-hardware report
 * open in place (`_setupPanel`), never on the classic dashboard.
 *
 * Config:
 *   type: custom:sem-next-system-card
 */

import { SEMNextBase, html, css, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import './sem-next-setup-panel.js';
import { sourceRows, ageLabel, freshness, SOURCE_ROWS, sourceEntityOf } from '../util/next-freshness.js';
import { plainReason, deviceName } from '../util/why-rows.js';
import { MISSING } from '../util/missing-value.js';
import { groups, applyPlan, pendingKey, navTarget, slotText, setupItems, loadSources, unavailableCount,
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
    .sent input, .sent select, .help input, .help select { font-size: 13px; padding: 2px 6px; max-width: 130px; min-height: 28px; }
    .sent .ro { font-weight: 500; color: var(--n-fg); }
    .fresh .tile .xs.warn { color: var(--n-warn); }
    .fresh .tile .xs.bad { color: var(--n-bad); }
    .fresh .tile .srcid { font-family: var(--code-font-family, monospace); overflow-wrap: anywhere; }
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
            _editing: { state: true },
            _options: { state: true },
            _applying: { state: true },
            _confirmObs: { state: true },
            _diagBusy: { state: true },
            _panel: { state: true },
            _chargerBusy: { state: true },
            _confirmRemove: { state: true },
            _pickerReady: { state: true },
        };
    }

    constructor() {
        super();
        this._pending = {};
        this._editing = '';
        this._options = null;
        this._entryId = '';
        this._applying = false;
        this._confirmObs = false;
        this._diagBusy = false;
        this._optionsAsked = false;
        this._panel = '';
        this._chargerBusy = false;
        this._confirmRemove = '';
        this._pickerReady = false;
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

    updated(changed) {
        super.updated(changed);
        if (changed.has('_editing') && this._editing) {
            const el = this.renderRoot?.querySelector('.edit input, .edit select');
            if (el) { el.focus(); if (el.select) el.select(); }
        }
    }

    // ── options (the integration's own dict, for the slots no entity carries) ──

    async _loadOptions() {
        if (!this._hass) return;
        try {
            const resp = await this._hass.callService('solar_energy_management', 'get_config', {},
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
        for (const l of loadSources(states)) {
            const e = states[l.entity];
            rows.push({ key: l.id, name: l.name, entity: l.entity, src: l.entity, state: freshness(e, now), age: null,
                        icon: 'mdi:power-plug', color: C.home });
        }
        return rows;
    }

    _freshTiles(rows) {
        return html`<div class="fresh">${rows.map((r) => {
            const cls = r.state === 'ok' ? 'dim' : (r.state === 'old' ? 'warn' : 'bad');
            const txt = r.state === 'ok' || r.state === 'old' ? (ageLabel(r.age) || this._t('next_fresh_ok')) : this._t('next_fresh_' + r.state);
            // (#1321) the value and the real entity SEM reads, for checking a setup
            const st = this._hass.states[r.entity];
            const val = !st ? '' : (typeof this._hass.formatEntityState === 'function' ? this._hass.formatEntityState(st)
                : `${st.state}${st.attributes?.unit_of_measurement ? ' ' + st.attributes.unit_of_measurement : ''}`);
            return html`<div class="tile" style="--c:${r.color}" role="button" tabindex="0" @click=${() => this._moreInfo(r.src && this._hass.states[r.src] ? r.src : r.entity)}>
                ${this._icon(r.icon)}<div style="min-width:0"><div class="sm" style="font-weight:500">${r.name}</div><div class="xs ${cls}">${val ? val + ' · ' : ''}${txt}</div>
                ${r.src ? html`<div class="xs dim srcid">${r.src}</div>` : nothing}</div></div>`;
        })}</div>`;
    }

    _setupRow() {
        const items = setupItems(this._hass.states, this._options);
        const counted = items.filter((i) => !i.optional);
        const done = counted.filter((i) => i.done).length;
        const value = done === counted.length ? this._t('config_setup_done')
            : this._tf('config_setup_progress', { done, total: counted.length });
        const grid = this._valLabel('diag_grid_sign');
        const batt = this._valLabel('diag_battery_sign');
        const sub = [grid ? `${this._t('next_grid_sign')} ${grid}` : '', batt ? `${this._t('next_battery_sign')} ${batt}` : ''].filter(Boolean).join(' · ');
        return this._row('mdi:check-decagram', this._t('next_setup_check'), value, sub, { onClick: () => this._togglePanel('setup') });
    }

    _hardwareRow() {
        const count = this._str('sensor.sem_diag_charger_count');
        const control = this._valLabel('diag_charger_control');
        const cap = this._num('sensor.sem_diag_battery_capacity');
        const gridMode = this._valLabel('diag_grid_mode');
        const report = this._attrs('sensor.sem_diag_charger_control').detection_report || null;
        const unmapped = report ? (report.near_misses || []).length : null;
        const strings = pvStrings(this._hass.states).length;
        const value = [count !== '' ? this._tf('next_chargers_n', { n: count }) : '', control ? `(${control})` : ''].filter(Boolean).join(' ') || MISSING;
        const sub = [
            strings ? this._tf('next_strings', { n: strings }) : '',
            cap !== null && cap > 0 ? this._tf('next_batt_cap', { kwh: cap.toFixed(1) }) : '',
            gridMode ? `${this._t('next_grid_mode')} ${gridMode}` : '',
            unmapped !== null ? this._tf('next_unmapped', { n: unmapped }) : '',
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

    _observerButton() {
        const obs = this._obs();
        if (this._confirmObs) {
            return html`<span class="confirm">${this._t(obs ? 'next_obs_confirm_off' : 'next_obs_confirm_on')}
                ${this._btn(this._t('next_yes'), () => { this._confirmObs = false; this._toggleSwitch('switch.sem_observer_mode'); }, { small: true, primary: true })}
                ${this._btn(this._t('next_cancel'), () => { this._confirmObs = false; }, { small: true, ghost: true })}</span>`;
        }
        return this._btn(html`${this._t('next_observer')}: ${obs ? this._t('on') : this._t('off')} · <span class="val">${this._t(obs ? 'next_turn_off' : 'next_turn_on')}</span>`,
                         () => { this._confirmObs = true; }, { small: true, icon: 'mdi:eye-outline' });
    }

    _health(rows) {
        return this._sec(this._t('next_health'), html`
            ${this._freshTiles(rows)}
            <div class="rows" style="margin-top:8px">${this._setupRow()}${this._panel === 'setup' ? this._setupPanel('setup') : nothing}${this._hardwareRow()}${this._panel === 'hardware' ? this._setupPanel('hardware') : nothing}${this._unavailableRow()}${this._versionRow()}</div>
            <div class="btns" style="margin-top:10px">
                ${this._btn(this._t('copy_diagnostics'), () => this._copyDiagnostics(), { small: true, icon: 'mdi:content-copy' })}
                ${this._btn(this._t('config_diagnose'), () => this._diagnose('all'), { small: true, icon: 'mdi:stethoscope', disabled: this._diagBusy })}
                ${this._btn(this._t('config_open_ha_settings'), () => this._go(HA_SETTINGS), { small: true, icon: 'mdi:cog-outline' })}
                ${this._observerButton()}
            </div>
`, { cls: 'span2' });
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
                `${deviceName(r, t)}${r.action ? ' · ' + r.action : ''}`,
                Number.isFinite(Number(r.power_w)) ? this._kw(Number(r.power_w)) : '',
                plainReason(r, t) || r.reason || ''))}</div>`
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
                provider: this._valLabel('tariff_provider') || this._str('sensor.sem_tariff_provider'),
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

    _part(p) {
        if (typeof p === 'string') return p;
        if (!p || typeof p !== 'object') return '';
        if (p.ro) return html`<span class="ro">${p.value}</span>`;
        // (#1354) a link to where a setting is asked works while SEM only watches
        if (p.kind === 'action' && p.nav) return this._val(this._t(p.labelKey), () => this._go(navTarget(window.location.pathname, p.action)));
        if (p.kind === 'action') return this._val(this._t(p.labelKey), () => this._action(p.action), { disabled: this._obs() });
        return this._slot(p);
    }

    _slot(slot) {
        const key = pendingKey(slot);
        const pend = this._pending[key];
        const value = pend ? pend.value : slot.value;
        const dis = this._obs();
        const t = (k) => this._t(k);
        if (slot.kind === 'switch') {
            return html`<button type="button" class="val ${pend ? 'dirty' : ''}" ?disabled=${dis} role="switch" aria-checked="${!!value}"
                @click=${() => this._stage(slot, !value)}>${slotText(slot, t, value, this._hass.states)}</button>`;
        }
        if (this._editing === key && !dis) return this._editor(slot, value);
        return html`<button type="button" class="val ${pend ? 'dirty' : ''}" ?disabled=${dis}
            @click=${() => this._edit(slot, key)}>${slotText(slot, t, value, this._hass.states)}</button>`;
    }

    _edit(slot, key) {
        this._editing = key;
        if (slot.kind === 'entity') this._ensureEntityPicker();
    }

    /** HA loads ha-entity-picker on demand; an entities card's editor pulls it in. */
    async _ensureEntityPicker() {
        if (customElements.get('ha-entity-picker')) { this._pickerReady = true; return; }
        try {
            const helpers = await window.loadCardHelpers?.();
            if (helpers?.createCardElement) {
                const el = await helpers.createCardElement({ type: 'entities', entities: [] });
                await el.constructor?.getConfigElement?.();
            }
        } catch (e) { /* the text input stays */ }
        this._pickerReady = !!customElements.get('ha-entity-picker');
    }

    _entityEditor(slot, value, close) {
        const done = (v) => { this._stage(slot, v || ''); close(); };
        const esc = (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } };
        if (!customElements.get('ha-entity-picker')) {
            return html`<span class="edit pick"><input type="text" .value=${String(value ?? '')} placeholder="sensor.…"
                @change=${(e) => done(e.target.value.trim())} @keydown=${(e) => { esc(e); if (e.key === 'Enter') { e.preventDefault(); done(e.target.value.trim()); } }}></span>`;
        }
        const dc = slot.deviceClass;
        return html`<span class="edit pick" @keydown=${esc}><ha-entity-picker
            .hass=${this._hass}
            .value=${value || ''}
            .includeDomains=${slot.domains || undefined}
            .includeDeviceClasses=${dc && !FILTER_CLASSES.has(dc) ? [dc] : undefined}
            .entityFilter=${dc ? ENTITY_FILTERS[dc] : undefined}
            .allowCustomEntity=${false}
            @value-changed=${(e) => done(e.detail?.value || '')}></ha-entity-picker>
            ${this._btn(this._t('next_cancel'), close, { small: true, ghost: true })}</span>`;
    }

    _editor(slot, value) {
        const close = () => { if (this._editing === pendingKey(slot)) this._editing = ''; };
        const keys = (e) => { if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); e.target.blur(); } };
        const t = (k) => this._t(k);
        if (slot.kind === 'entity') return this._entityEditor(slot, value, close);
        if (slot.kind === 'select') {
            return html`<span class="edit"><select @change=${(e) => { this._stage(slot, e.target.value); close(); }} @blur=${close} @keydown=${keys}>
                ${(slot.options || []).map((o) => html`<option value="${o.value}" ?selected=${String(o.value) === String(value)}>${o.labelKey ? t(o.labelKey) : (o.label ?? o.value)}</option>`)}
            </select></span>`;
        }
        if (slot.kind === 'number') {
            return html`<span class="edit"><input type="number" .value=${String(value ?? '')}
                min="${slot.min ?? nothing}" max="${slot.max ?? nothing}" step="${slot.step || 1}"
                @input=${(e) => this._stage(slot, e.target.value)} @blur=${close} @keydown=${keys}>${slot.unit ? html` ${slot.unit}` : nothing}</span>`;
        }
        return html`<span class="edit"><input type="text" .value=${String(value ?? '')} placeholder="${slot.placeholder || nothing}"
            @input=${(e) => this._stage(slot, e.target.value)} @blur=${close} @keydown=${keys}></span>`;
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
        return this._sec(this._t(g.titleKey), html`
            <p class="sent">${g.sentence.map((p) => this._part(p))}</p>
            ${g.key === 'chargers' ? this._chargerTools() : nothing}
            ${n ? html`<p class="help"><span data-more>${g.more.map((p) => this._part(p))}</span><span class="app-not-all">${this._tf('config_more_in_all', { n })}</span></p>` : nothing}`,
            { cls: 'group', extra });
    }

    // ── chargers: add and remove (classic _addCharger / _removeCharger) ──

    _chargerTools() {
        const dis = this._obs() || this._chargerBusy || this._applying || !this._options;
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
        await this._hass.callService('solar_energy_management', 'set_option',
            { options, ...(this._entryId ? { entry_id: this._entryId } : {}) }, undefined, false);
    }

    async _addCharger() {
        if (this._chargerBusy || !this._options || this._obs()) return;
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
        if (this._chargerBusy || !cid || this._obs()) return;
        this._chargerBusy = true;
        this._confirmRemove = '';
        try {
            await this._hass.callService('solar_energy_management', 'remove_charger', { charger_id: cid }, undefined, false);
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

    _discard() { this._pending = {}; this._editing = ''; }

    async _apply() {
        if (this._applying || !Object.keys(this._pending).length || !this._hass) return;
        this._applying = true;
        this._editing = '';
        const plan = applyPlan(this._pending, this._hass.states);
        try {
            for (const w of plan.entityWrites) await this._hass.callService(w.domain, w.service, w.data, undefined, false);
            if (Object.keys(plan.options).length) {
                await this._hass.callService('solar_energy_management', 'set_option',
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

    async _action(name) {
        if (!this._hass || this._obs()) return;
        try {
            if (name === 'flip_grid_sign' || name === 'flip_battery_sign') {
                const res = await this._hass.callService('solar_energy_management', name, {}, undefined, false, true);
                const payload = res && res.response ? res.response : res;
                const ok = await this._writeClipboard(JSON.stringify(payload || {}, null, 2), true);
                this._say(this._t(ok ? 'sign_flipped_copied' : 'sign_flipped'), 6000);
            } else if (name === 'reset_sign_detection') {
                await this._hass.callService('solar_energy_management', 'reset_sign_detection', {}, undefined, false);
                this._say(this._t('sign_relearn_started'), 4000);
            } else if (name === 'purge_status_history') {
                await this._hass.callService('solar_energy_management', 'purge_status_history', {}, undefined, false);
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
            const resp = await this._hass.callService('solar_energy_management', 'diagnose',
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
        const sub = this._obs() ? `${this._t('next_sys_sub')} ${this._t('next_observing_hint')}` : this._t('next_sys_sub');
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
