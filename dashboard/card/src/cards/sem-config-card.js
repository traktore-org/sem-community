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
// (#830) What a new install is shown before it asks for more.
//
// Guido: "if a user is starting with SEM he is overwhelmed with so many
// options and stops using it — it is just too much." The Config tab renders
// about ninety controls; making SEM work needs about eight.
//
// The default view is NAMELESS on purpose. Nobody is labelled a beginner —
// there is simply the configuration, and an "advanced" switch for people who
// want the rest. Advanced hides nothing: everything is one toggle away.
//
// This list is deliberately tiny and is pinned by a shrink-only test. Adding
// to it has to be argued for, because a default view is only useful while it
// stays small — and every individually reasonable addition is exactly how
// ninety happened.
const ESSENTIAL_SECTIONS = new Set([
    'overview',        // what is still missing, and the route to each
    'tariff',          // without a price, every saving SEM reports is zero
    'ev_chargers',     // the main sink on most installs
    'battery_zones',   // the floors that keep the house covered
]);

const ESSENTIAL_CONTROLS = new Set([
    // Tariff: the one decision, then the two numbers or the one entity.
    'tariff_mode',
    'electricity_import_rate',
    'electricity_export_rate',
    'dynamic_tariff_entity',
    // Battery: the safety floor. Everything else in that section is a
    // sensor override that detection normally supplies.
    'battery_discharge_protection_enabled',
]);

const ADV_KEY = 'sem_config_advanced_v1';

const SECTIONS = [
    {
        id: 'overview',
        icon: 'mdi:check-decagram',
        color: '#8DC892',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/README.md',
        titleKey: 'config_section_overview',
        subtitleFn: (c) => c._overviewSubtitle(),
        expanded: true,  // open by default — gives the user a quick status read
    },
    {
        // #628/#696 — one home for the three power-source overrides. SEM
        // derives grid/solar/battery power from HA's Energy Dashboard; these
        // pickers are the escape hatch when a detected sensor is wrong or
        // dead (e.g. inverter CTs dark off-grid → external meter).
        id: 'sensor_sources',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#sensor-source-overrides',
        icon: 'mdi:transmission-tower',
        color: '#488fc2',
        titleKey: 'config_section_sensor_sources',
        subtitleFn: (c) => c._sensorSourcesSubtitle(),
    },
    {
        // (#814 Pillar B) what SEM detected, with evidence — the #803/#802
        // class made visible: mis-detection shows up here as a reviewable
        // list, not downstream as broken behavior.
        id: 'detected_hardware',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SUPPORTED_HARDWARE.md',
        icon: 'mdi:radar',
        color: '#8DC892',
        titleKey: 'config_section_detected_hardware',
        subtitleFn: (c) => c._detectedHardwareSubtitle(),
    },
    {
        id: 'ev_chargers',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/EV_CHARGING_LOGIC.md#the-five-charge-modes',
        icon: 'mdi:ev-station',
        color: '#5BC8D8',
        titleKey: 'config_section_ev_chargers',
        subtitleFn: (c) => c._evChargersSubtitle(),
    },
    {
        id: 'battery_zones',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#6-soc-zone-strategy',
        icon: 'mdi:battery-charging-medium',
        color: '#4db6ac',
        titleKey: 'config_section_battery_zones',
        subtitleFn: (c) => c._batteryZonesSubtitle(),
    },
    {
        id: 'tariff',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#tariff-and-pricing-settings',
        icon: 'mdi:cash-multiple',
        color: '#96CAEE',
        titleKey: 'config_section_tariff',
        subtitleFn: (c) => c._tariffSubtitle(),
    },
    {
        id: 'heat_pump',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#10-heat-pump-and-hot-water',
        icon: 'mdi:heat-pump',
        color: '#4db6ac',
        titleKey: 'config_section_heat_pump',
        subtitleFn: (c) => c._heatPumpSubtitle(),
    },
    {
        id: 'hot_water',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#hot-water-boiler-separate-from-heat-pump',
        icon: 'mdi:water-boiler',
        color: '#5BC8D8',
        titleKey: 'config_section_hot_water',
        subtitleFn: (c) => c._hotWaterSubtitle(),
    },
    {
        id: 'battery_scheduler',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#9-battery-charge-scheduler',
        icon: 'mdi:calendar-clock',
        color: '#f06292',
        titleKey: 'config_section_battery_scheduler',
        subtitleFn: () => '',
    },
    {
        id: 'load_management',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/USER_GUIDE.md#load-management-settings',
        icon: 'mdi:flash-alert',
        color: '#ff9800',
        titleKey: 'config_section_load_management',
        subtitleFn: (c) => c._loadMgmtSubtitle(),
    },
    {
        id: 'forecast',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#forecast-settings',
        icon: 'mdi:weather-partly-cloudy',
        color: '#ff9800',
        titleKey: 'config_section_forecast',
        subtitleFn: (c) => c._forecastSubtitle(),
    },
    {
        // (#566) rename PV strings inline — only rendered when ≥2 strings are
        // detected (see the visibility filter in render()).
        id: 'pv_strings',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/PV_STRINGS.md#what-you-get',
        icon: 'mdi:solar-panel',
        color: '#ff9800',
        titleKey: 'config_section_pv_strings',
        subtitleFn: (c) => c._pvStringsSubtitle(),
    },
    {
        id: 'notifications',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#notification-settings',
        icon: 'mdi:bell-outline',
        color: '#96CAEE',
        titleKey: 'config_section_notifications',
        subtitleFn: () => '',
    },
    {
        id: 'advanced',
        docs: 'https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#advanced-settings',
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
    // #588: battery-sign fix, same section.
    'sensor.sem_diag_battery_sign',
];

// #528 — entity-wiring keys that trigger an entry RELOAD when changed (mirror
// of __init__.py:_SET_OPTION_STRUCTURAL_KEYS). Pickers for these stage their
// edit and commit on one Apply, so the reload fires once for the whole batch.
const STRUCTURAL_KEYS = new Set([
    'battery_soc_sensor',
    // #628/#696 — the three power-SOURCE overrides (Sensor sources section).
    // Read at SensorReader construction (#592/#597) → backend reloads on
    // set_option; staging batches the three into one Apply/reload.
    'grid_power_sensor', 'solar_production_sensor', 'battery_power_sensor',
    'heat_pump_relay1_entity', 'heat_pump_relay2_entity',
    'heat_pump_climate_entity', 'heat_pump_power_sensor',
    'heat_pump_temperature_sensor', 'heat_pump_invert_sg_ready',
    'hot_water_entity', 'hot_water_power_sensor', 'hot_water_temperature_sensor',
    'battery_force_discharge_control_entity', 'battery_strategy_control_entity',
    'battery_discharge_control_entity',  // #528 — discharge-limit (protection) entity
    // #550 — structural TOGGLES: reload the entry too, so they stage + commit on
    // Apply like the pickers (a live flip would reload and discard staged edits).
    'battery_discharge_protection_enabled', 'battery_setpoint_bidirectional',
]);

class SEMConfigCard extends SEMLitBase {
    static get watchedEntities() { return WATCHED; }

    static get properties() {
        return {
            ...super.properties,
            _retentionBusy: { state: true },
            _retentionMsg: { state: true },
            _showHelp: { state: true },
            _advanced: { state: true },
            _lmAdvancedOpen: { state: true },
            _entryId: { state: true },
            _saveStatus: { state: true },
            // #461 grid-sign fix button transient UI state.
            _signBusy: { state: true },
            _signMsg: { state: true },
            // #588 battery-sign fix button transient UI state.
            _battSignBusy: { state: true },
            _battSignMsg: { state: true },
            // #528 staged structural (entity-wiring) edits — committed in one
            // Apply so a reload fires once for the whole batch, not per field.
            _pending: { state: true },
            _applying: { state: true },
            // #528 Phase 4 — per-charger remove confirm (inline, no blocking
            // window.confirm) + add/remove busy flag.
            _pendingRemove: { state: true },
            _chargerBusy: { state: true },
            // #605 — staged TUNABLE edits (numbers/toggles/selects, entity- or
            // option-backed). Nothing writes until the section's Apply, so an
            // accidental scroll-flick on mobile stages a revertable change
            // instead of silently committing one.
            _staged: { state: true },
            _secApplying: { state: true },
            // #606 — per-row help open state (the small info button).
            _helpOpen: { state: true },
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
            load_management: true, forecast: true, pv_strings: true,
            notifications: true, advanced: true,
        };
        this._showHelp = false;
        // (#830) A VIEW preference, so it lives per browser like the
        // onboarding banner's dismissal — not in the config entry, which
        // would make one person's choice everyone's.
        this._advanced = (() => {
            try { return localStorage.getItem(ADV_KEY) === '1'; }
            catch (e) { return false; }
        })();
        this._lmAdvancedOpen = false;  // (#717) warning/emergency ladder disclosure
        this._entryId = '';
        this._saveStatus = {};  // { fieldKey: 'saving' | 'ok' | error-msg }
        this._statusTimers = new Set();  // pending ✓-clear timeouts (#476)
        this._signBusy = false;
        this._signMsg = '';
        this._battSignBusy = false;
        this._battSignMsg = '';
        this._pending = {};   // { structuralKey: stagedValue }
        this._applying = false;
        this._pendingRemove = '';  // charger id awaiting remove-confirm
        this._chargerBusy = false;
        // #605 staging: id → { kind, value }. id is an entity_id for
        // entity-backed controls, or 'opt:' + optionKey for option-backed.
        this._staged = {};
        this._secApplying = '';
        this._helpOpen = {};   // helpKey → bool (#606 per-row info)
        // Which section each control id belongs to — populated during render
        // (the section wrapper sets _sec while its content renders). Plain
        // object, not reactive: it's derived bookkeeping.
        this._secOf = {};
        this._sec = null;
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

    _toggleAdvanced() {
        this._advanced = !this._advanced;
        try { localStorage.setItem(ADV_KEY, this._advanced ? '1' : '0'); }
        catch (e) { /* private window / blocked storage — session only */ }
    }

    /** Should this control appear in the current view? */
    _showsControl(key) {
        if (this._advanced) return true;
        // Entity-backed controls carry their domain; compare on the
        // config key, which is what the tier list is written in.
        const k = String(key || '').replace(/^[a-z_]+\.sem_/, '');
        return ESSENTIAL_CONTROLS.has(k);
    }
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
        // (#830) One choke point for the default view: a control not on
        // the essential list is simply not rendered until advanced is on.
        if (!this._showsControl(entityId)) return nothing;

        return this._renderZoneKnob(entityId, labelKey, T, helpKey);
    }

    _renderToggle(entityId, labelKey, T, helpKey) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        this._reg(entityId);
        const dirty = this._isDirty(entityId);
        const cur = String(this._stagedVal(entityId, entity.state));
        const isOn = cur === 'on';
        return html`
            <div class="stepper-cell ${dirty ? 'dirty' : ''}">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(labelKey)}${dirty ? html`<span class="dirty-dot">●</span>` : nothing}${this._helpBtn(helpKey)}</span>
                    <div class="toggle-track ${isOn ? 'on' : ''}"
                         @click=${() => this._stage(entityId, 'switch', isOn ? 'off' : 'on')}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._helpBlock(helpKey)}
            </div>
        `;
    }

    _renderSelect(entityId, labelKey, T, helpKey) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        this._reg(entityId);
        const dirty = this._isDirty(entityId);
        const cur = String(this._stagedVal(entityId, entity.state));
        const options = entity.attributes.options || [];
        return html`
            <div class="stepper-cell ${dirty ? 'dirty' : ''}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(labelKey)}${dirty ? html`<span class="dirty-dot">●</span>` : nothing}${this._helpBtn(helpKey)}</span>
                    <select class="sem-select" .value=${cur}
                            @change=${(e) => this._stage(entityId, 'select', e.target.value)}>
                        ${options.map(o => html`<option value="${o}" ?selected=${o === cur}>${this._t(o.toLowerCase()) || o}</option>`)}
                    </select>
                </div>
                ${this._helpBlock(helpKey)}
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
            // (#830) The overview stopped at four subsystems while the Config
            // tab has fourteen sections, so "all set up" could read 100% with
            // no tariff configured — SEM cannot cost anything without one, and
            // nothing said so. These three are the ones whose absence changes
            // what SEM can DO, which is the bar for appearing here: a guide is
            // only useful if reaching the end of it means something.
            { key: 'tariff', labelKey: 'config_section_tariff', icon: 'mdi:cash-multiple',
              color: '#8353d1', sectionId: 'tariff',
              done: !!(opts.electricity_rate || opts.tariff_provider
                       || opts.tariff_entity) },
            { key: 'battery', labelKey: 'config_section_battery_zones', icon: 'mdi:battery-charging',
              color: '#4db6ac', sectionId: 'battery_zones',
              done: !!opts.has_battery },
            { key: 'loads', labelKey: 'config_section_load_management', icon: 'mdi:flash-alert',
              color: '#ff9800', sectionId: 'load_management',
              optional: true,
              done: (opts.managed_devices || []).length > 0 },
        ];
    }

    /** Has the user already set this subsystem up?

        Reuses the Setup overview's own done-signals rather than a second list:
        two answers to "is this configured" would drift, and the overview's is
        the one already shown to the user.
     */
    _sectionConfigured(id) {
        const item = this._setupItems().find(i => i.sectionId === id);
        if (item) return !!item.done;
        const opts = this._options || {};
        if (id === 'battery_scheduler') return !!opts.battery_charge_scheduler_enabled;
        if (id === 'notifications') return !!opts.enable_mobile_notifications;
        return false;
    }

    _openSection(id) {
        this._collapsed = { ...this._collapsed, [id]: false };
        this.requestUpdate();
    }

    _renderOverview(T) {
        const items = this._setupItems();
        // (#830) Optional subsystems do not hold the bar down. A user with no
        // controllable loads is not 86% set up — they are finished, and a
        // progress bar that disagrees teaches them to ignore it.
        const counted = items.filter(i => !i.optional);
        const done = counted.filter(i => i.done).length;
        const total = counted.length;
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
                        <div class="chip-value ${i.done ? 'c-ok' : (i.optional ? '' : 'c-warn')}">
                            ${i.done ? '✓'
                                : (i.optional ? this._t('config_setup_optional')
                                              : this._t('config_setup_action'))}
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
                                ?disabled=${this._chargerBusy}
                                @click=${() => { if (!this._chargerBusy) { this._pendingRemove = cid; this.requestUpdate(); } }}>✕</button>`}
                    </div>
                    ${this._pendingRemove === cid ? html`
                        <div class="charger-remove-confirm">
                            <span>${this._t('config_ev_remove_confirm')}</span>
                            <button class="charger-remove-cancel" @click=${() => { this._pendingRemove = ''; this.requestUpdate(); }}>${this._t('config_discard')}</button>
                            <button class="charger-remove-go" @click=${() => this._removeCharger(cid)}>${this._t('config_ev_remove')}</button>
                        </div>` : nothing}
                    ${/* #684: the config FLOW has always accepted a plain status
                          sensor here (``domain=["binary_sensor","sensor"]``) and
                          the reader decodes textual states — "plugged in",
                          "connected", "charging", … — but this picker listed
                          binary_sensor only, so a charger that reports plug
                          state as a text sensor (JuiceBox via JuiceBoxProxy,
                          Easee, OCPP) could not be configured from the card at
                          all. Match the flow. */ ''}
                    ${this._renderPickerNested(idx, cid, 'ev_connected_sensor', 'config_ev_connected_sensor',
                        ['binary_sensor', 'sensor'], null, opts, 'config_help_ev_connected_sensor')}
                    ${this._renderPickerNested(idx, cid, 'ev_charging_power_sensor', 'config_ev_charging_power',
                        'sensor', 'power', opts, 'config_help_ev_charging_power')}
                    ${this._renderPickerNested(idx, cid, 'ev_current_control_entity', 'config_ev_current_control',
                        'number', null, opts, 'config_help_ev_current_control')}
                    ${/* #627: the backend has always honoured a per-charger
                          ``ev_start_stop_entity`` (``__init__.py`` hands it to
                          ``CurrentControlDevice.start_stop_entity``, which
                          dispatches switch.turn_on/off or button.press), and
                          hardware_detection auto-fills it for several brands —
                          but nothing in the UI could WRITE it. A charger whose
                          current entity keeps a live contactor (Smart-EVSE-style)
                          therefore had no way to be told "and open the relay
                          too", so SEM dropped to 0 A and the box kept clicking.
                          Same shape as #684: a key the reader honours with no
                          surface to set it. */ ''}
                    ${this._renderPickerNested(idx, cid, 'ev_start_stop_entity', 'config_ev_start_stop',
                        ['switch', 'button'], null, opts, 'config_help_ev_start_stop')}
                    ${''/* (#804) phase-switch capability: the entity the user
                       NAMES (never inferred) + the 1p/3p values in its own
                       vocabulary. Value fields only show once the entity is
                       set; select entities REQUIRE them, number defaults to
                       1/3 and switch to off/on. */}
                    ${this._renderPickerNested(idx, cid, 'ev_phase_switch_entity', 'config_ev_phase_switch',
                        ['select', 'number', 'switch', 'input_select', 'input_number', 'input_boolean'],
                        null, opts, 'config_help_ev_phase_switch')}
                    ${charger.ev_phase_switch_entity ? html`
                        ${this._renderTextNested(idx, cid, 'ev_phase_switch_value_1p', 'config_ev_phase_1p',
                            opts, 'config_help_ev_phase_values', '1 / off / einphasig')}
                        ${this._renderTextNested(idx, cid, 'ev_phase_switch_value_3p', 'config_ev_phase_3p',
                            opts, 'config_help_ev_phase_values', '3 / on / dreiphasig')}` : nothing}
                    ${this._renderPickerNested(idx, cid, 'vehicle_soc_entity', 'config_ev_vehicle_soc',
                        'sensor', null, opts, 'config_help_ev_vehicle_soc')}
                    ${this._renderTargetTypeSelectNested(idx, cid, charger, opts)}
                    ${''/* The charger's current RANGE (#536 floor, #746
                       ceiling). SEM auto-finds a fussy car's start current
                       (day AND night) and settles back to Min — no Start Amps
                       / Vehicle Min Amps knobs. Max is what the wallbox is
                       rated for (or the supply you want to throttle it to);
                       before #746 it was an invisible 32 A on every install. */}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_minimum_current`, 'min_amps', T, 'tile_help_min_amps')}
                        ${this._renderStepper(`number.sem_charger_${cid}_maximum_current`, 'max_amps', T, 'tile_help_max_amps')}
                    </div>
                    ${/* (#576) The Surplus/Shed priority steppers were removed —
                          drag the charger in the Control-tab device-priority
                          list instead (surplus order = list position, shed =
                          reverse walk). One priority axis, one editor. */ ''}
                    ${/* (config-on-dashboard) the charge TARGET value — the
                          select above only picks kWh vs SOC; these set the
                          actual target + its ceiling (#245 range). */ ''}
                    ${charger.ev_target_type === 'soc' ? html`
                        <div class="stepper-pair">
                            ${this._renderStepper(`number.sem_charger_${cid}_target_soc`, 'config_ev_target_soc', T, 'config_help_ev_target_soc')}
                            ${this._renderStepper(`number.sem_charger_${cid}_target_soc_max`, 'config_ev_target_soc_max', T, 'config_help_ev_target_soc_max')}
                        </div>` : html`
                        <div class="stepper-pair">
                            ${this._renderStepper(`number.sem_charger_${cid}_daily_ev_target`, 'config_ev_daily_target', T, 'config_help_ev_daily_target')}
                            ${this._renderStepper(`number.sem_charger_${cid}_daily_ev_target_max`, 'config_ev_daily_target_max', T, 'config_help_ev_daily_target_max')}
                        </div>`}
                    ${/* Capacity moved down here when Max Amps took its slot
                          (#746) — it belongs with the other car properties
                          anyway, and the current range now reads as a pair. */ ''}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_battery_capacity_kwh`, 'capacity_kwh', T, 'tile_help_capacity')}
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_kwh_per_100km`, 'config_ev_kwh_per_100km', T, 'config_help_ev_kwh_per_100km')}
                    </div>
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_phases`, 'config_ev_phases', T, 'config_help_ev_phases')}
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
        this._reg(entityId);
        const live = parseFloat(e.state) || 0;
        // #605 — render the STAGED value; changes stage, Apply commits.
        const dirty = this._isDirty(entityId);
        const val = Number(this._stagedVal(entityId, live));
        const _mn = parseFloat(e.attributes.min);
        const _mx = parseFloat(e.attributes.max);
        const min = Number.isNaN(_mn) ? 0 : _mn;
        const max = Number.isNaN(_mx) ? 100 : _mx;
        const step = parseFloat(e.attributes.step) || 1;
        const unit = e.attributes.unit_of_measurement || '';
        const decimals = step < 1 ? 1 : 0;
        const pct = max > min ? Math.round(((val - min) / (max - min)) * 100) : 0;
        const stepBy = (dir) => {
            const next = Math.max(min, Math.min(max, val + dir * step));
            this._stage(entityId, 'number', next);
        };
        return html`
            <div class="zone-knob ${dirty ? 'dirty' : ''}">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(labelKey)}${this._helpBtn(helpKey)}</span>
                    <span class="zone-chip">${dirty ? html`<span class="dirty-dot">●</span>` : nothing}${val.toFixed(decimals)}${unit ? ' ' + unit : ''}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${() => stepBy(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${min} max=${max} step=${step} .value=${String(val)}
                        style=${`--fill:${pct}%`}
                        @change=${(ev) => this._stage(entityId, 'number', parseFloat(ev.target.value))} />
                    <button class="zone-mini" @click=${() => stepBy(1)}>+</button>
                </div>
                ${this._helpBlock(helpKey, e.attributes.sem_default, unit, entityId, 'number')}
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

    // #628/#696 — the three power-SOURCE overrides in one place. Each picker
    // shows the override (blank = auto from the Energy Dashboard); an
    // unavailable override gets a loud warning row instead of a silent
    // fallback. battery_power_sensor moved here from Battery & zones,
    // solar_production_sensor from Tariff — one concept, one home.
    _detectionReport() {
        const st = this._hass?.states?.['sensor.sem_diag_charger_control'];
        return st?.attributes?.detection_report || null;
    }

    _detectedHardwareSubtitle() {
        const r = this._detectionReport();
        if (!r) return this._t('config_detect_none');
        const n = (r.chargers || []).length;
        const nm = (r.near_misses || []).length;
        const base = `${n} ${this._t('config_detect_chargers')}`;
        return nm ? `${base} · ${nm} ${this._t('config_detect_near_misses')}` : base;
    }

    // (#814 Pillar B) Detected hardware with evidence. Read-only view of the
    // report the coordinator publishes; corrections happen with the existing
    // pickers in the charger / sensor-source sections.
    _renderDetectedHardware(T) {
        const r = this._detectionReport();
        if (!r) {
            return html`<div class="setting-help-text">${this._t('config_detect_none')}</div>`;
        }
        const chargers = r.chargers || [];
        const misses = r.near_misses || [];
        const prober = r.prober_candidates || [];
        const dis = r.disagreements || [];
        const roleRow = (k, v) => html`
            <div class="row"><span class="lbl">${k}</span>
                <span style="font-family:monospace;font-size:0.85em">${v.entity || v.value || '—'}
                    ${v.device_class ? html`<span style="opacity:.6"> · ${v.domain}/${v.device_class}</span>` : nothing}
                </span></div>`;
        return html`
            <div class="setting-help-text" style="margin:0 0 6px">${this._t('config_detect_intro')}</div>
            ${chargers.map((c) => html`
                <div class="row" style="font-weight:600">
                    <span class="lbl">${this._t('config_detect_charger')}: ${c.platform}</span>
                    <span>${c.control}</span>
                </div>
                ${Object.entries(c.mapped || {}).map(([k, v]) => roleRow(k, v))}
                ${(c.unmapped || []).length ? html`
                    <div class="setting-help-text" style="margin:2px 0 8px">
                        ${this._t('config_detect_unmapped')}: ${(c.unmapped || []).map((u) => u.entity).join(', ')}
                    </div>` : nothing}
            `)}
            ${misses.map((m) => html`
                <div class="row" style="color:${T.warn || '#ffb74d'}">
                    <span class="lbl">⚠ ${m.platform}</span>
                    <span>${this._t('config_detect_near_miss')}</span>
                </div>
                <div class="setting-help-text" style="margin:-2px 0 8px">
                    ${(m.entities || []).map((e) => e.entity).join(', ')}
                </div>`)}
            ${dis.filter((d) => d.kind === 'prober_only').map((d) => html`
                <div class="row"><span class="lbl">🔎 ${d.platform}</span>
                    <span>${this._t('config_detect_prober_only')}</span></div>`)}
            ${(!chargers.length && !misses.length && !prober.length) ? html`
                <div class="setting-help-text">${this._t('config_detect_nothing')}</div>` : nothing}
        `;
    }

    _renderSensorSources(T) {
        const opts = this._options || {};
        return html`
            <div class="setting-help-text" style="margin:0 0 6px">
                ${this._t('config_sources_intro')}</div>
            ${this._renderPicker('grid_power_sensor', 'config_grid_power_sensor',
                'sensor', 'power', opts, 'config_help_grid_power_sensor')}
            ${this._sourceUnavailableWarning('grid_power_sensor', opts, T)}
            ${this._renderPicker('solar_production_sensor', 'config_solar_production_sensor',
                'sensor', 'power', opts, 'config_help_solar_production_sensor')}
            ${this._sourceUnavailableWarning('solar_production_sensor', opts, T)}
            ${this._renderPicker('battery_power_sensor', 'config_battery_power_sensor',
                'sensor', 'power', opts, 'config_help_battery_power_sensor')}
            ${this._sourceUnavailableWarning('battery_power_sensor', opts, T)}
        `;
    }

    // Collapsed-header glance: "all auto" or "N overridden".
    _sensorSourcesSubtitle() {
        const opts = this._options || {};
        const n = ['grid_power_sensor', 'solar_production_sensor',
                   'battery_power_sensor'].filter((k) => opts[k]).length;
        if (!n) return this._t('config_sources_all_auto');
        return `${n} ${this._t('config_sources_overridden')}`;
    }

    // Failure honesty (#696): an override that stops reporting must be SEEN.
    // SEM keeps reading the override (no silent fallback to a sensor the user
    // explicitly replaced), so the card is where the user learns it's dead.
    _sourceUnavailableWarning(key, opts, T) {
        const ent = opts[key];
        if (!ent || !this._hass) return nothing;
        const st = this._hass.states[ent];
        if (st && st.state !== 'unavailable' && st.state !== 'unknown') return nothing;
        return html`<div class="setting-help-text"
            style="color:${T.warn || '#ffb74d'};margin:-2px 0 6px">
            ⚠ ${ent} — ${this._t('config_source_unavailable')}</div>`;
    }

    _renderBatteryZones(T) {
        const opts = this._options || {};
        return html`
            ${this._renderSocZoneStrip(T)}
            ${/* #550 — manual battery-SOC entity override. SEM auto-detects the
                  SOC sensor from the battery-power entity, but some hardware
                  (e.g. Deye + Seplos) isn't matched. This is the escape hatch:
                  no device_class filter so ANY sensor can be picked. Structural
                  → Apply-batched reload. */ ''}
            ${this._renderPicker('battery_soc_sensor', 'config_battery_soc_sensor',
                'sensor', null, opts, 'config_help_battery_soc_sensor')}
            ${/* #592/#597 battery power override → Sensor sources section (#628).
                  #593 — hardware cycle count stays here. */ ''}
            ${this._renderPicker('battery_cycles_sensor', 'config_battery_cycles_sensor',
                'sensor', null, opts, 'config_help_battery_cycles_sensor')}
            ${this._renderZoneKnob('number.sem_battery_priority_soc', 'priority_soc', T, 'zone_help_priority')}
            ${this._renderZoneKnob('number.sem_battery_buffer_soc', 'buffer_soc', T, 'zone_help_buffer')}
            ${this._renderZoneKnob('number.sem_battery_auto_start_soc', 'auto_start_soc', T, 'zone_help_autostart')}
            ${this._renderZoneKnob('number.sem_battery_assist_min_surplus', 'assist_min_surplus', T, 'zone_help_assist_min_surplus')}
            ${this._renderZoneKnob('number.sem_battery_assist_max_power', 'assist_max_power', T, 'zone_help_assist_max_power')}
            ${/* #528 — battery discharge-protection settings, migrated from the
                  options flow (async_step_settings). Visual separator only. */ ''}
            <div style="margin-top:6px;border-top:1px solid ${T.surfaceBorder};padding-top:4px"></div>
            ${this._renderOptionToggle('battery_discharge_protection_enabled', 'config_batt_protection',
                opts, 'config_help_batt_protection', true)}
            ${this._renderZoneKnob('number.sem_battery_max_discharge_power', 'battery_max_discharge_power', T, 'config_help_batt_max_discharge')}
            ${this._renderPicker('battery_discharge_control_entity', 'config_batt_discharge_entity',
                'number', null, opts, 'config_help_batt_discharge_entity')}
        `;
    }

    // (#751) a free-text option row — the four power-strategy VALUES a
    // non-Sessy select needs mapped. Same _saveOption path and status
    // chrome as every other row; Enter or blur saves.
    _renderTextOption(key, labelKey, opts, helpKey, placeholder) {
        const val = opts[key] ?? '';
        const status = this._saveStatus[key];
        return html`
            <div class="row">
                <span class="lbl" title="${helpKey ? this._t(helpKey) : ''}">${this._t(labelKey)}</span>
                <input type="text" class="txt-opt" .value=${String(val)}
                       placeholder="${placeholder || ''}"
                       @keydown=${(e) => { if (e.key === 'Enter') e.target.blur(); }}
                       @blur=${(e) => {
                           const v = e.target.value.trim();
                           if (v !== String(val)) this._saveOption(key, v, key);
                       }} />
                ${status === 'saving' ? html`<span class="sv">…</span>`
                  : status === 'ok' ? html`<span class="sv ok">✓</span>`
                  : status === 'err' ? html`<span class="sv err">!</span>`
                  : nothing}
            </div>
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
            ${/* #592 solar power override → Sensor sources section (#628). */ ''}
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
                            'config_help_strategy_entity')}
                        ${opts['battery_strategy_control_entity'] ? html`
                            ${this._renderTextOption('battery_strategy_active_value',
                                'config_strategy_val_active', opts,
                                'config_help_strategy_values', 'api')}
                            ${this._renderTextOption('battery_strategy_idle_value',
                                'config_strategy_val_idle', opts,
                                'config_help_strategy_values', 'eco')}
                            ${this._renderTextOption('battery_strategy_self_consume_value',
                                'config_strategy_val_selfc', opts,
                                'config_help_strategy_values', 'nom')}
                            ${this._renderTextOption('battery_strategy_off_value',
                                'config_strategy_val_off', opts,
                                'config_help_strategy_values', 'idle')}
                        ` : nothing}`;
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
                ${this._renderPicker('heat_pump_relay1_entity', 'config_hp_relay1', ['switch', 'input_boolean'],
                    null, opts, 'config_help_hp_relay')}
                ${this._renderPicker('heat_pump_relay2_entity', 'config_hp_relay2', ['switch', 'input_boolean'],
                    null, opts, 'config_help_hp_relay')}
                ${/* #550: relay contact polarity — read at HeatPumpController
                      construction (structural). Was only on the native flow. */ ''}
                ${this._renderOptionToggle('heat_pump_invert_sg_ready', 'config_hp_invert_sg_ready',
                    opts, 'config_help_hp_invert_sg_ready', false)}
                ${this._renderPicker('heat_pump_climate_entity', 'config_hp_climate', 'climate',
                    null, opts, 'config_help_hp_climate')}
                ${this._renderPicker('heat_pump_power_sensor', 'config_hp_power_sensor', 'sensor',
                    'power', opts, 'config_help_hp_power_sensor')}
                ${/* #600 — kWh energy counter fallback when there's no power sensor. */ ''}
                ${this._renderPicker('heat_pump_energy_sensor', 'config_hp_energy_sensor', 'sensor',
                    'energy', opts, 'config_help_hp_energy_sensor')}
                ${/* #602 — rated power (W); used when there's no power sensor to
                      calibrate from. Was config-only, now settable here. */ ''}
                ${this._renderOptionNumberInput('heat_pump_rated_power', 'config_hp_rated_power',
                    { min: 100, max: 30000, step: 50, unit: 'W', default: 2000 }, opts, 'config_help_hp_rated_power')}
                ${/* #550: HP temperature sensor override — structural key that had
                      no picker anywhere (unreachable). */ ''}
                ${this._renderPicker('heat_pump_temperature_sensor', 'config_hp_temperature_sensor',
                    'sensor', 'temperature', opts, 'config_help_hp_temperature_sensor')}
                ${/* #594 — external vacation signal (ViCare holiday etc.); OR'd
                      with switch.sem_vacation_mode. Tunable — read per cycle. */ ''}
                ${this._renderPicker('vacation_mode_entity', 'config_vacation_entity',
                    ['binary_sensor', 'input_boolean', 'switch', 'calendar'],
                    null, opts, 'config_help_vacation_entity')}
                ${registered
                    ? this._renderStepper('number.sem_heat_pump_boost_offset', 'heat_pump_boost_offset', T, 'config_help_hp_boost_offset')
                    : this._renderOptionSlider('heat_pump_boost_offset', 'heat_pump_boost_offset',
                        { min: 0, max: 10, step: 0.5, unit: '°C', default: 2.0 }, opts, 'config_help_hp_boost_offset')}
                ${this._renderOptionSlider('heat_pump_max_setpoint', 'config_hp_max_setpoint',
                    { min: 30, max: 80, step: 1, unit: '°C', default: 55 }, opts, 'config_help_hp_max_setpoint')}
                ${/* #602/#576 — heat_pump_priority slider retired: the heat pump
                      is a draggable row in the device-priority list now, so its
                      position IS its priority (single axis, no parallel knob). */ ''}
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
                    ['switch', 'input_boolean', 'water_heater', 'climate'],
                    null, opts, 'config_help_hw_entity')}
                ${this._renderPicker('hot_water_temperature_sensor', 'config_hw_temp_sensor',
                    'sensor', 'temperature', opts, 'config_help_hw_temp_sensor')}
                ${this._renderPicker('hot_water_power_sensor', 'config_hw_power_sensor',
                    'sensor', 'power', opts, 'config_help_hw_power_sensor')}
                ${/* #600 — kWh energy counter fallback when there's no power sensor. */ ''}
                ${this._renderPicker('hot_water_energy_sensor', 'config_hw_energy_sensor',
                    'sensor', 'energy', opts, 'config_help_hw_energy_sensor')}
                ${/* #602 — rated power (W); config-only before, now settable here. */ ''}
                ${this._renderOptionNumberInput('hot_water_rated_power', 'config_hw_rated_power',
                    { min: 100, max: 30000, step: 50, unit: 'W', default: 2500 }, opts, 'config_help_hw_rated_power')}
                ${this._renderStepper('number.sem_hot_water_solar_target', 'hot_water_solar_target',
                    T, 'config_help_hw_solar_target')}
                ${this._renderStepper('number.sem_hot_water_max_temperature', 'hot_water_max_temperature',
                    T, 'config_help_hw_max_temperature')}
                ${this._renderOptionSlider('hot_water_legionella_target', 'config_hw_legionella_target',
                    { min: 55, max: 80, step: 1, unit: '°C', default: 65 }, opts, 'config_help_hw_legionella_target')}
                ${this._renderOptionSlider('hot_water_minimum_temperature', 'config_hw_min_temperature',
                    { min: 30, max: 55, step: 1, unit: '°C', default: 40 }, opts, 'config_help_hw_min_temperature')}
                ${/* #602/#576 — hot_water_priority slider retired: hot water is a
                      draggable row in the device-priority list now (single axis). */ ''}
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
        // Uniqueness across BOTH the options list and the runtime charger ids
        // (a stale _options could otherwise collide → smart-merge would UPDATE
        // an existing charger instead of appending).
        const ids = new Set([
            ...existing.map(c => c && c.id).filter(Boolean),
            ...this._chargersList(),
        ]);
        let id = 'ev_charger', n = 1;
        while (ids.has(id)) { id = `ev_charger_${n++}`; }
        const charger = {
            id,
            name: `${this._t('config_ev_new_charger')} ${existing.length + 1}`,
            ev_min_current: 6,
            // (#746) no ceiling literal here. This line was the ONLY writer of
            // ``max_charging_current`` anywhere in SEM — a hardcoded 32 that
            // then became every install's un-raisable EVSE cap. The ceiling is
            // now ``ev_max_current``, seeded from DEFAULT_MAX_CHARGING_CURRENT
            // by devices.base.resolve_max_current and raised by the Max Amps
            // slider. Leaving it unset keeps one source of truth (class 46).
            ev_surplus_priority: existing.length + 3,
        };
        this._chargerBusy = true;
        this.requestUpdate();
        try {
            await this._saveOption('ev_chargers', [charger], 'ev_chargers_add');
            // _saveOption optimistically set _options.ev_chargers to the
            // single skeleton — re-read the merged list so siblings reappear.
            await this._refreshOptions();
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
            // Re-read so the removed block disappears without a page refresh.
            await this._refreshOptions();
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
    // (#804) free-text field bound to ev_chargers[index][key] — the 1p/3p
    // positions in the switch entity's own vocabulary. Same nested write
    // path + status chrome as the pickers; Enter or blur saves.
    _renderTextNested(chargerIndex, cid, chargerKey, labelKey, opts, helpKey, placeholder) {
        const chargers = opts.ev_chargers || [];
        const cur = chargers[chargerIndex]?.[chargerKey] ?? '';
        const statusKey = `ev_chargers.${chargerIndex}.${chargerKey}`;
        const status = this._saveStatus[statusKey];
        return html`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(labelKey)}</span>
                    <input type="text" class="txt-opt" .value=${String(cur)}
                           placeholder="${placeholder || ''}"
                           @keydown=${(e) => { if (e.key === 'Enter') e.target.blur(); }}
                           @blur=${(e) => {
                               const v = e.target.value.trim();
                               if (v !== String(cur)) {
                                   this._saveChargerField(chargerIndex, cid, chargerKey, v, statusKey, opts);
                               }
                           }} />
                </div>
                ${status === 'saving' ? html`<div class="save-status">${this._t('config_saving')}…</div>` : nothing}
                ${status === 'ok' ? html`<div class="save-status ok">✓ ${this._t('config_saved')}</div>` : nothing}
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
    }

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
                        .includeDomains=${domain ? (Array.isArray(domain) ? domain : [domain]) : undefined}
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
        // (#830) One choke point for the default view: a control not on
        // the essential list is simply not rendered until advanced is on.
        if (!this._showsControl(optionKey)) return nothing;

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
                        .includeDomains=${domain ? (Array.isArray(domain) ? domain : [domain]) : undefined}
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

    // ── #605 staged-tunable core ─────────────────────────────────────
    // Every tunable control renders the STAGED value when one exists and
    // routes its change into _stage() instead of writing live. The section
    // footer commits (Apply) or drops (Revert) the section's staged set.

    _reg(id) {
        // Bind a control id to the section currently rendering (see
        // _renderSection). Called from every tunable renderer.
        if (this._sec) this._secOf[id] = this._sec;
    }

    _liveOf(id, kind) {
        if (kind === 'option') {
            const o = this._options || {};
            return o[id.slice(4)];
        }
        const e = this._hass?.states[id];
        if (!e) return undefined;
        return kind === 'number' ? parseFloat(e.state) : e.state;
    }

    _stage(id, kind, value) {
        const live = this._liveOf(id, kind);
        const same = kind === 'number'
            ? Number(live) === Number(value)
            : String(live) === String(value);
        const st = { ...this._staged };
        if (same) delete st[id]; else st[id] = { kind, value };
        this._staged = st;
    }

    _isDirty(id) {
        return Object.prototype.hasOwnProperty.call(this._staged, id);
    }

    _stagedVal(id, live) {
        const s = this._staged[id];
        return s === undefined ? live : s.value;
    }

    _sectionStaged(secId) {
        return Object.keys(this._staged).filter(k => this._secOf[k] === secId);
    }

    _revertSection(secId) {
        const st = { ...this._staged };
        this._sectionStaged(secId).forEach(k => delete st[k]);
        this._staged = st;
    }

    async _applySection(secId) {
        const keys = this._sectionStaged(secId);
        if (!keys.length || this._secApplying) return;
        this._secApplying = secId;
        try {
            const optPayload = {};
            for (const k of keys) {
                const s = this._staged[k];
                if (s.kind === 'option') {
                    optPayload[k.slice(4)] = s.value;
                } else if (s.kind === 'number') {
                    await this._hass.callService('number', 'set_value',
                        { entity_id: k, value: Number(s.value) });
                } else if (s.kind === 'select') {
                    await this._hass.callService('select', 'select_option',
                        { entity_id: k, option: String(s.value) });
                } else if (s.kind === 'switch') {
                    await this._hass.callService('switch',
                        s.value === 'on' ? 'turn_on' : 'turn_off',
                        { entity_id: k });
                }
            }
            if (Object.keys(optPayload).length) {
                const entryId = await this._ensureEntryId();
                await this._hass.callService('solar_energy_management', 'set_option', {
                    options: optPayload, ...(entryId ? { entry_id: entryId } : {}),
                });
                this._options = { ...this._options, ...optPayload };
            }
            const st = { ...this._staged };
            keys.forEach(k => delete st[k]);
            this._staged = st;
        } catch (err) {
            console.error('[sem-config-card] section apply failed', err);
            this._saveStatus = {
                ...this._saveStatus,
                ['_sec_' + secId]: err?.message || 'apply failed',
            };
        } finally {
            this._secApplying = '';
            this.requestUpdate();
        }
    }

    // ── #606 per-row help (info button + default value) ──────────────

    _helpVisible(helpKey) {
        return !!(helpKey && (this._showHelp || this._helpOpen[helpKey]));
    }

    _helpBtn(helpKey) {
        if (!helpKey) return nothing;
        return html`<ha-icon class="row-help-btn ${this._helpOpen[helpKey] ? 'on' : ''}"
            icon="mdi:information-outline" style="--mdc-icon-size:14px"
            @click=${(e) => {
                e.stopPropagation();
                this._helpOpen = { ...this._helpOpen, [helpKey]: !this._helpOpen[helpKey] };
            }}></ha-icon>`;
    }

    _helpBlock(helpKey, def, unit, sid, kind) {
        if (!this._helpVisible(helpKey)) return nothing;
        const hasDef = def !== undefined && def !== null && def !== '';
        // #605 follow-up (Guido): reset-to-default STAGES the factory value
        // through the same Apply pipeline — previewable, revertable, and
        // committed only on the section Apply like any other edit.
        const canReset = hasDef && sid && kind;
        return html`<div class="setting-help-text">${this._t(helpKey)}${hasDef
            ? html` <span class="help-default">${this._t('config_default_label')}: ${def}${unit ? ' ' + unit : ''}</span>`
            : nothing}${canReset
            ? html` <button class="help-reset-btn" title="${this._t('config_reset_default')}"
                  @click=${(e) => { e.stopPropagation(); this._stage(sid, kind, def); }}>↺ ${this._t('config_reset_default')}</button>`
            : nothing}</div>`;
    }

    // Toggle bound to an entry.options key. Use when no runtime
    // ``switch.sem_*`` entity exists for the option.
    // Native <select> bound to an entry.options key.
    _renderOptionSelect(optionKey, labelKey, options, opts, helpKey, defaultVal) {
        // (#830) One choke point for the default view: a control not on
        // the essential list is simply not rendered until advanced is on.
        if (!this._showsControl(optionKey)) return nothing;

        const sid = 'opt:' + optionKey;
        this._reg(sid);
        const live = opts[optionKey] != null ? opts[optionKey] : defaultVal;
        const dirty = this._isDirty(sid);
        const cur = this._stagedVal(sid, live);
        return html`
            <div class="stepper-cell ${dirty ? 'dirty' : ''}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(labelKey)}${dirty ? html`<span class="dirty-dot">●</span>` : nothing}${this._helpBtn(helpKey)}</span>
                    <select class="sem-select"
                            .value=${cur}
                            @change=${(e) => this._stage(sid, 'option', e.target.value)}>
                        ${options.map(o => html`
                            <option value="${o.value}" ?selected=${o.value === cur}>${o.label}</option>
                        `)}
                    </select>
                </div>
                ${this._helpBlock(helpKey, defaultVal, undefined, sid, 'option')}
            </div>
        `;
    }

    // Boolean toggle backed by an entry OPTION (not a switch entity) —
    // saves a real boolean via set_option (#523 arbitrage opt-in).
    // #550: structural toggles (entity-wiring keys that reload the entry, e.g.
    // heat_pump_invert_sg_ready, battery_discharge_protection_enabled) stage
    // into _pending and commit on Apply — same as _renderPicker — so a flip
    // doesn't fire its own reload and discard a sibling picker's staged edit.
    // Non-structural toggles keep saving live on click (unchanged).
    _renderOptionToggle(optionKey, labelKey, opts, helpKey, defaultVal) {
        // (#830) One choke point for the default view: a control not on
        // the essential list is simply not rendered until advanced is on.
        if (!this._showsControl(optionKey)) return nothing;

        const structural = STRUCTURAL_KEYS.has(optionKey);
        const sid = 'opt:' + optionKey;
        if (!structural) this._reg(sid);
        const stagedStructural = structural && Object.prototype.hasOwnProperty.call(this._pending, optionKey);
        const liveOn = opts[optionKey] != null ? !!opts[optionKey] : !!defaultVal;
        const dirty = stagedStructural || (!structural && this._isDirty(sid));
        const cur = stagedStructural
            ? !!this._pending[optionKey]
            : (!structural && this._isDirty(sid) ? !!this._staged[sid].value : liveOn);
        const onToggle = () => {
            if (structural) {
                this._pending = { ...this._pending, [optionKey]: !cur };
                this.requestUpdate();
            } else {
                // #605 — tunable option toggles stage like everything else.
                this._stage(sid, 'option', !cur);
            }
        };
        return html`
            <div class="stepper-cell ${dirty ? 'dirty' : ''}">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(labelKey)}${dirty ? html`<span class="dirty-dot" title="${this._t('config_pending_hint')}">●</span>` : nothing}${this._helpBtn(helpKey)}</span>
                    <div class="toggle-track ${cur ? 'on' : ''}"
                         @click=${onToggle}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._helpBlock(helpKey)}
            </div>
        `;
    }

    // Native <input type="number"> for BOX-mode fields with large ranges
    // (e.g. battery_max_charge_power_w spans 500–25000 W). Steppers would
    // need hundreds of clicks; typing the number is faster. Commits on
    // blur and Enter to avoid one save per keystroke.
    _renderOptionNumberInput(optionKey, labelKey, cfg, opts, helpKey) {
        // (#830) One choke point for the default view: a control not on
        // the essential list is simply not rendered until advanced is on.
        if (!this._showsControl(optionKey)) return nothing;

        const sid = 'opt:' + optionKey;
        this._reg(sid);
        const live = opts[optionKey] != null ? opts[optionKey] : cfg.default;
        const dirty = this._isDirty(sid);
        const cur = this._stagedVal(sid, live);
        const commit = (val) => {
            const n = parseFloat(val);
            if (Number.isNaN(n)) return;
            const clamped = Math.max(cfg.min, Math.min(cfg.max, n));
            this._stage(sid, 'option', clamped);
        };
        return html`
            <div class="stepper-cell ${dirty ? 'dirty' : ''}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(labelKey)}${dirty ? html`<span class="dirty-dot">●</span>` : nothing}${this._helpBtn(helpKey)}</span>
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
                ${this._helpBlock(helpKey, cfg.default, cfg.unit, sid, 'option')}
            </div>
        `;
    }

    // Slider that writes to entry.options on change. Use for option-only
    // numeric fields that don't have a runtime ``number.sem_*`` entity.
    // #528: option-key slider in the same colorful accent style as the
    // entity knob (saves an entry.option live via _saveOption).
    _renderOptionSlider(optionKey, labelKey, cfg, opts, helpKey) {
        // (#830) One choke point for the default view: a control not on
        // the essential list is simply not rendered until advanced is on.
        if (!this._showsControl(optionKey)) return nothing;

        const sid = 'opt:' + optionKey;
        this._reg(sid);
        const live = parseFloat(opts[optionKey] != null ? opts[optionKey] : cfg.default) || 0;
        const dirty = this._isDirty(sid);
        const cur = Number(this._stagedVal(sid, live));
        const decimals = cfg.step < 1 ? 1 : 0;
        const unit = cfg.unit || '';
        const pct = cfg.max > cfg.min ? Math.round(((cur - cfg.min) / (cfg.max - cfg.min)) * 100) : 0;
        const stepBy = (d) => {
            const next = Math.min(cfg.max, Math.max(cfg.min, cur + d * cfg.step));
            this._stage(sid, 'option', next);
        };
        return html`
            <div class="zone-knob ${dirty ? 'dirty' : ''}">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(labelKey)}${this._helpBtn(helpKey)}</span>
                    <span class="zone-chip">${dirty ? html`<span class="dirty-dot">●</span>` : nothing}${cur.toFixed(decimals)}${unit ? ' ' + unit : ''}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${() => stepBy(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${cfg.min} max=${cfg.max} step=${cfg.step} .value=${String(cur)}
                        style=${`--fill:${pct}%`}
                        @change=${(ev) => this._stage(sid, 'option', parseFloat(ev.target.value))} />
                    <button class="zone-mini" @click=${() => stepBy(1)}>+</button>
                </div>
                ${this._helpBlock(helpKey, cfg.default, unit, sid, 'option')}
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

            ${''/* (#778) Forecast-led spending. Three switch ENTITIES rather
               than options, because they must be flippable from the dashboard
               without an Apply cycle — a permission a user revokes is usually
               revoked because they want it to stop NOW. The two permissions
               are separate switches rather than another battery mode: a mode
               is single-select and cannot say "may sell, may not touch the
               car". */}
            <div class="subsection-title">${this._t('config_section_forecast_spending')}</div>
            <div class="setup-intro">${this._t('config_forecast_spending_intro')}</div>
            ${this._renderToggle('switch.sem_forecast_spending_enabled',
                'forecast_spending_enabled', T, 'config_help_forecast_spending')}
            ${this._renderToggle('switch.sem_battery_may_export',
                'battery_may_export', T, 'config_help_battery_may_export')}
            ${this._renderToggle('switch.sem_battery_may_assist_ev',
                'battery_may_assist_ev', T, 'config_help_battery_may_assist_ev')}
        `;
    }

    _renderLoadManagement(T) {
        const opts = this._options || {};
        // #716 — read the toggle's STAGED value, not just the persisted one,
        // so the three kW fields disappear the moment it is flipped rather
        // than one Apply later.
        const usid = 'opt:peak_limit_unlimited';
        const unlimited = this._isDirty(usid)
            ? !!this._staged[usid].value
            : !!opts.peak_limit_unlimited;
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('load_management_status')}</span>
                <span class="readonly-value">${this._val('load_management_status') || '—'}</span>
            </div>
            ${this._renderOptionToggle('load_management_enabled', 'config_lm_enabled',
                opts, 'config_help_lm_enabled', true)}
            ${this._renderOptionToggle('peak_limit_unlimited', 'config_lm_unlimited',
                opts, 'config_help_lm_unlimited', false)}
            ${unlimited ? html`
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('config_lm_target_peak')}</span>
                    <span class="readonly-value">${this._t('config_lm_unlimited_value')}</span>
                </div>
            ` : html`
                ${this._renderOptionNumberInput('target_peak_limit', 'config_lm_target_peak',
                    { min: 1.0, max: 80.0, step: 0.1, unit: 'kW', default: 5.0 }, opts, 'config_help_lm_target_peak')}
                <div class="advanced-toggle-row" @click=${() => { this._lmAdvancedOpen = !this._lmAdvancedOpen; }}>
                    <ha-icon class="chevron" icon="mdi:chevron-down"
                             style="--mdc-icon-size:16px;transform:${this._lmAdvancedOpen ? 'rotate(0deg)' : 'rotate(-90deg)'}"></ha-icon>
                    <span>${this._t('config_section_advanced')}</span>
                </div>
                ${this._lmAdvancedOpen ? html`
                    ${this._renderOptionNumberInput('warning_peak_level', 'config_lm_warning_peak',
                        { min: 1.0, max: 80.0, step: 0.1, unit: 'kW', default: 4.5 }, opts, 'config_help_lm_warning_peak')}
                    ${this._renderOptionNumberInput('emergency_peak_level', 'config_lm_emergency_peak',
                        { min: 1.0, max: 80.0, step: 0.1, unit: 'kW', default: 6.0 }, opts, 'config_help_lm_emergency_peak')}
                ` : nothing}
            `}
        `;
    }

    _renderForecast(T) {
        const raw = this._val('forecast_source') || 'none';
        const label = raw === 'none' ? this._t('none') : this._forecastProviderLabel(raw);
        const opts = this._options || {};
        // (#819) Running Solcast, Forecast.Solar and Open-Meteo side by side to
        // compare them used to mean the first one on the ladder always won, and
        // the only lever was deactivating the others. Auto keeps that ladder.
        // Only offer what is actually installed: picking an absent source
        // would silently fall back to auto and look like the setting did
        // nothing. A stale choice stays listed (marked) so the user can see
        // WHY their pick is not being used rather than finding it vanished.
        // Reads the ATTRIBUTE, not a state: _val() resolves
        // sensor.sem_<suffix>.state, and there is no such entity for a
        // list. Getting this wrong returns '' and silently re-offers
        // every source — an inert half that looks fine on screen.
        const installed = this._hass?.states?.['sensor.sem_forecast_source']
            ?.attributes?.sources_available || [];
        const has = (k) => !Array.isArray(installed) || installed.includes(k);
        const chosen = opts.solar_forecast_source || 'auto';
        const named = [
            { value: 'solcast', label: 'Solcast PV Solar' },
            { value: 'forecast_solar', label: 'Forecast.Solar' },
            { value: 'open_meteo', label: 'Open-Meteo Solar Forecast' },
        ];
        const sourceOptions = [
            { value: 'auto', label: this._t('config_forecast_source_auto') },
            ...named
                .filter((o) => has(o.value) || o.value === chosen)
                .map((o) => (has(o.value)
                    ? o
                    : { ...o, label: `${o.label} — ${this._t('config_forecast_source_missing')}` })),
        ];
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('forecast_source')}</span>
                <span class="readonly-value">${label}</span>
            </div>
            ${this._renderOptionSelect('solar_forecast_source', 'config_solar_forecast_source',
                sourceOptions, opts, 'config_help_solar_forecast_source', 'auto')}
            ${raw === 'none' ? html`<div class="overview-help">${this._t('config_forecast_install_hint')}</div>` : nothing}
        `;
    }

    // (#566) Discovered PV-string power sensors → [{slot, power, displayName}],
    // ordered pv1, pv2, … . Drives both the subtitle count and the rename body.
    _pvStrings() {
        const st = this._hass?.states || {};
        const out = [];
        for (const id of Object.keys(st)) {
            const m = id.match(/^sensor\.sem_pv_string_(pv\d+)_power$/);
            if (!m) continue;
            const s = st[id];
            out.push({
                slot: m[1],
                power: parseFloat(s.state),
                displayName: s.attributes?.string_name || m[1].toUpperCase(),
            });
        }
        out.sort((a, b) => a.slot.localeCompare(b.slot, undefined, { numeric: true }));
        return out;
    }

    _pvStringsSubtitle() {
        const n = this._pvStrings().length;
        return n ? `${n} ${this._t('pv_strings_unit') || 'strings'}` : '';
    }

    _onPvNameInput(slot, val) {
        this._pvNameEdits = { ...(this._pvNameEdits || {}), [slot]: val };
    }

    async _savePvNames() {
        // Merge edits onto the saved names; a blank clears a name (reverts to
        // the compact "PVn" default). Saved via set_option — pv_string_names is
        // an unrouted key, so it triggers a coordinator reload (that's how the
        // new names reach the per-string sensor attributes). Rename is rare, so
        // the one-off reload on Save is acceptable.
        const names = { ...(this._options?.pv_string_names || {}) };
        const edits = this._pvNameEdits || {};
        for (const [slot, val] of Object.entries(edits)) {
            const v = (val || '').trim();
            if (v) names[slot] = v; else delete names[slot];
        }
        await this._saveOption('pv_string_names', names, 'pv_string_names');
        this._pvNameEdits = {};
    }

    _renderPvStrings(T) {
        const strings = this._pvStrings();
        const saved = this._options?.pv_string_names || {};
        const edits = this._pvNameEdits || {};
        const status = this._saveStatus?.pv_string_names;
        return html`
            <div class="setting-help-text">${this._t('config_pv_strings_help')}</div>
            ${strings.map((s) => {
                const cur = edits[s.slot] !== undefined ? edits[s.slot] : (saved[s.slot] || '');
                const pw = Number.isFinite(s.power) ? `${s.power.toFixed(0)} W` : '';
                return html`
                    <div class="pv-name-row">
                        <div class="pv-name-meta">
                            <span class="pv-name-slot">${s.slot.toUpperCase()}</span>
                            ${pw ? html`<span class="pv-name-power">${pw}</span>` : nothing}
                        </div>
                        <input type="text" class="pv-name-input"
                            placeholder=${s.slot.toUpperCase()}
                            .value=${cur}
                            @input=${(ev) => this._onPvNameInput(s.slot, ev.target.value)} />
                    </div>`;
            })}
            <div class="section-footer">
                ${status === 'ok' ? html`<span class="pv-save-ok">✓</span>` : nothing}
                <button class="pv-save-btn" ?disabled=${status === 'saving'}
                        @click=${() => this._savePvNames()}>
                    ${status === 'saving' ? '…' : this._t('config_pv_strings_save')}
                </button>
            </div>
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
        const opts = this._options || {};
        return html`
            ${/* #580 — Grid VPP dispatch (Axle Energy first). Observer mode is
                  the default: log/notify only, actuate nothing. First help text
                  links docs/GRID_VPP.md. */ ''}
            <div class="readonly-row" style="border-bottom:1px solid ${T.surfaceBorder};padding-bottom:4px;margin-bottom:4px">
                <span class="ctrl-label" style="font-weight:600">${this._t('config_vpp_section')}</span>
            </div>
            ${this._renderOptionToggle('vpp_enabled', 'config_vpp_enabled',
                opts, 'config_help_vpp_enabled', false)}
            ${this._renderOptionToggle('vpp_observer_mode', 'config_vpp_observer',
                opts, 'config_help_vpp_observer', true)}
            ${this._renderPicker('vpp_event_active_entity', 'config_vpp_event_entity',
                ['binary_sensor', 'sensor'], null, opts, 'config_help_vpp_event_active_entity')}
            ${this._renderPicker('vpp_direction_entity', 'config_vpp_direction_entity',
                ['sensor', 'select', 'input_select'], null, opts, 'config_help_vpp_direction_entity')}
            ${this._renderPicker('vpp_event_end_entity', 'config_vpp_event_end_entity',
                'sensor', 'timestamp', opts, 'config_help_vpp_event_end_entity')}
            ${this._renderPicker('vpp_pre_event_entity', 'config_vpp_pre_event_entity',
                ['binary_sensor', 'sensor'], null, opts, 'config_help_vpp_pre_event_entity')}
            ${this._renderOptionSlider('vpp_reserve_soc', 'config_vpp_reserve_soc',
                { min: 5, max: 80, step: 5, unit: '%', default: 20 }, opts,
                'config_help_vpp_reserve_soc')}
            <div style="margin-top:6px;border-top:1px solid ${T.surfaceBorder};padding-top:4px"></div>
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
            ${this._renderRetention(T)}
            ${this._renderGridSignFix(T)}
        `;
    }

    // (#829) Retention for SEM's OWN status entities. Safe by construction:
    // the purge list is derived from "has no state_class", so every charted
    // sensor - energy, power, anything with long-term statistics - is
    // excluded automatically, including ones added later.
    _renderRetention(T) {
        const opts = this._options || {};
        return html`
            <div style="margin-top:6px;border-top:1px solid ${T.surfaceBorder};padding-top:4px"></div>
            ${this._renderOptionSlider('status_retention_days', 'config_retention_label',
                { min: 0, max: 14, step: 1,
                  unit: ' ' + this._t('config_retention_unit_days'), default: 0 },
                opts, 'config_help_retention')}
            <div class="action-row">
                <button class="action-btn" ?disabled=${this._retentionBusy}
                        @click=${() => this._purgeStatusHistory()}>
                    ${this._t('config_retention_cleanup')}
                </button>
                <span class="readonly-value">${this._retentionMsg || ''}</span>
            </div>
        `;
    }

    async _purgeStatusHistory() {
        this._retentionBusy = true;
        this.requestUpdate();
        try {
            await this._hass.callService(
                'solar_energy_management', 'purge_status_history', {});
            this._retentionMsg = 'OK';
        } catch (e) {
            this._retentionMsg = String(e && e.message ? e.message : e).slice(0, 60);
        }
        this._retentionBusy = false;
        this.requestUpdate();
    }

    // #461: grid import/export sign — one-tap fix + re-learn. Lives in the
    // Advanced section: most users never need it, but a meter with a
    // swapped/mis-mapped convention shows inverted import/export and the
    // user can correct it here without Developer Tools → Actions.
    _renderGridSignFix(T) {
        const gridSign = this._val('diag_grid_sign') || '—';
        const battSign = this._val('diag_battery_sign') || '—';
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
                <div class="readonly-row" style="margin-top:8px">
                    <span class="ctrl-label">${this._t('battery_sign')}</span>
                    <span class="readonly-value">${battSign}</span>
                </div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._battSignBusy}
                            @click=${() => this._flipBatterySign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t('fix_battery_sign')}
                    </button>
                </div>
                ${this._battSignMsg
                    ? html`<div class="sign-feedback">${this._battSignMsg}</div>`
                    : nothing}
                ${this._showHelp
                    ? html`<div class="setting-help-text">${this._t('fix_battery_sign_help')}</div>`
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

    // #588 — battery charge/discharge sign flip, mirrors _flipGridSign.
    async _flipBatterySign() {
        if (!this._hass || this._battSignBusy) return;
        this._battSignBusy = true;
        this._battSignMsg = '';
        this.requestUpdate();
        let payload = null;
        try {
            const res = await this._hass.callService(
                'solar_energy_management', 'flip_battery_sign', {},
                undefined, false, true,
            );
            payload = (res && res.response) ? res.response : res;
        } catch (e) {
            payload = null;
        }
        const report = this._buildBatterySignReport(payload);
        let copied = false;
        try {
            await navigator.clipboard.writeText(report);
            copied = true;
        } catch (e) {
            copied = false;
        }
        this._battSignBusy = false;
        this._battSignMsg = copied
            ? this._t('sign_flipped_copied')
            : this._t('sign_flipped');
        this.requestUpdate();
        setTimeout(() => { this._battSignMsg = ''; this.requestUpdate(); }, 6000);
    }

    // Build the markdown battery-sign support report copied on flip.
    _buildBatterySignReport(payload) {
        const d = (payload && payload.diagnostics) || {};
        const flip = (payload && typeof payload.user_flip === 'boolean')
            ? String(payload.user_flip) : '?';
        const j = (v) => (v === undefined || v === null) ? '?' : String(v);
        const arr = (v) => (Array.isArray(v) && v.length) ? v.join(', ') : '(none)';
        const bt = String.fromCharCode(96); // backtick — kept out of source
        const code = (s) => bt + s + bt;
        const perBid = d.per_bid || {};
        const bidLines = Object.entries(perBid).map(([bid, info]) =>
            '  ' + bid + ': ' + j(info.inverted ? 'negated' : 'normal')
            + ' (detected=' + j(info.detected) + ', confidence=' + j(info.confidence)
            + ', samples=' + j(info.samples) + ')'
        );
        return [
            '### SEM battery-sign report (#588)',
            '',
            'I tapped **Fix battery sign** in the Configuration tab.',
            'battery_sign_user_flip is now ' + code(flip) + '.',
            '',
            '- Battery sensor: ' + code(j(d.battery_power_sensor)) + ' = ' + j(d.battery_power_raw_state) + ' (raw)',
            '- Battery integration: ' + j(d.battery_platform) + ' (brand-seeded: ' + j(d.brand_seeded) + ')',
            '- Per-battery sign state:',
            ...bidLines,
            '- Charge counters: ' + arr(d.charge_counters),
            '- Discharge counters: ' + arr(d.discharge_counters),
            '',
            'My hardware (please fill in): inverter / battery brand.',
            'After the flip, does battery charge/discharge show the correct direction?',
        ].join('\n');
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
                ${this._sectionStaged(section.id).length ? html`
                    <span class="header-dirty-badge" title="${this._t('config_pending_hint')}">● ${this._sectionStaged(section.id).length}</span>` : nothing}
                ${section.docs ? html`
                    <a class="section-docs-link" href="${section.docs}" target="_blank" rel="noopener"
                       title="${this._t('config_docs')}" @click=${(e) => e.stopPropagation()}>
                        <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:15px"></ha-icon>
                    </a>` : nothing}
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
        // #605 — bind every tunable rendered inside this section to it (the
        // renderers call _reg() while _sec is set), so the footer knows which
        // staged edits belong here.
        this._sec = section.id;
        const body = contentFn(T);
        this._sec = null;
        const dirty = this._sectionStaged(section.id);
        const busy = this._secApplying === section.id;
        const err = this._saveStatus['_sec_' + section.id];
        const footer = dirty.length ? html`
            <div class="section-stage-bar">
                <span class="stage-count">● ${dirty.length} ${this._t('config_unsaved')}</span>
                ${err ? html`<span class="stage-err">⚠ ${err}</span>` : nothing}
                <button class="stage-btn revert" ?disabled=${busy}
                        @click=${() => this._revertSection(section.id)}>↩ ${this._t('config_revert')}</button>
                <button class="stage-btn apply" ?disabled=${busy}
                        @click=${() => this._applySection(section.id)}>${busy
                            ? html`${this._t('config_saving')}…`
                            : html`✓ ${this._t('config_apply_section')}`}</button>
            </div>` : nothing;
        return html`
            <div class="section ${collapsed ? '' : 'expanded'}"
                 style="--section-accent: ${section.color}">
                ${this._renderSectionHeader(section, T)}
                <div class="section-content ${collapsed ? '' : 'expanded'}">
                    <div class="section-body">
                        ${body}
                        ${footer}
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
            sensor_sources: (T) => this._renderSensorSources(T),
            detected_hardware: (T) => this._renderDetectedHardware(T),
            ev_chargers: (T) => this._renderEvChargers(T),
            battery_zones: (T) => this._renderBatteryZones(T),
            tariff: (T) => this._renderTariff(T),
            heat_pump: (T) => this._renderHeatPump(T),
            hot_water: (T) => this._renderHotWater(T),
            battery_scheduler: (T) => this._renderBatteryScheduler(T),
            load_management: (T) => this._renderLoadManagement(T),
            forecast: (T) => this._renderForecast(T),
            pv_strings: (T) => this._renderPvStrings(T),
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
                .help-toggle-labeled {
                    display: inline-flex; align-items: center; gap: 5px;
                    padding: 4px 10px; border-radius: 14px;
                    border: 1px solid ${T.surfaceBorder};
                    font-size: 12px; cursor: pointer;
                    color: ${T.textDim || 'rgba(150,160,175,0.9)'};
                    transition: color 0.15s, border-color 0.15s;
                }
                .help-toggle-labeled:hover { color: ${accent}; border-color: ${accent}; }
                .help-toggle-labeled.on { color: ${accent}; border-color: ${accent}; }
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
                /* (#717) inline sub-disclosure for the warning/emergency
                   ladder — most users never touch it, the target slider on
                   the Control tab is the one live control that matters. */
                .advanced-toggle-row {
                    display: flex; align-items: center; gap: 6px;
                    padding: 8px 2px; margin-top: 2px; cursor: pointer; user-select: none;
                    font-size: 0.85em; font-weight: 600;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .advanced-toggle-row:hover { color: var(--primary-text-color, ${T.text}); }
                .section-content {
                    max-height: 0; opacity: 0; overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded { max-height: 2000px; opacity: 1; }
                .section-body { padding: 0 14px 14px; }
                .section-footer { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 10px; }

                /* (#566) PV-string rename rows */
                .pv-name-row {
                    display: flex; align-items: center; gap: 12px;
                    padding: 8px 0;
                }
                .pv-name-meta {
                    display: flex; flex-direction: column; min-width: 64px;
                }
                .pv-name-slot { font-size: 0.9em; font-weight: 700; color: #ff9800; }
                .pv-name-power {
                    font-size: 0.7em; color: var(--secondary-text-color, ${T.textSec});
                }
                .txt-opt {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                color: var(--primary-text-color, #e1e1e1);
                font-size: 12px;
                padding: 3px 8px;
                width: 110px;
            }
            .sv { font-size: 11px; }
            .sv.ok { color: #8DC892; }
            .sv.err { color: #f06292; }
            .pv-name-input {
                    flex: 1; min-width: 0;
                    background: var(--secondary-background-color, ${T.surface});
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    border-radius: 8px; padding: 8px 10px;
                    color: var(--primary-text-color, ${T.text});
                    font-family: inherit; font-size: 0.9em;
                }
                .pv-name-input:focus { outline: none; border-color: #ff9800; }
                .pv-save-btn {
                    background: #ff9800; color: #1a1a1a; border: none;
                    border-radius: 8px; padding: 7px 16px; cursor: pointer;
                    font-weight: 600; font-size: 0.85em;
                }
                .pv-save-btn:disabled { opacity: 0.6; cursor: default; }
                .pv-save-ok { color: #8DC892; font-weight: 700; }

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

                /* (#778) sub-heading inside a section — the forecast-spending
                   block sits under the battery scheduler rather than claiming
                   its own top-level section. */
                .subsection-title {
                    margin: 20px 0 2px;
                    font-size: 12px;
                    font-weight: 500;
                    letter-spacing: .07em;
                    text-transform: uppercase;
                    color: var(--sem-text-sec, #8fa3a0);
                    border-top: 1px solid rgba(255,255,255,.08);
                    padding-top: 16px;
                }

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

                /* ── #605 staged-changes UI ── */
                .zone-knob.dirty, .stepper-cell.dirty {
                    border-left: 3px solid var(--section-accent, ${accent});
                    padding-left: 8px; margin-left: -11px;
                    border-radius: 4px;
                }
                .dirty-dot {
                    color: var(--section-accent, ${accent});
                    font-size: 10px; margin: 0 4px; vertical-align: middle;
                }
                .section-stage-bar {
                    display: flex; align-items: center; gap: 10px;
                    margin-top: 12px; padding: 8px 12px;
                    background: ${T.surface}; border: 1px solid var(--section-accent, ${accent});
                    border-radius: 10px;
                    position: sticky; bottom: 8px; z-index: 3;
                    backdrop-filter: blur(8px);
                }
                .stage-count { font-size: 12.5px; color: var(--section-accent, ${accent}); font-weight: 600; flex: 1; }
                .stage-err { font-size: 12px; color: #ef5350; }
                .stage-btn {
                    padding: 6px 14px; border-radius: 8px; font-size: 13px;
                    cursor: pointer; border: 1px solid ${T.surfaceBorder};
                    background: ${T.surface}; color: var(--primary-text-color, ${T.text});
                    transition: background 0.15s, border-color 0.15s;
                }
                .stage-btn.apply {
                    background: var(--section-accent, ${accent}); color: #fff;
                    border-color: transparent; font-weight: 600;
                }
                .stage-btn:disabled { opacity: 0.55; cursor: default; }
                .stage-btn:not(:disabled):hover { filter: brightness(1.12); }
                .header-dirty-badge {
                    font-size: 11px; font-weight: 700;
                    color: var(--section-accent, ${accent});
                    margin-left: 6px; white-space: nowrap;
                }

                /* ── #606 per-row help + defaults + docs ── */
                .row-help-btn {
                    color: ${T.textDim || 'rgba(150,160,175,0.8)'};
                    cursor: pointer; margin-left: 5px; vertical-align: middle;
                    opacity: 0.7; transition: opacity 0.15s, color 0.15s;
                }
                .row-help-btn:hover { opacity: 1; }
                .row-help-btn.on { color: var(--section-accent, ${accent}); opacity: 1; }
                .help-default {
                    display: inline-block; margin-left: 8px;
                    font-size: 11px; font-weight: 600;
                    color: var(--section-accent, ${accent});
                    opacity: 0.9; white-space: nowrap;
                }
                .section-docs-link {
                    display: inline-flex; align-items: center;
                    color: ${T.textDim || 'rgba(150,160,175,0.8)'};
                    margin-left: 6px; opacity: 0.7; transition: opacity 0.15s;
                }
                .section-docs-link:hover { opacity: 1; color: var(--section-accent, ${accent}); }
                .help-reset-btn {
                    display: inline-block; margin-left: 8px;
                    padding: 1px 8px; border-radius: 9px;
                    font-size: 11px; cursor: pointer;
                    border: 1px solid ${T.surfaceBorder};
                    background: transparent;
                    color: var(--section-accent, ${accent});
                }
                .help-reset-btn:hover { border-color: var(--section-accent, ${accent}); }
            </style>
            <ha-card>
                <div class="wrap">
                    ${/* #606 — the bare (?) icon was not self-explanatory
                        (Guido): the global help toggle carries a visible
                        label now. */ ''}
                    <div class="card-help-bar">
                        <span class="help-toggle-labeled ${this._showHelp ? 'on' : ''}"
                              @click=${() => this._toggleHelp()}>
                            <ha-icon
                                icon="${this._showHelp ? 'mdi:help-circle' : 'mdi:help-circle-outline'}"
                                style="--mdc-icon-size:16px"
                            ></ha-icon>
                            <span>${this._t('config_help_label')}</span>
                        </span>
                        ${/* (#830) The advanced switch sits beside the help
                            switch because it is the same kind of thing: a view
                            preference, not a setting. The default view has no
                            name — nobody is told they are a beginner. */ ''}
                        <span class="help-toggle-labeled ${this._advanced ? 'on' : ''}"
                              @click=${() => this._toggleAdvanced()}>
                            <ha-icon
                                icon="${this._advanced ? 'mdi:tune-variant' : 'mdi:tune'}"
                                style="--mdc-icon-size:16px"
                            ></ha-icon>
                            <span>${this._t('config_advanced_label')}</span>
                        </span>
                    </div>
                    ${this._renderApplyBar()}
                    ${SECTIONS
                        .filter(s => s.id !== 'pv_strings' || this._pvStrings().length >= 2)
                        // (#830) The default view shows what SEM needs to work.
                        // A subsystem the user has already configured stays
                        // visible either way — hiding something someone set up
                        // is not simplification, it is losing their work.
                        .filter(s => this._advanced || ESSENTIAL_SECTIONS.has(s.id)
                                     || this._sectionConfigured(s.id))
                        .map(s => this._renderSection(s, renderers[s.id], T))}
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 12; }
    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-config-card', SEMConfigCard, {
    type: 'sem-config-card',
    name: 'SEM Configuration Card',
    description: 'In-dashboard SEM configuration surface (replaces the Settings → SEM → Configure flow for most users)',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-config-card',
    preview: false,
});
