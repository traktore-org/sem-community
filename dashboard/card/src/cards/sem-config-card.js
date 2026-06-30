/**
 * SEM Configuration Card (#442)
 *
 * One-stop SEM setup surface that lives inside the dashboard so users
 * don't have to navigate Settings → Devices & Services → SEM →
 * Configure for every tweak. Mirrors the visual + interaction language
 * of ``sem-control-card.js``:
 *   - accordion sections with color-accent stripe when expanded
 *   - shared (?) help toggle (beta.7 pattern) that reveals one-line
 *     descriptions next to every setting
 *   - stepper / toggle / select primitives backed by existing
 *     ``number.sem_*`` / ``switch.sem_*`` / ``select.sem_*`` runtime
 *     entities — no parallel data model
 *
 * For settings that don't have a runtime entity (entity pickers like
 * ``vehicle_soc_entity``, list-shaped settings like ev_chargers), the
 * card defers to ``<sem-entity-picker>`` (Phase 3) or deep-links to
 * the legacy OptionsFlow via a "Manage in HA settings" button.
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard, semCardSurfaceCSS } from '../base/sem-shared.js';

// Section index — order = visual order in the rendered tab. Each entry
// carries a colour-accent that matches the section icon, mirroring the
// Control card's design language.
const SECTIONS = [
    {
        id: 'overview',
        icon: 'mdi:check-decagram',
        color: '#8DC892',
        titleKey: 'config_section_overview',
        subtitleFn: (c) => c._overviewSubtitle(),
        expanded: true,  // open by default — gives the user a quick status read
    },
    {
        id: 'ev_chargers',
        icon: 'mdi:ev-station',
        color: '#5BC8D8',
        titleKey: 'config_section_ev_chargers',
        subtitleFn: (c) => c._evChargersSubtitle(),
    },
    {
        id: 'battery_zones',
        icon: 'mdi:battery-charging-medium',
        color: '#4db6ac',
        titleKey: 'config_section_battery_zones',
        subtitleFn: (c) => c._batteryZonesSubtitle(),
    },
    {
        id: 'tariff',
        icon: 'mdi:cash-multiple',
        color: '#96CAEE',
        titleKey: 'config_section_tariff',
        subtitleFn: (c) => c._tariffSubtitle(),
    },
    {
        id: 'heat_pump',
        icon: 'mdi:heat-pump',
        color: '#4db6ac',
        titleKey: 'config_section_heat_pump',
        subtitleFn: (c) => c._heatPumpSubtitle(),
    },
    {
        id: 'hot_water',
        icon: 'mdi:water-boiler',
        color: '#5BC8D8',
        titleKey: 'config_section_hot_water',
        subtitleFn: (c) => c._hotWaterSubtitle(),
    },
    {
        id: 'battery_scheduler',
        icon: 'mdi:calendar-clock',
        color: '#f06292',
        titleKey: 'config_section_battery_scheduler',
        subtitleFn: () => '',
    },
    {
        id: 'load_management',
        icon: 'mdi:flash-alert',
        color: '#ff9800',
        titleKey: 'config_section_load_management',
        subtitleFn: (c) => c._loadMgmtSubtitle(),
    },
    {
        id: 'forecast',
        icon: 'mdi:weather-partly-cloudy',
        color: '#ff9800',
        titleKey: 'config_section_forecast',
        subtitleFn: (c) => c._forecastSubtitle(),
    },
    {
        id: 'notifications',
        icon: 'mdi:bell-outline',
        color: '#96CAEE',
        titleKey: 'config_section_notifications',
        subtitleFn: () => '',
    },
    {
        id: 'advanced',
        icon: 'mdi:cog-outline',
        color: '#888',
        titleKey: 'config_section_advanced',
        subtitleFn: () => '',
    },
];

// Watched HA entities — every entity that drives a subtitle / body
// computation. shouldUpdate compares old vs new states for these only.
const WATCHED = [
    'binary_sensor.sem_heat_pump_registered',
    'sensor.sem_heat_pump_mode', 'sensor.sem_heat_pump_sg_ready_state',
    'number.sem_heat_pump_boost_offset',
    'sensor.sem_tariff_provider', 'sensor.sem_tariff_price_level',
    'sensor.sem_tariff_current_import_rate',
    'sensor.sem_forecast_source',
    'sensor.sem_load_management_status',
    'sensor.sem_battery_soc', 'sensor.sem_battery_status',
    'number.sem_battery_priority_soc', 'number.sem_battery_buffer_soc',
    'number.sem_battery_auto_start_soc',
    'number.sem_battery_assist_min_surplus', 'number.sem_battery_assist_max_power',
    'number.sem_cheap_price_threshold', 'number.sem_expensive_price_threshold',
    'number.sem_minimum_solar_power',
    'number.sem_update_interval',
    'number.sem_ev_enable_delay_seconds', 'number.sem_ev_disable_delay_seconds',
    // #492: regulation_offset moved here from sem-control-card (Config
    // is the single settings home; Control is live-ops only).
    'number.sem_regulation_offset',
    'switch.sem_observer_mode',
    // #461: grid-sign fix lives in the Advanced section now.
    'sensor.sem_diag_grid_sign',
];

// #528 — entity-wiring keys that trigger an entry RELOAD when changed (mirror
// of __init__.py:_SET_OPTION_STRUCTURAL_KEYS). Pickers for these stage their
// edit and commit on one Apply, so the reload fires once for the whole batch.
const STRUCTURAL_KEYS = new Set([
    'battery_soc_sensor',
    'heat_pump_relay1_entity', 'heat_pump_relay2_entity',
    'heat_pump_climate_entity', 'heat_pump_power_sensor',
    'heat_pump_temperature_sensor', 'heat_pump_invert_sg_ready',
    'hot_water_entity', 'hot_water_power_sensor', 'hot_water_temperature_sensor',
    'battery_force_discharge_control_entity', 'battery_strategy_control_entity',
    'battery_discharge_control_entity',  // #528 — discharge-limit (protection) entity
]);

class SEMConfigCard extends SEMLitBase {
    static get watchedEntities() { return WATCHED; }

    static get properties() {
        return {
            ...super.properties,
            _showHelp: { state: true },
            _entryId: { state: true },
            _saveStatus: { state: true },
            // #461 grid-sign fix button transient UI state.
            _signBusy: { state: true },
            _signMsg: { state: true },
            // #528 staged structural (entity-wiring) edits — committed in one
            // Apply so a reload fires once for the whole batch, not per field.
            _pending: { state: true },
            _applying: { state: true },
            // #528 Phase 4 — per-charger remove confirm (inline, no blocking
            // window.confirm) + add/remove busy flag.
            _pendingRemove: { state: true },
            _chargerBusy: { state: true },
        };
    }

    constructor() {
        super();
        // Overview open by default; everything else collapsed so the
        // tab doesn't feel overwhelming on first open.
        this._collapsed = {
            overview: false,
            ev_chargers: true, battery_zones: true, tariff: true,
            heat_pump: true, hot_water: true, battery_scheduler: true,
            load_management: true, forecast: true, notifications: true,
            advanced: true,
        };
        this._showHelp = false;
        this._entryId = '';
        this._saveStatus = {};  // { fieldKey: 'saving' | 'ok' | error-msg }
        this._statusTimers = new Set();  // pending ✓-clear timeouts (#476)
        this._signBusy = false;
        this._signMsg = '';
        this._pending = {};   // { structuralKey: stagedValue }
        this._applying = false;
        this._pendingRemove = '';  // charger id awaiting remove-confirm
        this._chargerBusy = false;
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        // Cancel pending save-status clears — they hold `this` alive and
        // fire requestUpdate() on a detached element when the dashboard
        // is switched away mid-save (#476).
        for (const t of this._statusTimers) clearTimeout(t);
        this._statusTimers.clear();
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || 'sensor.sem_';
        if (config.entry_id) this._entryId = config.entry_id;
    }

    // Look up the SEM ConfigEntry id once we have hass — needed to write
    // option changes back via the public ``config_entries/update`` WS API.
    async _ensureEntryId() {
        if (this._entryId || !this._hass) return this._entryId;
        try {
            const entries = await this._hass.callWS({
                type: 'config_entries/get',
                domain: 'solar_energy_management',
            });
            if (Array.isArray(entries) && entries.length > 0) {
                this._entryId = entries[0].entry_id;
                this.requestUpdate();
            }
        } catch (err) {
            console.warn('[sem-config-card] entry lookup failed', err);
        }
        return this._entryId;
    }

    // Write one option key (or several) to ``entry.options`` via the
    // SEM-side ``solar_energy_management.set_option`` service. We can't
    // use HA's public ``config_entries/update`` WS call here — it
    // explicitly rejects the ``options`` field (reserved for the
    // OptionsFlow round-trip). The service is SEM's supported escape
    // hatch and fires the same ``update_listener`` the OptionsFlow
    // does, so the coordinator reloads on structural changes.
    async _saveOption(key, value, fieldKey) {
        const entryId = await this._ensureEntryId();
        this._saveStatus = { ...this._saveStatus, [fieldKey || key]: 'saving' };
        try {
            await this._hass.callService(
                'solar_energy_management',
                'set_option',
                {
                    options: { [key]: value },
                    ...(entryId ? { entry_id: entryId } : {}),
                },
            );
            this._saveStatus = { ...this._saveStatus, [fieldKey || key]: 'ok' };
            // Refresh local cache so the displayed value updates
            // immediately — without waiting for the next render cycle.
            this._options = { ...this._options, [key]: value };
            this.requestUpdate();
            const timer = setTimeout(() => {
                this._statusTimers.delete(timer);
                this._saveStatus = { ...this._saveStatus };
                delete this._saveStatus[fieldKey || key];
                this.requestUpdate();
            }, 1200);
            this._statusTimers.add(timer);
        } catch (err) {
            console.error('[sem-config-card] save failed', key, err);
            this._saveStatus = { ...this._saveStatus, [fieldKey || key]: err?.message || 'save failed' };
            this.requestUpdate();
        }
    }

    // Cached options dict from the SEM entry — refreshed on entryId
    // lookup and after any save. Reads are synchronous in render().
    _options = {};

    async _refreshOptions() {
        if (!this._hass) return;
        try {
            // HA's public ``config_entries/get`` strips data/options for
            // security. SEM's ``get_config`` service is the supported
            // way to read the merged config dict the OptionsFlow uses.
            const resp = await this._hass.callService(
                'solar_energy_management',
                'get_config',
                {},
                undefined,
                undefined,  // notifyOnError
                true,       // returnResponse
            );
            const cfg = resp?.response?.config || {};
            this._options = cfg;
            if (resp?.response?.entry_id && !this._entryId) {
                this._entryId = resp.response.entry_id;
            }
            this.requestUpdate();
        } catch (err) {
            // Tolerate — older SEM installs without the service still
            // render with empty options (defaults shown).
            console.warn('[sem-config-card] get_config failed', err);
        }
    }

    connectedCallback() {
        super.connectedCallback();
        // Defer until hass arrives. If hass is already set, fire now.
        if (this._hass) {
            this._ensureEntryId().then(() => this._refreshOptions());
        } else {
            // hass setter triggers this once via _afterFirstHass below.
            this._needsEntryLookup = true;
        }
    }

    // Override hass setter so we can fire the entry lookup on first hass.
    set hass(hass) {
        super.hass = hass;
        if (this._needsEntryLookup && hass) {
            this._needsEntryLookup = false;
            this._ensureEntryId().then(() => this._refreshOptions());
        }
    }
    get hass() { return super.hass; }

    _toggleHelp() { this._showHelp = !this._showHelp; }
    _toggleSection(id) {
        // `_collapsed` is a plain instance property (not a Lit reactive
        // state) — mutating it does NOT schedule a re-render on its own.
        // Mirror the Control card pattern: explicit ``requestUpdate()``.
        this._collapsed = { ...this._collapsed, [id]: !this._collapsed[id] };
        this.requestUpdate();
    }

    // ── Entity helpers ──

    _val(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }
    /**
     * Read a BINARY sensor state — ``binary_sensor.sem_<suffix>``.
     * Returns ``true`` when state is ``"on"``, ``false`` otherwise.
     *
     * v1.7.2-beta.5 (#448): ``_val()`` prepends ``sensor.sem_`` so it
     * doesn't work for binary_sensor entities. ``heat_pump_registered``,
     * ``heat_pump_solar_boost``, ``ev_charging``, ``solar_active``, etc.
     * are BINARY sensors. Reading them via ``_val()`` always returns ''
     * — the subtitle ended up showing "not_configured" even when the
     * heat pump WAS registered (RienduPre).
     */
    _bin(suffix) {
        return this._hass?.states[`binary_sensor.sem_${suffix}`]?.state === 'on';
    }
    _valNum(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        const n = parseFloat(e.state);
        return Number.isNaN(n) ? fallback : n;
    }
    _switchOn(suffix) {
        const e = this._hass?.states[`switch.sem_${suffix}`];
        return e?.state === 'on';
    }

    async _toggleSwitch(entityId) {
        const s = this._hass?.states[entityId];
        if (!s) return;
        await this._hass.callService('switch', s.state === 'on' ? 'turn_off' : 'turn_on', { entity_id: entityId });
    }
    async _stepNumber(entityId, dir) {
        const s = this._hass?.states[entityId];
        if (!s) return;
        const step = parseFloat(s.attributes.step) || 1;
        const min = parseFloat(s.attributes.min) ?? 0;
        const max = parseFloat(s.attributes.max) ?? 100;
        const cur = parseFloat(s.state) || 0;
        let next = cur + dir * step;
        next = Math.max(min, Math.min(max, next));
        await this._hass.callService('number', 'set_value', { entity_id: entityId, value: next });
    }
    async _selectOption(entityId, value) {
        await this._hass.callService('select', 'select_option', { entity_id: entityId, option: value });
    }
    // Direct-set a number entity to an exact value (slider drag), clamped to
    // the entity's own min/max. Live tunable — no entry reload.
    async _setNumber(entityId, value) {
        const s = this._hass?.states[entityId];
        if (!s) return;
        const min = parseFloat(s.attributes.min);
        const max = parseFloat(s.attributes.max);
        let v = value;
        if (!Number.isNaN(min)) v = Math.max(min, v);
        if (!Number.isNaN(max)) v = Math.min(max, v);
        await this._hass.callService('number', 'set_value', { entity_id: entityId, value: v });
    }
    // Read a full entity_id as a number (no prefix), fallback when unavailable.
    _num(id, fb = null) {
        const e = this._hass?.states[id];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fb;
        const n = parseFloat(e.state);
        return Number.isNaN(n) ? fb : n;
    }

    // ── Subtitles ──

    _overviewSubtitle() {
        const chargers = this._chargersList().length;
        const heatpump = this._bin('heat_pump_registered');
        const parts = [];
        parts.push(`${chargers} ${this._t('config_subtitle_chargers')}`);
        if (heatpump) parts.push(this._t('config_subtitle_heatpump_on'));
        return parts.join(' · ');
    }
    _evChargersSubtitle() {
        const n = this._chargersList().length;
        return `${n}`;
    }
    _batteryZonesSubtitle() {
        const soc = this._valNum('battery_soc');
        return `${this._t('soc')} ${soc.toFixed(0)}%`;
    }
    _tariffSubtitle() {
        const provider = this._val('tariff_provider') || '—';
        const level = this._val('tariff_price_level') || '';
        return level ? `${provider} · ${this._t(level.toLowerCase()) || level}` : provider;
    }
    _heatPumpSubtitle() {
        return this._bin('heat_pump_registered')
            ? this._t('configured')
            : this._t('not_configured');
    }
    _hotWaterSubtitle() {
        // The HotWaterController is not currently instantiated in the
        // production path — until that hookup lands, the subtitle just
        // says whether the user has configured a hot_water_entity at
        // all. The Diagnose modal still works and shows the configured
        // sensor + targets, useful for support.
        const opts = this._options || {};
        return opts.hot_water_entity
            ? this._t('configured')
            : this._t('not_configured');
    }
    _loadMgmtSubtitle() {
        return this._val('load_management_status') || '';
    }
    _forecastSubtitle() {
        const label = this._forecastProviderLabel(this._val('forecast_source'));
        return label ? label : this._t('not_configured');
    }

    // ── Helpers ──

    _chargersList() {
        // Walk HA entity registry mirror via the per-charger entities
        // that SEM creates. Each charger has a stable
        // ``number.sem_charger_<id>_minimum_current`` entity.
        const ids = new Set();
        for (const eid of Object.keys(this._hass?.states || {})) {
            const m = eid.match(/^number\.sem_charger_(.+)_minimum_current$/);
            if (m) ids.add(m[1]);
        }
        return Array.from(ids).sort();
    }

    _openHaSettings(stepId = '') {
        // Deep-link to the SEM integration's options flow at the
        // requested step. The user lands on Settings → Devices &
        // Services → SEM with the options dialog already open.
        const url = stepId
            ? `/config/integrations/integration/solar_energy_management`
            : `/config/integrations/integration/solar_energy_management`;
        window.history.pushState(null, '', url);
        // Trigger HA's frontend router via popstate
        window.dispatchEvent(new PopStateEvent('popstate'));
    }

    // ── Reusable inline primitives ──

    // #528: every number setting now uses the colorful accent-slider knob
    // (battery design language) instead of the flat −/+ row. ``_renderStepper``
    // delegates to ``_renderZoneKnob`` so all sections (tariff, heat pump,
    // hot water, advanced, per-charger) restyle uniformly with one change.
    _renderStepper(entityId, labelKey, T, helpKey) {
        return this._renderZoneKnob(entityId, labelKey, T, helpKey);
    }

    _renderToggle(entityId, labelKey, T, helpKey) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        const isOn = entity.state === 'on';
        return html`
            <div class="stepper-cell">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(labelKey)}</span>
                    <div class="toggle-track ${isOn ? 'on' : ''}" @click=${() => this._toggleSwitch(entityId)}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    _renderSelect(entityId, labelKey, T, helpKey) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        const cur = entity.state;
        const options = entity.attributes.options || [];
        return html`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(labelKey)}</span>
                    <select class="sem-select" .value=${cur}
                            @change=${(e) => this._selectOption(entityId, e.target.value)}>
                        ${options.map(o => html`<option value="${o}" ?selected=${o === cur}>${this._t(o.toLowerCase()) || o}</option>`)}
                    </select>
                </div>
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    _renderHaSettingsButton(labelKey) {
        return html`
            <button class="ha-settings-btn" @click=${() => this._openHaSettings()}>
                <ha-icon icon="mdi:cog-outline" style="--mdc-icon-size:14px"></ha-icon>
                ${this._t(labelKey)}
            </button>
        `;
    }

    // ── Per-section content renderers ──

    // #528 — first-run completeness guide. Lists the optional subsystems with
    // their status; an unconfigured one is a clickable "Set up →" chip that
    // expands its section. Core (Energy Dashboard) is guaranteed by the native
    // flow so it's always ✓. Turns all-green and shows "All set up" when done.
    _setupItems() {
        const opts = this._options || {};
        return [
            { key: 'energy', labelKey: 'config_overview_energy_dashboard', icon: 'mdi:flash',
              color: '#ff9800', sectionId: 'overview',
              done: !!this._hass?.states['sensor.sem_charging_state'] },
            { key: 'ev', labelKey: 'config_overview_chargers', icon: 'mdi:ev-station',
              color: '#5BC8D8', sectionId: 'ev_chargers',
              done: this._chargersList().length > 0 },
            { key: 'hp', labelKey: 'heat_pump_title', icon: 'mdi:heat-pump',
              color: '#4db6ac', sectionId: 'heat_pump',
              done: this._bin('heat_pump_registered') },
            { key: 'hw', labelKey: 'config_section_hot_water', icon: 'mdi:water-boiler',
              color: '#5BC8D8', sectionId: 'hot_water',
              done: !!opts.hot_water_entity },
        ];
    }

    _openSection(id) {
        this._collapsed = { ...this._collapsed, [id]: false };
        this.requestUpdate();
    }

    _renderOverview(T) {
        const items = this._setupItems();
        const done = items.filter(i => i.done).length;
        const total = items.length;
        const allDone = done === total;
        const pct = total ? Math.round((done / total) * 100) : 100;
        return html`
            <div class="setup-progress">
                <div class="setup-progress-top">
                    <span class="setup-progress-label">
                        ${allDone
                            ? this._t('config_setup_done')
                            : this._t('config_setup_progress').replace(/\{done\}/g, String(done)).replace(/\{total\}/g, String(total))}
                    </span>
                    <span class="setup-progress-pct">${pct}%</span>
                </div>
                <div class="setup-progress-bar">
                    <div class="setup-progress-fill ${allDone ? 'done' : ''}" style=${`width:${pct}%`}></div>
                </div>
            </div>
            <div class="chips">
                ${items.map(i => html`
                    <div class="chip ${i.done ? '' : 'chip-todo'}"
                        @click=${i.done ? undefined : () => this._openSection(i.sectionId)}>
                        <ha-icon icon="${i.icon}" style="--mdc-icon-size:16px;color:${i.color}"></ha-icon>
                        <div class="chip-label">${this._t(i.labelKey)}</div>
                        <div class="chip-value ${i.done ? 'c-ok' : 'c-warn'}">
                            ${i.done ? '✓' : this._t('config_setup_action')}
                        </div>
                    </div>`)}
            </div>
            <div class="overview-help">${this._t('config_overview_help')}</div>
            <div class="overview-actions">
                ${this._renderHaSettingsButton('config_open_ha_settings')}
            </div>
        `;
    }

    _renderEvChargers(T) {
        const opts = this._options || {};
        // Iterate over opts.ev_chargers (canonical source) so idx is
        // aligned with the nested-write path. Fall back to runtime
        // discovery for the per-charger ``number.sem_charger_<id>_*``
        // entity steppers (cid is the SEM-assigned id, not the index).
        const optsChargers = opts.ev_chargers || [];
        const runtimeIds = this._chargersList();
        if (optsChargers.length === 0 && runtimeIds.length === 0) {
            return html`
                <div class="empty-state">
                    <ha-icon icon="mdi:ev-station-outline" style="--mdc-icon-size:32px;color:#5BC8D8;opacity:0.7"></ha-icon>
                    <div class="empty-title">${this._t('config_ev_no_chargers')}</div>
                    <button class="add-charger-btn" ?disabled=${this._chargerBusy} @click=${() => this._addCharger()}>
                        <ha-icon icon="mdi:plus" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t('config_ev_add_charger')}
                    </button>
                </div>
            `;
        }
        // Prefer iterating options-shape; align each opts entry with
        // the runtime id of the same position when present.
        const rows = optsChargers.length ? optsChargers : runtimeIds.map(_ => ({}));
        return html`
            ${rows.map((charger, idx) => {
                // No id on the entry AND no runtime id at this position
                // (opts list longer than discovered chargers): skip rather
                // than render steppers against entities like
                // number.sem_charger_undefined_minimum_current (#476).
                const cid = charger.id || runtimeIds[idx];
                if (!cid) return nothing;
                return html`
                <div class="charger-block">
                    <div class="charger-block-title">
                        <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:18px;color:#5BC8D8"></ha-icon>
                        <span style="flex:1">${this._chargerFriendlyName(cid)}</span>
                        ${this._pendingRemove === cid ? nothing : html`
                            <button class="charger-remove-x" title="${this._t('config_ev_remove')}"
                                @click=${() => { this._pendingRemove = cid; this.requestUpdate(); }}>✕</button>`}
                    </div>
                    ${this._pendingRemove === cid ? html`
                        <div class="charger-remove-confirm">
                            <span>${this._t('config_ev_remove_confirm')}</span>
                            <button class="charger-remove-cancel" @click=${() => { this._pendingRemove = ''; this.requestUpdate(); }}>${this._t('config_discard')}</button>
                            <button class="charger-remove-go" @click=${() => this._removeCharger(cid)}>${this._t('config_ev_remove')}</button>
                        </div>` : nothing}
                    ${this._renderPickerNested(idx, cid, 'ev_connected_sensor', 'config_ev_connected_sensor',
                        'binary_sensor', null, opts, 'config_help_ev_connected_sensor')}
                    ${this._renderPickerNested(idx, cid, 'ev_charging_power_sensor', 'config_ev_charging_power',
                        'sensor', 'power', opts, 'config_help_ev_charging_power')}
                    ${this._renderPickerNested(idx, cid, 'ev_current_control_entity', 'config_ev_current_control',
                        'number', null, opts, 'config_help_ev_current_control')}
                    ${this._renderPickerNested(idx, cid, 'vehicle_soc_entity', 'config_ev_vehicle_soc',
                        'sensor', null, opts, 'config_help_ev_vehicle_soc')}
                    ${this._renderTargetTypeSelectNested(idx, cid, charger, opts)}
                    ${''/* ONE current knob (#536): Min Amps. SEM auto-finds a
                       fussy car's start current (day AND night) and settles
                       back here — no Start Amps / Vehicle Min Amps knobs. */}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_minimum_current`, 'min_amps', T, 'tile_help_min_amps')}
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_battery_capacity_kwh`, 'capacity_kwh', T, 'tile_help_capacity')}
                    </div>
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_surplus_priority`, 'surplus_priority', T, 'tile_help_surplus_priority')}
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_shed_priority`, 'shed_priority', T, 'tile_help_shed_priority')}
                    </div>
                </div>
            `;})}
            <div class="section-footer">
                <button class="add-charger-btn" ?disabled=${this._chargerBusy} @click=${() => this._addCharger()}>
                    <ha-icon icon="mdi:plus" style="--mdc-icon-size:16px"></ha-icon>
                    ${this._t('config_ev_add_charger')}
                </button>
            </div>
        `;
    }

    _chargerFriendlyName(cid) {
        const name = this._hass?.states[`number.sem_charger_${cid}_minimum_current`]?.attributes?.friendly_name || cid;
        return name.replace(/\s+Min Amps$/i, '');
    }

    // Colorful accent slider + value chip + fine −/+ buttons (#528 — the
    // battery-card design language restored to the config controls). Live
    // tunable: drag → _setNumber, no entry reload. Themed via
    // ``var(--section-accent)`` so each section keeps its colour.
    _renderZoneKnob(entityId, labelKey, T, helpKey) {
        const e = this._hass?.states[entityId];
        if (!e) return nothing;
        const val = parseFloat(e.state) || 0;
        const _mn = parseFloat(e.attributes.min);
        const _mx = parseFloat(e.attributes.max);
        const min = Number.isNaN(_mn) ? 0 : _mn;
        const max = Number.isNaN(_mx) ? 100 : _mx;
        const step = parseFloat(e.attributes.step) || 1;
        const unit = e.attributes.unit_of_measurement || '';
        const decimals = step < 1 ? 1 : 0;
        const pct = max > min ? Math.round(((val - min) / (max - min)) * 100) : 0;
        return html`
            <div class="zone-knob">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(labelKey)}</span>
                    <span class="zone-chip">${val.toFixed(decimals)}${unit ? ' ' + unit : ''}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${() => this._stepNumber(entityId, -1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${min} max=${max} step=${step} .value=${String(val)}
                        style=${`--fill:${pct}%`}
                        @change=${(ev) => this._setNumber(entityId, parseFloat(ev.target.value))} />
                    <button class="zone-mini" @click=${() => this._stepNumber(entityId, 1)}>+</button>
                </div>
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // SOC-zone strip — visualises the three thresholds on a 0–100 % bar so
    // the priority/buffer/auto-start relationship is obvious at a glance
    // (the "very nice and colorful" battery viz, #528).
    _renderSocZoneStrip(T) {
        const p = this._num('number.sem_battery_priority_soc');
        const b = this._num('number.sem_battery_buffer_soc');
        const a = this._num('number.sem_battery_auto_start_soc');
        if (p == null || b == null || a == null) return nothing;
        const soc = this._num('sensor.sem_battery_soc');
        const clamp = (x) => Math.max(0, Math.min(100, x));
        return html`
            <div class="soc-strip">
                <div class="soc-bar">
                    <div class="soc-zone" style=${`width:${clamp(p)}%;background:#e57373`}></div>
                    <div class="soc-zone" style=${`width:${clamp(b - p)}%;background:#ffb74d`}></div>
                    <div class="soc-zone" style=${`width:${clamp(a - b)}%;background:#81c784`}></div>
                    <div class="soc-zone" style=${`width:${clamp(100 - a)}%;background:#64b5f6`}></div>
                    ${soc != null ? html`<div class="soc-now" style=${`left:${clamp(soc)}%`} title="SOC ${soc}%"></div>` : nothing}
                    <div class="soc-tick" style=${`left:${clamp(p)}%`}><span>${p}</span></div>
                    <div class="soc-tick" style=${`left:${clamp(b)}%`}><span>${b}</span></div>
                    <div class="soc-tick" style=${`left:${clamp(a)}%`}><span>${a}</span></div>
                </div>
                <div class="soc-legend">
                    <span><i style="background:#e57373"></i>${this._t('zone_legend_reserve')}</span>
                    <span><i style="background:#ffb74d"></i>${this._t('zone_legend_buffer')}</span>
                    <span><i style="background:#81c784"></i>${this._t('zone_legend_assist')}</span>
                    <span><i style="background:#64b5f6"></i>${this._t('zone_legend_surplus')}</span>
                </div>
            </div>
        `;
    }

    _renderBatteryZones(T) {
        const opts = this._options || {};
        return html`
            ${this._renderSocZoneStrip(T)}
            ${this._renderZoneKnob('number.sem_battery_priority_soc', 'priority_soc', T, 'zone_help_priority')}
            ${this._renderZoneKnob('number.sem_battery_buffer_soc', 'buffer_soc', T, 'zone_help_buffer')}
            ${this._renderZoneKnob('number.sem_battery_auto_start_soc', 'auto_start_soc', T, 'zone_help_autostart')}
            ${this._renderZoneKnob('number.sem_battery_assist_min_surplus', 'assist_min_surplus', T, 'zone_help_assist_min_surplus')}
            ${this._renderZoneKnob('number.sem_battery_assist_max_power', 'assist_max_power', T, 'zone_help_assist_max_power')}
            ${/* #528 — battery discharge-protection settings, migrated from the
                  options flow (async_step_settings). */ ''}
            <div class="readonly-row" style="margin-top:6px;border-top:1px solid ${T.surfaceBorder};padding-top:8px">
                <span class="ctrl-label" style="font-weight:600">${this._t('config_batt_protection')}</span>
            </div>
            ${this._renderOptionToggle('battery_discharge_protection_enabled', 'config_batt_protection',
                opts, 'config_help_batt_protection', true)}
            ${this._renderZoneKnob('number.sem_battery_max_discharge_power', 'battery_max_discharge_power', T, 'config_help_batt_max_discharge')}
            ${this._renderPicker('battery_discharge_control_entity', 'config_batt_discharge_entity',
                'number', null, opts, 'config_help_batt_discharge_entity')}
        `;
    }

    _renderTariff(T) {
        const opts = this._options || {};
        const rateEntity = this._hass?.states['sensor.sem_tariff_current_import_rate'];
        const rate = rateEntity ? rateEntity.state : '—';
        const unit = rateEntity?.attributes?.unit_of_measurement || '';
        const currency = this._hass?.config?.currency || 'EUR';
        const tariffModeOptions = [
            { value: 'static', label: this._t('config_tariff_mode_static') },
            { value: 'dynamic', label: this._t('config_tariff_mode_dynamic') },
            { value: 'calendar', label: this._t('config_tariff_mode_calendar') },
        ];
        const classModeOptions = [
            { value: 'percentile', label: this._t('config_tariff_class_percentile') },
            { value: 'static', label: this._t('config_tariff_class_static') },
        ];
        const mode = opts.tariff_mode || 'static';
        return html`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t('current_electricity_price')}</span>
                <span class="readonly-value tariff-rate-value">${rate} ${unit}</span>
            </div>
            ${this._renderOptionSelect('tariff_mode', 'config_tariff_mode',
                tariffModeOptions, opts, 'config_help_tariff_mode', 'static')}
            ${mode === 'dynamic' ? html`
                ${this._renderPicker('dynamic_tariff_entity', 'config_dynamic_tariff_entity',
                    'sensor', null, opts, 'config_help_dynamic_tariff_entity')}
                ${this._renderPicker('dynamic_forecast_entity', 'config_dynamic_forecast_entity',
                    'sensor', null, opts, 'config_help_dynamic_forecast_entity')}
                ${this._renderPicker('dynamic_feedin_entity', 'config_dynamic_feedin_entity',
                    'sensor', null, opts, 'config_help_dynamic_feedin_entity')}
                ${this._renderOptionSelect('tariff_classification_mode', 'config_tariff_class_mode',
                    classModeOptions, opts, 'config_help_tariff_class_mode', 'percentile')}
            ` : nothing}
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_cheap_price_threshold', 'cheap_threshold', T, 'setting_help_cheap_threshold')}
                ${this._renderStepper('number.sem_expensive_price_threshold', 'expensive_threshold', T, 'setting_help_expensive_threshold')}
            </div>
            ${/* #549: currency-agnostic max (covers high-denomination currencies
                  like LKR/IDR/VND); fine step keeps decimal currencies exact. */ ''}
            ${this._renderOptionNumberInput('electricity_import_rate', 'config_import_rate',
                { min: 0, max: 10000, step: 0.001, unit: `${currency}/kWh`, default: 0.3387 }, opts, 'config_help_import_rate')}
            ${this._renderOptionNumberInput('electricity_off_peak_rate', 'config_off_peak_rate',
                { min: 0, max: 10000, step: 0.001, unit: `${currency}/kWh`, default: 0.3387 }, opts, 'config_help_off_peak_rate')}
            ${this._renderOptionNumberInput('electricity_export_rate', 'config_export_rate',
                { min: 0, max: 10000, step: 0.001, unit: `${currency}/kWh`, default: 0.075 }, opts, 'config_help_export_rate')}
            ${this._renderOptionNumberInput('demand_charge_rate', 'config_demand_charge_rate',
                { min: 0, max: 100000, step: 0.01, unit: `${currency}/kW/Mt`, default: 4.32 }, opts, 'config_help_demand_charge_rate')}
            ${this._renderPicker('grid_import_power_entity', 'config_grid_import_entity',
                'sensor', 'power', opts, 'config_help_grid_import_entity')}
            ${this._renderPicker('grid_export_power_entity', 'config_grid_export_entity',
                'sensor', 'power', opts, 'config_help_grid_export_entity')}
            ${this._hasBattery() ? html`
                <div class="readonly-row" style="margin-top:6px;border-top:1px solid ${T.surfaceBorder};padding-top:8px">
                    <span class="ctrl-label" style="font-weight:600">${this._t('config_battery_control')}</span>
                </div>
                ${(() => {
                    // #523 battery control entities — needed for force_charge /
                    // per-battery modes AND arbitrage, so they live here (not
                    // gated behind the arbitrage toggle). Multi-battery installs
                    // get one picker per battery; single-battery keeps the
                    // global picker.
                    const n = this._batteryCount();
                    if (n > 1) {
                        return html`${Array.from({ length: n }, (_, i) => html`
                            ${this._renderBatteryDischargePicker(i, n, opts)}
                            ${this._renderBatteryStrategyPicker(i, n, opts)}`)}`;
                    }
                    return html`
                        ${this._renderPicker('battery_force_discharge_control_entity',
                            'config_force_discharge_entity', 'number', null, opts,
                            'config_help_force_discharge_entity')}
                        ${this._renderPicker('battery_strategy_control_entity',
                            'config_strategy_entity', 'select', null, opts,
                            'config_help_strategy_entity')}`;
                })()}
                ${this._renderOptionToggle('battery_setpoint_bidirectional',
                    'config_battery_bidirectional', opts,
                    'config_help_battery_bidirectional', false)}
            ` : nothing}
            ${''/* Battery→grid arbitrage UI is deactivated for the stable
               release (drained a real battery to its reserve floor when a
               restart stranded an in-flight discharge — see #532). The toggle
               is forced off on upgrade and its config section is hidden so the
               selling path can't be enabled from the dashboard. The decision
               code + per-battery modes stay intact; arbitrage ships again in a
               later release once it has soaked. */}
        `;
    }

    _renderHeatPump(T) {
        const registered = this._bin('heat_pump_registered');
        const opts = this._options || {};
        // Live-status block — only when SEM has the heat pump registered
        const statusBlock = registered ? html`
            <div class="hp-status">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('heat_pump_mode')}</span>
                    <span class="readonly-value">${this._val('heat_pump_mode') || '—'}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('heat_pump_sg_ready_state')}</span>
                    <span class="readonly-value">${this._val('heat_pump_sg_ready_state') || '—'}</span>
                </div>
            </div>
        ` : html`
            <div class="setup-intro">
                ${this._t('config_heat_pump_intro')}
            </div>
        `;
        return html`
            ${statusBlock}
            <div class="hp-form">
                ${this._renderPicker('heat_pump_relay1_entity', 'config_hp_relay1', 'switch',
                    null, opts, 'config_help_hp_relay')}
                ${this._renderPicker('heat_pump_relay2_entity', 'config_hp_relay2', 'switch',
                    null, opts, 'config_help_hp_relay')}
                ${this._renderPicker('heat_pump_climate_entity', 'config_hp_climate', 'climate',
                    null, opts, 'config_help_hp_climate')}
                ${this._renderPicker('heat_pump_power_sensor', 'config_hp_power_sensor', 'sensor',
                    'power', opts, 'config_help_hp_power_sensor')}
                ${registered
                    ? this._renderStepper('number.sem_heat_pump_boost_offset', 'heat_pump_boost_offset', T, 'config_help_hp_boost_offset')
                    : this._renderOptionSlider('heat_pump_boost_offset', 'heat_pump_boost_offset',
                        { min: 0, max: 10, step: 0.5, unit: '°C', default: 2.0 }, opts, 'config_help_hp_boost_offset')}
                ${this._renderOptionSlider('heat_pump_max_setpoint', 'config_hp_max_setpoint',
                    { min: 30, max: 80, step: 1, unit: '°C', default: 55 }, opts, 'config_help_hp_max_setpoint')}
                ${this._renderOptionSlider('heat_pump_priority', 'config_hp_priority',
                    { min: 1, max: 10, step: 1, unit: '', default: 4 }, opts, 'config_help_hp_priority')}
            </div>
        `;
    }

    _renderHotWater(T) {
        // v1.7.2-beta.7 (#454 Phase 2-4): live-status block when the
        // HotWaterController is registered with the SurplusController.
        // Pre-wire-up this was config-only; now surfaces the runtime
        // telemetry SEM sees on every cycle (current temp, Legionella
        // status, the #420 decision-path attributes).
        const opts = this._options || {};
        const registered = this._bin('hot_water_registered');
        const currentTemp = this._val('hot_water_current_temperature');
        const solarTarget = this._val('hot_water_solar_target');
        const legHours = this._val('hot_water_hours_since_legionella');
        const legActive = this._bin('hot_water_legionella_cycle_active');
        const tempReadingPath = this._val('hot_water_temperature_reading_path');
        const tempSafetyPath = this._val('hot_water_temperature_safety_path');
        const activationPath = this._val('hot_water_activation_path');

        const statusBlock = registered ? html`
            <div class="hp-status">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('hot_water_current_temperature')}</span>
                    <span class="readonly-value">${currentTemp ? `${parseFloat(currentTemp).toFixed(1)} °C` : '—'}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('hot_water_solar_target')}</span>
                    <span class="readonly-value">${solarTarget ? `${parseFloat(solarTarget).toFixed(0)} °C` : '—'}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('hot_water_hours_since_legionella')}</span>
                    <span class="readonly-value">${
                        legActive ? this._t('hot_water_legionella_cycle_running')
                        : (legHours && parseFloat(legHours) < 999)
                            ? `${parseFloat(legHours).toFixed(0)} h`
                            : this._t('hot_water_legionella_never_run')
                    }</span>
                </div>
                ${tempReadingPath ? html`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t('hot_water_temperature_reading_path')}</span>
                        <span class="readonly-value">${tempReadingPath}</span>
                    </div>
                ` : nothing}
                ${tempSafetyPath && tempSafetyPath !== 'uninitialized' ? html`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t('hot_water_temperature_safety_path')}</span>
                        <span class="readonly-value">${tempSafetyPath}</span>
                    </div>
                ` : nothing}
                ${activationPath && activationPath !== 'uninitialized' ? html`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t('hot_water_activation_path')}</span>
                        <span class="readonly-value">${activationPath}</span>
                    </div>
                ` : nothing}
            </div>
        ` : html`
            <div class="setup-intro">
                ${this._t('config_hot_water_intro')}
            </div>
        `;

        return html`
            ${statusBlock}
            <div class="hp-form">
                ${this._renderPicker('hot_water_entity', 'config_hw_entity',
                    null, null, opts, 'config_help_hw_entity')}
                ${this._renderPicker('hot_water_temperature_sensor', 'config_hw_temp_sensor',
                    'sensor', 'temperature', opts, 'config_help_hw_temp_sensor')}
                ${this._renderPicker('hot_water_power_sensor', 'config_hw_power_sensor',
                    'sensor', 'power', opts, 'config_help_hw_power_sensor')}
                ${this._renderStepper('number.sem_hot_water_solar_target', 'hot_water_solar_target',
                    T, 'config_help_hw_solar_target')}
                ${this._renderStepper('number.sem_hot_water_max_temperature', 'hot_water_max_temperature',
                    T, 'config_help_hw_max_temperature')}
                ${this._renderOptionSlider('hot_water_legionella_target', 'config_hw_legionella_target',
                    { min: 55, max: 80, step: 1, unit: '°C', default: 65 }, opts, 'config_help_hw_legionella_target')}
                ${this._renderOptionSlider('hot_water_minimum_temperature', 'config_hw_min_temperature',
                    { min: 30, max: 55, step: 1, unit: '°C', default: 40 }, opts, 'config_help_hw_min_temperature')}
                ${this._renderOptionSlider('hot_water_priority', 'config_hw_priority',
                    { min: 1, max: 10, step: 1, unit: '', default: 5 }, opts, 'config_help_hw_priority')}
            </div>
        `;
    }

    // Single write path for nested per-charger fields (#485 K3 — the
    // clone/materialize/inject-id/save closure was duplicated per
    // renderer; the id-injection guard below is what keeps ghost
    // chargers out of the backend smart-merge, so it must not rely on
    // every future nested editor remembering to copy it).
    async _saveChargerField(chargerIndex, cid, key, value, statusKey, opts) {
        const newChargers = (opts.ev_chargers || []).map(c => ({ ...c }));
        if (!newChargers[chargerIndex]) newChargers[chargerIndex] = {};
        // Always carry the charger id — the backend smart-merge targets
        // by id and drops id-less entries (would otherwise become a
        // ghost charger colliding with a real sibling, #462/#464).
        if (!newChargers[chargerIndex].id && cid) newChargers[chargerIndex].id = cid;
        newChargers[chargerIndex][key] = value;
        await this._saveOption('ev_chargers', newChargers, statusKey);
    }

    // #528 Phase 4 — add a charger from the dashboard. Sends ONLY the new
    // skeleton; the backend smart-merge (#464) appends it by id and preserves
    // siblings. The new charger appears as a block to wire via the per-charger
    // pickers (it's inert until a power sensor + control entity are set).
    async _addCharger() {
        if (this._chargerBusy) return;
        const existing = (this._options.ev_chargers || []);
        const ids = new Set(existing.map(c => c && c.id).filter(Boolean));
        let id = 'ev_charger', n = 1;
        while (ids.has(id)) { id = `ev_charger_${n++}`; }
        const charger = {
            id,
            name: `${this._t('config_ev_new_charger')} ${existing.length + 1}`,
            ev_min_current: 6,
            max_charging_current: 32,
            ev_surplus_priority: existing.length + 3,
        };
        this._chargerBusy = true;
        this.requestUpdate();
        try {
            await this._saveOption('ev_chargers', [charger], 'ev_chargers_add');
        } finally {
            this._chargerBusy = false;
            this.requestUpdate();
        }
    }

    async _removeCharger(cid) {
        if (this._chargerBusy || !cid) return;
        this._chargerBusy = true;
        this._pendingRemove = '';
        this.requestUpdate();
        try {
            await this._hass.callService('solar_energy_management', 'remove_charger',
                { charger_id: cid });
        } catch (err) {
            console.error('[sem-config-card] remove_charger failed', err);
        } finally {
            this._chargerBusy = false;
            this.requestUpdate();
        }
    }

    // EV target-type select bound to ev_chargers[index].ev_target_type.
    // The SOC option is disabled (#446 GUI gate) when this charger has
    // no ``vehicle_soc_entity`` configured — preventing the saved-bad-state
    // class of bug that idled PROD 2026-06-06. The runtime trusts the
    // saved config; the GUI is the only gatekeeper.
    _renderTargetTypeSelectNested(chargerIndex, cid, charger, opts) {
        const cur = charger.ev_target_type || 'kwh';
        const hasSensor = !!charger.vehicle_soc_entity;
        const statusKey = `ev_chargers.${chargerIndex}.ev_target_type`;
        const status = this._saveStatus[statusKey];
        const onChange = (e) => this._saveChargerField(
            chargerIndex, cid, 'ev_target_type', e.target.value, statusKey, opts,
        );
        return html`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t('config_ev_target_type')}</span>
                    <select class="sem-select" .value=${cur} @change=${onChange}>
                        <option value="kwh" ?selected=${cur !== 'soc'}>
                            ${this._t('config_ev_target_type_kwh')}
                        </option>
                        <option value="soc" ?disabled=${!hasSensor}
                                            ?selected=${cur === 'soc'}>
                            ${this._t('config_ev_target_type_soc')}${hasSensor ? '' : ' — ' + this._t('config_ev_target_type_requires_sensor')}
                        </option>
                    </select>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓</div>` : nothing}
                ${this._showHelp ? html`<div class="setting-help-text">${this._t('config_help_ev_target_type')}</div>` : nothing}
            </div>
        `;
    }

    // Entity picker bound to ev_chargers[index][key] — writes the nested
    // list shape back via config_entries/update.
    _renderPickerNested(chargerIndex, cid, chargerKey, labelKey, domain, deviceClass, opts, helpKey) {
        const chargers = opts.ev_chargers || [];
        const cur = chargers[chargerIndex]?.[chargerKey] || '';
        const statusKey = `ev_chargers.${chargerIndex}.${chargerKey}`;
        const status = this._saveStatus[statusKey];
        const onChange = (val) => this._saveChargerField(
            chargerIndex, cid, chargerKey, val, statusKey, opts,
        );
        return html`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(labelKey)}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${cur}
                        .includeDomains=${[domain]}
                        .includeDeviceClasses=${deviceClass ? [deviceClass] : undefined}
                        .allowCustomEntity=${false}
                        @value-changed=${(e) => onChange(e.detail?.value || '')}>
                    </ha-entity-picker>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓ ${this._t('config_saved')}</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // Number of batteries SEM senses (multi-battery installs expose
    // ``sensor.sem_battery_b<N>_power``). Drives per-battery control rows.
    _batteryCount() {
        if (!this._hass) return 0;
        const s = new Set();
        for (const e of Object.keys(this._hass.states)) {
            const m = e.match(/^sensor\.sem_battery_(b\d+)_power$/);
            if (m) s.add(m[1]);
        }
        return s.size;
    }

    // Has a battery at all (single OR multi). ``_batteryCount`` is 0 on a
    // single-battery install (no per-battery sensors), so gate the battery-
    // control section on the single-battery SOC/power sensor too — otherwise
    // single-battery users (Sessy combined, etc.) couldn't reach the
    // force-discharge / strategy / bidirectional config (#523).
    _hasBattery() {
        if (!this._hass) return false;
        if (this._batteryCount() > 0) return true;
        return (
            'sensor.sem_battery_soc' in this._hass.states ||
            'sensor.sem_battery_power' in this._hass.states
        );
    }

    // Per-battery power-strategy select picker (#523). Writes
    // ``battery_strategy_entities[idx]`` — the select.* (Sessy power_strategy)
    // SEM switches to the API value while it drives the setpoint.
    _renderBatteryStrategyPicker(idx, count, opts) {
        const listKey = 'battery_strategy_entities';
        const lst = Array.isArray(opts[listKey]) ? opts[listKey] : [];
        const cur = lst[idx] || '';
        const fieldKey = `${listKey}.${idx}`;
        const status = this._saveStatus[fieldKey];
        return html`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t('config_strategy_entity')} — B${idx + 1}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${cur}
                        .includeDomains=${['select', 'input_select']}
                        .allowCustomEntity=${false}
                        @value-changed=${(e) => this._saveListField(listKey, idx, e.detail?.value || '', count)}>
                    </ha-entity-picker>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓ ${this._t('config_saved')}</div>` : nothing}
            </div>
        `;
    }

    // Write one entry of an idx-aligned list option (#523 per-battery
    // control entities), padding to ``count`` so a sibling is never dropped.
    async _saveListField(listKey, idx, value, count) {
        const cur = Array.isArray(this._options[listKey])
            ? [...this._options[listKey]] : [];
        while (cur.length < count) cur.push(null);
        cur[idx] = value || null;
        await this._saveOption(listKey, cur, `${listKey}.${idx}`);
    }

    // Per-battery force-discharge control-entity picker (#523). Writes
    // ``battery_force_discharge_entities[idx]`` so each battery can be sold
    // to grid independently (number.* hardware setpoint or input_number.*).
    _renderBatteryDischargePicker(idx, count, opts) {
        const listKey = 'battery_force_discharge_entities';
        const lst = Array.isArray(opts[listKey]) ? opts[listKey] : [];
        const cur = lst[idx] || '';
        const fieldKey = `${listKey}.${idx}`;
        const status = this._saveStatus[fieldKey];
        return html`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t('config_force_discharge_entity')} — B${idx + 1}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${cur}
                        .includeDomains=${['number', 'input_number']}
                        .allowCustomEntity=${false}
                        @value-changed=${(e) => this._saveListField(listKey, idx, e.detail?.value || '', count)}>
                    </ha-entity-picker>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓ ${this._t('config_saved')}</div>` : nothing}
            </div>
        `;
    }

    // Entity picker bound to an entry.options key. Auto-saves via WebSocket
    // on change → SEM update_listener reloads → registered=on within ~1s.
    _renderPicker(optionKey, labelKey, domain, deviceClass, opts, helpKey) {
        const status = this._saveStatus[optionKey];
        // #528: structural (entity-wiring) keys reload the entry — stage the
        // edit locally and commit on Apply so the reload fires once for the
        // whole batch. Non-structural keys save live on change (unchanged).
        const structural = STRUCTURAL_KEYS.has(optionKey);
        const staged = structural && Object.prototype.hasOwnProperty.call(this._pending, optionKey);
        const cur = staged ? this._pending[optionKey] : (opts[optionKey] || '');
        const onChange = (val) => {
            if (structural) {
                this._pending = { ...this._pending, [optionKey]: val || '' };
                this.requestUpdate();
            } else {
                this._saveOption(optionKey, val, optionKey);
            }
        };
        return html`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(labelKey)}${staged ? html`<span class="pending-dot" title="${this._t('config_pending_hint')}">●</span>` : nothing}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${cur}
                        .includeDomains=${[domain]}
                        .includeDeviceClasses=${deviceClass ? [deviceClass] : undefined}
                        .allowCustomEntity=${false}
                        @value-changed=${(e) => onChange(e.detail?.value || '')}>
                    </ha-entity-picker>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓ ${this._t('config_saved')}</div>` : nothing}
                ${status && status !== 'saving' && status !== 'ok' ? html`<div class="save-status err">⚠ ${status}</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // #528 — commit all staged structural edits in ONE set_option call (one
    // entry reload for the whole batch) and clear the buffer.
    async _applyPending() {
        const keys = Object.keys(this._pending);
        if (!keys.length || this._applying) return;
        const entryId = await this._ensureEntryId();
        this._applying = true;
        // Clear any prior apply error before retrying.
        const ss = { ...this._saveStatus }; delete ss._apply; this._saveStatus = ss;
        this.requestUpdate();
        try {
            const options = { ...this._pending };
            await this._hass.callService('solar_energy_management', 'set_option', {
                options, ...(entryId ? { entry_id: entryId } : {}),
            });
            // Reflect locally; the entry reload will re-publish authoritative state.
            this._options = { ...this._options, ...options };
            this._pending = {};
        } catch (err) {
            console.error('[sem-config-card] apply failed', err);
            this._saveStatus = { ...this._saveStatus, _apply: err?.message || 'apply failed' };
        } finally {
            this._applying = false;
            this.requestUpdate();
        }
    }

    _discardPending() {
        this._pending = {};
        this.requestUpdate();
    }

    // Sticky bar shown whenever structural edits are staged.
    _renderApplyBar() {
        const n = Object.keys(this._pending).length;
        if (!n && !this._applying) return nothing;
        const err = this._saveStatus._apply;
        return html`
            <div class="apply-bar ${err ? 'apply-err' : ''}">
                <span class="apply-msg">
                    ${this._applying
                        ? html`<span class="apply-spin"></span>${this._t('config_applying')}`
                        : (err
                            ? html`⚠ ${err}`
                            : this._t('config_pending_changes').replace(/\{n\}/g, String(n)))}
                </span>
                ${this._applying ? nothing : html`
                    <button class="apply-discard" @click=${() => this._discardPending()}>${this._t('config_discard')}</button>
                    <button class="apply-btn" @click=${() => this._applyPending()}>${this._t('config_apply')}</button>
                `}
            </div>
        `;
    }

    // Toggle bound to an entry.options key. Use when no runtime
    // ``switch.sem_*`` entity exists for the option.
    _renderOptionToggle(optionKey, labelKey, opts, helpKey, defaultVal = false) {
        const cur = opts[optionKey] != null ? !!opts[optionKey] : defaultVal;
        const status = this._saveStatus[optionKey];
        return html`
            <div class="stepper-cell">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(labelKey)}</span>
                    <div class="toggle-track ${cur ? 'on' : ''}"
                         @click=${() => this._saveOption(optionKey, !cur, optionKey)}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // Native <select> bound to an entry.options key.
    _renderOptionSelect(optionKey, labelKey, options, opts, helpKey, defaultVal) {
        const cur = opts[optionKey] != null ? opts[optionKey] : defaultVal;
        const status = this._saveStatus[optionKey];
        return html`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(labelKey)}</span>
                    <select class="sem-select"
                            .value=${cur}
                            @change=${(e) => this._saveOption(optionKey, e.target.value, optionKey)}>
                        ${options.map(o => html`
                            <option value="${o.value}" ?selected=${o.value === cur}>${o.label}</option>
                        `)}
                    </select>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // Boolean toggle backed by an entry OPTION (not a switch entity) —
    // saves a real boolean via set_option (#523 arbitrage opt-in).
    _renderOptionToggle(optionKey, labelKey, opts, helpKey, defaultVal) {
        const cur = opts[optionKey] != null ? !!opts[optionKey] : !!defaultVal;
        const status = this._saveStatus[optionKey];
        return html`
            <div class="stepper-cell">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(labelKey)}</span>
                    <div class="toggle-track ${cur ? 'on' : ''}"
                         @click=${() => this._saveOption(optionKey, !cur, optionKey)}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${status === 'ok' ? html`<div class="save-status ok">✓</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // Native <input type="number"> for BOX-mode fields with large ranges
    // (e.g. battery_max_charge_power_w spans 500–25000 W). Steppers would
    // need hundreds of clicks; typing the number is faster. Commits on
    // blur and Enter to avoid one save per keystroke.
    _renderOptionNumberInput(optionKey, labelKey, cfg, opts, helpKey) {
        const cur = opts[optionKey] != null ? opts[optionKey] : cfg.default;
        const status = this._saveStatus[optionKey];
        const commit = (val) => {
            const n = parseFloat(val);
            if (Number.isNaN(n)) return;
            const clamped = Math.max(cfg.min, Math.min(cfg.max, n));
            this._saveOption(optionKey, clamped, optionKey);
        };
        return html`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(labelKey)}</span>
                    <div class="num-input-wrap">
                        <input class="sem-num-input" type="number"
                               .value=${String(cur)}
                               min=${cfg.min} max=${cfg.max} step=${cfg.step}
                               @change=${(e) => commit(e.target.value)}
                               @blur=${(e) => commit(e.target.value)}
                               @keydown=${(e) => { if (e.key === 'Enter') e.target.blur(); }}>
                        ${cfg.unit ? html`<span class="num-unit">${cfg.unit}</span>` : nothing}
                    </div>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    // Slider that writes to entry.options on change. Use for option-only
    // numeric fields that don't have a runtime ``number.sem_*`` entity.
    // #528: option-key slider in the same colorful accent style as the
    // entity knob (saves an entry.option live via _saveOption).
    _renderOptionSlider(optionKey, labelKey, cfg, opts, helpKey) {
        const cur = parseFloat(opts[optionKey] != null ? opts[optionKey] : cfg.default) || 0;
        const status = this._saveStatus[optionKey];
        const decimals = cfg.step < 1 ? 1 : 0;
        const unit = cfg.unit || '';
        const pct = cfg.max > cfg.min ? Math.round(((cur - cfg.min) / (cfg.max - cfg.min)) * 100) : 0;
        const stepBy = (d) => {
            const next = Math.min(cfg.max, Math.max(cfg.min, cur + d * cfg.step));
            this._saveOption(optionKey, next, optionKey);
        };
        return html`
            <div class="zone-knob">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(labelKey)}</span>
                    <span class="zone-chip">${cur.toFixed(decimals)}${unit ? ' ' + unit : ''}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${() => stepBy(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${cfg.min} max=${cfg.max} step=${cfg.step} .value=${String(cur)}
                        style=${`--fill:${pct}%`}
                        @change=${(ev) => this._saveOption(optionKey, parseFloat(ev.target.value), optionKey)} />
                    <button class="zone-mini" @click=${() => stepBy(1)}>+</button>
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

    _renderBatteryScheduler(T) {
        const opts = this._options || {};
        return html`
            <div class="setup-intro">${this._t('config_battery_scheduler_intro')}</div>
            ${this._renderOptionToggle('battery_charge_scheduler_enabled', 'config_bs_enabled',
                opts, 'config_help_bs_enabled', false)}
            ${this._renderOptionNumberInput('battery_capacity_kwh', 'config_bs_capacity',
                { min: 1, max: 100, step: 0.5, unit: 'kWh', default: 10.0 }, opts, 'config_help_bs_capacity')}
            ${this._renderOptionNumberInput('battery_max_charge_power_w', 'config_bs_max_charge',
                { min: 500, max: 25000, step: 100, unit: 'W', default: 5000 }, opts, 'config_help_bs_max_charge')}
            ${this._renderOptionSlider('battery_roundtrip_efficiency', 'config_bs_efficiency',
                { min: 0.70, max: 0.99, step: 0.01, unit: '', default: 0.92 }, opts, 'config_help_bs_efficiency')}
            ${this._renderOptionNumberInput('battery_cycle_cost', 'config_bs_cycle_cost',
                { min: 0, max: 0.5, step: 0.001, unit: 'EUR/kWh', default: 0.02 }, opts, 'config_help_bs_cycle_cost')}
            ${this._renderOptionSlider('battery_precharge_trigger_hour', 'config_bs_trigger_hour',
                { min: 18, max: 23, step: 1, unit: 'h', default: 21 }, opts, 'config_help_bs_trigger_hour')}
            ${this._renderOptionSlider('battery_replan_interval_min', 'config_bs_replan_interval',
                { min: 5, max: 120, step: 5, unit: 'min', default: 30 }, opts, 'config_help_bs_replan_interval')}
            ${this._renderOptionToggle('battery_prefer_consecutive_window', 'config_bs_block_mode',
                opts, 'config_help_bs_block_mode', true)}
            ${this._renderOptionSlider('battery_max_target_soc', 'config_bs_max_target_soc',
                { min: 50, max: 100, step: 5, unit: '%', default: 95.0 }, opts, 'config_help_bs_max_target_soc')}
            ${this._renderOptionNumberInput('battery_min_deficit_kwh', 'config_bs_min_deficit',
                { min: 0.5, max: 10, step: 0.5, unit: 'kWh', default: 2.0 }, opts, 'config_help_bs_min_deficit')}
            ${this._renderOptionSlider('battery_pessimism_weight', 'config_bs_pessimism',
                { min: 0, max: 1, step: 0.1, unit: '', default: 0.3 }, opts, 'config_help_bs_pessimism')}
            ${this._renderOptionToggle('battery_force_charge_negative_price', 'config_bs_force_neg',
                opts, 'config_help_bs_force_neg', true)}
        `;
    }

    _renderLoadManagement(T) {
        const opts = this._options || {};
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('load_management_status')}</span>
                <span class="readonly-value">${this._val('load_management_status') || '—'}</span>
            </div>
            ${this._renderOptionToggle('load_management_enabled', 'config_lm_enabled',
                opts, 'config_help_lm_enabled', true)}
            ${this._renderOptionSlider('target_peak_limit', 'config_lm_target_peak',
                { min: 1.0, max: 15.0, step: 0.5, unit: 'kW', default: 5.0 }, opts, 'config_help_lm_target_peak')}
            ${this._renderOptionSlider('warning_peak_level', 'config_lm_warning_peak',
                { min: 1.0, max: 15.0, step: 0.5, unit: 'kW', default: 4.5 }, opts, 'config_help_lm_warning_peak')}
            ${this._renderOptionSlider('emergency_peak_level', 'config_lm_emergency_peak',
                { min: 1.0, max: 20.0, step: 0.5, unit: 'kW', default: 6.0 }, opts, 'config_help_lm_emergency_peak')}
        `;
    }

    _renderForecast(T) {
        const raw = this._val('forecast_source') || 'none';
        const label = raw === 'none' ? this._t('none') : this._forecastProviderLabel(raw);
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('forecast_source')}</span>
                <span class="readonly-value">${label}</span>
            </div>
            ${raw === 'none' ? html`<div class="overview-help">${this._t('config_forecast_install_hint')}</div>` : nothing}
        `;
    }

    _renderNotifications(T) {
        const opts = this._options || {};
        // Build the notify-service dropdown from hass.services.
        const notifyServices = [{ value: '', label: this._t('config_notif_none') }];
        const services = this._hass?.services || {};
        for (const svcName of Object.keys(services.notify || {})) {
            notifyServices.push({ value: svcName, label: `notify.${svcName}` });
        }
        for (const svcName of Object.keys(services.rest_command || {})) {
            notifyServices.push({ value: svcName, label: `rest_command.${svcName}` });
        }
        return html`
            <div class="setup-intro">${this._t('config_notifications_intro')}</div>
            ${this._renderOptionToggle('enable_charger_notifications', 'config_notif_charger',
                opts, 'config_help_notif_charger', true)}
            ${this._renderOptionToggle('enable_mobile_notifications', 'config_notif_mobile',
                opts, 'config_help_notif_mobile', false)}
            ${this._renderOptionSelect('mobile_notification_service', 'config_notif_service',
                notifyServices, opts, 'config_help_notif_service', '')}
        `;
    }

    _renderAdvanced(T) {
        return html`
            ${this._renderToggle('switch.sem_observer_mode', 'observer_mode', T, 'config_help_observer_mode')}
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_update_interval', 'update_interval', T, 'config_help_update_interval')}
                ${this._renderStepper('number.sem_minimum_solar_power', 'min_solar_power', T, 'config_help_min_solar_power')}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_regulation_offset', 'regulation_offset', T, 'config_help_regulation_offset')}
                ${this._renderStepper('number.sem_ev_enable_delay_seconds', 'ev_enable_delay', T, 'config_help_ev_enable_delay')}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_ev_disable_delay_seconds', 'ev_disable_delay', T, 'config_help_ev_disable_delay')}
            </div>
            ${this._renderGridSignFix(T)}
        `;
    }

    // #461: grid import/export sign — one-tap fix + re-learn. Lives in the
    // Advanced section: most users never need it, but a meter with a
    // swapped/mis-mapped convention shows inverted import/export and the
    // user can correct it here without Developer Tools → Actions.
    _renderGridSignFix(T) {
        const gridSign = this._val('diag_grid_sign') || '—';
        return html`
            <div class="grid-sign-block">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('grid_sign')}</span>
                    <span class="readonly-value">${gridSign}</span>
                </div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._signBusy}
                            @click=${() => this._flipGridSign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t('fix_grid_sign')}
                    </button>
                    <button class="action-btn action-btn-ghost"
                            @click=${() => this._resetSignDetection()}>
                        ${this._t('reset_sign_detection')}
                    </button>
                </div>
                ${this._signMsg
                    ? html`<div class="sign-feedback">${this._signMsg}</div>`
                    : nothing}
                ${this._showHelp
                    ? html`<div class="setting-help-text">${this._t('fix_grid_sign_help')}</div>`
                    : nothing}
            </div>
        `;
    }

    _resetSignDetection() {
        if (!this._hass) return;
        this._hass.callService('solar_energy_management', 'reset_sign_detection', {});
        this._signMsg = this._t('sign_relearn_started');
        this.requestUpdate();
        setTimeout(() => { this._signMsg = ''; this.requestUpdate(); }, 4000);
    }

    async _flipGridSign() {
        if (!this._hass || this._signBusy) return;
        this._signBusy = true;
        this._signMsg = '';
        this.requestUpdate();
        let payload = null;
        try {
            const res = await this._hass.callService(
                'solar_energy_management', 'flip_grid_sign', {},
                undefined, false, true,
            );
            payload = (res && res.response) ? res.response : res;
        } catch (e) {
            payload = null;
        }
        const report = this._buildSignReport(payload);
        let copied = false;
        try {
            await navigator.clipboard.writeText(report);
            copied = true;
        } catch (e) {
            copied = false;
        }
        this._signBusy = false;
        this._signMsg = copied
            ? this._t('sign_flipped_copied')
            : this._t('sign_flipped');
        this.requestUpdate();
        setTimeout(() => { this._signMsg = ''; this.requestUpdate(); }, 6000);
    }

    // Build the markdown support report copied on flip. Plain string
    // concatenation only (no html template) — safe for backticks.
    _buildSignReport(payload) {
        const d = (payload && payload.diagnostics) || {};
        const flip = (payload && typeof payload.user_flip === 'boolean')
            ? String(payload.user_flip) : '?';
        const j = (v) => (v === undefined || v === null) ? '?' : String(v);
        const arr = (v) => (Array.isArray(v) && v.length) ? v.join(', ') : '(none)';
        const bt = String.fromCharCode(96); // backtick, kept out of source
        const code = (s) => bt + s + bt;
        return [
            '### SEM grid-sign report (#461)',
            '',
            'I tapped **Fix grid sign** in the Configuration tab.',
            'grid_sign_user_flip is now ' + code(flip) + '.',
            '',
            '- Meter sensor: ' + code(j(d.grid_power_sensor)) + ' = ' + j(d.grid_power_raw_state) + ' (raw)',
            '- Meter integration: ' + j(d.grid_platform) + ' (brand-seeded: ' + j(d.brand_seeded) + ')',
            '- Auto-detect: detected=' + j(d.auto_detected) + ', inverted=' + j(d.auto_inverted),
            '- Manual grid_sign_invert: ' + j(d.manual_grid_sign_invert),
            '- Counter correlation: confidence=' + j(d.confidence) + ', evidence=' + j(d.evidence) + ', samples=' + j(d.samples),
            '- Solar correlation: confidence=' + j(d.solar_confidence) + ', evidence=' + j(d.solar_evidence) + ', samples=' + j(d.solar_samples),
            '- Seen import=' + j(d.seen_import) + ', export=' + j(d.seen_export),
            '- Import counters: ' + arr(d.import_counters),
            '- Export counters: ' + arr(d.export_counters),
            '',
            'My hardware (please fill in): inverter / grid meter / battery brand.',
            'After the flip, do the Home-tab import vs export arrows now point the right way?',
        ].join('\n');
    }

    // ── Section header ──

    _renderSectionHeader(section, T) {
        const collapsed = this._collapsed[section.id];
        const chevronRotate = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
        const subtitle = section.subtitleFn(this);
        // Map section ids to the diagnose service ``section`` arg. The
        // ``overview`` section dumps EVERYTHING (the maintainer's
        // "general diagnose" payload); other sections get a focused
        // slice. The mapping is 1:1 except overview→all.
        const diagnoseSection = section.id === 'overview' ? 'all' : section.id;
        return html`
            <div class="section-header" @click=${() => this._toggleSection(section.id)}>
                <div class="section-dot" style="background:${section.color}"></div>
                <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                <span class="section-title-text">${this._t(section.titleKey)}</span>
                <span class="section-subtitle" style="color:${subtitle ? section.color : ''}">${subtitle}</span>
                <sem-diagnose-button
                    .hass=${this._hass}
                    section="${diagnoseSection}"
                    label="${this._t('config_diagnose')}"
                    @click=${(e) => e.stopPropagation()}>
                </sem-diagnose-button>
                <ha-icon class="chevron" icon="mdi:chevron-down"
                         style="--mdc-icon-size:18px;transform:${chevronRotate}"></ha-icon>
            </div>
        `;
    }

    _renderSection(section, contentFn, T) {
        const collapsed = this._collapsed[section.id];
        return html`
            <div class="section ${collapsed ? '' : 'expanded'}"
                 style="--section-accent: ${section.color}">
                ${this._renderSectionHeader(section, T)}
                <div class="section-content ${collapsed ? '' : 'expanded'}">
                    <div class="section-body">
                        ${contentFn(T)}
                    </div>
                </div>
            </div>
        `;
    }

    render() {
        if (!this._config) return nothing;
        const T = this._theme();
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';

        const renderers = {
            overview: (T) => this._renderOverview(T),
            ev_chargers: (T) => this._renderEvChargers(T),
            battery_zones: (T) => this._renderBatteryZones(T),
            tariff: (T) => this._renderTariff(T),
            heat_pump: (T) => this._renderHeatPump(T),
            hot_water: (T) => this._renderHotWater(T),
            battery_scheduler: (T) => this._renderBatteryScheduler(T),
            load_management: (T) => this._renderLoadManagement(T),
            forecast: (T) => this._renderForecast(T),
            notifications: (T) => this._renderNotifications(T),
            advanced: (T) => this._renderAdvanced(T),
        };

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${semCardSurfaceCSS(T, '#8DC892')};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }
                .card-help-bar {
                    display: flex; justify-content: flex-end;
                    margin: -4px 0 6px;
                }
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${T.textSec});
                    opacity: 0.6;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    padding: 4px;
                    border-radius: 50%;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle.on { color: ${accent}; opacity: 1; }

                /* ── Sections: same surface shape as the battery card's
                       per-battery sections (.battery-section) so the
                       Config tab reads like the Battery tab. ── */
                .section {
                    margin-bottom: 12px;
                    border-radius: 12px;
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1), box-shadow 0.2s;
                    position: relative;
                }
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${T.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'}; }
                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px; cursor: pointer; user-select: none;
                    transition: background 0.15s;
                }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .section-title-text {
                    font-size: 0.95em; font-weight: 600; white-space: nowrap;
                    color: var(--primary-text-color, ${T.text});
                }
                .section-subtitle {
                    flex: 1; font-size: 0.75em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                    color: var(--secondary-text-color, ${T.textSec});
                    text-align: right; white-space: nowrap;
                    overflow: hidden; text-overflow: ellipsis; margin-right: 4px;
                }
                .chevron { transition: transform 0.25s ease; color: var(--secondary-text-color, ${T.textSec}); }
                .section-content {
                    max-height: 0; opacity: 0; overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded { max-height: 2000px; opacity: 1; }
                .section-body { padding: 0 14px 14px; }
                .section-footer { display: flex; justify-content: flex-end; margin-top: 10px; }

                /* Overview chips — same shape as the battery card's
                   daily chips (.chip / .chip-label / .chip-value). */
                .chips { display: flex; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${T.surface});
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${T.surfaceHover}); }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color, ${T.textSec});
                    font-weight: 500; letter-spacing: 0.3px; margin: 3px 0;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-ok { color: #8DC892; }
                .c-warn { color: #ff9800; }
                .overview-help { font-size: 12px; color: var(--secondary-text-color, ${T.textSec}); padding: 4px 0; }
                .overview-actions { display: flex; gap: 8px; margin-top: 10px; }

                .empty-state {
                    display: flex; flex-direction: column; align-items: center;
                    gap: 8px; padding: 16px 8px; text-align: center;
                }
                .empty-title { font-size: 14px; font-weight: 600; color: var(--primary-text-color, ${T.text}); }
                .empty-help {
                    font-size: 12px; color: var(--secondary-text-color, ${T.textSec});
                    max-width: 320px; line-height: 1.4;
                }
                .info-box-text { font-size: 13px; color: var(--secondary-text-color, ${T.textSec}); padding: 6px 0; line-height: 1.4; }

                /* Inline edit primitives (same look as Control card) */
                .ctrl-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${T.text});
                    padding: 6px 10px; font-size: 14px; font-family: inherit;
                    cursor: pointer; min-width: 120px; outline: none;
                }
                .sem-select option { background: ${isDark ? '#1e232d' : '#fff'}; color: ${isDark ? '#e0e0e0' : '#333'}; }
                .stepper-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .stepper-label {
                    font-size: 14px; font-weight: 500; flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px; border-radius: 8px;
                    border: 1px solid ${T.surfaceBorder};
                    background: ${T.surface}; color: var(--primary-text-color, ${T.text});
                    font-size: 16px; font-weight: 600; cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s; user-select: none;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover { background: ${T.surfaceHover}; border-color: ${accent}; }
                .stepper-value {
                    font-size: 14px; font-weight: 600; min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }
                .readonly-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .readonly-row .ctrl-label { font-size: 12px; color: var(--secondary-text-color, ${T.textSec}); font-weight: 500; }
                .readonly-value {
                    font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text});
                }
                /* #461 grid-sign fix block */
                .grid-sign-block { margin-top: 6px; padding-top: 8px; border-top: 1px solid ${T.surfaceBorder}; }
                .grid-sign-block .action-row { display: flex; justify-content: flex-end; gap: 8px; padding: 6px 0 2px; }
                .grid-sign-block .action-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    padding: 7px 14px; border-radius: 9px; cursor: pointer;
                    font-size: 13px; font-weight: 600;
                    color: var(--primary-text-color, ${T.text});
                    background: var(--secondary-background-color, rgba(255,255,255,0.07));
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    transition: background 0.15s;
                }
                .grid-sign-block .action-btn:hover { background: rgba(255,255,255,0.13); }
                .grid-sign-block .action-btn[disabled] { opacity: 0.5; cursor: default; }
                .grid-sign-block .action-btn-ghost {
                    background: transparent; font-weight: 500;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .grid-sign-block .sign-feedback {
                    text-align: right; font-size: 12px; padding: 4px 0 2px;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .tariff-rate-row { gap: 8px; border-bottom: 1px solid ${T.surfaceBorder}; margin-bottom: 8px; padding-bottom: 10px; }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${T.text}; }
                .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .toggle-label { font-size: 14px; font-weight: 500; }
                .toggle-track {
                    position: relative; width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.18)'};
                    cursor: pointer; transition: background 0.2s; flex-shrink: 0;
                }
                .toggle-track.on { background: ${accent}; }
                .toggle-thumb {
                    position: absolute; top: 2px; left: 2px;
                    width: 20px; height: 20px; border-radius: 50%;
                    background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                .stepper-cell { display: flex; flex-direction: column; }

                /* ── #528: colorful zone controls (battery design language) ── */
                .zone-knob { padding: 8px 2px 10px; }
                .zone-knob-top {
                    display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 7px;
                }
                .zone-knob-label { font-size: 14px; font-weight: 600; }
                .zone-chip {
                    background: color-mix(in srgb, var(--section-accent) 18%, transparent);
                    color: var(--section-accent);
                    font-weight: 700; font-size: 0.92em;
                    padding: 2px 11px; border-radius: 11px;
                    border: 1px solid color-mix(in srgb, var(--section-accent) 40%, transparent);
                    min-width: 56px; text-align: center;
                }
                .zone-knob-slider { display: flex; align-items: center; gap: 10px; }
                .zone-mini {
                    width: 28px; height: 28px; flex-shrink: 0;
                    border-radius: 8px; cursor: pointer;
                    border: 1px solid color-mix(in srgb, var(--section-accent) 35%, ${T.surfaceBorder});
                    background: color-mix(in srgb, var(--section-accent) 8%, transparent);
                    color: var(--section-accent);
                    font-size: 18px; line-height: 1; font-weight: 600;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.12s;
                }
                .zone-mini:hover { background: color-mix(in srgb, var(--section-accent) 20%, transparent); }
                .zone-range {
                    -webkit-appearance: none; appearance: none;
                    flex: 1; min-width: 0; height: 6px; border-radius: 3px;
                    cursor: pointer; outline: none;
                    background: linear-gradient(to right,
                        var(--section-accent) 0%, var(--section-accent) var(--fill, 0%),
                        ${isDark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.12)'} var(--fill, 0%),
                        ${isDark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.12)'} 100%);
                }
                .zone-range::-webkit-slider-thumb {
                    -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
                    background: var(--section-accent); border: 2px solid #fff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.45); cursor: pointer;
                }
                .zone-range::-moz-range-thumb {
                    width: 16px; height: 16px; border-radius: 50%;
                    background: var(--section-accent); border: 2px solid #fff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.45); cursor: pointer;
                }

                /* SOC-zone strip */
                .soc-strip { padding: 4px 2px 12px; }
                .soc-bar {
                    position: relative; display: flex;
                    height: 14px; border-radius: 7px; overflow: hidden;
                    margin-bottom: 22px;
                }
                .soc-zone { height: 100%; }
                .soc-now {
                    position: absolute; top: -3px; width: 3px; height: 20px;
                    background: #fff; border-radius: 2px;
                    box-shadow: 0 0 4px rgba(0,0,0,0.6); transform: translateX(-50%);
                }
                .soc-tick {
                    position: absolute; bottom: -20px; transform: translateX(-50%);
                    font-size: 10px; color: var(--secondary-text-color, ${T.textSec});
                }
                .soc-tick::before {
                    content: ''; position: absolute; top: -7px; left: 50%;
                    width: 1px; height: 6px; background: var(--secondary-text-color, ${T.textSec});
                    opacity: 0.5; transform: translateX(-50%);
                }
                .soc-legend {
                    display: flex; flex-wrap: wrap; gap: 4px 14px;
                    font-size: 11px; color: var(--secondary-text-color, ${T.textSec});
                }
                .soc-legend span { display: inline-flex; align-items: center; gap: 5px; }
                .soc-legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }

                /* #528 staged-changes Apply bar (sticky at top of the card) */
                .apply-bar {
                    position: sticky; top: 6px; z-index: 5;
                    display: flex; align-items: center; gap: 10px;
                    margin: 0 0 12px; padding: 9px 12px;
                    border-radius: 10px;
                    background: color-mix(in srgb, ${accent} 16%, ${T.surface});
                    border: 1px solid color-mix(in srgb, ${accent} 45%, ${T.surfaceBorder});
                    box-shadow: 0 2px 10px rgba(0,0,0,0.25);
                }
                .apply-msg { flex: 1; font-size: 12.5px; font-weight: 600;
                    display: inline-flex; align-items: center; gap: 8px; }
                .apply-btn, .apply-discard {
                    border: none; border-radius: 8px; cursor: pointer;
                    font-size: 12.5px; font-weight: 700; padding: 6px 14px;
                }
                .apply-btn { background: ${accent}; color: #fff; }
                .apply-discard {
                    background: transparent; color: var(--secondary-text-color, ${T.textSec});
                    border: 1px solid ${T.surfaceBorder};
                }
                .apply-spin {
                    width: 13px; height: 13px; border-radius: 50%;
                    border: 2px solid color-mix(in srgb, ${accent} 30%, transparent);
                    border-top-color: ${accent}; display: inline-block;
                    animation: applyspin 0.7s linear infinite;
                }
                @keyframes applyspin { to { transform: rotate(360deg); } }
                .apply-bar.apply-err {
                    background: color-mix(in srgb, #e57373 18%, ${T.surface});
                    border-color: color-mix(in srgb, #e57373 55%, ${T.surfaceBorder});
                }
                .apply-bar.apply-err .apply-msg { color: #e57373; }
                .pending-dot { color: ${accent}; font-size: 9px; margin-left: 6px; vertical-align: middle; }

                /* #528 Phase 4 — add/remove charger */
                .add-charger-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    margin-top: 8px; padding: 8px 16px; border-radius: 9px; cursor: pointer;
                    background: color-mix(in srgb, #5BC8D8 16%, transparent);
                    border: 1px dashed color-mix(in srgb, #5BC8D8 55%, ${T.surfaceBorder});
                    color: #5BC8D8; font-size: 13px; font-weight: 700;
                }
                .add-charger-btn:hover { background: color-mix(in srgb, #5BC8D8 28%, transparent); }
                .add-charger-btn[disabled] { opacity: 0.5; cursor: default; }
                .charger-remove-x {
                    border: none; background: transparent; cursor: pointer;
                    color: var(--secondary-text-color, ${T.textSec}); font-size: 14px;
                    padding: 2px 6px; border-radius: 6px; line-height: 1;
                }
                .charger-remove-x:hover { color: #e57373; background: color-mix(in srgb, #e57373 15%, transparent); }
                .charger-remove-confirm {
                    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
                    margin: 4px 0 8px; padding: 8px 10px; border-radius: 8px;
                    background: color-mix(in srgb, #e57373 14%, ${T.surface});
                    border: 1px solid color-mix(in srgb, #e57373 45%, ${T.surfaceBorder});
                    font-size: 12.5px;
                }
                .charger-remove-confirm span { flex: 1; }
                .charger-remove-go {
                    border: none; border-radius: 7px; cursor: pointer; font-weight: 700;
                    padding: 5px 12px; background: #e57373; color: #fff; font-size: 12px;
                }
                .charger-remove-cancel {
                    border: 1px solid ${T.surfaceBorder}; border-radius: 7px; cursor: pointer;
                    padding: 5px 12px; background: transparent;
                    color: var(--secondary-text-color, ${T.textSec}); font-size: 12px;
                }

                /* #528 first-run completeness guide */
                .setup-progress { margin: 2px 2px 12px; }
                .setup-progress-top {
                    display: flex; justify-content: space-between; align-items: baseline;
                    margin-bottom: 6px;
                }
                .setup-progress-label { font-size: 13px; font-weight: 700; }
                .setup-progress-pct { font-size: 12px; color: var(--secondary-text-color, ${T.textSec}); }
                .setup-progress-bar {
                    height: 7px; border-radius: 4px; overflow: hidden;
                    background: ${isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.1)'};
                }
                .setup-progress-fill {
                    height: 100%; border-radius: 4px;
                    background: #ffb74d; transition: width 0.4s cubic-bezier(0.4,0,0.2,1);
                }
                .setup-progress-fill.done { background: #81c784; }
                .chip-todo { cursor: pointer; border-style: dashed !important; }
                .chip-todo:hover { border-color: ${accent} !important; }
                .chip-todo .c-warn { color: ${accent} !important; font-weight: 700; white-space: nowrap; }

                .setting-help-text {
                    font-size: 11px; line-height: 1.35;
                    color: var(--secondary-text-color, ${T.textSec});
                    opacity: 0.75; padding: 2px 4px 6px 0; margin-top: -4px;
                    font-style: italic;
                }

                /* Entity picker + slider cells for option-only fields */
                .picker-cell { display: flex; flex-direction: column; padding: 6px 0; }
                .picker-row { display: flex; align-items: center; gap: 10px; }
                .picker-label {
                    font-size: 14px; font-weight: 500;
                    min-width: 150px; flex-shrink: 0;
                }
                .picker-row ha-entity-picker { flex: 1; min-width: 0; }
                .save-status {
                    font-size: 11px; padding: 2px 0 0 154px;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .save-status.ok { color: #8DC892; }
                .save-status.err { color: var(--error-color, #d33); }

                .setup-intro {
                    font-size: 12px; line-height: 1.45;
                    color: var(--secondary-text-color, ${T.textSec});
                    padding: 6px 0 12px; border-bottom: 1px solid ${T.surfaceBorder};
                    margin-bottom: 8px;
                }
                .hp-status, .hp-form { display: flex; flex-direction: column; }
                .hp-status { margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid ${T.surfaceBorder}; }

                /* number input for box-mode large-range fields */
                .num-input-wrap { display: flex; align-items: center; gap: 6px; }
                .sem-num-input {
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${T.text});
                    padding: 5px 8px; font-size: 14px; font-family: inherit;
                    width: 90px; text-align: right;
                    font-variant-numeric: tabular-nums;
                    outline: none;
                }
                .sem-num-input:focus { border-color: ${accent}; }
                .num-unit {
                    font-size: 12px; color: var(--secondary-text-color, ${T.textSec});
                }

                @media (max-width: 500px) {
                    .picker-row { flex-wrap: wrap; }
                    .picker-label { flex: 1 1 100%; min-width: 0; }
                    .picker-row ha-entity-picker { flex: 1 1 100%; }
                    .save-status { padding-left: 0; }
                }

                .charger-block {
                    border-left: 3px solid ${accent};
                    padding: 6px 0 6px 10px; margin-bottom: 10px;
                }
                .charger-block-title {
                    display: flex; align-items: center; gap: 6px;
                    font-size: 14px; font-weight: 600;
                    margin-bottom: 6px;
                }

                .ha-settings-btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 6px 12px; border-radius: 8px;
                    background: ${T.surface}; border: 1px solid ${T.surfaceBorder};
                    color: var(--primary-text-color, ${T.text});
                    font-size: 13px; cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .ha-settings-btn:hover { background: ${T.surfaceHover}; border-color: ${accent}; }
            </style>
            <ha-card>
                <div class="wrap">
                    <div class="card-help-bar">
                        <ha-icon
                            class="help-toggle ${this._showHelp ? 'on' : ''}"
                            icon="${this._showHelp ? 'mdi:help-circle' : 'mdi:help-circle-outline'}"
                            title="${this._t('zone_help_toggle')}"
                            @click=${() => this._toggleHelp()}
                            style="--mdc-icon-size:18px"
                        ></ha-icon>
                    </div>
                    ${this._renderApplyBar()}
                    ${SECTIONS.map(s => this._renderSection(s, renderers[s.id], T))}
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 12; }
    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-config-card', SEMConfigCard, {
    type: 'custom:sem-config-card',
    name: 'SEM Configuration Card',
    description: 'In-dashboard SEM configuration surface (replaces the Settings → SEM → Configure flow for most users)',
    preview: false,
});
