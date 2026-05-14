/**
 * SEM Control Card — LitElement migration
 *
 * Consolidated control panel with 8 collapsible sections:
 *   EV Charging · Surplus · Battery · Hot Water · Solar · Tariff · Peak · System
 *
 * Config:
 *   type: custom:sem-control-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const SECTIONS = [
    {
        id: 'ev', icon: 'mdi:ev-station', color: '#8DC892', titleKey: 'ev_charging_title',
        subtitleFn: (c) => {
            const state = c._val('charging_state') || '—';
            const daily = c._valNum('daily_ev_energy').toFixed(1);
            const target = c._numVal('daily_ev_target').toFixed(0);
            return `${state} · ${daily}/${target} kWh`;
        },
    },
    {
        id: 'surplus', icon: 'mdi:solar-power', color: '#ff9800', titleKey: 'surplus_control',
        subtitleFn: (c) => {
            const active = c._valNum('surplus_active_devices').toFixed(0);
            const total = c._valNum('surplus_total_devices').toFixed(0);
            const alloc = c._valNum('surplus_allocated_w').toFixed(0);
            return `${active}/${total} ${c._t('devices')} · ${alloc}W`;
        },
    },
    {
        id: 'battery', icon: 'mdi:battery-medium', color: '#4db6ac', titleKey: 'battery_management',
        subtitleFn: (c) => {
            const soc = c._valNum('battery_soc').toFixed(0);
            const status = c._val('battery_status') || '—';
            return `SOC ${soc}% · ${status}`;
        },
    },
    {
        id: 'hotwater', icon: 'mdi:water-thermometer', color: '#f06292', titleKey: 'hot_water_title',
        subtitleFn: () => '',
    },
    {
        id: 'solar', icon: 'mdi:solar-panel-large', color: '#ff9800', titleKey: 'solar_power_section',
        subtitleFn: () => '',
    },
    {
        id: 'tariff', icon: 'mdi:cash-multiple', color: '#96CAEE', titleKey: 'tariff_pricing',
        subtitleFn: (c) => {
            const provider = c._val('tariff_provider') || '—';
            const level = c._val('tariff_price_level') || '';
            return level ? `${provider} · ${level}` : provider;
        },
    },
    {
        id: 'peak', icon: 'mdi:flash-alert', color: '#ff9800', titleKey: 'peak_load_management',
        subtitleFn: (c) => {
            const peak = c._valNum('consecutive_peak_15min').toFixed(1);
            const monthly = c._valNum('monthly_consecutive_peak').toFixed(1);
            return `${c._t('peak')} ${peak} kW · ${c._t('monthly_peak')} ${monthly} kW`;
        },
    },
    {
        id: 'system', icon: 'mdi:cog-outline', color: '#96CAEE', titleKey: 'system',
        subtitleFn: () => '',
    },
];

/** All entity IDs watched for shouldUpdate comparison. */
const WATCHED = [
    'sensor.sem_charging_state', 'sensor.sem_daily_ev_energy',
    'number.sem_daily_ev_target', 'select.sem_ev_charging_mode',
    'switch.sem_night_charging', 'switch.sem_smart_night_charging',
    'number.sem_ev_night_initial_current', 'number.sem_ev_minimum_current',
    'number.sem_ev_stall_cooldown', 'number.sem_ev_phases',
    'sensor.sem_surplus_active_devices', 'sensor.sem_surplus_total_devices',
    'sensor.sem_surplus_allocated_w', 'sensor.sem_surplus_total_w',
    'sensor.sem_surplus_distributable_w', 'sensor.sem_surplus_unallocated_w',
    'number.sem_regulation_offset',
    'sensor.sem_battery_soc', 'sensor.sem_battery_status',
    'number.sem_battery_priority_soc', 'number.sem_battery_minimum_soc',
    'number.sem_battery_resume_soc', 'sensor.sem_diag_battery_capacity',
    'number.sem_hot_water_solar_target', 'number.sem_legionella_target_temp',
    'number.sem_minimum_solar_power', 'number.sem_maximum_grid_import',
    'sensor.sem_tariff_provider', 'sensor.sem_tariff_price_level',
    'sensor.sem_tariff_current_import_rate',
    'number.sem_cheap_price_threshold', 'number.sem_expensive_price_threshold',
    'sensor.sem_consecutive_peak_15min', 'sensor.sem_monthly_consecutive_peak',
    'sensor.sem_current_vs_peak_percentage', 'sensor.sem_load_management_status',
    'sensor.sem_load_management_recommendation',
    'sensor.sem_peak_margin', 'sensor.sem_available_load_reduction',
    'sensor.sem_controllable_devices_count',
    'switch.sem_observer_mode',
];

class SEMControlCard extends SEMLitBase {
    static get watchedEntities() { return WATCHED; }

    constructor() {
        super();
        // ev + battery + tariff expanded by default; surplus, hotwater, solar, peak, system collapsed
        this._collapsed = {
            ev: false, surplus: true, battery: false,
            hotwater: true, solar: true, tariff: false,
            peak: true, system: true,
        };
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    // ── Entity helpers ──

    /** String state for a sensor.sem_ suffixed entity. */
    _val(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    /** Numeric state for a sensor.sem_ suffixed entity. */
    _valNum(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    /** Numeric state for a number.sem_ suffixed entity. */
    _numVal(suffix, fallback = 0) {
        const e = this._hass?.states[`number.sem_${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    /** Boolean: is switch.sem_<suffix> on? */
    _switchOn(suffix) {
        return this._hass?.states[`switch.sem_${suffix}`]?.state === 'on';
    }

    // ── Section toggle ──

    _toggleSection(id) {
        this._collapsed = { ...this._collapsed, [id]: !this._collapsed[id] };
        this.requestUpdate();
    }

    // ── Shared control renderers ──

    _renderToggle(entityId, labelKey, T) {
        const isOn = this._hass?.states[entityId]?.state === 'on';
        return html`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(labelKey)}</span>
                <div class="toggle-track ${isOn ? 'on' : ''}" @click=${() => this._toggleSwitch(entityId)}>
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `;
    }

    _renderStepper(entityId, labelKey, T) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        const frozen = this._frozenEntities[entityId];
        const val = frozen ? frozen.value : (parseFloat(entity.state) || 0);
        const step = parseFloat(entity.attributes.step) || 1;
        const unit = entity.attributes.unit_of_measurement || '';
        const decimals = step < 1 ? 1 : 0;
        const displayVal = val.toFixed(decimals) + (unit ? ' ' + unit : '');

        return html`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(labelKey)}</span>
                <div class="stepper-controls">
                    <button
                        class="stepper-minus" aria-label="Decrease"
                        @click=${() => this._stepNumber(entityId, -1)}
                        @pointerdown=${() => this._startHold(entityId, -1)}
                        @pointerup=${() => this._stopHold(entityId)}
                        @pointerleave=${() => this._stopHold(entityId)}
                    >−</button>
                    <span class="stepper-value">${displayVal}</span>
                    <button
                        class="stepper-plus" aria-label="Increase"
                        @click=${() => this._stepNumber(entityId, 1)}
                        @pointerdown=${() => this._startHold(entityId, 1)}
                        @pointerup=${() => this._stopHold(entityId)}
                        @pointerleave=${() => this._stopHold(entityId)}
                    >+</button>
                </div>
            </div>
        `;
    }

    _renderSelect(entityId, labelKey, T) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        const frozen = this._frozenEntities[entityId];
        const currentVal = frozen ? frozen.value : entity.state;
        const options = entity.attributes.options || [];

        return html`
            <div class="ctrl-row">
                <span class="ctrl-label">${this._t(labelKey)}</span>
                <select
                    class="sem-select"
                    .value=${currentVal}
                    @change=${(e) => this._selectOption(entityId, e.target.value)}
                >
                    ${options.map(o => html`<option value="${o}" ?selected=${o === currentVal}>${o}</option>`)}
                </select>
            </div>
        `;
    }

    // ── Section content renderers ──

    _renderEvSection(T) {
        const minCurEntity = this._hass?.states['number.sem_ev_minimum_current'];
        const showMinCur = minCurEntity && parseFloat(minCurEntity.state) > 0;
        const phasesEntity = this._hass?.states['number.sem_ev_phases'];
        const showPhases = phasesEntity && parseFloat(phasesEntity.state) > 0;

        return html`
            ${this._renderSelect('select.sem_ev_charging_mode', 'ev_charging_mode', T)}
            <div class="toggle-group">
                ${this._renderToggle('switch.sem_night_charging', 'night_charging', T)}
                ${this._renderToggle('switch.sem_smart_night_charging', 'smart_night', T)}
            </div>
            ${this._renderStepper('number.sem_daily_ev_target', 'night_charge_target', T)}
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_ev_night_initial_current', 'night_start_amps', T)}
                ${showMinCur ? this._renderStepper('number.sem_ev_minimum_current', 'min_current', T) : nothing}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_ev_stall_cooldown', 'stall_cooldown', T)}
                ${showPhases ? this._renderStepper('number.sem_ev_phases', 'charger_phases', T) : nothing}
            </div>
        `;
    }

    _renderSurplusSection(T) {
        const total = this._valNum('surplus_total_w').toFixed(0);
        const dist = this._valNum('surplus_distributable_w').toFixed(0);
        const alloc = this._valNum('surplus_allocated_w').toFixed(0);
        const free = this._valNum('surplus_unallocated_w').toFixed(0);

        return html`
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t('surplus_available')}</span>
                        <span class="info-tile-values">
                            <span>${total}W</span>
                            <span class="info-tile-sep">·</span>
                            <span>${dist}W</span>
                        </span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:chart-pie" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t('surplus_allocation')}</span>
                        <span class="info-tile-values">
                            <span>${alloc}W</span>
                            <span class="info-tile-sep">·</span>
                            <span>${free}W</span>
                        </span>
                    </div>
                </div>
            </div>
            ${this._renderStepper('number.sem_regulation_offset', 'regulation_offset', T)}
        `;
    }

    _renderBatterySection(T) {
        const capacity = this._valNum('diag_battery_capacity');
        const capStr = capacity > 0 ? capacity.toFixed(1) + ' kWh' : '—';

        return html`
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_battery_priority_soc', 'priority_soc', T)}
                ${this._renderStepper('number.sem_battery_minimum_soc', 'minimum_soc', T)}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_battery_resume_soc', 'resume_soc', T)}
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t('capacity_kwh')}</span>
                    <span class="readonly-value">${capStr}</span>
                </div>
            </div>
        `;
    }

    _renderHotWaterSection(T) {
        return html`
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_hot_water_solar_target', 'solar_boost_target', T)}
                ${this._renderStepper('number.sem_legionella_target_temp', 'legionella_target', T)}
            </div>
            <div class="info-box">
                <ha-icon icon="mdi:shield-alert" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                <div>
                    <div class="info-box-title">${this._t('legionella_prevention')}</div>
                    <div class="info-box-text">
                        DE (DVGW W 551): ≥ 60°C · CH (SIA 385/1): ≥ 60°C · AT (ÖNORM B 5019): 60°C / 70°C 3 min
                    </div>
                </div>
            </div>
        `;
    }

    _renderSolarSection(T) {
        return html`
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_minimum_solar_power', 'min_solar', T)}
                ${this._renderStepper('number.sem_maximum_grid_import', 'max_grid_import', T)}
            </div>
        `;
    }

    _renderTariffSection(T) {
        const rateEntity = this._hass?.states['sensor.sem_tariff_current_import_rate'];
        const rate = rateEntity ? rateEntity.state : '—';
        const rateUnit = rateEntity?.attributes?.unit_of_measurement || '';

        return html`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t('current_electricity_price')}</span>
                <span class="readonly-value tariff-rate-value">${rate} ${rateUnit}</span>
            </div>
            <div class="stepper-pair">
                ${this._renderStepper('number.sem_cheap_price_threshold', 'cheap_threshold', T)}
                ${this._renderStepper('number.sem_expensive_price_threshold', 'expensive_threshold', T)}
            </div>
        `;
    }

    _renderPeakSection(T) {
        const peakPct = this._valNum('current_vs_peak_percentage');
        const peakColor = peakPct > 90 ? '#f44336' : peakPct > 70 ? '#ff9800' : '#8DC892';
        const shedDevices = this._valNum('controllable_devices_count').toFixed(0);
        const shed = this._valNum('available_load_reduction');

        return html`
            <div class="peak-hero">
                <span class="peak-pct" style="color:${peakColor}">${peakPct.toFixed(0)}%</span>
                <span class="peak-of-limit">${this._t('of_limit')}</span>
            </div>
            <div class="peak-detail">
                <span class="peak-status">${this._val('load_management_status') || '—'}</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec">${this._val('load_management_recommendation') || ''}</span>
            </div>
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:shield-check" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t('peak_margin')}</span>
                        <span class="info-tile-value">${this._valNum('peak_margin').toFixed(1)} kW</span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:power-plug-off" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t('sheddable')}</span>
                        <span class="info-tile-value">${shed.toFixed(1)} kW · ${shedDevices} ${this._t('devices')}</span>
                    </div>
                </div>
            </div>
        `;
    }

    _renderSystemSection(T) {
        return html`
            <div class="toggle-group">
                ${this._renderToggle('switch.sem_observer_mode', 'observer_mode', T)}
            </div>
        `;
    }

    // ── Section shell ──

    _renderSectionHeader(section, T) {
        const collapsed = this._collapsed[section.id];
        const chevronRotate = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
        return html`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!collapsed}"
                @click=${() => this._toggleSection(section.id)}
                @keydown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._toggleSection(section.id); } }}
            >
                <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                <span class="section-title-text">${this._t(section.titleKey)}</span>
                <span class="section-subtitle">${section.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${chevronRotate}"
                ></ha-icon>
            </div>
        `;
    }

    _renderSection(section, contentFn, T) {
        const collapsed = this._collapsed[section.id];
        return html`
            <div class="section">
                ${this._renderSectionHeader(section, T)}
                <div class="section-content ${collapsed ? '' : 'expanded'}">
                    <div class="section-body">
                        ${contentFn(T)}
                    </div>
                </div>
            </div>
        `;
    }

    // ── Main render ──

    render() {
        if (!this._config) return nothing;

        const T = this._theme();
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';
        const obsOn = this._switchOn('observer_mode');

        const sectionRenderers = {
            ev:       (T) => this._renderEvSection(T),
            surplus:  (T) => this._renderSurplusSection(T),
            battery:  (T) => this._renderBatterySection(T),
            hotwater: (T) => this._renderHotWaterSection(T),
            solar:    (T) => this._renderSolarSection(T),
            tariff:   (T) => this._renderTariffSection(T),
            peak:     (T) => this._renderPeakSection(T),
            system:   (T) => this._renderSystemSection(T),
        };

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }

                /* ── Observer warning ── */
                .observer-warning {
                    display: flex; align-items: center; gap: 10px;
                    border-radius: 12px;
                    background: radial-gradient(ellipse 60% 50% at 50% 40%, rgba(244,67,54,0.12) 0%, transparent 100%);
                    border: 1px solid rgba(244,67,54,0.35);
                    color: #f44336;
                    font-size: 13px; font-weight: 500;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease, margin-bottom 0.3s ease, padding 0.3s ease;
                    max-height: ${obsOn ? '60px' : '0'};
                    opacity: ${obsOn ? '1' : '0'};
                    margin-bottom: ${obsOn ? '12px' : '0'};
                    padding: ${obsOn ? '12px 16px' : '0 16px'};
                }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s;
                }
                .section:hover { border-color: ${isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'}; }

                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${T.surfaceHover}; }
                .section-title-text { font-size: 14px; font-weight: 600; white-space: nowrap; }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${T.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${T.textSec});
                    flex-shrink: 0;
                }

                /* ── Collapsible content ── */
                .section-content {
                    max-height: 0;
                    opacity: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded {
                    max-height: 1000px;
                    opacity: 1;
                }
                .section-body { padding: 0 14px 14px; }

                /* ── Toggle ── */
                .toggle-group {
                    border-bottom: 1px solid ${T.surfaceBorder};
                    margin-bottom: 8px;
                    padding-bottom: 4px;
                }
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                }
                .toggle-label { font-size: 13px; font-weight: 500; }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.18)'};
                    cursor: pointer;
                    transition: background 0.2s;
                    flex-shrink: 0;
                }
                .toggle-track.on { background: ${accent}; }
                .toggle-thumb {
                    position: absolute;
                    top: 2px; left: 2px;
                    width: 20px; height: 20px;
                    border-radius: 50%;
                    background: white;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${T.surfaceBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label { font-size: 13px; font-weight: 500; }
                .sem-select {
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${T.text});
                    padding: 6px 10px;
                    font-size: 13px;
                    font-family: inherit;
                    cursor: pointer;
                    min-width: 120px;
                    outline: none;
                }
                .sem-select:focus { border-color: ${accent}; }
                .sem-select option {
                    background: ${isDark ? '#1e232d' : '#fff'};
                    color: ${isDark ? '#e0e0e0' : '#333'};
                }

                /* ── Number stepper ── */
                .stepper-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .stepper-label {
                    font-size: 13px; font-weight: 500;
                    flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px;
                    border-radius: 8px;
                    border: 1px solid ${T.surfaceBorder};
                    background: ${T.surface};
                    color: var(--primary-text-color, ${T.text});
                    font-size: 16px; font-weight: 600;
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s;
                    user-select: none; -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${T.surfaceHover};
                    border-color: ${accent};
                }
                .stepper-minus:active, .stepper-plus:active {
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.08)'};
                }
                .stepper-value {
                    font-size: 13px; font-weight: 600;
                    min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 16px;
                }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }

                /* ── Read-only row ── */
                .readonly-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .readonly-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .tariff-rate-row {
                    gap: 8px;
                    border-bottom: 1px solid ${T.surfaceBorder};
                    margin-bottom: 8px; padding-bottom: 10px;
                }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${T.text}; }

                /* ── Info tiles (surplus, peak) ── */
                .info-tiles {
                    display: grid; grid-template-columns: 1fr 1fr;
                    gap: 8px; margin: 8px 0;
                }
                .info-tile {
                    display: flex; align-items: flex-start; gap: 8px;
                    padding: 10px; border-radius: 10px;
                    background: ${isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)'};
                    border: 1px solid ${T.surfaceBorder};
                }
                .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
                .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .info-tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    color: var(--secondary-text-color, ${T.textSec});
                    letter-spacing: 0.3px;
                }
                .info-tile-values { font-size: 13px; font-weight: 600; display: flex; gap: 4px; flex-wrap: wrap; }
                .info-tile-value { font-size: 13px; font-weight: 600; }
                .info-tile-sep { color: var(--secondary-text-color, ${T.textSec}); }
                @media (max-width: 480px) { .info-tiles { grid-template-columns: 1fr; } }

                /* ── Info box (legionella) ── */
                .info-box {
                    display: flex; gap: 8px;
                    padding: 10px 12px; border-radius: 10px;
                    background: ${isDark ? 'rgba(255,152,0,0.06)' : 'rgba(255,152,0,0.05)'};
                    border: 1px solid rgba(255,152,0,0.2);
                    margin-top: 8px;
                }
                .info-box ha-icon { flex-shrink: 0; margin-top: 1px; }
                .info-box-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
                .info-box-text {
                    font-size: 11px; line-height: 1.4;
                    color: var(--secondary-text-color, ${T.textSec});
                }

                /* ── Peak hero ── */
                .peak-hero {
                    display: flex; align-items: baseline; justify-content: center;
                    gap: 6px; padding: 4px 0;
                }
                .peak-pct { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .peak-of-limit {
                    font-size: 12px; font-weight: 500;
                    color: var(--secondary-text-color, ${T.textSec});
                    text-transform: uppercase;
                }
                .peak-detail {
                    text-align: center; padding: 0 0 8px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .peak-sep { margin: 0 4px; }
            </style>
            <div class="wrap">
                <div class="observer-warning">
                    <ha-icon icon="mdi:eye-outline" style="--mdc-icon-size:20px;color:#f44336"></ha-icon>
                    <span>${this._t('observer_mode_active')} — ${this._t('observer_mode_readonly')}</span>
                </div>
                ${SECTIONS.map(s => this._renderSection(s, sectionRenderers[s.id], T))}
            </div>
        `;
    }

    getCardSize() { return 12; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-control-card', SEMControlCard, {
    type: 'custom:sem-control-card',
    name: 'SEM Control Card',
    description: 'Consolidated control panel for Solar Energy Management',
    preview: false,
});
