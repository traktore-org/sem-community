/**
 * SEM Flow Card — LitElement migration
 *
 * Animated energy flow diagram for Home Assistant. Supports any HA entities
 * (not just SEM) via "entities" config, or SEM prefix via "entity_prefix".
 *
 * Key differences from legacy version:
 * - LitElement render() builds static SVG structure
 * - updated() lifecycle manages flow animations imperatively
 * - ResizeObserver + IntersectionObserver in firstUpdated() / disconnectedCallback()
 * - No semReady wrapper — ES module import
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { unsafeSVG } from 'lit/directives/unsafe-svg.js';
import {
    semTheme, semFormatPower, semCalcDuration, semGetCurrency, semDefineCard,
    SEM_COLORS, SEM_DEVICE_COLORS, SEM_FLOW_ACTIVE_THRESHOLD,
    semDiscoverPVStrings, semPVStringsCSS, semPVStringStatesKey,
} from '../base/sem-shared.js';

/* ── Defaults ── */
const SFC_DEFAULTS = {
    solar:    { nameKey: 'solar',      color: '#ff9800' },
    grid:     { nameKey: 'grid',       color_import: '#488fc2', color_export: '#8353d1' },
    battery:  { nameKey: 'battery',    color: '#4db6ac' },
    home:     { nameKey: 'home',       color: '#5BC8D8' },
    ev:       { nameKey: 'ev_charger', color: '#8DC892' },
    inverter: { nameKey: 'inverter',   color: '#96CAEE' },
};

class SEMFlowCard extends SEMLitBase {
    constructor() {
        super();
        this._lastKey = '';
        this._animFrames = {};
        this._currentValues = {};
        this._compact = false;
        this._visible = true;
        this._deviceConfigSig = '';
        this._devicePositions = [];
        this._updateTimer = null;
        this._resizeObserver = null;
        this._intersectionObserver = null;
        this._resizeTimeout = null;
        this._mode = 'prefix';
        this._prefix = 'sensor.sem_';
        this._entities = null;
    }

    // ── Config ──
    setConfig(config) {
        this._config = config;
        if (config.entity_prefix) {
            this._mode = 'prefix';
            this._prefix = config.entity_prefix;
        } else if (config.entities) {
            this._mode = 'entities';
            this._entities = config.entities;
        } else {
            throw new Error('sem-flow-card requires either "entities" or "entity_prefix" config');
        }
        this._showLabels  = config.show_labels  !== false;
        this._showValues  = config.show_values  !== false;
        this._showGlow    = config.show_glow    !== false;
        this._showInverter = config.show_inverter !== false;
        this.requestUpdate();
    }

    // ── hass setter — debounce flow updates ──
    set hass(hass) {
        const oldLang = this._hass?.language;
        this._hass = hass;
        const lang = hass?.language;
        if (lang !== this._lang) {
            this._lang = lang;
            this.requestUpdate();
            return;
        }
        // v1.7.0 / #312: the per-PV-string chip strip is rendered in
        // Lit's ``render()``, not in the imperative-update path.
        // Without this dirty-check the chips freeze at first render
        // because the only re-render triggers below are language and
        // resize changes. Observed on HA-PROD 2026-06-01: chip values
        // diverged between sem-flow-card and sem-system-diagram-card
        // because each card froze at a different sample time.
        const newPVKey = semPVStringStatesKey(hass, this._prefix);
        if (newPVKey !== this._lastPVKey) {
            this._lastPVKey = newPVKey;
            this.requestUpdate();
            return;
        }
        if (!this._visible) return;
        clearTimeout(this._updateTimer);
        this._updateTimer = setTimeout(() => this._updateFlowsImperative(), 100);
    }

    get hass() { return this._hass; }

    // ── Observers ──
    firstUpdated() {
        this._resizeTimeout = null;
        this._resizeObserver = new ResizeObserver(entries => {
            if (this._resizeTimeout) clearTimeout(this._resizeTimeout);
            this._resizeTimeout = setTimeout(() => {
                for (const entry of entries) {
                    const compact = entry.contentRect.width < 400;
                    if (compact !== this._compact) {
                        this._compact = compact;
                        this._lastKey = '';
                        this._deviceConfigSig = '';
                        this.requestUpdate();
                    }
                }
            }, 100);
        });
        this._resizeObserver.observe(this);

        this._intersectionObserver = new IntersectionObserver(entries => {
            this._visible = entries[0].isIntersecting;
            const svg = this.renderRoot.querySelector('svg');
            if (svg) svg.style.animationPlayState = this._visible ? 'running' : 'paused';
            // Back on-screen → refresh now: hass updates that arrived while
            // hidden were dropped by the _visible gate in set hass.
            if (this._visible && this._hass) this._updateFlowsImperative();
        }, { threshold: 0.01 });
        this._intersectionObserver.observe(this);

        // Display-truth reconcile (same class as sem-system-diagram-card,
        // PROD 2026-07-18 stale iOS nodes): iOS suspends/drops rAF in a
        // backgrounded WebView, freezing value texts while the internal cache
        // advances; a missed intersection transition can also leave _visible
        // stuck false. Re-sync on every app resume.
        this._onVisibility = () => {
            if (document.visibilityState === 'visible' && this._hass) {
                this._visible = true;
                this._updateFlowsImperative();
            }
        };
        document.addEventListener('visibilitychange', this._onVisibility);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
        if (this._intersectionObserver) { this._intersectionObserver.disconnect(); this._intersectionObserver = null; }
        clearTimeout(this._updateTimer);
        clearTimeout(this._resizeTimeout);
        if (this._onVisibility) {
            document.removeEventListener('visibilitychange', this._onVisibility);
            this._onVisibility = null;
        }
        for (const id of Object.keys(this._animFrames)) cancelAnimationFrame(this._animFrames[id]);
        this._animFrames = {};
    }

    // ── Lit lifecycle: run imperative updates after each render ──
    updated() {
        this._setupClickHandlers();
        this._updateFlowsImperative();
    }

    // ── Static CSS ──
    static get styles() {
        return css`
            :host { display: block; }
            ha-card {
                overflow: hidden; padding: 0;
                background: var(--ha-card-background, var(--card-background-color, transparent)) !important;
                border-radius: var(--ha-card-border-radius, 12px);
            }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .glow-ring { transition: opacity 1s ease; }
            #soc-arc, #autarky-arc { transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1), stroke 1s ease; }
            text { font-variant-numeric: tabular-nums; }
            @keyframes socPulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
            @keyframes socDrain { 0%,100%{opacity:0.75} 50%{opacity:0.4} }
            .clickable-node { cursor: pointer; pointer-events: bounding-box; }
            .clickable-node:hover { opacity: 0.85; }
            .device-clickable { cursor: pointer; }
            .device-clickable:hover { opacity: 0.85; }
        `;
    }

    // ── Main render — returns static SVG structure ──
    render() {
        if (!this._config) return nothing;

        const L = this._getLayout();
        const S = L.solar, I = L.inverter, B = L.battery, G = L.grid, H = L.home, E = L.ev;
        const socCirc = (2 * Math.PI * L.socR).toFixed(1);
        const autarkyCirc = (2 * Math.PI * L.autarkyR).toFixed(1);
        const fl = L.font.label, fv = L.font.value, fs = L.font.sub, fhv = L.font.homeVal;
        const F = "'Segoe UI','Roboto',sans-serif";

        const gridImportColor = this._getNodeColor('grid_import');
        const gridExportColor = this._getNodeColor('grid_export');
        const solarColor      = this._getNodeColor('solar');
        const batteryColor    = this._getNodeColor('battery');
        const homeColor       = this._getNodeColor('home');
        const evColor         = this._getNodeColor('ev');
        const invColor        = SFC_DEFAULTS.inverter.color;

        const hasSolar   = this._hasNode('solar');
        const hasBattery = this._hasNode('battery');
        const hasGrid    = this._hasNode('grid');
        const hasEv      = this._hasNode('ev');
        const hasInverter = this._showInverter && this._hasNode('inverter');

        // v1.7.1 / #312: per-PV-string chip strip — auto-shown when
        // ≥ 2 strings exist (gated on v1.7.0 sensor discovery). Sits
        // above the SVG flow diagram, doesn't change the diagram layout.
        const pvStrings = semDiscoverPVStrings(this._hass, this._prefix);

        // Build SVG as tagged-template string (inside html``)
        return html`
            <ha-card>
                <style>${semPVStringsCSS}</style>
                ${pvStrings.length >= 2 ? html`
                    <div class="pv-strings-row">
                        ${pvStrings.map(s => html`
                            <div class="pv-chip"
                                 title="${s.entityId}"
                                 data-entity="${s.entityId}"
                                 @click=${() => this._fireMoreInfo?.(s.entityId)}>
                                <span class="pv-chip-label">${s.name}</span>
                                <span class="pv-chip-value">${(Math.abs(s.watts)/1000).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                ` : nothing}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${L.vb}" style="background:transparent">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="45%" r="60%">
                            <stop offset="0%" style="stop-color:var(--primary-text-color,#c8dcf0);stop-opacity:0.04"/>
                            <stop offset="100%" style="stop-color:transparent;stop-opacity:0"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                            <circle cx="25" cy="25" r="0.7" fill="var(--secondary-text-color,#808080)" opacity="0.12"/>
                        </pattern>
                        ${this._svgRaw(this._glowFilter('glowSolar',      solarColor,      8))}
                        ${this._svgRaw(this._glowFilter('glowBattery',    batteryColor,    8))}
                        ${this._svgRaw(this._glowFilter('glowGridImport', gridImportColor, 8))}
                        ${this._svgRaw(this._glowFilter('glowGridExport', gridExportColor, 8))}
                        ${this._svgRaw(this._glowFilter('glowHome',       homeColor,       10))}
                        ${this._svgRaw(this._glowFilter('glowEV',         evColor,         8))}
                        ${this._svgRaw(this._glowFilter('glowInverter',   invColor,        6))}
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%"  fill="url(#dotGrid)"/>

                    ${this._svgRaw(hasSolar ? this._track(L.paths.solar, solarColor) : '')}
                    ${this._svgRaw(hasSolar || hasInverter ? this._track(L.paths.home, homeColor) : '')}
                    ${this._svgRaw(hasBattery ? this._track(L.paths.battery, batteryColor) : '')}
                    ${this._svgRaw(hasGrid ? `<path id="track-grid" d="${L.paths.grid}" fill="none" stroke="${gridImportColor}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>` : '')}
                    ${this._svgRaw(hasEv ? this._track(L.paths.ev, evColor) : '')}

                    ${this._svgRaw(hasSolar ? `<g id="flow-solar" class="flow-group" style="opacity:0" data-path-d="${L.paths.solar}" data-color="${solarColor}" data-count="2"></g>` : '')}
                    ${this._svgRaw(hasBattery ? `<g id="flow-battery" class="flow-group" style="opacity:0" data-path-d="${L.paths.battery}" data-color="${batteryColor}" data-count="3"></g>` : '')}
                    ${this._svgRaw(hasGrid ? `<g id="flow-grid" class="flow-group" style="opacity:0" data-path-d="${L.paths.grid}" data-color="${gridImportColor}" data-count="3"></g>` : '')}
                    ${this._svgRaw(hasSolar || hasInverter ? `<g id="flow-home" class="flow-group" style="opacity:0" data-path-d="${L.paths.home}" data-color="${homeColor}" data-count="2"></g>` : '')}
                    ${this._svgRaw(hasEv ? `<g id="flow-ev" class="flow-group" style="opacity:0" data-path-d="${L.paths.ev}" data-color="${evColor}" data-count="3"></g>` : '')}

                    ${this._svgRaw(hasSolar ? `
                    <g id="node-solar" filter="url(#glowSolar)">
                        ${this._glowRing(S, solarColor)}
                        <circle cx="${S.cx}" cy="${S.cy}" r="${S.r}" fill="${this._hexToRgba(solarColor, 0.07)}" stroke="${solarColor}" stroke-width="1.8"/>
                        <g transform="translate(${S.cx},${S.cy - 8})" stroke="${solarColor}" fill="none" opacity="0.75">
                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>
                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>
                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>
                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>
                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>
                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>
                        </g>
                    </g>
                    <text x="${S.cx}" y="${S.cy + S.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${solarColor}">${this._escSvg(this._getNodeName('solar'))}</text>
                    <text id="val-solar" x="${S.cx}" y="${S.cy + S.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${solarColor}">0 W</text>
                    <text id="val-today-solar" x="${S.cx}" y="${S.cy + S.r + 18 + fv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${solarColor}" opacity="0.7">\u00A0</text>
                    ` : '')}

                    ${this._svgRaw(hasInverter ? `
                    <g id="node-inverter" filter="url(#glowInverter)">
                        <circle cx="${I.cx}" cy="${I.cy}" r="${I.r}" fill="${this._hexToRgba(invColor, 0.07)}" stroke="${invColor}" stroke-width="1"/>
                        <path d="M${I.cx - 10},${I.cy} Q${I.cx - 4},${I.cy - 8} ${I.cx},${I.cy} Q${I.cx + 4},${I.cy + 8} ${I.cx + 10},${I.cy}" fill="none" stroke="${invColor}" stroke-width="1.8" opacity="0.7"/>
                    </g>
                    <text id="val-inverter-status" x="${I.cx}" y="${I.cy + I.r + 14}" text-anchor="middle" font-family="${F}" font-size="${this._compact ? 11 : 10}" fill="var(--secondary-text-color,#5a7a9a)" opacity="0.7">\u00A0</text>
                    ` : '')}

                    ${this._svgRaw(hasBattery ? `
                    <g id="node-battery" filter="url(#glowBattery)">
                        ${this._glowRing(B, batteryColor)}
                        <circle cx="${B.cx}" cy="${B.cy}" r="${B.r}" fill="${this._hexToRgba(batteryColor, 0.07)}" stroke="${batteryColor}" stroke-width="1.8"/>
                        <circle cx="${B.cx}" cy="${B.cy}" r="${L.socR}" fill="none" stroke="${this._hexToRgba(batteryColor, 0.1)}" stroke-width="5"/>
                        <circle id="soc-arc" cx="${B.cx}" cy="${B.cy}" r="${L.socR}" fill="none" stroke="${batteryColor}" stroke-width="5"
                                stroke-dasharray="${socCirc}" stroke-dashoffset="${socCirc}"
                                transform="rotate(-90 ${B.cx} ${B.cy})" stroke-linecap="round" opacity="0.75"/>
                        <g transform="translate(${B.cx},${B.cy}) scale(0.8)" stroke="${batteryColor}" fill="none" opacity="0.7">
                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>
                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="${batteryColor}" opacity="0.5" stroke="none"/>
                        </g>
                    </g>
                    <text x="${B.cx}" y="${B.cy + B.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${batteryColor}">${this._escSvg(this._getNodeName('battery'))}</text>
                    <text id="val-battery-soc" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${batteryColor}">0%</text>
                    <text id="val-battery-power" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="500" fill="${batteryColor}" opacity="0.7">0 W</text>
                    <text id="label-battery-state" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${batteryColor}" opacity="0.7"></text>
                    <text id="val-today-battery" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl * 2 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${batteryColor}" opacity="0.65">\u00A0</text>
                    ` : '')}

                    ${this._svgRaw(hasGrid ? `
                    <g id="node-grid" filter="url(#glowGridImport)">
                        ${this._glowRing(G, gridImportColor)}
                        <circle id="grid-circle" cx="${G.cx}" cy="${G.cy}" r="${G.r}" fill="${this._hexToRgba(gridImportColor, 0.07)}" stroke="${gridImportColor}" stroke-width="1.8"/>
                        <g id="grid-icon" transform="translate(${G.cx},${G.cy})" stroke="${gridImportColor}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">
                            <line x1="0" y1="-16" x2="0" y2="14"/>
                            <line x1="-10" y1="-8" x2="10" y2="-8"/>
                            <line x1="-7" y1="-1" x2="7" y2="-1"/>
                            <line x1="-10" y1="-8" x2="-5" y2="14"/>
                            <line x1="10" y1="-8" x2="5" y2="14"/>
                        </g>
                    </g>
                    <text x="${G.cx}" y="${G.cy + G.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${gridImportColor}">${this._escSvg(this._getNodeName('grid'))}</text>
                    <text id="val-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${gridImportColor}">0 W</text>
                    <text id="label-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9 + fl}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="500" fill="${gridImportColor}" opacity="0.7">GRID</text>
                    <text id="val-today-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9 + fl + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${gridImportColor}" opacity="0.65">\u00A0</text>
                    ` : '')}

                    <g id="node-home" filter="url(#glowHome)">
                        ${this._svgRaw(this._glowRing(H, homeColor, 1.4))}
                        <circle cx="${H.cx}" cy="${H.cy}" r="${H.r}" fill="${this._hexToRgba(homeColor, 0.06)}" stroke="${homeColor}" stroke-width="2"/>
                        <circle cx="${H.cx}" cy="${H.cy}" r="${L.autarkyR}" fill="none" stroke="${this._hexToRgba(homeColor, 0.08)}" stroke-width="4"/>
                        <circle id="autarky-arc" cx="${H.cx}" cy="${H.cy}" r="${L.autarkyR}" fill="none" stroke="#4CAF50" stroke-width="4"
                                stroke-dasharray="${autarkyCirc}" stroke-dashoffset="${autarkyCirc}"
                                transform="rotate(-90 ${H.cx} ${H.cy})" stroke-linecap="round" opacity="0"/>
                        <g transform="translate(${H.cx},${H.cy - 5})" stroke="${homeColor}" fill="none" opacity="0.6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M-20,2 L0,-14 L20,2"/>
                            <rect x="-14" y="2" width="28" height="20" rx="2"/>
                            <rect x="-4" y="10" width="8" height="12"/>
                        </g>
                    </g>
                    <text x="${H.cx}" y="${H.cy + H.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl + 1}" font-weight="600" fill="${homeColor}">${this._escSvg(this._getNodeName('home'))}</text>
                    <text id="val-home" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fhv}" font-weight="700" fill="${homeColor}">0 W</text>
                    <text id="val-autarky" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${homeColor}" opacity="0.7">\u00A0</text>
                    <text id="val-today-home" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9 + (fs + 4) * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${homeColor}" opacity="0.65">\u00A0</text>

                    ${this._svgRaw(hasEv ? `
                    <g id="node-ev" filter="url(#glowEV)">
                        ${this._glowRing(E, evColor)}
                        <circle cx="${E.cx}" cy="${E.cy}" r="${E.r}" fill="${this._hexToRgba(evColor, 0.07)}" stroke="${evColor}" stroke-width="1.8"/>
                        <g transform="translate(${E.cx},${E.cy})" stroke="${evColor}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>
                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>
                            <path d="M-1,-1 L0,3 L1,-1"/>
                            <line x1="0" y1="9" x2="0" y2="13"/>
                            <circle cx="0" cy="15" r="1.5" fill="${evColor}" opacity="0.4" stroke="none"/>
                        </g>
                    </g>
                    <text x="${E.cx}" y="${E.cy + E.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${evColor}">${this._escSvg(this._getNodeName('ev'))}</text>
                    <text id="val-ev" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${evColor}">0 W</text>
                    <text id="val-today-ev" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${evColor}" opacity="0.65">\u00A0</text>
                    <text id="val-ev-subtitle" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9 + (fs + 4) * 2}" text-anchor="middle" font-family="${F}" font-size="${fs - 1}" fill="${evColor}" opacity="0.6"></text>
                    ` : '')}

                    <g id="device-labels"></g>

                    <text x="${this._compact ? 470 : 960}" y="${this._compact ? 1050 : 770}" text-anchor="end"
                          font-family="${F}" font-size="10" font-weight="300" letter-spacing="2"
                          fill="var(--secondary-text-color,#808080)" opacity="0.15">SEM</text>
                </svg>
            </ha-card>
        `;
    }

    // ── svg raw helper (bypasses Lit's text-node escaping for SVG markup strings) ──
    _svgRaw(str) {
        if (!str) return nothing;
        return unsafeSVG(str);
    }

    // ── HTML escape helper for user-controlled strings injected into SVG innerHTML ──
    _escSvg(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ── Imperative flow update (called from updated()) ──
    _updateFlowsImperative() {
        if (!this._hass) return;

        let solar = this._getState('solar_power');
        if (this._entities?.solar?.reverse) solar = -solar;

        let battery;
        if (this._mode === 'entities' && (this._entities?.battery?.charge || this._entities?.battery?.discharge)) {
            battery = this._getState('battery_charge_power') - this._getState('battery_discharge_power');
        } else {
            let raw = this._getState('battery_power');
            battery = this._entities?.battery?.reverse ? -raw : raw;
        }

        let gridImport, gridExport;
        if (this._mode === 'entities' && this._entities?.grid?.entity) {
            const gp = this._getState('grid_power');
            const rev = this._entities.grid.reverse;
            gridImport = Math.max(0, rev ? -gp : gp);
            gridExport = Math.max(0, rev ? gp : -gp);
        } else {
            gridImport = this._getState('grid_import_power');
            gridExport = this._getState('grid_export_power');
        }

        let ev = this._getState('ev_power');
        if (this._entities?.ev?.invert) ev = -ev;
        const soc     = this._getState('battery_soc');
        const autarky = this._getState('autarky_rate');

        const battCharge    = Math.max(0, battery);
        const battDischarge = Math.max(0, -battery);

        const homeEId = this._getEntityId('home_consumption_power');
        let home;
        if (homeEId && this._hass?.states[homeEId]) {
            home = this._getState('home_consumption_power');
            if (this._entities?.home?.invert) home = -home;
        } else {
            home = Math.max(0, solar + gridImport + battDischarge - gridExport - battCharge - ev);
        }

        const dailySolar      = this._getStateStr('daily_solar_energy');
        const dailyEv         = this._getStateStr('daily_ev_energy');
        const dailyGridImport = this._getStateStr('daily_grid_import_energy');
        const dailyGridExport = this._getStateStr('daily_grid_export_energy');
        const dailyBattery    = this._getStateStr('daily_battery_energy');
        const dailyHome       = this._getStateStr('daily_home_energy');

        const vals = { solar, battery, gridImport, gridExport, home, ev, soc, autarky,
                       dailySolar, dailyEv, dailyGridImport, dailyGridExport, dailyBattery, dailyHome };
        const key = JSON.stringify(vals);
        if (this._lastKey === key) return;
        this._lastKey = key;

        // Animated values
        this._animateValue('val-solar', solar);

        const battPrefix = battery > 10 ? '\u25BC ' : (battery < -10 ? '\u25B2 ' : '');
        this._animateValue('val-battery-power', Math.abs(battery), 800,
            w => battPrefix + semFormatPower(w));

        const isImport = gridImport > gridExport;
        const gridPrefix = isImport ? '\u2193 ' : (gridExport > 10 ? '\u2191 ' : '');
        this._animateValue('val-grid', isImport ? gridImport : gridExport, 800,
            w => gridPrefix + semFormatPower(w));

        this._animateValue('val-home', home);
        this._animateValue('val-ev', ev);

        const evCount = this._getState('ev_charger_count');
        this._setText('val-ev-subtitle', evCount > 1 ? `(${evCount} ${this._t('chargers')})` : '');

        this._animateValue('val-battery-soc', soc, 800, v => `${v.toFixed(0)}%`);

        const autarkyEntity = this._getEntityId('autarky_rate');
        if (autarkyEntity) {
            this._animateValue('val-autarky', autarky, 800, v => `\u26A1 ${v.toFixed(0)}% self`);
        }

        this._setText('val-inverter-status', this._getStateStr('charging_state'));

        const _today = this._t('today');
        this._setText('val-today-solar',   dailySolar   ? `${_today} ${dailySolar} kWh`   : '');
        this._setText('val-today-ev',      dailyEv      ? `${_today} ${dailyEv} kWh`      : '');
        this._setText('val-today-battery', dailyBattery ? `${_today} ${dailyBattery} kWh` : '');
        this._setText('val-today-home',    dailyHome    ? `${_today} ${dailyHome} kWh`    : '');

        const gridParts = [];
        if (dailyGridImport) gridParts.push(`\u2193${dailyGridImport}`);
        if (dailyGridExport) gridParts.push(`\u2191${dailyGridExport}`);
        if (dailyGridImport && dailyGridExport) {
            const net = (parseFloat(dailyGridImport) - parseFloat(dailyGridExport)).toFixed(1);
            gridParts.push(`Net ${net > 0 ? '+' : ''}${net}`);
        }
        this._setText('val-today-grid', gridParts.length ? gridParts.join(' ') + ' kWh' : '');

        // SOC arc
        const L = this._getLayout();
        const socArc = this.renderRoot.getElementById('soc-arc');
        if (socArc) {
            const circ = 2 * Math.PI * L.socR;
            socArc.style.strokeDashoffset = (circ * (1 - soc / 100)).toFixed(1);
            socArc.style.animation = battCharge > 10
                ? 'socPulse 2s ease-in-out infinite'
                : battDischarge > 10 ? 'socDrain 2.5s ease-in-out infinite' : 'none';
        }

        // Autarky arc
        const autarkyArc = this.renderRoot.getElementById('autarky-arc');
        if (autarkyArc && autarkyEntity && autarky > 0) {
            const circ = 2 * Math.PI * L.autarkyR;
            autarkyArc.style.strokeDashoffset = (circ * (1 - autarky / 100)).toFixed(1);
            autarkyArc.style.stroke   = this._autarkyColor(autarky);
            autarkyArc.style.opacity  = '0.75';
        } else if (autarkyArc) {
            autarkyArc.style.opacity = '0';
        }

        // Grid color update
        const gridColor = isImport
            ? this._getNodeColor('grid_import')
            : (gridExport > 10 ? this._getNodeColor('grid_export') : this._getNodeColor('grid_import'));
        this._updateGridColor(gridColor, isImport);

        // Grid label
        const gridLabel = this.renderRoot.getElementById('label-grid');
        if (gridLabel) {
            gridLabel.textContent = isImport
                ? this._t('importing')
                : (gridExport > 10 ? this._t('exporting') : this._t('grid'));
        }

        // Battery label + dynamic color
        const battColor = battCharge > 10 ? '#f06292' : (battDischarge > 10 ? '#4db6ac' : this._getNodeColor('battery'));
        const battLabel = this.renderRoot.getElementById('label-battery-state');
        if (battLabel) {
            battLabel.textContent = battCharge > 10 ? this._t('charging') : (battDischarge > 10 ? this._t('discharging') : '');
        }
        for (const id of ['val-battery-soc', 'val-battery-power', 'label-battery-state', 'val-today-battery']) {
            const el = this.renderRoot.getElementById(id);
            if (el) el.setAttribute('fill', battColor);
        }
        const socArcEl = this.renderRoot.getElementById('soc-arc');
        if (socArcEl && (battCharge > 10 || battDischarge > 10)) socArcEl.style.stroke = battColor;

        // Flow animations
        this._updateFlow('flow-solar',   solar > 10,                false,            semCalcDuration(solar));
        this._updateFlow('flow-battery', Math.abs(battery) > 10,   battery < 0,       semCalcDuration(battery), battColor);
        this._updateFlow('flow-grid',    gridImport > 10 || gridExport > 10, isImport, semCalcDuration(gridImport || gridExport), gridColor);
        this._updateFlow('flow-home',    home > 10,                false,             semCalcDuration(home));
        this._updateFlow('flow-ev',      ev > 10,                  false,             semCalcDuration(ev));

        // Glow intensity
        this._setGlowIntensity('node-solar',   solar,                  10000);
        this._setGlowIntensity('node-battery', Math.abs(battery),       5000);
        this._setGlowIntensity('node-grid',    Math.max(gridImport, gridExport), 10000);
        this._setGlowIntensity('node-home',    home,                    8000);
        this._setGlowIntensity('node-ev',      ev,                     11000);

        this._updateDeviceLabels();
    }

    // ── Flow animation helpers ──
    _updateFlow(groupId, active, reverse, duration, dynamicColor) {
        const group = this.renderRoot.getElementById(groupId);
        if (!group) return;
        group.style.opacity = active ? '1' : '0';
        if (!active) { group.dataset.sig = ''; return; }

        const color = dynamicColor || group.dataset.color;
        if (dynamicColor) group.dataset.color = dynamicColor;

        const pathD  = group.dataset.pathD;
        const count  = parseInt(group.dataset.count, 10) || 2;
        const newSig = `${reverse ? 'r' : 'f'}:${duration.toFixed(1)}:${color}`;
        if (group.dataset.sig === newSig) return;
        group.dataset.sig = newSig;
        group.innerHTML = this._flowEffects(pathD, color, count, duration, reverse);
    }

    _flowEffects(pathD, color, count, duration, reverse) {
        const dur = duration.toFixed(1);
        const dashOffset = reverse ? '32' : '-32';
        const reverseAttrs = reverse ? ' keyPoints="1;0" keyTimes="0;1"' : '';
        let svg = `<path d="${pathD}" fill="none" stroke="${color}" stroke-width="3"
                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">
                     <animate attributeName="stroke-dashoffset" from="0" to="${dashOffset}"
                              dur="${dur}s" repeatCount="indefinite"/>
                   </path>`;
        // #591 — inline path= instead of an mpath href="#id" reference: WebKit (every iOS
        // browser) only resolves xlink:href on mpath, so the plain-href
        // reference never bound and the flow dots stood still on iOS.
        for (let i = 0; i < count; i++) {
            const delay = (i / count) * duration;
            svg += `
                <circle r="5" fill="${color}" opacity="0.12">
                    <animateMotion path="${pathD}" dur="${dur}s" repeatCount="indefinite" calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s"/>
                </circle>
                <circle r="2.5" fill="${color}" opacity="0.9">
                    <animateMotion path="${pathD}" dur="${dur}s" repeatCount="indefinite" calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s"/>
                </circle>`;
        }
        return svg;
    }

    // ── Grid color update ──
    _updateGridColor(color, isImport) {
        const nodeGrid = this.renderRoot.getElementById('node-grid');
        if (nodeGrid) nodeGrid.setAttribute('filter', `url(#glowGrid${isImport ? 'Import' : 'Export'})`);
        const gridCircle = this.renderRoot.getElementById('grid-circle');
        if (gridCircle) {
            gridCircle.setAttribute('stroke', color);
            gridCircle.setAttribute('fill', this._hexToRgba(color, 0.07));
        }
        const glowRing = this.renderRoot.querySelector('#node-grid .glow-ring');
        if (glowRing) glowRing.setAttribute('stroke', color);
        const gridIcon = this.renderRoot.getElementById('grid-icon');
        if (gridIcon) gridIcon.setAttribute('stroke', color);
        for (const id of ['val-grid', 'label-grid', 'val-today-grid']) {
            const el = this.renderRoot.getElementById(id);
            if (el) el.setAttribute('fill', color);
        }
        const gridTrack = this.renderRoot.getElementById('track-grid');
        if (gridTrack) gridTrack.setAttribute('stroke', color);
    }

    // ── Device labels ──
    _updateDeviceLabels() {
        const container = this.renderRoot.getElementById('device-labels');
        if (!container) return;
        const devices = this._getDeviceList();
        const configSig = devices.map(([id, info], idx) =>
            `${info.power_entity}:${info.name}:${info.color || SEM_DEVICE_COLORS[idx % SEM_DEVICE_COLORS.length]}:${info.icon_override || ''}:${info.daily_energy_entity || ''}`
        ).join('|');

        if (this._deviceConfigSig !== configSig) {
            this._deviceConfigSig = configSig;
            this._buildDeviceDOM(container, devices);
        }
        this._updateDeviceValues(devices);
    }

    _getDeviceList() {
        let devices = [];
        if (this._mode === 'entities' && this._entities?.individual) {
            devices = this._entities.individual.map((dev, idx) => [
                dev.entity || `device_${idx}`,
                {
                    name: dev.name || dev.entity?.split('.').pop() || `Device ${idx + 1}`,
                    power_entity: dev.entity,
                    device_type: dev.device_type || 'appliance',
                    is_on: false, current_power: 0,
                    color: dev.color, icon_override: dev.icon, daily_energy_entity: dev.daily_energy,
                },
            ]);
        } else if (this._mode === 'prefix') {
            const devicesEntity = this._hass.states[`${this._prefix}controllable_devices_count`];
            if (devicesEntity?.attributes?.devices) {
                devices = Object.entries(devicesEntity.attributes.devices)
                    .filter(([, info]) => info.power_entity || info.current_power > 0)
                    .sort((a, b) => (a[1].priority || 5) - (b[1].priority || 5));
            }
        }
        return devices.slice(0, 6);
    }

    _buildDeviceDOM(container, devices) {
        if (!devices.length) { container.innerHTML = ''; this._devicePositions = []; return; }

        const F = "'Segoe UI','Roboto',sans-serif";
        const L = this._getLayout();
        const H = L.home;
        const compact   = this._compact;
        const nodeR     = compact ? 26 : 24;
        const cols      = compact ? 2 : Math.min(devices.length, 3);
        const vbW       = compact ? 500 : 1000;
        const margin    = compact ? 30 : 60;
        const colWidth  = (vbW - margin * 2) / cols;
        const baseY     = L.deviceY;
        const maxChars  = compact ? 18 : 20;
        const fs        = 11;
        let svgHtml = '';
        this._devicePositions = [];

        devices.forEach(([id, info], idx) => {
            let name = (info.name || id);
            if (name.length > maxChars) name = name.substring(0, maxChars - 1) + '\u2026';
            const color = info.color || SEM_DEVICE_COLORS[idx % SEM_DEVICE_COLORS.length];
            const icon  = this._deviceIcon(info.device_type, info.name || id);
            const col   = idx % cols;
            const row   = Math.floor(idx / cols);
            const cx    = margin + col * colWidth + colWidth / 2;
            const cy    = baseY + row * (compact ? 100 : 90);
            this._devicePositions.push({ cx, cy, nodeR, color });

            svgHtml += `<path id="dev-conn-${idx}" d="M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${cx},${cy - 40} ${cx},${cy - nodeR}" fill="none" stroke="${color}" stroke-width="1.2" stroke-dasharray="3,5" opacity="0.1"/>`;
            svgHtml += `<g id="dev-flow-${idx}"></g>`;
            // #591 — the flow dot now inlines its path (path=) instead of
            // referencing this via an mpath href reference, so the invisible target path
            // is no longer needed.
            const entityAttr = info.power_entity ? ` data-entity="${info.power_entity}"` : '';
            svgHtml += `<g id="dev-group-${idx}" class="device-clickable"${entityAttr} data-idx="${idx}">`;
            svgHtml += `<circle id="dev-circle-${idx}" cx="${cx}" cy="${cy}" r="${nodeR}" fill="rgba(128,128,128,0.03)" stroke="${color}" stroke-width="1.2" opacity="0.4"/>`;
            svgHtml += `<g transform="translate(${cx},${cy})" stroke="${color}" fill="none" opacity="0.35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${icon}</g>`;
            svgHtml += `<text x="${cx}" y="${cy + nodeR + 14}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="500" fill="${color}" opacity="0.8">${this._escSvg(name)}</text>`;
            svgHtml += `<text id="dev-val-${idx}" x="${cx}" y="${cy + nodeR + 14 + fs + 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="600" fill="${color}" opacity="0.7">0 W</text>`;
            svgHtml += `<text id="dev-daily-${idx}" x="${cx}" y="${cy + nodeR + 14 + (fs + 2) * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${color}" opacity="0.65"></text>`;
            svgHtml += `</g>`;
        });

        container.innerHTML = svgHtml;

        container.querySelectorAll('.device-clickable[data-entity]').forEach(el => {
            const idx = parseInt(el.dataset.idx);
            this._setupNodeActions(el, `device_${idx}`, el.dataset.entity);
        });

        devices.forEach((_, idx) => { delete this._currentValues[`dev-val-${idx}`]; });
    }

    _updateDeviceValues(devices) {
        const L = this._getLayout();
        const H = L.home;
        devices.forEach(([id, info], idx) => {
            const powerEntity = info.power_entity ? this._hass.states[info.power_entity] : null;
            const power = powerEntity ? parseFloat(powerEntity.state) || 0 : (info.current_power || 0);
            const isOn  = power > 5;
            const color = info.color || SEM_DEVICE_COLORS[idx % SEM_DEVICE_COLORS.length];
            const pos   = this._devicePositions[idx];
            if (!pos) return;

            this._animateValue(`dev-val-${idx}`, power);
            if (info.daily_energy_entity) {
                const de = this._hass.states[info.daily_energy_entity];
                this._setText(`dev-daily-${idx}`, de ? `${this._t('today')} ${de.state} kWh` : '');
            }

            const conn = this.renderRoot.getElementById(`dev-conn-${idx}`);
            if (conn) conn.setAttribute('opacity', isOn ? '0.3' : '0.1');
            const circle = this.renderRoot.getElementById(`dev-circle-${idx}`);
            if (circle) {
                circle.setAttribute('fill', `rgba(128,128,128,${isOn ? 0.08 : 0.03})`);
                circle.setAttribute('opacity', isOn ? '1' : '0.4');
            }
            const valEl = this.renderRoot.getElementById(`dev-val-${idx}`);
            if (valEl) valEl.setAttribute('opacity', isOn ? '1' : '0.5');
            const group = this.renderRoot.getElementById(`dev-group-${idx}`);
            if (group) {
                const iconG = group.querySelector('g[transform]');
                if (iconG) iconG.setAttribute('opacity', isOn ? '0.7' : '0.35');
            }

            const flowGroup = this.renderRoot.getElementById(`dev-flow-${idx}`);
            if (flowGroup) {
                if (power > 5) {
                    const dur = semCalcDuration(power).toFixed(1);
                    if (flowGroup.dataset.sig !== dur) {
                        flowGroup.dataset.sig = dur;
                        const pathD = `M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${pos.cx},${pos.cy - 40} ${pos.cx},${pos.cy - pos.nodeR}`;
                        flowGroup.innerHTML = `
                            <path d="${pathD}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">
                                <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${dur}s" repeatCount="indefinite"/>
                            </path>
                            <circle r="2" fill="${color}" opacity="0.8">
                                <animateMotion path="${pathD}" dur="${dur}s" repeatCount="indefinite" calcMode="paced" begin="-${(idx * 0.3).toFixed(1)}s"/>
                            </circle>`;
                    }
                } else if (flowGroup.dataset.sig !== '') {
                    flowGroup.dataset.sig = '';
                    flowGroup.innerHTML = '';
                }
            }
        });
    }

    // ── Click handler setup (called from updated()) ──
    _setupClickHandlers() {
        const entityMap = {
            'node-solar': 'solar_power', 'val-solar': 'solar_power',
            'val-today-solar': 'daily_solar_energy',
            'node-battery': 'battery_soc', 'val-battery-soc': 'battery_soc',
            'val-battery-power': 'battery_power', 'label-battery-state': 'battery_power',
            'val-today-battery': 'daily_battery_energy',
            'node-grid': 'grid_import_power', 'val-grid': 'grid_import_power',
            'label-grid': 'grid_import_power', 'val-today-grid': 'daily_grid_import_energy',
            'node-home': 'home_consumption_power', 'val-home': 'home_consumption_power',
            'val-autarky': 'autarky_rate', 'val-today-home': 'daily_home_energy',
            'node-ev': 'ev_power', 'val-ev': 'ev_power',
            'val-today-ev': 'daily_ev_energy', 'val-inverter-status': 'charging_state',
        };
        for (const [id, key] of Object.entries(entityMap)) {
            const entityId = this._getEntityId(key);
            if (!entityId) continue;
            const el = this.renderRoot.getElementById(id);
            if (el) { el.setAttribute('data-entity', entityId); el.style.cursor = 'pointer'; }
        }

        // Delegated SVG click
        const svg = this.renderRoot.querySelector('svg');
        if (svg && !svg._semClickBound) {
            svg._semClickBound = true;
            svg.addEventListener('click', (e) => {
                let target = e.target;
                for (let i = 0; i < 5 && target && target !== svg; i++) {
                    const entity = target.getAttribute?.('data-entity');
                    if (entity) { this._fireMoreInfo(entity); return; }
                    target = target.parentElement;
                }
            });
        }

        // Tap/hold/double-tap for main nodes
        const nodes = [
            { ids: ['node-solar'],   node: 'solar',   key: 'solar_power' },
            { ids: ['node-battery'], node: 'battery', key: 'battery_soc' },
            { ids: ['node-grid'],    node: 'grid',    key: 'grid_import_power' },
            { ids: ['node-home'],    node: 'home',    key: 'home_consumption_power' },
            { ids: ['node-ev'],      node: 'ev',      key: 'ev_power' },
        ];
        for (const { ids, node, key } of nodes) {
            const entityId = this._getEntityId(key);
            if (!entityId) continue;
            for (const id of ids) {
                const el = this.renderRoot.getElementById(id);
                if (el && !el._semActionsBound) {
                    el._semActionsBound = true;
                    el.classList.add('clickable-node');
                    this._setupNodeActions(el, node, entityId);
                }
            }
        }
    }

    // ── Node action wiring (tap/hold/double-tap) ──
    _setupNodeActions(el, node, entityId) {
        let holdTimer = null, held = false, lastTap = 0, tapTimeout = null;
        el.style.cursor = 'pointer';
        el.addEventListener('pointerdown', () => {
            held = false;
            holdTimer = setTimeout(() => {
                held = true;
                const action = this._getActionConfig(node, 'hold_action');
                if (action.action !== 'none') this._handleAction(action, entityId);
            }, 500);
        });
        el.addEventListener('pointerup',    () => clearTimeout(holdTimer));
        el.addEventListener('pointercancel', () => { clearTimeout(holdTimer); held = false; });
        el.addEventListener('click', () => {
            if (held) { held = false; return; }
            const dta = this._getActionConfig(node, 'double_tap_action');
            if (!dta || dta.action === 'none') {
                this._handleAction(this._getActionConfig(node, 'tap_action'), entityId);
                return;
            }
            const now = Date.now();
            if (now - lastTap < 300) {
                clearTimeout(tapTimeout);
                lastTap = 0;
                this._handleAction(dta, entityId);
            } else {
                lastTap = now;
                tapTimeout = setTimeout(() => {
                    lastTap = 0;
                    this._handleAction(this._getActionConfig(node, 'tap_action'), entityId);
                }, 300);
            }
        });
    }

    _getActionConfig(node, actionType) {
        const e = this._entities;
        if (!e) return { action: actionType === 'tap_action' ? 'more-info' : 'none' };
        let nodeConfig;
        if (node.startsWith('device_')) {
            const idx = parseInt(node.split('_')[1]);
            nodeConfig = e.individual?.[idx];
        } else {
            const map = { solar: e.solar, battery: e.battery, grid: e.grid, home: e.home, ev: e.ev || e.individual?.[0] };
            nodeConfig = map[node];
        }
        const action = nodeConfig?.[actionType];
        if (!action) return { action: actionType === 'tap_action' ? 'more-info' : 'none' };
        return typeof action === 'string' ? { action } : action;
    }

    _handleAction(config, entityId) {
        if (!config) config = { action: 'more-info' };
        switch (config.action) {
            case 'more-info': this._fireMoreInfo(config.entity || entityId); break;
            case 'toggle':
                if (this._hass) this._hass.callService('homeassistant', 'toggle', { entity_id: config.entity || entityId });
                break;
            case 'navigate':
                if (config.navigation_path) {
                    window.history.pushState(null, '', config.navigation_path);
                    window.dispatchEvent(new CustomEvent('location-changed'));
                }
                break;
            case 'call-service':
                if (config.service && this._hass) {
                    const [domain, service] = config.service.split('.');
                    this._hass.callService(domain, service, config.service_data || {});
                }
                break;
            case 'url':
                if (config.url_path) window.open(config.url_path, '_blank');
                break;
        }
    }

    _fireMoreInfo(entityId) {
        if (!entityId) return;
        this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId }, bubbles: true, composed: true }));
    }

    // ── Glow intensity ──
    _setGlowIntensity(nodeId, watts, maxWatts) {
        const ring = this.renderRoot.querySelector(`#${nodeId} .glow-ring`);
        if (!ring) return;
        const ratio = Math.min(1, Math.abs(watts) / maxWatts);
        ring.style.opacity = (0.15 + ratio * 0.85).toFixed(2);
    }

    // ── Animated value counter ──
    _animateValue(id, newVal, duration = 800, formatFn = null) {
        const el = this.renderRoot.getElementById(id);
        if (!el) return;
        if (this._animFrames[id]) cancelAnimationFrame(this._animFrames[id]);
        const fmt = formatFn || (v => semFormatPower(v));
        const oldVal = this._currentValues[id] || 0;
        this._currentValues[id] = newVal;
        if (Math.abs(oldVal - newVal) < 0.5) { el.textContent = fmt(newVal); return; }
        const startTime = performance.now();
        const animate = (now) => {
            const progress = Math.min(1, (now - startTime) / duration);
            const eased = progress < 0.5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
            el.textContent = fmt(oldVal + (newVal - oldVal) * eased);
            if (progress < 1) { this._animFrames[id] = requestAnimationFrame(animate); }
            else { delete this._animFrames[id]; }
        };
        this._animFrames[id] = requestAnimationFrame(animate);
        // Settle fallback: rAF frames die silently on a backgrounded/resumed
        // iOS WebView — guarantee the FINAL value lands. No-op when a newer
        // target superseded this one.
        setTimeout(() => {
            if (this._currentValues[id] !== newVal) return;
            if (this._animFrames[id]) {
                cancelAnimationFrame(this._animFrames[id]);
                delete this._animFrames[id];
            }
            el.textContent = fmt(newVal);
        }, duration + 250);
    }

    _setText(id, text) {
        const el = this.renderRoot.getElementById(id);
        if (el) el.textContent = text;
    }

    // ── Entity helpers ──
    _getState(key) {
        if (!this._hass) return 0;
        const entityId = this._mode === 'prefix' ? `${this._prefix}${key}` : this._resolveEntity(key);
        if (!entityId) return 0;
        const entity = this._hass.states[entityId];
        if (!entity) return 0;
        const val = parseFloat(entity.state);
        return isNaN(val) ? 0 : val;
    }

    _getStateStr(key) {
        if (!this._hass) return '';
        const entityId = this._mode === 'prefix' ? `${this._prefix}${key}` : this._resolveEntity(key);
        if (!entityId) return '';
        const entity = this._hass.states[entityId];
        return entity ? entity.state : '';
    }

    _getEntityId(key) {
        if (this._mode === 'prefix') return `${this._prefix}${key}`;
        return this._resolveEntity(key);
    }

    _resolveEntity(key) {
        const e = this._entities;
        if (!e) return null;
        const map = {
            solar_power: e.solar?.entity,
            battery_power: e.battery?.entity,
            battery_charge_power: e.battery?.charge,
            battery_discharge_power: e.battery?.discharge,
            grid_power: e.grid?.entity,
            grid_import_power: e.grid?.consumption,
            grid_export_power: e.grid?.production,
            ev_power: e.ev?.entity || e.individual?.[0]?.entity,
            battery_soc: e.battery?.state_of_charge,
            home_consumption_power: e.home?.entity,
            charging_state: e.inverter?.entity,
            daily_solar_energy: e.solar?.daily_energy,
            daily_ev_energy: e.ev?.daily_energy || e.individual?.[0]?.daily_energy,
            daily_grid_import_energy: e.grid?.daily_import_energy,
            daily_grid_export_energy: e.grid?.daily_export_energy,
            daily_battery_energy: e.battery?.daily_energy,
            daily_home_energy: e.home?.daily_energy,
            autarky_rate: e.home?.autarky,
            ev_charger_count: e.ev?.charger_count || 'sensor.sem_ev_charger_count',
        };
        return map[key] || null;
    }

    _hasNode(node) {
        if (this._mode === 'prefix') return true;
        const e = this._entities;
        if (!e) return false;
        const map = {
            solar: !!e.solar?.entity,
            battery: !!(e.battery?.entity || e.battery?.charge || e.battery?.discharge),
            grid: !!(e.grid?.consumption || e.grid?.entity),
            home: true,
            ev: !!(e.ev?.entity || e.individual?.[0]?.entity),
            inverter: !!e.inverter?.entity || !!(e.solar?.entity),
        };
        return map[node] || false;
    }

    _getNodeColor(node) {
        const e = this._entities;
        const defaults = {
            solar: SFC_DEFAULTS.solar.color, battery: SFC_DEFAULTS.battery.color,
            grid: SFC_DEFAULTS.grid.color_import, grid_import: SFC_DEFAULTS.grid.color_import,
            grid_export: SFC_DEFAULTS.grid.color_export, home: SFC_DEFAULTS.home.color,
            ev: SFC_DEFAULTS.ev.color, inverter: SFC_DEFAULTS.inverter.color,
        };
        if (!e) return defaults[node] || '#888';
        const overrides = {
            solar: e.solar?.color, battery: e.battery?.color,
            grid: e.grid?.color_import, grid_import: e.grid?.color_import,
            grid_export: e.grid?.color_export, home: e.home?.color,
            ev: e.ev?.color || e.individual?.[0]?.color,
        };
        return overrides[node] || defaults[node] || '#888';
    }

    _getNodeName(node) {
        const e = this._entities;
        const defaultKey = SFC_DEFAULTS[node]?.nameKey;
        const defaultTranslated = defaultKey ? this._t(defaultKey) : node;
        if (!e) return defaultTranslated;
        const overrides = { solar: e.solar?.name, battery: e.battery?.name, grid: e.grid?.name, home: e.home?.name, ev: e.ev?.name || e.individual?.[0]?.name };
        return overrides[node] || defaultTranslated;
    }

    // ── Layout ──
    _getLayout() {
        if (this._compact) {
            return {
                vb: '0 0 500 1100',
                solar:    { cx: 250, cy: 70,  r: 48 },
                inverter: { cx: 250, cy: 225, r: 20 },
                battery:  { cx: 100, cy: 340, r: 48 },
                grid:     { cx: 400, cy: 340, r: 48 },
                home:     { cx: 250, cy: 510, r: 60 },
                ev:       { cx: 100, cy: 660, r: 42 },
                socR: 33, autarkyR: 48,
                paths: {
                    solar:   'M250,118 L250,205',
                    home:    'M250,245 L250,450',
                    battery: 'M230,230 C180,260 120,290 100,292',
                    grid:    'M270,230 C320,260 380,290 400,292',
                    ev:      'M230,240 C180,380 130,560 100,618',
                },
                font: { label: 14, value: 22, sub: 12, homeVal: 26 },
                deviceY: 810,
            };
        }
        return {
            vb: '0 0 1000 800',
            solar:    { cx: 500, cy: 65,  r: 50 },
            inverter: { cx: 500, cy: 210, r: 20 },
            battery:  { cx: 150, cy: 270, r: 50 },
            grid:     { cx: 850, cy: 270, r: 50 },
            home:     { cx: 500, cy: 385, r: 62 },
            ev:       { cx: 150, cy: 460, r: 44 },
            socR: 40, autarkyR: 50,
            paths: {
                solar:   'M500,115 L500,190',
                home:    'M500,230 L500,323',
                battery: 'M480,215 C380,230 250,245 200,270',
                grid:    'M520,215 C620,230 750,245 800,270',
                ev:      'M480,225 C380,330 250,410 195,460',
            },
            font: { label: 13, value: 20, sub: 11, homeVal: 24 },
            deviceY: 590,
        };
    }

    // ── SVG helpers ──
    _glowFilter(id, color, blur) {
        return `<filter id="${id}" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="${blur}" result="blur"/>
            <feFlood flood-color="${color}" flood-opacity="0.25"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`;
    }

    _glowRing(node, color, sw = 1.2) {
        const gr = node.r + 5;
        return `<circle class="glow-ring" cx="${node.cx}" cy="${node.cy}" r="${gr}" fill="none" stroke="${color}" stroke-width="${sw}" opacity="0.3">
            <animate attributeName="r" values="${gr};${gr + 5};${gr}" dur="3s" repeatCount="indefinite"/>
            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>
        </circle>`;
    }

    _track(d, color) {
        return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`;
    }

    _hexToRgba(hex, alpha) {
        const m = hex.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
        if (!m) return `rgba(128,128,128,${alpha})`;
        return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${alpha})`;
    }

    _autarkyColor(pct) {
        pct = Math.max(0, Math.min(100, pct));
        if (pct <= 50) {
            const t = pct / 50;
            return `rgb(220,${Math.round(50 + 150 * t)},50)`;
        }
        const t = (pct - 50) / 50;
        return `rgb(${Math.round(220 - 170 * t)},200,50)`;
    }

    _deviceIcon(type, name) {
        const n = (name || '').toLowerCase();
        const t = (type || '').toLowerCase();
        if (t === 'ev_charger' || n.includes('keba') || n.includes('charger') || n.includes('wallbox'))
            return `<rect x="-6" y="-10" width="12" height="16" rx="2"/><path d="M-2,-4 L0,2 L2,-4"/><line x1="0" y1="6" x2="0" y2="10"/>`;
        if (n.includes('heiz') || n.includes('heat') || n.includes('warm') || n.includes('boiler'))
            return `<path d="M-4,-10 C-4,-4 4,-4 4,-10"/><path d="M-4,-3 C-4,3 4,3 4,-3"/><path d="M-4,4 C-4,10 4,10 4,4"/>`;
        if (n.includes('wash') || n.includes('sp\u00FCl') || n.includes('geschirr') || n.includes('wasch'))
            return `<circle r="10" fill="none"/><circle r="5" fill="none"/><circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>`;
        if (n.includes('dryer') || n.includes('trockn'))
            return `<circle r="10" fill="none"/><path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>`;
        if (n.includes('pool') || n.includes('pump'))
            return `<circle r="8" fill="none"/><path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/><path d="M-4,-4 L4,4 M4,-4 L-4,4"/>`;
        if (n.includes('klima') || n.includes('ac') || n.includes('cool') || n.includes('air'))
            return `<rect x="-10" y="-6" width="20" height="12" rx="2"/><path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/><path d="M2,6 C2,10 6,10 6,6" fill="none"/>`;
        if (n.includes('light') || n.includes('licht') || n.includes('lamp'))
            return `<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/><line x1="-2" y1="8" x2="2" y2="8"/>`;
        if (n.includes('shelly') || n.includes('plug') || n.includes('switch') || n.includes('steckdose'))
            return `<rect x="-8" y="-10" width="16" height="20" rx="3"/><circle cx="-3" cy="-2" r="2" fill="none"/><circle cx="3" cy="-2" r="2" fill="none"/><line x1="0" y1="4" x2="0" y2="7"/>`;
        return `<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>`;
    }

    getCardSize() { return 8; }

    static async getConfigElement() {
        return document.createElement('sem-flow-card-editor');
    }

    static getStubConfig(hass) {
        const states = hass ? Object.keys(hass.states) : [];
        const find = (patterns) => {
            for (const p of patterns) {
                const m = states.find(id => id.includes(p));
                if (m) return m;
            }
            return null;
        };
        return {
            entities: {
                solar: { entity: find(['solar_power', 'pv_power']) || 'sensor.solar_power' },
                grid: {
                    consumption: find(['grid_import', 'grid_consumption']) || 'sensor.grid_import_power',
                    production:  find(['grid_export', 'grid_feed'])        || 'sensor.grid_export_power',
                },
                battery: {
                    entity: find(['battery_power', 'batt_power'])              || 'sensor.battery_power',
                    state_of_charge: find(['battery_soc', 'battery_level'])    || 'sensor.battery_soc',
                },
                home: { entity: find(['home_consumption', 'house_power']) || 'sensor.home_consumption_power' },
            },
        };
    }
}

semDefineCard('sem-flow-card', SEMFlowCard, {
    type: 'sem-flow-card',
    name: 'SEM Flow Card',
    description: 'Animated energy flow diagram — works with any HA entities',
});
