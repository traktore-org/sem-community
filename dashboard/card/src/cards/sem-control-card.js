/**
 * SEM Control Card — LitElement migration
 *
 * Live-operations panel with 6 collapsible sections:
 *   Surplus · Battery · Hot Water · Heat Pump · Tariff · Peak
 *
 * #492: settings de-duplicated to sem-config-card — this card is the
 * monitoring/live-status view; every writable setting lives on the
 * Configuration tab (the cards target the same HA entities, so the
 * live values here always reflect Config-tab changes).
 *
 * Config:
 *   type: custom:sem-control-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

// EV section removed in #282 audit: every control (charging mode, night
// charging, smart night, target, currents, phases, stall cooldown) is
// per-charger now (#193, #255) and presented per-charger on the EV tab.
// Surfacing them again here under a global-looking 'EV Charging' label
// silently controlled only the primary charger in multi-charger setups
// and duplicated the EV tab's UI in single-charger setups.
const SECTIONS = [
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
            const statusRaw = c._val('battery_status') || '';
            const status = statusRaw ? c._t(statusRaw.toLowerCase()) : '—';
            return `SOC ${soc}% · ${status}`;
        },
    },
    {
        id: 'hotwater', icon: 'mdi:water-thermometer', color: '#f06292', titleKey: 'hot_water_title',
        subtitleFn: () => '',
    },
    {
        // #437 — heat pump section, surfaces SG-Ready state, boost
        // offset stepper, and the active mode (SG-Ready vs Climate-only).
        // Auto-hidden when no heat pump is registered (sg_ready_state
        // entity is missing). Visible when the user configured a heat
        // pump in either mode.
        id: 'heatpump', icon: 'mdi:heat-pump', color: '#4db6ac', titleKey: 'heat_pump_title',
        subtitleFn: (c) => {
            // #523: gate on the registered BINARY sensor. sg_ready_state
            // defaults to 2 even with no heat pump, so the old check made
            // the header show "normal · 2" while the body said "not
            // configured" — the contradiction RienduPre reported.
            if (!c._bin('heat_pump_registered')) return '';
            const state = c._val('heat_pump_sg_ready_state');
            const mode = c._val('heat_pump_mode');
            if (!state) return '';
            return `${mode || '—'} · ${state}`;
        },
    },
    {
        id: 'tariff', icon: 'mdi:cash-multiple', color: '#96CAEE', titleKey: 'tariff_pricing',
        subtitleFn: (c) => {
            const provider = c._val('tariff_provider') || '—';
            const level = c._val('tariff_price_level') || '';
            return level ? `${provider} · ${c._t(level.toLowerCase())}` : provider;
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
];

/** All entity IDs watched for shouldUpdate comparison.
 *
 * Cleaned in #282 audit: dropped all EV-related entities now that the EV
 * section has been removed from this card (per-charger controls live on
 * the EV tab via sem-ev-status-card).
 *
 * Pruned again in #492: the 10 settings duplicated on sem-config-card
 * (SOC steppers, price thresholds, solar/grid limits, boost offset,
 * solar-target, observer toggle) render only there now, so their
 * number.* entities are no longer read here. switch.sem_observer_mode
 * stays — the live observer-warning banner reads it.
 */
const WATCHED = [
    'sensor.sem_surplus_active_devices', 'sensor.sem_surplus_total_devices',
    'sensor.sem_surplus_allocated_w', 'sensor.sem_surplus_total_w',
    'sensor.sem_surplus_distributable_w', 'sensor.sem_surplus_unallocated_w',
    'sensor.sem_battery_soc', 'sensor.sem_battery_status',
    'sensor.sem_diag_battery_capacity',
    'number.sem_legionella_target_temp',
    // #437 — heat pump section: registered? mode, sg_ready_state
    'binary_sensor.sem_heat_pump_registered',
    'sensor.sem_heat_pump_sg_ready_state', 'sensor.sem_heat_pump_mode',
    'binary_sensor.sem_heat_pump_solar_boost',
    'sensor.sem_tariff_provider', 'sensor.sem_tariff_price_level',
    'sensor.sem_tariff_current_import_rate',
    'sensor.sem_consecutive_peak_15min', 'sensor.sem_monthly_consecutive_peak',
    'sensor.sem_current_vs_peak_percentage', 'sensor.sem_load_management_status',
    'sensor.sem_load_management_recommendation',
    'sensor.sem_peak_margin', 'sensor.sem_available_load_reduction',
    'sensor.sem_controllable_devices_count',
    'switch.sem_observer_mode',
];

class SEMControlCard extends SEMLitBase {
    static get watchedEntities() { return WATCHED; }

    static get properties() {
        return { ...super.properties };
    }

    constructor() {
        super();
        // battery + tariff expanded by default; surplus, hotwater, heatpump, peak collapsed
        this._collapsed = {
            surplus: true, battery: false,
            hotwater: true, heatpump: true, tariff: false,
            peak: true,
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
        return parseFloat(e.state) ?? fallback;
    }

    /** Numeric state for a number.sem_ suffixed entity. */
    _numVal(suffix, fallback = 0) {
        const e = this._hass?.states[`number.sem_${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    /** Boolean: is switch.sem_<suffix> on? */
    _switchOn(suffix) {
        return this._hass?.states[`switch.sem_${suffix}`]?.state === 'on';
    }

    /** Boolean: is binary_sensor.sem_<suffix> on? (#523)
     * ``_val()`` prepends ``sensor.sem_`` so it silently returns '' for
     * binary_sensor entities — reading ``heat_pump_registered`` (a
     * BINARY sensor) through it always looked "not configured" while the
     * section subtitle (a real sensor) showed it WAS configured. */
    _bin(suffix) {
        return this._hass?.states[`binary_sensor.sem_${suffix}`]?.state === 'on';
    }

    // ── Section toggle ──

    _toggleSection(id) {
        this._collapsed = { ...this._collapsed, [id]: !this._collapsed[id] };
        this.requestUpdate();
    }

    // ── Shared control renderers ──

    _renderStepper(entityId, labelKey, T, helpKey) {
        const entity = this._hass?.states[entityId];
        if (!entity) return nothing;
        const frozen = this._frozenEntities[entityId];
        const val = frozen ? frozen.value : (parseFloat(entity.state) || 0);
        const step = parseFloat(entity.attributes.step) || 1;
        const unit = entity.attributes.unit_of_measurement || '';
        const decimals = step < 1 ? 1 : 0;
        const displayVal = val.toFixed(decimals) + (unit ? ' ' + unit : '');

        return html`
            <div class="stepper-cell">
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
                ${(this._showHelp && helpKey) ? html`<div class="setting-help-text">${this._t(helpKey)}</div>` : nothing}
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
        `;
    }

    _renderBatterySection(T) {
        const capacity = this._valNum('diag_battery_capacity');
        const capStr = capacity > 0 ? capacity.toFixed(1) + ' kWh' : '—';
        // #461: grid-sign read-out only. The fix / re-learn buttons moved
        // to the Configuration tab's Advanced section (the settings home);
        // this card stays live-ops/monitoring.
        const gridSign = this._val('diag_grid_sign') || '—';

        return html`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('capacity_kwh')}</span>
                <span class="readonly-value">${capStr}</span>
            </div>
            <div class="readonly-row">
                <span class="ctrl-label">${this._t('grid_sign')}</span>
                <span class="readonly-value">${gridSign}</span>
            </div>
        `;
    }

    _renderHeatPumpSection(T) {
        // Auto-hide body when no HeatPumpController is registered.
        // sg_ready_state defaults to 2 / "normal" via the dataclass
        // even when no controller exists, so we can't gate on it
        // (reviewer-flagged). Use the explicit ``heat_pump_registered``
        // presence flag (coordinator/types.py:597 + populated in
        // coordinator.py:_run_phase_pipeline from the surplus
        // controller's device list). #523: it's a BINARY sensor — read it
        // via _bin(), not _val() (which prepends sensor.sem_ and always
        // returned '' → false → spurious "not configured").
        const isRegistered = this._bin('heat_pump_registered');
        if (!isRegistered) {
            return html`<div class="info-box-text" style="opacity:0.6">
                ${this._t('heat_pump_not_configured')}
            </div>`;
        }
        const sgStateRaw = this._val('heat_pump_sg_ready_state');
        const mode = this._val('heat_pump_mode') || '—';
        const boosted = this._switchOn('heat_pump_solar_boost');
        const accent = boosted ? '#ff9800' : '#4db6ac';
        return html`
            <div class="readonly-row">
                <ha-icon icon="mdi:heat-pump-outline" style="--mdc-icon-size:18px;color:${accent}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t('heat_pump_mode')}</span>
                <span class="readonly-value">${this._t(mode.toLowerCase()) || mode}</span>
            </div>
            <div class="readonly-row">
                <ha-icon icon="mdi:transmission-tower" style="--mdc-icon-size:18px;color:${accent}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t('heat_pump_sg_ready_state')}</span>
                <span class="readonly-value">${sgStateRaw}</span>
            </div>
        `;
    }

    _renderHotWaterSection(T) {
        // #492: solar_boost_target moved to sem-config-card. The
        // legionella stepper deliberately stays — it's a global number
        // entity with no Config-card equivalent (Config's
        // hot_water_legionella_target is a *different* storage path via
        // set_option; unifying them is the out-of-scope follow-up).
        return html`
            ${this._renderStepper('number.sem_legionella_target_temp', 'legionella_target', T)}
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
                <span class="peak-status">${(() => { const s = this._val('load_management_status'); return s ? this._t(s) : '—'; })()}</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec">${(() => { const r = this._val('load_management_recommendation'); return r ? this._t(r) : ''; })()}</span>
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

    // ── Main render ──

    render() {
        if (!this._config) return nothing;

        const T = this._theme();
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';
        const obsOn = this._switchOn('observer_mode');

        const sectionRenderers = {
            surplus:  (T) => this._renderSurplusSection(T),
            battery:  (T) => this._renderBatterySection(T),
            hotwater: (T) => this._renderHotWaterSection(T),
            heatpump: (T) => this._renderHeatPumpSection(T),
            tariff:   (T) => this._renderTariffSection(T),
            peak:     (T) => this._renderPeakSection(T),
        };

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
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

                /* ── Sections (polish: color accent + EV-card-matching typography) ── */
                .section {
                    margin-bottom: 10px;
                    border-radius: 14px;
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s, box-shadow 0.2s;
                    position: relative;
                }
                /* When expanded: subtle color-coded accent stripe matching the
                   section icon's color, plus a soft glow that ties the card
                   together with the EV card's hint-row aesthetic. */
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${T.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'}; }

                .section-header {
                    display: flex; align-items: center; gap: 10px;
                    padding: 13px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${T.surfaceHover}; }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-title-text {
                    font-size: 15px; font-weight: 600;
                    white-space: nowrap;
                    letter-spacing: 0.1px;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 13px;
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

                .stepper-cell { display: flex; flex-direction: column; }

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${T.surfaceBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${T.text});
                    padding: 6px 10px;
                    font-size: 14px;
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
                    font-size: 14px; font-weight: 500;
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
                    font-size: 14px; font-weight: 600;
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
                    font-size: 14px; font-weight: 600;
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
