(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Costs Detail Card — Financial details for the Costs tab
 *
 * Replaces mushroom cards on the Costs tab with collapsible sections:
 *   - EV Economics (read-only lifetime cost/solar stats)
 *   - Investment (system investment cost stepper)
 *   - Demand Charge (monthly peak, power charge, rate stepper)
 *   - Tariff Rates (current rates + optional static rate steppers)
 *
 * Config:
 *   type: custom:sem-costs-detail-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

const DETAIL_SECTIONS = [
    {
        id: 'ev_econ', icon: 'mdi:car-electric', color: '#8DC892', titleKey: 'ev_charging_economics',
        subtitleFn: (c) => {
            const energy = c._state('lifetime_ev_energy');
            if (energy <= 0) return c._t('no_ev_data');
            const cost = c._state('lifetime_ev_cost');
            const share = c._state('lifetime_ev_solar_share');
            const curr = semGetCurrency(c._hass);
            const perKwh = energy > 0 ? (cost / energy) : 0;
            return `${perKwh.toFixed(2)} ${curr}/kWh · ${share.toFixed(0)}% solar`;
        },
    },
    {
        id: 'investment', icon: 'mdi:bank', color: '#96CAEE', titleKey: 'system_investment_cost',
        subtitleFn: (c) => {
            const inv = c._numState('system_investment_cost');
            const curr = semGetCurrency(c._hass);
            return inv > 0 ? `${inv.toFixed(0)} ${curr}` : '';
        },
    },
    {
        id: 'demand', icon: 'mdi:flash-triangle', color: '#ff9800', titleKey: 'demand_charge',
        subtitleFn: (c) => {
            const peak = c._state('monthly_consecutive_peak');
            const charge = c._state('power_charge_cost');
            const curr = semGetCurrency(c._hass);
            return `${peak.toFixed(1)} kW · ${charge.toFixed(2)} ${curr}`;
        },
    },
    {
        id: 'tariff', icon: 'mdi:tag-multiple', color: '#488fc2', titleKey: 'tariff_rates',
        subtitleFn: (c) => {
            const imp = c._state('tariff_current_import_rate');
            const level = c._stateStr('tariff_price_level');
            const curr = semGetCurrency(c._hass);
            return level ? `${imp.toFixed(4)} ${curr} · ${level}` : `${imp.toFixed(4)} ${curr}`;
        },
    },
];

class SEMCostsDetailCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
        this._lastKey = '';
        this._collapsed = {};
        this._holdTimers = {};
        this._holdIntervals = {};
        this._frozenEntities = {};
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _numState(suffix, fallback = 0) {
        const entityId = `number.sem_${suffix}`;
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value;
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _entityExists(entityId) {
        const e = this._hass?.states[entityId];
        return !!(e && e.state !== 'unavailable' && e.state !== 'unknown');
    }

    // ── Freeze/thaw pattern ──
    _freezeEntity(entityId, optimisticValue) {
        const existing = this._frozenEntities[entityId];
        if (existing?.timer) clearTimeout(existing.timer);
        this._frozenEntities[entityId] = {
            value: optimisticValue,
            timer: setTimeout(() => {
                delete this._frozenEntities[entityId];
                if (this._hass) this._update();
            }, 1000),
        };
    }

    _isFrozen() { return Object.keys(this._frozenEntities).length > 0; }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        if (this._isFrozen() && !localeChanged) return;

        const watchKeys = [
            'sensor.sem_lifetime_ev_energy', 'sensor.sem_lifetime_ev_cost',
            'sensor.sem_lifetime_ev_solar_share',
            'number.sem_system_investment_cost',
            'sensor.sem_monthly_consecutive_peak', 'sensor.sem_power_charge_cost',
            'number.sem_demand_charge_rate',
            'sensor.sem_tariff_current_import_rate', 'sensor.sem_tariff_current_export_rate',
            'sensor.sem_tariff_price_level',
            'number.sem_electricity_import_rate', 'number.sem_electricity_export_rate',
        ];
        const key = watchKeys.map(k => hass.states[k]?.state || '').join(',');

        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;

        if (!this._rendered || localeChanged) {
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
            this._update();
            requestAnimationFrame(() => { this.style.visibility = ''; });
            return;
        }
        this._update();
    }

    _toggleSection(id) {
        this._collapsed[id] = !this._collapsed[id];
        const section = this.shadowRoot.querySelector(`[data-section="${id}"]`);
        if (!section) return;
        const body = section.querySelector('.section-body');
        const chevron = section.querySelector('.chevron');
        if (this._collapsed[id]) {
            body.style.maxHeight = '0';
            body.style.opacity = '0';
            chevron.style.transform = 'rotate(-90deg)';
        } else {
            body.style.maxHeight = body.scrollHeight + 'px';
            body.style.opacity = '1';
            chevron.style.transform = 'rotate(0deg)';
            setTimeout(() => { if (!this._collapsed[id]) body.style.maxHeight = 'none'; }, 350);
        }
    }

    async _callService(domain, service, data) {
        if (!this._hass) return;
        try {
            await this._hass.callService(domain, service, data);
        } catch (e) {
            console.error('[SEM Costs Detail]', domain, service, data, e);
        }
    }

    _setNumber(entityId, value) {
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const min = parseFloat(entity.attributes.min) ?? 0;
        const max = parseFloat(entity.attributes.max) ?? 100;
        const clamped = Math.max(min, Math.min(max, value));
        this._freezeEntity(entityId, clamped);
        this._callService('number', 'set_value', { entity_id: entityId, value: clamped });
    }

    _stepNumber(entityId, delta) {
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const frozen = this._frozenEntities[entityId];
        const current = frozen ? frozen.value : (parseFloat(entity.state) ?? 0);
        const step = parseFloat(entity.attributes.step) ?? 1;
        this._setNumber(entityId, current + delta * step);
        this._update(); // show optimistic value immediately
    }

    _startHold(entityId, delta) {
        this._stopHold(entityId);
        this._holdTimers[entityId] = setTimeout(() => {
            this._holdIntervals[entityId] = setInterval(() => {
                this._stepNumber(entityId, delta);
            }, 150);
        }, 400);
    }

    _stopHold(entityId) {
        clearTimeout(this._holdTimers[entityId]);
        clearInterval(this._holdIntervals[entityId]);
        delete this._holdTimers[entityId];
        delete this._holdIntervals[entityId];
    }

    _updateStepper(selector, entityId) {
        const el = this.shadowRoot.querySelector(selector);
        if (!el) return;
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const frozen = this._frozenEntities[entityId];
        const val = frozen ? frozen.value : (parseFloat(entity.state) ?? 0);
        const step = parseFloat(entity.attributes.step) ?? 1;
        const unit = entity.attributes.unit_of_measurement || '';
        const valEl = el.querySelector('.stepper-value');
        if (valEl) {
            const decimals = step < 1 ? 2 : 0;
            const text = val.toFixed(decimals) + (unit ? ' ' + unit : '');
            if (valEl.textContent !== text) valEl.textContent = text;
        }
        if (!el._semBound) {
            el._semBound = true;
            const minBtn = el.querySelector('.stepper-minus');
            const plusBtn = el.querySelector('.stepper-plus');
            if (minBtn) {
                minBtn.addEventListener('click', () => this._stepNumber(entityId, -1));
                minBtn.addEventListener('pointerdown', () => this._startHold(entityId, -1));
                minBtn.addEventListener('pointerup', () => this._stopHold(entityId));
                minBtn.addEventListener('pointerleave', () => this._stopHold(entityId));
            }
            if (plusBtn) {
                plusBtn.addEventListener('click', () => this._stepNumber(entityId, 1));
                plusBtn.addEventListener('pointerdown', () => this._startHold(entityId, 1));
                plusBtn.addEventListener('pointerup', () => this._stopHold(entityId));
                plusBtn.addEventListener('pointerleave', () => this._stopHold(entityId));
            }
        }
    }

    _update() {
        if (!this._hass) return;
        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => {
            const el = $(sel);
            if (el && el.textContent !== text) el.textContent = text;
        };
        const curr = semGetCurrency(this._hass);

        // Section subtitles
        for (const s of DETAIL_SECTIONS) {
            setVal(`[data-section="${s.id}"] .section-subtitle`, s.subtitleFn(this));
            setVal(`[data-section="${s.id}"] .section-title-text`, this._t(s.titleKey));
        }

        // ── EV Economics ──
        const evEnergy = this._state('lifetime_ev_energy');
        const evNoData = $('.ev-no-data');
        const evStats = $('.ev-stats');
        const hasEvData = evEnergy > 0;
        const evNoDisplay = hasEvData ? 'none' : '';
        const evStDisplay = hasEvData ? '' : 'none';
        if (evNoData && evNoData.style.display !== evNoDisplay) evNoData.style.display = evNoDisplay;
        if (evStats && evStats.style.display !== evStDisplay) evStats.style.display = evStDisplay;
        if (hasEvData) {
            const evCost = this._state('lifetime_ev_cost');
            const evShare = this._state('lifetime_ev_solar_share');
            const perKwh = evCost / evEnergy;
            setVal('.ev-cost-per-kwh-val', perKwh.toFixed(4) + ' ' + curr + '/kWh');
            setVal('.ev-solar-share-val', evShare.toFixed(1) + '%');
            setVal('.ev-cost-per-kwh-lbl', this._t('cost_per_kwh'));
            setVal('.ev-solar-share-lbl', this._t('solar_share'));
        }
        setVal('.ev-no-data', this._t('no_ev_data'));

        // ── Investment ──
        this._updateStepper('.inv-cost', 'number.sem_system_investment_cost');
        setVal('.inv-cost .stepper-label', this._t('system_investment_cost'));

        // ── Demand Charge ──
        const peak = this._state('monthly_consecutive_peak');
        const powerCharge = this._state('power_charge_cost');
        setVal('.demand-peak-val', peak.toFixed(2) + ' kW');
        setVal('.demand-charge-val', powerCharge.toFixed(2) + ' ' + curr);
        setVal('.demand-peak-lbl', this._t('monthly_peak'));
        setVal('.demand-charge-lbl', this._t('demand_charge'));
        this._updateStepper('.demand-rate', 'number.sem_demand_charge_rate');
        setVal('.demand-rate .stepper-label', this._t('demand_charge_rate'));

        // ── Tariff Rates ──
        const impRateEnt = this._hass.states['sensor.sem_tariff_current_import_rate'];
        const expRateEnt = this._hass.states['sensor.sem_tariff_current_export_rate'];
        const priceLevelEnt = this._hass.states[`${this._prefix}tariff_price_level`];

        const impRate = impRateEnt?.state ?? '—';
        const impUnit = impRateEnt?.attributes?.unit_of_measurement || curr;
        const expRate = expRateEnt?.state ?? '—';
        const expUnit = expRateEnt?.attributes?.unit_of_measurement || curr;
        const priceLevel = priceLevelEnt?.state ?? '—';

        setVal('.tariff-import-val', `${impRate} ${impUnit}`);
        setVal('.tariff-export-val', `${expRate} ${expUnit}`);
        setVal('.tariff-level-val', priceLevel);
        setVal('.tariff-import-lbl', this._t('current_import_rate'));
        setVal('.tariff-export-lbl', this._t('current_export_rate'));
        setVal('.tariff-level-lbl', this._t('price_level'));

        // Conditional static rate steppers
        const hasStaticImport = this._entityExists('number.sem_electricity_import_rate');
        const hasStaticExport = this._entityExists('number.sem_electricity_export_rate');
        const staticImportRow = $('.tariff-static-import-row');
        const staticExportRow = $('.tariff-static-export-row');
        if (staticImportRow) {
            const siDisplay = hasStaticImport ? '' : 'none';
            if (staticImportRow.style.display !== siDisplay) staticImportRow.style.display = siDisplay;
            if (hasStaticImport) {
                this._updateStepper('.tariff-static-import', 'number.sem_electricity_import_rate');
                setVal('.tariff-static-import .stepper-label', this._t('current_import_rate'));
            }
        }
        if (staticExportRow) {
            const seDisplay = hasStaticExport ? '' : 'none';
            if (staticExportRow.style.display !== seDisplay) staticExportRow.style.display = seDisplay;
            if (hasStaticExport) {
                this._updateStepper('.tariff-static-export', 'number.sem_electricity_export_rate');
                setVal('.tariff-static-export .stepper-label', this._t('current_export_rate'));
            }
        }
    }

    _makeStepperHTML(cls, labelKey) {
        return `
            <div class="${cls} stepper-row">
                <span class="stepper-label">${this._t(labelKey)}</span>
                <div class="stepper-controls">
                    <button class="stepper-minus" aria-label="Decrease">−</button>
                    <span class="stepper-value">—</span>
                    <button class="stepper-plus" aria-label="Increase">+</button>
                </div>
            </div>`;
    }

    _makeInfoTileHTML(labelCls, valueCls, icon, iconColor, labelKey) {
        return `
            <div class="info-tile">
                <ha-icon icon="${icon}" style="--mdc-icon-size:18px;color:${iconColor}"></ha-icon>
                <div class="info-tile-content">
                    <span class="${labelCls} info-tile-label">${this._t(labelKey)}</span>
                    <span class="${valueCls} info-tile-value">—</span>
                </div>
            </div>`;
    }

    _makeSectionHTML(section, bodyHTML) {
        const collapsed = this._collapsed[section.id];
        return `
            <div class="section" data-section="${section.id}">
                <div class="section-header" tabindex="0" role="button" aria-expanded="${!collapsed}">
                    <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                    <span class="section-title-text">${this._t(section.titleKey)}</span>
                    <span class="section-subtitle"></span>
                    <ha-icon class="chevron" icon="mdi:chevron-down"
                             style="--mdc-icon-size:18px;transform:rotate(${collapsed ? '-90deg' : '0deg'})"></ha-icon>
                </div>
                <div class="section-body" style="max-height:${collapsed ? '0' : 'none'};opacity:${collapsed ? '0' : '1'}">
                    ${bodyHTML}
                </div>
            </div>`;
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const surfHover = T.surfaceHover || 'rgba(255,255,255,0.10)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';

        // ── EV Economics body ──
        const evBody = `
            <div class="ev-no-data info-empty">${this._t('no_ev_data')}</div>
            <div class="ev-stats" style="display:none">
                <div class="info-tiles">
                    ${this._makeInfoTileHTML('ev-cost-per-kwh-lbl', 'ev-cost-per-kwh-val', 'mdi:currency-usd', '#8DC892', 'cost_per_kwh')}
                    ${this._makeInfoTileHTML('ev-solar-share-lbl', 'ev-solar-share-val', 'mdi:solar-power', '#ff9800', 'solar_share')}
                </div>
            </div>`;

        // ── Investment body ──
        const investBody = `
            ${this._makeStepperHTML('inv-cost', 'system_investment_cost')}`;

        // ── Demand Charge body ──
        const demandBody = `
            <div class="info-tiles">
                ${this._makeInfoTileHTML('demand-peak-lbl', 'demand-peak-val', 'mdi:chart-bell-curve', '#ff9800', 'monthly_peak')}
                ${this._makeInfoTileHTML('demand-charge-lbl', 'demand-charge-val', 'mdi:currency-usd', '#f06292', 'demand_charge')}
            </div>
            ${this._makeStepperHTML('demand-rate', 'demand_charge_rate')}`;

        // ── Tariff Rates body ──
        const tariffBody = `
            <div class="info-tiles tariff-info-tiles">
                ${this._makeInfoTileHTML('tariff-import-lbl', 'tariff-import-val', 'mdi:transmission-tower-import', '#488fc2', 'current_import_rate')}
                ${this._makeInfoTileHTML('tariff-export-lbl', 'tariff-export-val', 'mdi:transmission-tower-export', '#8353d1', 'current_export_rate')}
                ${this._makeInfoTileHTML('tariff-level-lbl', 'tariff-level-val', 'mdi:signal-cellular-outline', '#96CAEE', 'price_level')}
            </div>
            <div class="tariff-static-import-row">
                ${this._makeStepperHTML('tariff-static-import', 'current_import_rate')}
            </div>
            <div class="tariff-static-export-row">
                ${this._makeStepperHTML('tariff-static-export', 'current_export_rate')}
            </div>`;

        const bodies = {
            ev_econ: evBody,
            investment: investBody,
            demand: demandBody,
            tariff: tariffBody,
        };

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(240,98,146,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
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
                .section-header:hover { background: ${surfHover}; }
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${textSecCol});
                    flex-shrink: 0;
                }

                .section-body {
                    padding: 0 14px;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.25s ease;
                }
                .section-body > *:last-child { margin-bottom: 14px; }

                /* ── Number Stepper ── */
                .stepper-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .stepper-label {
                    font-size: 13px; font-weight: 500;
                    flex: 1;
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .stepper-controls {
                    display: flex; align-items: center; gap: 2px;
                    flex-shrink: 0;
                }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px;
                    border-radius: 8px;
                    border: 1px solid ${surfBorder};
                    background: ${surfaceCol};
                    color: var(--primary-text-color, ${textCol});
                    font-size: 16px; font-weight: 600;
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0;
                    line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${surfHover};
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
                    background: ${isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)'};
                    border: 1px solid ${surfBorder};
                }
                .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
                .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .info-tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    color: var(--secondary-text-color, ${textSecCol});
                    letter-spacing: 0.3px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                .info-tile-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── EV no data ── */
                .info-empty {
                    font-size: 13px;
                    color: var(--secondary-text-color, ${textSecCol});
                    text-align: center;
                    padding: 12px 0;
                    font-style: italic;
                }
            </style>
            <div class="wrap">
                ${DETAIL_SECTIONS.map(s => this._makeSectionHTML(s, bodies[s.id])).join('')}
            </div>`;

        // Bind section header clicks
        for (const s of DETAIL_SECTIONS) {
            const header = this.shadowRoot.querySelector(`[data-section="${s.id}"] .section-header`);
            if (header) {
                header.addEventListener('click', () => this._toggleSection(s.id));
                header.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._toggleSection(s.id); }
                });
            }
        }
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

});
