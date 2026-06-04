/**
 * SEM Battery Card — LitElement migration
 *
 * Battery hero card with SOC arc ring, session section, and daily/monthly chips.
 * Matches the Lumina-styled design from the original sem-battery-card.js exactly,
 * but uses Lit reactive rendering instead of innerHTML + manual DOM patching.
 *
 * Config:
 *   type: custom:sem-battery-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semCardSurfaceCSS, SEM_COLORS, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const WATCHED_SUFFIXES = [
    'battery_soc', 'battery_power', 'battery_charge_power', 'battery_discharge_power',
    'battery_status', 'battery_health_score', 'battery_cycles_estimated',
    'battery_temperature', 'battery_session_type', 'battery_session_energy',
    'battery_session_solar_share', 'battery_session_duration', 'battery_session_avg_power',
    'battery_session_cost', 'battery_session_savings',
    'daily_battery_charge_energy', 'daily_battery_discharge_energy', 'daily_battery_savings',
    'flow_solar_to_battery_energy', 'flow_grid_to_battery_energy',
    'monthly_battery_charge_energy', 'monthly_battery_discharge_energy',
];

// Phase B of per-battery card mirror — same shape as the EV card
// ``CHARGER_COLORS`` palette: one stable colour per discovered
// battery, indexed by discovery order. Drawn from the SEM device
// palette so it visually rhymes with the EV side.
const BATTERY_COLORS = ['#4db6ac', '#FFB74D', '#BA68C8', '#64B5F6'];

class SEMBatteryCard extends SEMLitBase {
    constructor() {
        super();
        // Phase B: dynamic per-battery discovery. ``_batteries`` is
        // the list of short slugs found in ``hass.states`` (``b1``,
        // ``b2`` …); empty on single-battery installs so the card
        // renders the legacy hero-only layout unchanged.
        this._batteries = [];
        this._lastStateCount = 0;
    }

    static get watchedEntities() {
        return WATCHED_SUFFIXES.map(s => `${DEFAULT_PREFIX}${s}`);
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    // Override hass setter: key-based comparison since entities are prefix-dynamic
    set hass(hass) {
        this._hass = hass;

        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }

        // Re-discover per-battery sensors when the entity count
        // changes. Single-battery installs find zero matches and the
        // render stays the legacy hero-only layout.
        const stateCount = Object.keys(hass.states).length;
        if (stateCount !== this._lastStateCount) {
            this._lastStateCount = stateCount;
            const batteries = [];
            for (const eid of Object.keys(hass.states)) {
                const m = eid.match(/^sensor\.sem_battery_(b\d+)_power$/);
                if (m) batteries.push(m[1]);
            }
            batteries.sort();
            this._batteries = batteries;
        }

        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen() && !localeChanged) return;

        // Skip transient unavailable states caused by coordinator refresh —
        // async_request_refresh() briefly marks all entities unavailable before
        // new data arrives (~600ms). Rendering during this window shows "Idle".
        const statusState = hass?.states[`${this._prefix}battery_status`]?.state;
        if (statusState === 'unavailable' || statusState === 'unknown') {
            if (!localeChanged) return;
        }

        let key = WATCHED_SUFFIXES
            .map(s => hass?.states[`${this._prefix}${s}`]?.state || '')
            .join(',') + '|' + lang;

        // Per-battery reactivity — re-render whenever any per-battery
        // sensor value changes. No-op on single-battery installs
        // (``_batteries`` is empty).
        if (this._batteries.length) {
            key += '|' + this._batteries.map(bid => [
                `battery_${bid}_power`, `battery_${bid}_soc`,
                `battery_${bid}_status`, `battery_${bid}_capacity_kwh`,
            ].map(s => hass?.states[`${this._prefix}${s}`]?.state || '').join(':')).join('|');
        }

        if (key === this._lastBattKey && !localeChanged) return;
        this._lastBattKey = key;
        this._scheduleUpdate();
    }

    get hass() { return this._hass; }

    /* ── Prefix-scoped helpers ── */
    _val(suffix, fallback = 0) {
        return this._state(`${this._prefix}${suffix}`, fallback);
    }

    _valStr(suffix) {
        return this._stateStr(`${this._prefix}${suffix}`);
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    // Show sub-90-minute sessions as plain minutes ("47 min"); switch
    // to "Hh Mm" once the user is past the point where the minute
    // count stops reading at a glance.
    _fmtDuration(min) {
        if (min == null || isNaN(min)) return '—';
        const m = Math.round(min);
        if (m < 90) return `${m} min`;
        const h = Math.floor(m / 60);
        const rem = m - h * 60;
        return rem === 0 ? `${h} h` : `${h} h ${rem} min`;
    }

    /* ── Per-battery section helpers (Phase B) ── */
    _batteryName(bid) {
        const e = this._hass?.states[`${this._prefix}battery_${bid}_power`];
        let name = bid.toUpperCase();
        if (e?.attributes?.friendly_name) {
            // Strip the SEM prefix + "Power" suffix that HA adds so the
            // section header reads cleanly ("B1" instead of "Battery
            // B1 Power"). Keeps the user's chosen battery name when
            // they override it via the entity registry.
            name = e.attributes.friendly_name
                .replace(/^SEM\s+/i, '')
                .replace(/\s+Power$/i, '');
        }
        return name;
    }

    _renderMiniSocRing(soc, color) {
        const socVal = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
        const r = 22;
        const circumference = 2 * Math.PI * r;
        const offset = circumference * (1 - socVal / 100);
        return html`
            <svg viewBox="0 0 56 56" width="56" height="56"
                 style="display:block;">
                <circle cx="28" cy="28" r="${r}" fill="none"
                        stroke="rgba(255,255,255,0.12)" stroke-width="4" />
                <circle cx="28" cy="28" r="${r}" fill="none"
                        stroke="${color}" stroke-width="4"
                        stroke-linecap="round"
                        stroke-dasharray="${circumference.toFixed(1)}"
                        stroke-dashoffset="${offset.toFixed(1)}"
                        transform="rotate(-90 28 28)" />
                <text x="28" y="32" text-anchor="middle"
                      fill="white" font-size="13" font-weight="700"
                      font-family="'Segoe UI','Roboto',sans-serif"
                      opacity="0.95">
                    ${soc != null ? Math.round(socVal) + '%' : '—'}
                </text>
            </svg>
        `;
    }

    _renderBatterySection(bid, idx) {
        const color = BATTERY_COLORS[idx % BATTERY_COLORS.length];
        const power = this._val(`battery_${bid}_power`, 0);
        const soc = this._val(`battery_${bid}_soc`, null);
        const status = this._valStr(`battery_${bid}_status`) || 'idle';
        const capacity = this._val(`battery_${bid}_capacity_kwh`, 0);
        const name = this._batteryName(bid);

        const statusKey = status === 'charging'
            ? 'charging'
            : status === 'discharging' ? 'discharging' : 'idle';
        const statusColor = status === 'charging' ? '#f06292'
            : status === 'discharging' ? '#4db6ac' : '#999';

        return html`
            <div class="battery-section">
                <div class="battery-section-header">
                    <div class="battery-dot" style="background:${color}"></div>
                    <span class="battery-section-name">${name}</span>
                    <span class="battery-section-status"
                          style="color:${statusColor}">
                        ${this._t(statusKey)}
                    </span>
                </div>
                <div class="battery-section-body">
                    <div class="battery-section-ring">
                        ${this._renderMiniSocRing(soc, color)}
                        <span class="battery-section-soc-label">SOC</span>
                    </div>
                    <div class="battery-section-metrics">
                        <div class="bs-row">
                            <span class="bs-label">${this._t('power')}</span>
                            <span class="bs-val"
                                  style="color:${power > 50 || power < -50 ? color : ''}">
                                ${semFormatPower(Math.abs(power))}
                            </span>
                        </div>
                        ${capacity > 0 ? html`
                            <div class="bs-row">
                                <span class="bs-label">${this._t('capacity')}</span>
                                <span class="bs-val">${this._fmt(capacity, 1)} kWh</span>
                            </div>
                        ` : nothing}
                    </div>
                </div>
            </div>
        `;
    }

    /* ── Render ── */
    render() {
        if (!this._hass || !this._config) return nothing;

        const T = this._theme();
        const circumference = 2 * Math.PI * 42;
        const circumferenceFixed = circumference.toFixed(1);

        // State reads
        const soc = this._val('battery_soc', 0);
        const power = this._val('battery_power', 0);
        const chargePower = this._val('battery_charge_power', 0);
        const dischargePower = this._val('battery_discharge_power', 0);
        const statusRaw = this._valStr('battery_status');
        const health = this._val('battery_health_score', 0);
        const cycles = this._val('battery_cycles_estimated', 0);
        const dailyCharge = this._val('daily_battery_charge_energy', 0);
        const dailyDischarge = this._val('daily_battery_discharge_energy', 0);
        const dailySavings = this._val('daily_battery_savings', 0);
        const monthCharge = this._val('monthly_battery_charge_energy', 0);
        const monthDischarge = this._val('monthly_battery_discharge_energy', 0);
        const solarToBatt = this._val('flow_solar_to_battery_energy', 0);
        const currency = semGetCurrency(this._hass);

        // Temperature — may be unavailable
        const tempEntity = this._hass?.states[`${this._prefix}battery_temperature`];
        const temp = (tempEntity && tempEntity.state !== 'unavailable' && tempEntity.state !== 'unknown')
            ? parseFloat(tempEntity.state) : null;

        // Charge state
        const isCharging = statusRaw === 'charging' || chargePower > 10;
        const isDischarging = statusRaw === 'discharging' || dischargePower > 10;
        const statusText = isCharging ? this._t('charging')
            : isDischarging ? this._t('discharging')
            : this._t('idle');
        const arcColor = isCharging ? '#f06292' : '#4db6ac';
        const statusColor = isCharging ? '#f06292' : isDischarging ? '#4db6ac' : (T.textSec || '#888');
        const glowOpacity = (isCharging || isDischarging) ? '0.5' : '0.2';
        const arcAnim = (isCharging || isDischarging) ? 'socPulse 2s ease-in-out infinite' : 'none';

        // SOC arc
        const pct = Math.min(Math.max(soc / 100, 0), 1);
        const arcOffset = (circumference * (1 - pct)).toFixed(1);

        // Solar attribution
        const solarPct = dailyCharge > 0 ? Math.round(solarToBatt / dailyCharge * 100) : 0;

        // Session
        const sessionType = this._valStr('battery_session_type');
        const sessionActive = sessionType === 'charge' || sessionType === 'discharge';
        const isChargeSess = sessionType === 'charge';
        const sEnergy = sessionActive ? this._val('battery_session_energy', 0) : 0;
        const sDuration = sessionActive ? this._val('battery_session_duration', 0) : 0;
        const sAvgPower = sessionActive ? this._val('battery_session_avg_power', 0) : 0;
        const sSolarShare = sessionActive ? this._val('battery_session_solar_share', 0) : 0;
        const sCost = sessionActive ? this._val('battery_session_cost', 0) : 0;
        const sSavings = sessionActive ? this._val('battery_session_savings', 0) : 0;
        const sessColor = isChargeSess ? '#f06292' : '#4db6ac';

        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.05)';
        const surfHover = T.surfaceHover || 'rgba(255,255,255,0.12)';
        const textSecCol = T.textSec || '#999';
        const chipLblCol = T.textTertiary || '#888';

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${semCardSurfaceCSS(T, SEM_COLORS.battery)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }
                .battery-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .battery-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(77,182,172,0.12); stroke-width: 5; }
                .soc-arc {
                    fill: none; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#batt-glow);
                }
                .glow-ring {
                    fill: none; stroke-width: 8; opacity: 0.2;
                    filter: url(#batt-glow-soft);
                    animation: glowPulse 3s ease-in-out infinite;
                }
                @keyframes glowPulse { 0%,100% { opacity: 0.2; } 50% { opacity: 0.08; } }
                @keyframes socPulse  { 0%,100% { opacity: 1; }   50% { opacity: 0.6; } }
                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .battery-icon { display: block; margin: 0 auto 1px; }
                .soc-value {
                    font-size: 14px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    text-shadow: 0 0 8px rgba(77,182,172,0.3); line-height: 1;
                }
                .metrics-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; gap: 8px;
                }
                .metric-label { font-size: 12px; color: var(--secondary-text-color, ${textSecCol}); font-weight: 500; }
                .metric-val { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; color: #4db6ac; }
                .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${surfHover}); }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color, ${chipLblCol});
                    font-weight: 500; letter-spacing: 0.3px; margin-bottom: 3px;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 9px; color: var(--secondary-text-color, ${chipLblCol}); margin-top: 1px; }
                .session-section {
                    margin-top: 14px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .sess-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
                .sess-title {
                    font-size: 12px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .sess-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
                .sess-item-label { font-size: 10px; color: var(--secondary-text-color, ${chipLblCol}); }
                .sess-item-value {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .monthly-section { display: flex; gap: 8px; margin-top: 10px; }

                /* ── Per-battery sections (Phase B). Same structural
                       shape as the EV card's per-charger sections so
                       a user who already knows the EV tab reads the
                       battery tab without re-learning the layout. ── */
                .battery-sections {
                    margin-top: 16px;
                    display: flex; flex-direction: column;
                    gap: 12px;
                }
                .battery-section {
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    border-radius: 12px;
                    padding: 12px 14px;
                }
                .battery-section-header {
                    display: flex; align-items: center; gap: 8px;
                    margin-bottom: 10px;
                }
                .battery-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .battery-section-name {
                    flex: 1; font-weight: 600; font-size: 0.95em;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .battery-section-status {
                    font-size: 0.75em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-body {
                    display: flex; align-items: center; gap: 12px;
                }
                .battery-section-ring {
                    flex-shrink: 0; width: 56px; text-align: center;
                }
                .battery-section-soc-label {
                    display: block;
                    font-size: 9px; color: ${textSecCol};
                    margin-top: 2px;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-metrics {
                    flex: 1;
                    display: flex; flex-direction: column; gap: 2px;
                }
                .bs-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 1px 0;
                }
                .bs-label {
                    font-size: 10px; color: ${textSecCol};
                    font-weight: 500;
                }
                .bs-val {
                    font-size: 11px; font-weight: 600;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                    font-variant-numeric: tabular-nums;
                }
                /* Phase B mobile breakpoint — single column from the
                   ring + metrics layout collapses to stacked at
                   < 480 px (mirrors the sem-solar-card pattern). */
                @media (max-width: 480px) {
                    .battery-section-body {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .battery-section-ring { margin: 0 auto; }
                }
                .month-chip {
                    flex: 1; text-align: center; padding: 6px 8px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 8px;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="batt-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="${arcColor}" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="batt-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <div class="hero">
                        <div class="battery-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42"
                                    style="stroke:${arcColor};opacity:${glowOpacity}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="soc-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${circumferenceFixed}"
                                    style="stroke-dashoffset:${arcOffset};stroke:${arcColor};animation:${arcAnim}"/>
                            </svg>
                            <div class="ring-center">
                                <svg class="battery-icon" width="16" height="22" viewBox="0 0 20 30"
                                    fill="none" stroke="#4db6ac" stroke-width="1.8" opacity="0.7">
                                    <rect x="2" y="4" width="16" height="26" rx="3"/>
                                    <rect x="6" y="0" width="8" height="5" rx="2"
                                        fill="#4db6ac" opacity="0.5" stroke="none"/>
                                </svg>
                                <div class="soc-value" style="color:${arcColor}">
                                    ${soc.toFixed(0)}%
                                </div>
                            </div>
                        </div>

                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label">${this._t('soc')}</span>
                                <span class="metric-val">${this._fmt(soc, 1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('power')}</span>
                                <span class="metric-val">${semFormatPower(power)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('status')}</span>
                                <span class="metric-val" style="color:${statusColor}">${statusText}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('health')}</span>
                                <span class="metric-val">${this._fmt(health, 1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('cycles')}</span>
                                <span class="metric-val">${this._fmt(cycles, 1)}</span>
                            </div>
                            ${this._batteries.length > 1 ? '' : html`
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('temperature')}</span>
                                    <span class="metric-val">
                                        ${temp != null ? `${this._fmt(temp, 1)} °C` : '—'}
                                    </span>
                                </div>
                            `}
                            <!-- #404: On multi-battery installs (length > 1)
                                 the fleet-tile temperature is hidden because
                                 each battery has its own temperature shown in
                                 its per-battery section. Per RienduPre's UX
                                 confirmation 2026-06-04. Single-battery
                                 installs (today's PROD majority) unchanged. -->
                        </div>
                    </div>

                    ${this._batteries.length >= 1 ? html`
                        <div class="battery-sections">
                            ${this._batteries.map(
                                (bid, idx) => this._renderBatterySection(bid, idx),
                            )}
                        </div>
                    ` : nothing}

                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync"
                                style="--mdc-icon-size:14px;color:${sessionActive ? sessColor : T.textSec}">
                            </ha-icon>
                            <span class="sess-title" style="color:${sessionActive ? sessColor : T.textSec}">
                                ${sessionActive
                                    ? (isChargeSess ? this._t('charging') : this._t('discharging'))
                                    : this._t('idle')}
                            </span>
                        </div>
                        ${sessionActive ? html`
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t('energy')}</div>
                                <div class="sess-item-value">${this._fmt(sEnergy, 2)} kWh</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('duration')}</div>
                                <div class="sess-item-value">${this._fmtDuration(sDuration)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('avg_power')}</div>
                                <div class="sess-item-value">${semFormatPower(sAvgPower)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('source')}</div>
                                <div class="sess-item-value">
                                    ${isChargeSess ? `${this._t('solar')}: ${this._fmt(sSolarShare, 0)}%` : ''}
                                </div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('cost')}</div>
                                <div class="sess-item-value">
                                    ${isChargeSess
                                        ? `${this._fmt(sCost, 2)} ${currency}`
                                        : `${this._t('saved')} ${this._fmt(sSavings, 2)} ${currency}`}
                                </div>
                            </div>
                        </div>
                        ` : html``}
                    </div>

                    <div class="chips">
                        <div class="chip">
                            <div class="chip-label">${this._t('charge_today')}</div>
                            <div class="chip-value c-charge">${this._fmt(dailyCharge, 2)} kWh</div>
                            <div class="chip-src">
                                ${solarPct > 0 ? `${solarPct}% ${this._t('solar')}` : ''}
                            </div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t('discharge_today')}</div>
                            <div class="chip-value c-discharge">${this._fmt(dailyDischarge, 2)} kWh</div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t('savings_today')}</div>
                            <div class="chip-value c-savings">
                                ${this._fmt(dailySavings, 2)} ${currency}
                            </div>
                        </div>
                    </div>

                    <div class="monthly-section">
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t('monthly')} ${this._t('charge')}
                            </div>
                            <div class="chip-value c-charge">${this._fmt(monthCharge, 1)} kWh</div>
                        </div>
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t('monthly')} ${this._t('discharge')}
                            </div>
                            <div class="chip-value c-discharge">${this._fmt(monthDischarge, 1)} kWh</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 3; }

    static getStubConfig() { return {}; }
}

semDefineCard('sem-battery-card', SEMBatteryCard, {
    type: 'sem-battery-card',
    name: 'SEM Battery',
    description: 'Lumina-styled battery hero card with SOC arc ring and key metrics',
});
