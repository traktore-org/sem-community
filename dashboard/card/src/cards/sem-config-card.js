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
import { semTheme, semDefineCard } from '../base/sem-shared.js';

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
    'number.sem_battery_auto_start_soc', 'number.sem_battery_assist_floor_soc',
    'number.sem_battery_minimum_soc', 'number.sem_battery_resume_soc',
    'number.sem_cheap_price_threshold', 'number.sem_expensive_price_threshold',
    'number.sem_minimum_solar_power', 'number.sem_maximum_grid_import',
    'number.sem_update_interval', 'number.sem_power_delta',
    'number.sem_current_delta', 'number.sem_soc_delta',
    'switch.sem_observer_mode',
];

class SEMConfigCard extends SEMLitBase {
    static get watchedEntities() { return WATCHED; }

    static get properties() {
        return {
            ...super.properties,
            _showHelp: { state: true },
        };
    }

    constructor() {
        super();
        // Overview open by default; everything else collapsed so the
        // tab doesn't feel overwhelming on first open.
        this._collapsed = {
            overview: false,
            ev_chargers: true, battery_zones: true, tariff: true,
            heat_pump: true, battery_scheduler: true, load_management: true,
            forecast: true, notifications: true, advanced: true,
        };
        this._showHelp = false;
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || 'sensor.sem_';
        this._entryId = config.entry_id || '';  // for HA settings deep-link
    }

    _toggleHelp() { this._showHelp = !this._showHelp; }
    _toggleSection(id) {
        this._collapsed = { ...this._collapsed, [id]: !this._collapsed[id] };
    }

    // ── Entity helpers ──

    _val(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
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

    // ── Subtitles ──

    _overviewSubtitle() {
        const chargers = this._chargersList().length;
        const heatpump = this._val('heat_pump_registered') === 'on';
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
        return this._val('heat_pump_registered') === 'on'
            ? this._t('configured')
            : this._t('not_configured');
    }
    _loadMgmtSubtitle() {
        return this._val('load_management_status') || '';
    }
    _forecastSubtitle() {
        const src = this._val('forecast_source') || '';
        return src ? src : this._t('not_configured');
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

    _renderStepper(entityId, labelKey, T, helpKey) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        const val = parseFloat(entity.state) || 0;
        const step = parseFloat(entity.attributes.step) || 1;
        const unit = entity.attributes.unit_of_measurement || '';
        const decimals = step < 1 ? 1 : 0;
        const displayVal = val.toFixed(decimals) + (unit ? ' ' + unit : '');
        return html`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <span class="stepper-label">${this._t(labelKey)}</span>
                    <div class="stepper-controls">
                        <button class="stepper-minus" @click=${() => this._stepNumber(entityId, -1)}>−</button>
                        <span class="stepper-value">${displayVal}</span>
                        <button class="stepper-plus" @click=${() => this._stepNumber(entityId, 1)}>+</button>
                    </div>
                </div>
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
            </div>
        `;
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

    _renderOverview(T) {
        const dashboardReady = !!this._hass?.states['sensor.sem_charging_state'];
        const chargers = this._chargersList().length;
        const heatpump = this._val('heat_pump_registered') === 'on';
        return html`
            <div class="overview-grid">
                <div class="overview-item">
                    <ha-icon icon="mdi:flash" style="color:#ff9800"></ha-icon>
                    <span>${this._t('config_overview_energy_dashboard')}</span>
                    <span class="overview-status ${dashboardReady ? 'ok' : 'warn'}">${dashboardReady ? '✓' : '!'}</span>
                </div>
                <div class="overview-item">
                    <ha-icon icon="mdi:ev-station" style="color:#5BC8D8"></ha-icon>
                    <span>${this._t('config_overview_chargers')}: ${chargers}</span>
                </div>
                <div class="overview-item">
                    <ha-icon icon="mdi:heat-pump" style="color:#4db6ac"></ha-icon>
                    <span>${this._t('heat_pump_title')}: ${heatpump ? this._t('configured') : this._t('not_configured')}</span>
                </div>
            </div>
            <div class="overview-help">${this._t('config_overview_help')}</div>
            <div class="overview-actions">
                ${this._renderHaSettingsButton('config_open_ha_settings')}
            </div>
        `;
    }

    _renderEvChargers(T) {
        const chargers = this._chargersList();
        if (chargers.length === 0) {
            return html`
                <div class="empty-state">
                    <ha-icon icon="mdi:ev-station-outline" style="--mdc-icon-size:32px;color:#5BC8D8;opacity:0.7"></ha-icon>
                    <div class="empty-title">${this._t('config_ev_no_chargers')}</div>
                    <div class="empty-help">${this._t('config_ev_add_via_settings')}</div>
                    ${this._renderHaSettingsButton('config_ev_add_button')}
                </div>
            `;
        }
        return html`
            ${chargers.map(cid => html`
                <div class="charger-block">
                    <div class="charger-block-title">
                        <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:18px;color:#5BC8D8"></ha-icon>
                        ${this._chargerFriendlyName(cid)}
                    </div>
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_minimum_current`, 'minimum_soc', T, 'tile_help_min_amps')}
                        ${this._renderStepper(`number.sem_charger_${cid}_vehicle_min_current`, 'vehicle_min_current', T, 'tile_help_vehicle_min_amps')}
                    </div>
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${cid}_initial_current`, 'initial_current', T, 'tile_help_start_amps')}
                        ${this._renderStepper(`number.sem_charger_${cid}_ev_battery_capacity_kwh`, 'capacity_kwh', T, 'tile_help_capacity')}
                    </div>
                </div>
            `)}
            <div class="section-footer">
                ${this._renderHaSettingsButton('config_ev_manage')}
            </div>
        `;
    }

    _chargerFriendlyName(cid) {
        const name = this._hass?.states[`number.sem_charger_${cid}_minimum_current`]?.attributes?.friendly_name || cid;
        return name.replace(/\s+Min Amps$/i, '');
    }

    _renderBatteryZones(T) {
        return html`
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_battery_auto_start_soc', 'auto_start_soc', T, 'zone_help_autostart')}
                ${this._renderStepper('number.sem_battery_buffer_soc', 'buffer_soc', T, 'zone_help_buffer')}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_battery_assist_floor_soc', 'assist_floor', T, 'zone_help_floor')}
                ${this._renderStepper('number.sem_battery_priority_soc', 'priority_soc', T, 'zone_help_priority')}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_battery_minimum_soc', 'minimum_soc', T, 'setting_help_minimum_soc')}
                ${this._renderStepper('number.sem_battery_resume_soc', 'resume_soc', T, 'setting_help_resume_soc')}
            </div>
        `;
    }

    _renderTariff(T) {
        const rateEntity = this._hass?.states['sensor.sem_tariff_current_import_rate'];
        const rate = rateEntity ? rateEntity.state : '—';
        const unit = rateEntity?.attributes?.unit_of_measurement || '';
        return html`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t('current_electricity_price')}</span>
                <span class="readonly-value tariff-rate-value">${rate} ${unit}</span>
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_cheap_price_threshold', 'cheap_threshold', T, 'setting_help_cheap_threshold')}
                ${this._renderStepper('number.sem_expensive_price_threshold', 'expensive_threshold', T, 'setting_help_expensive_threshold')}
            </div>
            <div class="section-footer">
                ${this._renderHaSettingsButton('config_tariff_manage')}
            </div>
        `;
    }

    _renderHeatPump(T) {
        const registered = this._val('heat_pump_registered') === 'on';
        if (!registered) {
            return html`
                <div class="empty-state">
                    <ha-icon icon="mdi:heat-pump-outline" style="--mdc-icon-size:32px;color:#4db6ac;opacity:0.7"></ha-icon>
                    <div class="empty-title">${this._t('not_configured')}</div>
                    <div class="empty-help">${this._t('heat_pump_not_configured')}</div>
                    ${this._renderHaSettingsButton('config_heat_pump_setup')}
                </div>
            `;
        }
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('heat_pump_mode')}</span>
                <span class="readonly-value">${this._val('heat_pump_mode') || '—'}</span>
            </div>
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('heat_pump_sg_ready_state')}</span>
                <span class="readonly-value">${this._val('heat_pump_sg_ready_state') || '—'}</span>
            </div>
            ${this._renderStepper('number.sem_heat_pump_boost_offset', 'heat_pump_boost_offset', T)}
            <div class="section-footer">
                ${this._renderHaSettingsButton('config_heat_pump_manage')}
            </div>
        `;
    }

    _renderBatteryScheduler(T) {
        return html`
            <div class="info-box-text">${this._t('config_battery_scheduler_intro')}</div>
            <div class="section-footer">
                ${this._renderHaSettingsButton('config_battery_scheduler_manage')}
            </div>
        `;
    }

    _renderLoadManagement(T) {
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('load_management_status')}</span>
                <span class="readonly-value">${this._val('load_management_status') || '—'}</span>
            </div>
            ${this._renderStepper('number.sem_maximum_grid_import', 'max_grid_import', T, 'tile_help_max_grid_import')}
            <div class="section-footer">
                ${this._renderHaSettingsButton('config_load_management_manage')}
            </div>
        `;
    }

    _renderForecast(T) {
        const src = this._val('forecast_source') || 'none';
        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('forecast_source')}</span>
                <span class="readonly-value">${src}</span>
            </div>
            ${src === 'none' ? html`<div class="overview-help">${this._t('config_forecast_install_hint')}</div>` : nothing}
        `;
    }

    _renderNotifications(T) {
        return html`
            <div class="info-box-text">${this._t('config_notifications_intro')}</div>
            <div class="section-footer">
                ${this._renderHaSettingsButton('config_notifications_manage')}
            </div>
        `;
    }

    _renderAdvanced(T) {
        return html`
            ${this._renderToggle('switch.sem_observer_mode', 'observer_mode', T, 'config_help_observer_mode')}
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_update_interval', 'update_interval', T, 'config_help_update_interval')}
                ${this._renderStepper('number.sem_power_delta', 'power_delta', T, 'config_help_power_delta')}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_current_delta', 'current_delta', T, 'config_help_current_delta')}
                ${this._renderStepper('number.sem_soc_delta', 'soc_delta', T, 'config_help_soc_delta')}
            </div>
            ${this._renderStepper('number.sem_minimum_solar_power', 'min_solar_power', T, 'config_help_min_solar_power')}
        `;
    }

    // ── Section header ──

    _renderSectionHeader(section, T) {
        const collapsed = this._collapsed[section.id];
        const chevronRotate = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
        const subtitle = section.subtitleFn(this);
        return html`
            <div class="section-header" @click=${() => this._toggleSection(section.id)}>
                <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                <span class="section-title-text">${this._t(section.titleKey)}</span>
                <span class="section-subtitle">${subtitle}</span>
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
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(141,200,146,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
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

                .section {
                    margin-bottom: 10px;
                    border-radius: 14px;
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s, box-shadow 0.2s;
                    position: relative;
                }
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${T.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'}; }
                .section-header {
                    display: flex; align-items: center; gap: 10px;
                    padding: 13px 14px; cursor: pointer; user-select: none;
                    transition: background 0.15s;
                }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-title-text {
                    font-size: 15px; font-weight: 600; white-space: nowrap; letter-spacing: 0.1px;
                }
                .section-subtitle {
                    flex: 1; font-size: 13px;
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

                /* Overview tiles */
                .overview-grid { display: flex; flex-direction: column; gap: 6px; margin: 6px 0; }
                .overview-item { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 6px 0; }
                .overview-item span { flex: 1; }
                .overview-status { font-weight: 700; font-size: 14px; }
                .overview-status.ok { color: #8DC892; }
                .overview-status.warn { color: #ff9800; }
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
                .readonly-value {
                    font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums;
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
                .setting-help-text {
                    font-size: 11px; line-height: 1.35;
                    color: var(--secondary-text-color, ${T.textSec});
                    opacity: 0.75; padding: 2px 4px 6px 0; margin-top: -4px;
                    font-style: italic;
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
                ${SECTIONS.map(s => this._renderSection(s, renderers[s.id], T))}
            </div>
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
