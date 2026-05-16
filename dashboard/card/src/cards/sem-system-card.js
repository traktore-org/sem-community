/**
 * SEM System Card — LitElement migration
 *
 * Consolidated system panel with 4 collapsible sections:
 *   System Info · Health Overview · Mode Controls · Diagnostics
 *
 * Config:
 *   type: custom:sem-system-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semCardSurfaceCSS, SEM_COLORS, semDefineCard } from '../base/sem-shared.js';

const SECTIONS = [
    {
        id: 'info',
        icon: 'mdi:information-outline',
        color: '#96CAEE',
        titleKey: 'system_info',
        subtitleFn: (c) => {
            const ver = c._val('diag_version') || '—';
            const mode = c._val('diag_grid_mode') || '—';
            const modeT = mode === 'combined' ? c._t('grid_combined')
                : mode === 'split' ? c._t('grid_split') : mode;
            return `v${ver} · ${modeT}`;
        },
    },
    {
        id: 'health',
        icon: 'mdi:heart-pulse',
        color: '#8DC892',
        titleKey: 'health_overview',
        subtitleFn: (c) => {
            const solar = c._valNum('solar_power').toFixed(0);
            const soc = c._valNum('battery_soc').toFixed(0);
            return `${solar}W solar · SOC ${soc}%`;
        },
    },
    {
        id: 'modes',
        icon: 'mdi:toggle-switch-outline',
        color: '#96CAEE',
        titleKey: 'mode_controls',
        subtitleFn: (c) => {
            const obs = c._switchOn('observer_mode');
            const night = c._switchOn('night_charging');
            return [obs && 'Observer', night && 'Night'].filter(Boolean).join(' · ') || '—';
        },
    },
    {
        id: 'diag',
        icon: 'mdi:bug-outline',
        color: '#ff9800',
        titleKey: 'diagnostics',
        subtitleFn: () => '',
    },
];

const HEALTH_CHIPS = [
    { key: 'solar_power',                icon: 'mdi:solar-power',       color: '#ff9800', suffix: 'W' },
    { key: 'grid_power',                 icon: 'mdi:transmission-tower', color: '#488fc2', suffix: 'W' },
    { key: 'battery_soc',                icon: 'mdi:battery',            color: '#4db6ac', suffix: '%' },
    { key: 'ev_power',                   icon: 'mdi:ev-station',         color: '#8DC892', suffix: 'W' },
    { key: 'forecast_today',             icon: 'mdi:weather-sunny',      color: '#ff9800', suffix: 'kWh' },
    { key: 'tariff_current_import_rate', icon: 'mdi:tag',                color: '#96CAEE', suffix: '' },
];

/** Watched entity IDs for shouldUpdate comparison. */
const WATCHED = [
    'sensor.sem_diag_version', 'sensor.sem_diag_grid_mode',
    'sensor.sem_diag_battery_capacity', 'sensor.sem_diag_update_interval',
    'sensor.sem_diag_charger_count', 'sensor.sem_diag_charger_control_type',
    'sensor.sem_diag_unavailable_sensors',
    'sensor.sem_solar_power', 'sensor.sem_grid_power',
    'sensor.sem_battery_soc', 'sensor.sem_ev_power',
    'sensor.sem_forecast_today', 'sensor.sem_tariff_current_import_rate',
    'switch.sem_observer_mode', 'switch.sem_night_charging',
    'switch.sem_smart_night_charging',
    'sensor.sem_home_consumption_power', 'sensor.sem_grid_import_power',
    'sensor.sem_grid_export_power', 'sensor.sem_autarky_rate',
    'sensor.sem_self_consumption_rate', 'sensor.sem_battery_power',
    'sensor.sem_night_mode', 'sensor.sem_solar_mode', 'sensor.sem_ev_connected',
    'sensor.sem_calculated_current', 'sensor.sem_daily_ev_energy',
    'sensor.sem_daily_ev_target', 'sensor.sem_night_mode_status',
    'sensor.sem_solar_mode_status', 'sensor.sem_battery_status',
    'sensor.sem_grid_status',
];

class SEMSystemCard extends SEMLitBase {
    static get watchedEntities() { return WATCHED; }

    constructor() {
        super();
        // Default: info + health expanded, modes + diag collapsed
        this._collapsed = { info: false, health: false, modes: true, diag: true };
        this._copyFeedback = '';
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    // ── Entity helpers using prefix ──

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

    /** Boolean: is switch.sem_<suffix> on? */
    _switchOn(suffix) {
        return this._hass?.states[`switch.sem_${suffix}`]?.state === 'on';
    }

    /** True if entity exists and is not unavailable/unknown. */
    _available(entityId) {
        const e = this._hass?.states[entityId];
        return !!(e && e.state !== 'unavailable' && e.state !== 'unknown');
    }

    // ── Section toggle ──

    _toggleSection(id) {
        this._collapsed = { ...this._collapsed, [id]: !this._collapsed[id] };
        this.requestUpdate();
    }

    // ── Diagnostics copy ──

    _copyDiagnostics() {
        const ver = this._val('diag_version') || '—';
        const gridMode = this._val('diag_grid_mode') || '—';
        const chargerCount = this._val('diag_charger_count') || '—';
        const controlType = this._val('diag_charger_control_type') || '—';
        const capacity = this._valNum('diag_battery_capacity');
        const capStr = capacity > 0 ? capacity.toFixed(1) : '—';
        const unavailable = this._val('diag_unavailable_sensors') || '0';

        const text = `SEM ${ver} | Grid: ${gridMode} | Chargers: ${chargerCount} (${controlType}) | Battery: ${capStr}kWh | Unavailable: ${unavailable}`;

        navigator.clipboard.writeText(text).then(() => {
            this._copyFeedback = this._t('copied');
            this.requestUpdate();
            setTimeout(() => {
                this._copyFeedback = '';
                this.requestUpdate();
            }, 2000);
        }).catch(err => {
            console.error('[SEM System] clipboard copy failed', err);
        });
    }

    // ── Section renderers ──

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

    _renderInfoSection(T) {
        const cap = this._valNum('diag_battery_capacity');
        const interval = this._valNum('diag_update_interval');
        const chargerCount = this._val('diag_charger_count') || '—';
        const controlType = this._val('diag_charger_control_type') || '';
        const chargersVal = controlType ? `${chargerCount} (${controlType})` : chargerCount;

        return html`
            <div class="info-row">
                <span class="info-row-label">${this._t('version')}</span>
                <span class="info-row-value">${this._val('diag_version') || '—'}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t('grid_mode')}</span>
                <span class="info-row-value">${(() => { const m = this._val('diag_grid_mode') || '—'; return m === 'combined' ? this._t('grid_combined') : m === 'split' ? this._t('grid_split') : m; })()}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t('battery_capacity')}</span>
                <span class="info-row-value">${cap > 0 ? cap.toFixed(1) + ' kWh' : '—'}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t('update_interval')}</span>
                <span class="info-row-value">${interval > 0 ? interval.toFixed(0) + ' s' : '—'}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t('chargers')}</span>
                <span class="info-row-value">${chargersVal}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t('unavailable_sensors')}</span>
                <span class="info-row-value">${this._val('diag_unavailable_sensors') || '0'}</span>
            </div>
        `;
    }

    _renderHealthSection(T) {
        return html`
            <div class="health-chips">
                ${HEALTH_CHIPS.map(chip => {
                    const entityId = `${this._prefix}${chip.key}`;
                    const available = this._available(entityId);
                    const e = this._hass?.states[entityId];
                    const val = e ? e.state : '—';
                    const chipBg = available ? 'rgba(141,200,146,0.12)' : 'rgba(244,67,54,0.12)';
                    const chipBorder = available ? 'rgba(141,200,146,0.3)' : 'rgba(244,67,54,0.3)';
                    return html`
                        <div class="health-chip" style="background:${chipBg};border:1px solid ${chipBorder}">
                            <ha-icon icon="${chip.icon}" style="--mdc-icon-size:16px;color:${chip.color}"></ha-icon>
                            <span class="chip-value">${available ? `${val}${chip.suffix}` : '—'}</span>
                        </div>
                    `;
                })}
            </div>
        `;
    }

    _renderToggle(entityId, labelKey, T) {
        const isOn = this._hass?.states[entityId]?.state === 'on';
        return html`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(labelKey)}</span>
                <div
                    class="toggle-track ${isOn ? 'on' : ''}"
                    @click=${() => this._toggleSwitch(entityId)}
                >
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `;
    }

    _renderModesSection(T) {
        return html`
            <div class="toggle-group">
                ${this._renderToggle('switch.sem_night_charging', 'night_charging', T)}
                ${this._renderToggle('switch.sem_smart_night_charging', 'smart_night', T)}
            </div>
        `;
    }

    _renderDiagBlock(labelKey, value) {
        return html`
            <div class="diag-block">
                <span class="diag-block-label">${this._t(labelKey)}</span>
                <span class="diag-block-text">${value}</span>
            </div>
        `;
    }

    _renderDiagSection(T) {
        const solar = this._valNum('solar_power').toFixed(0);
        const grid = this._valNum('grid_power').toFixed(0);
        const battery = this._valNum('battery_power').toFixed(0);
        const soc = this._valNum('battery_soc').toFixed(0);
        const ev = this._valNum('ev_power').toFixed(0);
        const sourceStr = `Solar ${solar}W · Grid ${grid}W · Battery ${battery}W · SOC ${soc}% · EV ${ev}W`;

        const home = this._valNum('home_consumption_power').toFixed(0);
        const imp = this._valNum('grid_import_power').toFixed(0);
        const exp = this._valNum('grid_export_power').toFixed(0);
        const autarky = this._valNum('autarky_rate').toFixed(0);
        const selfCons = this._valNum('self_consumption_rate').toFixed(0);
        const derivedStr = `Home ${home}W · Import ${imp}W · Export ${exp}W · Autarky ${autarky}% · Self ${selfCons}%`;

        const nightMode = this._val('night_mode') || '—';
        const solarMode = this._val('solar_mode') || '—';
        const calcCurrent = this._val('calculated_current') || '—';
        const dailyEv = this._valNum('daily_ev_energy').toFixed(1);
        const evTarget = this._val('daily_ev_target') || '—';
        const evPlug = this._val('ev_connected') || '—';
        const evStr = `Night mode: ${nightMode} · Solar: ${solarMode} · ${calcCurrent}A · ${dailyEv}/${evTarget}kWh · Plug: ${evPlug}`;

        const nightStatus = this._val('night_mode_status') || '—';
        const solarStatus = this._val('solar_mode_status') || '—';
        const battStatus = this._val('battery_status') || '—';
        const gridStatus = this._val('grid_status') || '—';
        const modesStr = `Night: ${nightStatus} · Solar: ${solarStatus} · Battery: ${battStatus} · Grid: ${gridStatus}`;

        return html`
            ${this._renderDiagBlock('source_sensors', sourceStr)}
            ${this._renderDiagBlock('derived_values', derivedStr)}
            ${this._renderDiagBlock('ev_charging', evStr)}
            ${this._renderDiagBlock('mode_status', modesStr)}
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

    render() {
        if (!this._config) return nothing;

        const T = this._theme();
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';

        const sectionRenderers = {
            info:   (T) => this._renderInfoSection(T),
            health: (T) => this._renderHealthSection(T),
            modes:  (T) => this._renderModesSection(T),
            diag:   (T) => this._renderDiagSection(T),
        };

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background: ${semCardSurfaceCSS(T, SEM_COLORS.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
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
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
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
                .section-body {
                    padding: 0 14px 14px;
                }

                /* ── Info rows ── */
                .info-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                    border-bottom: 1px solid ${T.surfaceBorder};
                }
                .info-row:last-child { border-bottom: none; }
                .info-row-label {
                    font-size: 13px; font-weight: 500;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .info-row-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Health chips ── */
                .health-chips {
                    display: flex; flex-wrap: wrap; gap: 8px;
                    padding: 8px 0 4px;
                }
                .health-chip {
                    display: flex; align-items: center; gap: 6px;
                    padding: 6px 10px;
                    border-radius: 20px;
                    transition: background 0.2s, border-color 0.2s;
                }
                .chip-value {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Toggle ── */
                .toggle-group { padding-top: 2px; }
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 9px 0;
                    border-bottom: 1px solid ${T.surfaceBorder};
                }
                .toggle-row:last-child { border-bottom: none; }
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

                /* ── Diagnostics ── */
                .diag-block {
                    padding: 8px 0;
                    border-bottom: 1px solid ${T.surfaceBorder};
                }
                .diag-block:last-child { border-bottom: none; }
                .diag-block-label {
                    display: block;
                    font-size: 11px; font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${T.textSec});
                    margin-bottom: 3px;
                }
                .diag-block-text {
                    display: block;
                    font-size: 12px; font-weight: 500;
                    line-height: 1.5;
                    word-break: break-word;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Copy button ── */
                .copy-row {
                    margin-top: 10px;
                    display: flex; flex-direction: column; align-items: center; gap: 4px;
                }
                .copy-btn {
                    display: flex; align-items: center; gap: 6px;
                    padding: 8px 18px;
                    border-radius: 10px;
                    border: 1px solid ${T.surfaceBorder};
                    background: ${T.surface};
                    color: var(--primary-text-color, ${T.text});
                    font-size: 13px; font-weight: 600;
                    font-family: inherit;
                    cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .copy-btn:hover { background: ${T.surfaceHover}; border-color: #96CAEE; }
                .copy-btn:active { background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.08)'}; }
                .copy-feedback {
                    font-size: 11px;
                    color: #8DC892;
                    min-height: 16px;
                    transition: opacity 0.3s;
                    opacity: ${this._copyFeedback ? '1' : '0'};
                }

                @media (max-width: 480px) {
                    .health-chips { gap: 6px; }
                    .health-chip { padding: 5px 8px; }
                }
            </style>
            <div class="wrap">
                ${SECTIONS.map(s => this._renderSection(s, sectionRenderers[s.id], T))}
                <div class="copy-row">
                    <button class="copy-btn" @click=${() => this._copyDiagnostics()}>
                        <ha-icon icon="mdi:content-copy" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t('copy_diagnostics')}
                    </button>
                    <span class="copy-feedback">${this._copyFeedback}</span>
                </div>
            </div>
        `;
    }

    getCardSize() { return 8; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-system-card', SEMSystemCard, {
    type: 'custom:sem-system-card',
    name: 'SEM System Card',
    description: 'Consolidated system panel for Solar Energy Management',
    preview: false,
});
