/**
 * SEM Costs Detail Card — LitElement migration
 *
 * Collapsible sections with steppers and toggles for the Costs tab:
 *   - EV Economics (read-only lifetime cost/solar stats)
 *   - Investment (system investment cost stepper)
 *   - Demand Charge (monthly peak, power charge, rate stepper)
 *   - Tariff Rates (current rates + optional static rate steppers)
 *
 * Config:
 *   type: custom:sem-costs-detail-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const DETAIL_SECTIONS = [
    { id: 'ev_econ',    icon: 'mdi:car-electric',       color: '#8DC892', titleKey: 'ev_charging_economics' },
    { id: 'investment', icon: 'mdi:bank',                color: '#96CAEE', titleKey: 'system_investment_cost' },
    { id: 'demand',     icon: 'mdi:flash-triangle',      color: '#ff9800', titleKey: 'demand_charge' },
    { id: 'tariff',     icon: 'mdi:tag-multiple',        color: '#488fc2', titleKey: 'tariff_rates' },
];

class SEMCostsDetailCard extends SEMLitBase {
    static get watchedEntities() {
        return [
            `${DEFAULT_PREFIX}lifetime_ev_energy`,
            `${DEFAULT_PREFIX}lifetime_ev_cost`,
            `${DEFAULT_PREFIX}lifetime_ev_solar_share`,
            'number.sem_system_investment_cost',
            `${DEFAULT_PREFIX}monthly_consecutive_peak`,
            `${DEFAULT_PREFIX}power_charge_cost`,
            'number.sem_demand_charge_rate',
            `${DEFAULT_PREFIX}tariff_current_import_rate`,
            `${DEFAULT_PREFIX}tariff_current_export_rate`,
            `${DEFAULT_PREFIX}tariff_price_level`,
            'number.sem_electricity_import_rate',
            'number.sem_electricity_export_rate',
        ];
    }

    constructor() {
        super();
        this._collapsed = {};
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    /** Read numeric sensor state via prefix */
    _val(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    /** Read string sensor state via prefix */
    _valStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    /** Read number entity (frozen or live) */
    _numVal(entityId, fallback = 0) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value;
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _entityExists(entityId) {
        const e = this._hass?.states[entityId];
        return !!(e && e.state !== 'unavailable' && e.state !== 'unknown');
    }

    _toggleSection(id) {
        this._collapsed = { ...this._collapsed, [id]: !this._collapsed[id] };
        this.requestUpdate();
    }

    _sectionSubtitle(id, curr) {
        if (id === 'ev_econ') {
            const energy = this._val('lifetime_ev_energy');
            if (energy <= 0) return this._t('no_ev_data');
            const cost = this._val('lifetime_ev_cost');
            const share = this._val('lifetime_ev_solar_share');
            const perKwh = energy > 0 ? (cost / energy) : 0;
            return `${perKwh.toFixed(2)} ${curr}/kWh · ${share.toFixed(0)}% solar`;
        }
        if (id === 'investment') {
            const inv = this._numVal('number.sem_system_investment_cost');
            return inv > 0 ? `${inv.toFixed(0)} ${curr}` : '';
        }
        if (id === 'demand') {
            const peak = this._val('monthly_consecutive_peak');
            const charge = this._val('power_charge_cost');
            return `${peak.toFixed(1)} kW · ${charge.toFixed(2)} ${curr}`;
        }
        if (id === 'tariff') {
            const imp = this._val('tariff_current_import_rate');
            const level = this._valStr('tariff_price_level');
            return level ? `${imp.toFixed(4)} ${curr} · ${level}` : `${imp.toFixed(4)} ${curr}`;
        }
        return '';
    }

    _renderStepper(entityId, labelKey) {
        const entity = this._hass?.states[entityId];
        const val = this._numVal(entityId);
        const step = entity ? (parseFloat(entity.attributes.step) || 1) : 1;
        const unit = entity?.attributes?.unit_of_measurement || '';
        const decimals = step < 1 ? 2 : 0;
        const display = val.toFixed(decimals) + (unit ? ' ' + unit : '');

        return html`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(labelKey)}</span>
                <div class="stepper-controls">
                    <button
                        class="stepper-minus"
                        aria-label="Decrease"
                        @click=${() => this._stepNumber(entityId, -1)}
                        @pointerdown=${() => this._startHold(entityId, -1)}
                        @pointerup=${() => this._stopHold(entityId)}
                        @pointerleave=${() => this._stopHold(entityId)}
                    >−</button>
                    <span class="stepper-value">${display}</span>
                    <button
                        class="stepper-plus"
                        aria-label="Increase"
                        @click=${() => this._stepNumber(entityId, 1)}
                        @pointerdown=${() => this._startHold(entityId, 1)}
                        @pointerup=${() => this._stopHold(entityId)}
                        @pointerleave=${() => this._stopHold(entityId)}
                    >+</button>
                </div>
            </div>
        `;
    }

    _renderInfoTile(icon, iconColor, labelKey, value) {
        return html`
            <div class="info-tile">
                <ha-icon icon="${icon}" style="--mdc-icon-size:18px;color:${iconColor}"></ha-icon>
                <div class="info-tile-content">
                    <span class="info-tile-label">${this._t(labelKey)}</span>
                    <span class="info-tile-value">${value}</span>
                </div>
            </div>
        `;
    }

    _renderSectionBody(id, curr) {
        if (id === 'ev_econ') {
            const evEnergy = this._val('lifetime_ev_energy');
            const hasEvData = evEnergy > 0;
            if (!hasEvData) {
                return html`<div class="info-empty">${this._t('no_ev_data')}</div>`;
            }
            const evCost = this._val('lifetime_ev_cost');
            const evShare = this._val('lifetime_ev_solar_share');
            const perKwh = evCost / evEnergy;
            return html`
                <div class="info-tiles">
                    ${this._renderInfoTile('mdi:currency-usd', '#8DC892', 'cost_per_kwh', perKwh.toFixed(4) + ' ' + curr + '/kWh')}
                    ${this._renderInfoTile('mdi:solar-power', '#ff9800', 'solar_share', evShare.toFixed(1) + '%')}
                </div>
            `;
        }

        if (id === 'investment') {
            return html`${this._renderStepper('number.sem_system_investment_cost', 'system_investment_cost')}`;
        }

        if (id === 'demand') {
            const peak = this._val('monthly_consecutive_peak');
            const powerCharge = this._val('power_charge_cost');
            return html`
                <div class="info-tiles">
                    ${this._renderInfoTile('mdi:chart-bell-curve', '#ff9800', 'monthly_peak', peak.toFixed(2) + ' kW')}
                    ${this._renderInfoTile('mdi:currency-usd', '#f06292', 'demand_charge', powerCharge.toFixed(2) + ' ' + curr)}
                </div>
                ${this._renderStepper('number.sem_demand_charge_rate', 'demand_charge_rate')}
            `;
        }

        if (id === 'tariff') {
            const impRateEnt = this._hass?.states['sensor.sem_tariff_current_import_rate'];
            const expRateEnt = this._hass?.states['sensor.sem_tariff_current_export_rate'];
            const priceLevelEnt = this._hass?.states[`${this._prefix}tariff_price_level`];
            const impRate = impRateEnt?.state ?? '—';
            const impUnit = impRateEnt?.attributes?.unit_of_measurement || curr;
            const expRate = expRateEnt?.state ?? '—';
            const expUnit = expRateEnt?.attributes?.unit_of_measurement || curr;
            const priceLevel = priceLevelEnt?.state ?? '—';

            const hasStaticImport = this._entityExists('number.sem_electricity_import_rate');
            const hasStaticExport = this._entityExists('number.sem_electricity_export_rate');

            return html`
                <div class="info-tiles tariff-info-tiles">
                    ${this._renderInfoTile('mdi:transmission-tower-import', '#488fc2', 'current_import_rate', `${impRate} ${impUnit}`)}
                    ${this._renderInfoTile('mdi:transmission-tower-export', '#8353d1', 'current_export_rate', `${expRate} ${expUnit}`)}
                    ${this._renderInfoTile('mdi:signal-cellular-outline', '#96CAEE', 'price_level', priceLevel)}
                </div>
                ${hasStaticImport ? this._renderStepper('number.sem_electricity_import_rate', 'current_import_rate') : nothing}
                ${hasStaticExport ? this._renderStepper('number.sem_electricity_export_rate', 'current_export_rate') : nothing}
            `;
        }

        return nothing;
    }

    _renderSection(section, curr) {
        const collapsed = this._collapsed[section.id];
        const subtitle = this._sectionSubtitle(section.id, curr);

        return html`
            <div class="section">
                <div
                    class="section-header"
                    tabindex="0"
                    role="button"
                    aria-expanded="${!collapsed}"
                    @click=${() => this._toggleSection(section.id)}
                    @keydown=${(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            this._toggleSection(section.id);
                        }
                    }}
                >
                    <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                    <span class="section-title-text">${this._t(section.titleKey)}</span>
                    <span class="section-subtitle">${subtitle}</span>
                    <ha-icon
                        class="chevron"
                        icon="mdi:chevron-down"
                        style="--mdc-icon-size:18px;transform:rotate(${collapsed ? '-90deg' : '0deg'});transition:transform 0.25s ease"
                    ></ha-icon>
                </div>
                ${collapsed ? nothing : html`
                    <div class="section-body">
                        ${this._renderSectionBody(section.id, curr)}
                    </div>
                `}
            </div>
        `;
    }

    render() {
        if (!this._config || !this._hass) return nothing;

        const curr = semGetCurrency(this._hass);

        return html`
            <div class="wrap">
                ${DETAIL_SECTIONS.map(s => this._renderSection(s, curr))}
            </div>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            .wrap {
                padding: 16px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 20%, rgba(240,98,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* ── Sections ── */
            .section {
                margin-bottom: 8px;
                border-radius: 14px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                overflow: hidden;
                transition: border-color 0.2s;
            }
            .section:hover {
                border-color: rgba(255,255,255,0.18);
            }

            .section-header {
                display: flex; align-items: center; gap: 8px;
                padding: 12px 14px;
                cursor: pointer;
                user-select: none;
                -webkit-user-select: none;
                transition: background 0.15s;
            }
            .section-header:hover {
                background: rgba(255,255,255,0.10);
            }
            .section-title-text {
                font-size: 14px; font-weight: 600;
                white-space: nowrap;
            }
            .section-subtitle {
                flex: 1;
                font-size: 12px;
                color: var(--secondary-text-color, #999);
                text-align: right;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                margin-right: 4px;
            }

            .section-body {
                padding: 0 14px 14px;
                overflow: hidden;
            }

            /* ── Number Stepper ── */
            .stepper-row {
                display: flex; align-items: center; justify-content: space-between;
                padding: 7px 0;
            }
            .stepper-label {
                font-size: 13px; font-weight: 500;
                flex: 1; min-width: 0;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .stepper-controls {
                display: flex; align-items: center; gap: 2px;
                flex-shrink: 0;
            }
            .stepper-minus, .stepper-plus {
                width: 30px; height: 30px;
                border-radius: 8px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                color: var(--primary-text-color, #e0e0e0);
                font-size: 16px; font-weight: 600;
                cursor: pointer;
                display: flex; align-items: center; justify-content: center;
                transition: background 0.15s, border-color 0.15s;
                user-select: none;
                -webkit-user-select: none;
                touch-action: manipulation;
                padding: 0; line-height: 1;
            }
            .stepper-minus:hover, .stepper-plus:hover {
                background: rgba(255,255,255,0.10);
                border-color: var(--primary-color, #42a5f5);
            }
            .stepper-value {
                font-size: 13px; font-weight: 600;
                min-width: 60px; text-align: center;
                font-variant-numeric: tabular-nums;
            }

            /* ── Info tiles ── */
            .info-tiles {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin: 8px 0;
            }
            .tariff-info-tiles {
                grid-template-columns: 1fr 1fr 1fr;
            }
            @media (max-width: 480px) {
                .info-tiles { grid-template-columns: 1fr; }
                .tariff-info-tiles { grid-template-columns: 1fr 1fr; }
            }
            .info-tile {
                display: flex; align-items: flex-start; gap: 8px;
                padding: 10px;
                border-radius: 10px;
                background: rgba(255,255,255,0.03);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            }
            .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
            .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .info-tile-label {
                font-size: 11px; font-weight: 500; text-transform: uppercase;
                color: var(--secondary-text-color, #999);
                letter-spacing: 0.3px;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .info-tile-value {
                font-size: 13px; font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            /* ── EV no data ── */
            .info-empty {
                font-size: 13px;
                color: var(--secondary-text-color, #999);
                text-align: center;
                padding: 12px 0;
                font-style: italic;
            }
        `;
    }

    getCardSize() { return 8; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-costs-detail-card', SEMCostsDetailCard, {
    type: 'custom:sem-costs-detail-card',
    name: 'SEM Costs Detail Card',
    description: 'Financial details — EV economics, investment, demand charge, and tariff rates',
    preview: false,
});
