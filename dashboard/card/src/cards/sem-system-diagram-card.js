/**
 * SEM System Diagram Card — Inline SVG Illustrations
 *
 * Responsive power flow visualization with detailed inline SVG illustrations
 * for each energy system component. Replaces image-overlay approach with
 * pure SVG embedded directly in the card.
 *
 * Layout:
 *   Desktop (>=500px): viewBox 0 0 700 480 — left-to-right flow
 *   Compact (<500px):  viewBox 0 0 400 680 — vertical stack
 *
 * Architecture:
 * - Lit render() produces static SVG structure with illustration groups
 * - _updateFlowsImperative() handles all data-driven DOM mutations
 * - ResizeObserver drives compact/wide toggle
 * - IntersectionObserver pauses animation when off-screen
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import {
    semFormatPower, semCalcDuration, semDefineCard, SEM_DEVICE_COLORS,
    semDiscoverPVStrings, semPVStringsCSS,
} from '../base/sem-shared.js';

/* ── Required IDs for imperative updates (must exist in render output) ──
 * val-solar, val-solar-kwh
 * val-home, val-home-kwh
 * val-ev, val-ev-kwh
 * val-batt-power, label-batt-state, val-batt-kwh, batt-soc-text, batt-fill, batt-bolt
 * val-grid-single, val-grid-kwh, label-grid
 * val-inv-temp, val-inv-status
 * sun-circle, sun-glow, sun-power-label, sun-rising, sun-setting
 * moon-crescent, stars, sun-arc-group
 * entity-status
 * flow-solar, flow-battery, flow-grid, flow-home, flow-ev
 */

class SEMSystemDiagramCard extends SEMLitBase {
    constructor() {
        super();
        this._lastKey        = '';
        this._animFrames     = {};
        this._currentValues  = {};
        this._compact        = false;
        this._visible        = true;
        this._updateTimer    = null;
        this._resizeObserver = null;
        this._intersectionObserver = null;
        this._resizeTimeout  = null;
    }

    setConfig(config) {
        this._config      = config;
        this.entityPrefix = config.entity_prefix || 'sensor.sem_';
        this.requestUpdate();
    }

    // ── hass: debounce flow updates ──
    set hass(hass) {
        this._hass = hass;
        const lang = hass?.language;
        if (lang !== this._lang) {
            this._lang = lang;
            this._lastKey = '';
            this.requestUpdate();
            return;
        }
        if (!this._visible) return;
        clearTimeout(this._updateTimer);
        this._updateTimer = setTimeout(() => this._updateFlowsImperative(), 100);
    }

    get hass() { return this._hass; }

    // ── Observers: set up after first render ──
    firstUpdated() {
        this._resizeObserver = new ResizeObserver(entries => {
            if (this._resizeTimeout) clearTimeout(this._resizeTimeout);
            this._resizeTimeout = setTimeout(() => {
                for (const entry of entries) {
                    const compact = entry.contentRect.width < 500;
                    if (compact !== this._compact) {
                        this._compact = compact;
                        this._lastKey = '';
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
        }, { threshold: 0.01 });
        this._intersectionObserver.observe(this);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
        if (this._intersectionObserver) { this._intersectionObserver.disconnect(); this._intersectionObserver = null; }
        clearTimeout(this._updateTimer);
        clearTimeout(this._resizeTimeout);
        for (const id of Object.keys(this._animFrames)) cancelAnimationFrame(this._animFrames[id]);
        this._animFrames = {};
    }

    // ── Run imperative updates after each Lit render ──
    updated() {
        super.updated();
        this._updateFlowsImperative();
    }

    // ── Static CSS ──
    static get styles() {
        return css`
            :host { display: block; }
            ha-card { overflow: hidden; padding: 0; background: transparent !important; }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .clickable { cursor: pointer; pointer-events: bounding-box; }
            .clickable:hover { filter: brightness(1.2); }
            text { font-variant-numeric: tabular-nums; }
            @media (prefers-reduced-motion: reduce) {
                .flow-group { transition: none; }
                animate, animateMotion { display: none; }
            }
        `;
    }

    // ── Render static SVG structure with inline illustrations ──
    render() {
        if (!this._config) return nothing;

        const L = this._getLayout();
        const c = this._compact;
        const F = "'Segoe UI','Roboto',sans-serif";
        const fl = L.font.label, fv = L.font.value, fs = L.font.sub;

        // v1.7.1 / #312: per-PV-string HUD chip strip — auto-shown
        // when ≥ 2 strings exist. The illustrated SVG sun motif
        // doesn't split well visually, so chips sit above as a
        // compact heads-up overview instead.
        const pvStrings = semDiscoverPVStrings(this._hass, this._prefix);

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
                                <span class="pv-chip-label">PV${s.slot.replace(/^pv/,'')}</span>
                                <span class="pv-chip-value">${(Math.abs(s.watts)/1000).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                ` : nothing}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${L.vb}"
                     style="background:transparent;overflow:hidden"
                     role="img" aria-label="Solar energy system power flow diagram">
                    <defs>
                        <!-- Background gradient -->
                        <radialGradient id="bgGrad" cx="50%" cy="40%" r="65%">
                            <stop offset="0%" stop-color="rgba(150,202,238,0.06)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <!-- Dot grid pattern -->
                        <pattern id="dotGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                            <circle cx="20" cy="20" r="0.6" fill="rgba(128,128,128,0.07)"/>
                        </pattern>

                        <!-- Glow filters -->
                        ${this._glowFilter('glowSolar',    '#ff9800', 10)}
                        ${this._glowFilter('glowBattery',  '#4db6ac', 8)}
                        ${this._glowFilter('glowGrid',     '#488fc2', 8)}
                        ${this._glowFilter('glowHome',     '#5BC8D8', 12)}
                        ${this._glowFilter('glowEV',       '#8DC892', 8)}
                        ${this._glowFilter('glowInverter', '#96CAEE', 6)}
                        ${this._glowFilter('glowSun',      '#FCD170', 14)}

                        <!-- Solar panel cell gradient -->
                        <linearGradient id="panelBlue" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1565C0" stop-opacity="0.9"/>
                            <stop offset="50%" stop-color="#1976D2" stop-opacity="0.8"/>
                            <stop offset="100%" stop-color="#0D47A1" stop-opacity="0.95"/>
                        </linearGradient>
                        <linearGradient id="panelBlue2" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1E88E5" stop-opacity="0.85"/>
                            <stop offset="100%" stop-color="#1565C0" stop-opacity="0.9"/>
                        </linearGradient>
                        <linearGradient id="panelReflect" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="rgba(255,255,255,0.18)"/>
                            <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
                        </linearGradient>

                        <!-- Battery gradient -->
                        <linearGradient id="battBody" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#1a2e2c"/>
                            <stop offset="100%" stop-color="#1f3835"/>
                        </linearGradient>
                        <linearGradient id="battFillGrad" x1="0%" y1="100%" x2="0%" y2="0%">
                            <stop offset="0%" stop-color="#4db6ac"/>
                            <stop offset="100%" stop-color="#80cbc4"/>
                        </linearGradient>

                        <!-- House roof gradient -->
                        <linearGradient id="roofGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#c62828"/>
                            <stop offset="100%" stop-color="#b71c1c"/>
                        </linearGradient>
                        <!-- House wall gradient -->
                        <linearGradient id="wallGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#37474F"/>
                            <stop offset="100%" stop-color="#263238"/>
                        </linearGradient>
                        <!-- Window glow gradient -->
                        <radialGradient id="windowGlow" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4" stop-opacity="0.9"/>
                            <stop offset="100%" stop-color="#F9A825" stop-opacity="0.3"/>
                        </radialGradient>

                        <!-- Grid pole gradient -->
                        <linearGradient id="poleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#5c7a9b"/>
                            <stop offset="50%" stop-color="#6d8fad"/>
                            <stop offset="100%" stop-color="#5c7a9b"/>
                        </linearGradient>

                        <!-- Inverter box gradient -->
                        <linearGradient id="invGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#1a2740"/>
                            <stop offset="100%" stop-color="#0f1820"/>
                        </linearGradient>

                        <!-- EV car body gradient -->
                        <linearGradient id="carGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#2e5a3c"/>
                            <stop offset="100%" stop-color="#1b3b27"/>
                        </linearGradient>

                        <!-- Sun glow radial -->
                        <radialGradient id="sunGradInner" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4"/>
                            <stop offset="60%" stop-color="#FCD170"/>
                            <stop offset="100%" stop-color="#F7941E"/>
                        </radialGradient>

                        <!-- Flow paths (referenced by animateMotion) -->
                        <path id="path-solar"   d="${L.paths.solar}"/>
                        <path id="path-home"    d="${L.paths.home}"/>
                        <path id="path-battery" d="${L.paths.battery}"/>
                        <path id="path-grid"    d="${L.paths.grid}"/>
                        <path id="path-ev"      d="${L.paths.ev}"/>
                    </defs>

                    <!-- Background -->
                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="100%" fill="url(#dotGrid)"/>

                    <!-- ══════════════════════════════════════════════
                         SUN ARC (top decorative element)
                         Positioned along arc, moves with solar position
                    ══════════════════════════════════════════════ -->
                    <g id="sun-arc-group">
                        <!-- Arc track -->
                        <path id="sun-arc-path" d="${L.sunArc}" fill="none" stroke="rgba(252,209,112,0.12)"
                              stroke-width="2" stroke-dasharray="4,8"/>
                        <!-- Rising time label -->
                        <text id="sun-rising" x="${L.sunRisingX}" y="${L.sunLabelY}"
                              text-anchor="middle" font-family="${F}" font-size="${fs}"
                              fill="#FCD170" opacity="0.45"></text>
                        <!-- Setting time label -->
                        <text id="sun-setting" x="${L.sunSettingX}" y="${L.sunLabelY}"
                              text-anchor="middle" font-family="${F}" font-size="${fs}"
                              fill="#FCD170" opacity="0.45"></text>
                        <!-- Sun disc — position updated imperatively -->
                        <g id="sun-glow" filter="url(#glowSun)" style="opacity:0.85">
                            <!-- Outer warm halo -->
                            <circle id="sun-circle" cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR + 6}"
                                    fill="rgba(252,209,112,0.15)"/>
                            <!-- Ray spikes (8 rays) — drawn around center -->
                            ${this._sunRays(L.sunX, L.sunY, L.sunR)}
                            <!-- Core disc -->
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR}"
                                    fill="url(#sunGradInner)"/>
                            <!-- Highlight -->
                            <ellipse cx="${L.sunX - L.sunR * 0.25}" cy="${L.sunY - L.sunR * 0.28}"
                                     rx="${L.sunR * 0.35}" ry="${L.sunR * 0.22}"
                                     fill="rgba(255,255,255,0.35)"/>
                        </g>
                        <!-- Moon (shown at night) -->
                        <g id="moon-crescent" style="display:none">
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR}"
                                    fill="#1a2540"/>
                            <circle cx="${L.sunX + L.sunR * 0.38}" cy="${L.sunY - L.sunR * 0.22}"
                                    r="${L.sunR * 0.78}" fill="#0d1a30"/>
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR}"
                                    fill="none" stroke="rgba(200,220,255,0.5)" stroke-width="1"/>
                        </g>
                        <!-- Stars (shown at night) -->
                        <g id="stars" style="display:none" fill="rgba(200,220,255,0.6)">
                            <circle cx="${L.starX[0]}" cy="${L.starY[0]}" r="1.2"/>
                            <circle cx="${L.starX[1]}" cy="${L.starY[1]}" r="0.9"/>
                            <circle cx="${L.starX[2]}" cy="${L.starY[2]}" r="1.4"/>
                            <circle cx="${L.starX[3]}" cy="${L.starY[3]}" r="0.8"/>
                            <circle cx="${L.starX[4]}" cy="${L.starY[4]}" r="1.1"/>
                        </g>
                        <!-- Solar power label on sun -->
                        <text id="sun-power-label" x="${L.sunX}" y="${L.sunY + L.sunR + 14}"
                              text-anchor="middle" font-family="${F}" font-size="${fs}"
                              fill="#FCD170" opacity="0.7" font-weight="600"></text>

                        <!-- Sun-to-solar energy wave (populated imperatively) -->
                        <g id="sun-spark" style="opacity:0"></g>
                    </g>

                    <!-- ══════════════════════════════════════════════
                         FLOW TRACKS (static dashed paths)
                    ══════════════════════════════════════════════ -->
                    <path d="${L.paths.solar}"   fill="none" stroke="#ff9800" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.home}"    fill="none" stroke="#5BC8D8" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.battery}" fill="none" stroke="#4db6ac" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.grid}"    fill="none" stroke="#488fc2" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.ev}"      fill="none" stroke="#8DC892" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>

                    <!-- ══════════════════════════════════════════════
                         FLOW ANIMATION GROUPS
                    ══════════════════════════════════════════════ -->
                    <g id="flow-solar"   class="flow-group" style="opacity:0"
                       data-path-id="path-solar"   data-path-d="${L.paths.solar}"
                       data-color="#ff9800" data-count="2"></g>
                    <g id="flow-battery" class="flow-group" style="opacity:0"
                       data-path-id="path-battery" data-path-d="${L.paths.battery}"
                       data-color="#4db6ac" data-count="3"></g>
                    <g id="flow-grid"    class="flow-group" style="opacity:0"
                       data-path-id="path-grid"    data-path-d="${L.paths.grid}"
                       data-color="#488fc2" data-count="3"></g>
                    <g id="flow-home"    class="flow-group" style="opacity:0"
                       data-path-id="path-home"    data-path-d="${L.paths.home}"
                       data-color="#5BC8D8" data-count="2"></g>
                    <g id="flow-ev"      class="flow-group" style="opacity:0"
                       data-path-id="path-ev"      data-path-d="${L.paths.ev}"
                       data-color="#8DC892" data-count="3"></g>

                    <!-- ══════════════════════════════════════════════
                         SOLAR PANELS ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-solar" filter="url(#glowSolar)" class="clickable" @click=${() => this._showMoreInfo('solar_power')}>
                        ${this._illustrationSolarPanel(L.S.cx, L.S.cy, L.S.r)}
                    </g>
                    <text x="${L.S.cx}" y="${L.S.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#ff9800" letter-spacing="0.5">${this._t('solar')}</text>
                    <text id="val-solar" x="${L.S.cx}" y="${L.S.labelY + fv * 1.1}" class="clickable"
                          @click=${() => this._showMoreInfo('solar_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#ff9800">0 W</text>
                    <text id="val-solar-kwh" x="${L.S.cx}" y="${L.S.labelY + fv * 1.1 + fs + 3}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_solar_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#ff9800" opacity="0.6" font-weight="600"></text>
                    <text id="val-solar-forecast" x="${L.S.cx}" y="${L.S.labelY + fv * 1.1 + (fs + 3) * 2}" class="clickable"
                          @click=${() => this._showMoreInfo('forecast_corrected_today')}
                          text-anchor="middle" font-family="${F}" font-size="${fs}"
                          fill="#ff9800" opacity="0.4" font-weight="500"></text>

                    <!-- ══════════════════════════════════════════════
                         INVERTER ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-inverter" filter="url(#glowInverter)">
                        ${this._illustrationInverter(L.I.cx, L.I.cy, L.I.r)}
                    </g>
                    <text id="val-inv-temp" x="${L.I.cx}" y="${L.I.cy + L.I.r + 14}"
                          text-anchor="middle" font-family="${F}" font-size="${fs}"
                          fill="#96CAEE" opacity="0.6" font-weight="600"></text>
                    <text id="val-inv-status" x="${L.I.cx}" y="${L.I.cy + L.I.r + 14 + fs + 2}"
                          text-anchor="middle" font-family="${F}" font-size="${fs - 1}"
                          fill="#96CAEE" opacity="0.35"></text>

                    <!-- ══════════════════════════════════════════════
                         BATTERY ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-battery" filter="url(#glowBattery)" class="clickable" @click=${() => this._showMoreInfo('battery_soc')}>
                        ${this._illustrationBattery(L.B.cx, L.B.cy, L.B.r)}
                    </g>
                    <text x="${L.B.cx}" y="${L.B.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#4db6ac" letter-spacing="0.5">${this._t('battery')}</text>
                    <text id="val-batt-power" x="${L.B.cx}" y="${L.B.labelY + fv * 1.0}" class="clickable"
                          @click=${() => this._showMoreInfo('battery_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#4db6ac">0 W</text>
                    <text id="label-batt-state" x="${L.B.cx}" y="${L.B.labelY + fv * 1.0 + fl}"
                          text-anchor="middle" font-family="${F}" font-size="${fl}"
                          fill="#4db6ac" opacity="0.6"></text>
                    <text id="val-batt-kwh" x="${L.B.cx}" y="${L.B.labelY + fv * 1.0 + fl + fs + 2}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_battery_charge_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#4db6ac" opacity="0.6" font-weight="600"></text>
                    </g>

                    <!-- ══════════════════════════════════════════════
                         GRID / POWER POLE ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-grid" filter="url(#glowGrid)" class="clickable" @click=${() => this._showMoreInfo('grid_import_power')}>
                        ${this._illustrationGrid(L.G.cx, L.G.cy, L.G.r)}
                    </g>
                    <text id="label-grid" x="${L.G.cx}" y="${L.G.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#488fc2" letter-spacing="0.5">${this._t('grid')}</text>
                    <text id="val-grid-single" x="${L.G.cx}" y="${L.G.labelY + fv}" class="clickable"
                          @click=${() => this._showMoreInfo('grid_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#488fc2">0 W</text>
                    <text id="label-grid-state" x="${L.G.cx}" y="${L.G.labelY + fv + fl + 1}"
                          text-anchor="middle" font-family="${F}" font-size="${fl}"
                          fill="#488fc2" opacity="0.6"></text>
                    <text id="val-grid-kwh" x="${L.G.cx}" y="${L.G.labelY + fv + fl + fs + 4}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_grid_import_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#488fc2" opacity="0.6" font-weight="600"></text>

                    <!-- ══════════════════════════════════════════════
                         HOUSE ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-home" filter="url(#glowHome)" class="clickable" @click=${() => this._showMoreInfo('home_consumption_power')}>
                        ${this._illustrationHouse(L.H.cx, L.H.cy, L.H.r)}
                    </g>
                    <text x="${L.H.cx}" y="${L.H.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#5BC8D8" letter-spacing="0.5">${this._t('home')}</text>
                    <text id="val-home" x="${L.H.cx}" y="${L.H.labelY + fv * 1.1}" class="clickable"
                          @click=${() => this._showMoreInfo('home_consumption_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#5BC8D8">0 W</text>
                    <text id="val-home-kwh" x="${L.H.cx}" y="${L.H.labelY + fv * 1.1 + fs + 3}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_home_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#5BC8D8" opacity="0.6" font-weight="600"></text>

                    <!-- ══════════════════════════════════════════════
                         EV CHARGER ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-ev" filter="url(#glowEV)" class="clickable" @click=${() => this._showMoreInfo('ev_power')}>
                        ${this._illustrationEV(L.E.cx, L.E.cy, L.E.r)}
                    </g>
                    <text x="${L.E.cx}" y="${L.E.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#8DC892" letter-spacing="0.5">${this._t('ev_charging')}</text>
                    <text id="val-ev" x="${L.E.cx}" y="${L.E.labelY + fv * 1.0}" class="clickable"
                          @click=${() => this._showMoreInfo('ev_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#8DC892">0 W</text>
                    <text id="label-ev-state" x="${L.E.cx}" y="${L.E.labelY + fv * 1.0 + fl}"
                          text-anchor="middle" font-family="${F}" font-size="${fl}"
                          fill="#8DC892" opacity="0.6"></text>
                    <text id="val-ev-kwh" x="${L.E.cx}" y="${L.E.labelY + fv * 1.0 + fl + fs + 2}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_ev_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#8DC892" opacity="0.6" font-weight="600"></text>

                    <!-- Device labels (populated imperatively) -->
                    <g id="device-labels"></g>

                    <!-- Entity status indicator -->
                    <foreignObject x="${c ? 8 : 10}" y="${L.statusY}" width="220" height="22">
                        <div xmlns="http://www.w3.org/1999/xhtml" id="entity-status"
                             style="display:none;font-family:'Segoe UI','Roboto',sans-serif;font-size:10px;color:#ef5350;opacity:0.75;white-space:nowrap"></div>
                    </foreignObject>

                    <!-- SEM watermark -->
                    <text x="${L.wmX}" y="${L.wmY}" text-anchor="end"
                          font-family="${F}" font-size="9" font-weight="300"
                          letter-spacing="2.5" fill="rgba(255,255,255,0.06)">SEM</text>
                </svg>
            </ha-card>
        `;
    }

    // ══════════════════════════════════════════════════════════════════
    //  INLINE SVG ILLUSTRATION HELPERS
    // ══════════════════════════════════════════════════════════════════

    /**
     * Solar panel array — 3x2 tilted perspective panel grid on mounting frame
     * cx, cy = center of bounding circle, r = radius of bounding circle
     */
    _illustrationSolarPanel(cx, cy, r) {
        const s = r / 50; // scale factor
        const W = 86 * s, H = 58 * s; // panel array total size
        const x = cx - W / 2, y = cy - H / 2 - 4 * s;
        // Panel cell dimensions (3 cols, 2 rows)
        const pw = W / 3, ph = H / 2;
        // Mounting frame points (slight perspective skew)
        const skew = 6 * s;
        const frameH = 12 * s;
        return svg`
            <!-- Outer glow halo -->
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#ff9800" stroke-width="1.2" opacity="0.25"/>

            <!-- Mounting structure frame -->
            <line x1="${x + skew}" y1="${y + H}" x2="${x + skew - 4*s}" y2="${y + H + frameH}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${x + W - skew}" y1="${y + H}" x2="${x + W - skew + 4*s}" y2="${y + H + frameH}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${x + W/2}" y1="${y + H}" x2="${x + W/2}" y2="${y + H + frameH * 0.8}"
                  stroke="#ff9800" stroke-width="${1.5*s}" stroke-linecap="round" opacity="0.5"/>
            <!-- Ground bar -->
            <line x1="${x + skew - 6*s}" y1="${y + H + frameH}"
                  x2="${x + W - skew + 6*s}" y2="${y + H + frameH}"
                  stroke="#ff9800" stroke-width="${2.5*s}" stroke-linecap="round" opacity="0.6"/>

            <!-- Rail behind panels -->
            <line x1="${x}" y1="${y + H * 0.52}" x2="${x + W}" y2="${y + H * 0.52}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${x}" y1="${y}" x2="${x + W}" y2="${y}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>

            <!-- Panel cells: 3 cols x 2 rows alternating blue shades -->
            <rect x="${x}"        y="${y}"      width="${pw}" height="${ph}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${x + pw}"   y="${y}"      width="${pw}" height="${ph}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${x + pw*2}" y="${y}"      width="${pw}" height="${ph}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${x}"        y="${y + ph}" width="${pw}" height="${ph}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${x + pw}"   y="${y + ph}" width="${pw}" height="${ph}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${x + pw*2}" y="${y + ph}" width="${pw}" height="${ph}" fill="url(#panelBlue2)" rx="${1*s}"/>

            <!-- Panel divider lines (vertical) -->
            <line x1="${x + pw}"   y1="${y}" x2="${x + pw}"   y2="${y + H}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <line x1="${x + pw*2}" y1="${y}" x2="${x + pw*2}" y2="${y + H}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <!-- Panel divider line (horizontal) -->
            <line x1="${x}" y1="${y + ph}" x2="${x + W}" y2="${y + ph}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <!-- Inner cell lines (each panel has 2x3 micro-cells) -->
            ${[0,1,2].map(col => svg`
                <line x1="${x + col*pw + pw/3}"   y1="${y}" x2="${x + col*pw + pw/3}"   y2="${y+H}" stroke="rgba(0,0,0,0.2)" stroke-width="${0.7*s}"/>
                <line x1="${x + col*pw + pw*2/3}" y1="${y}" x2="${x + col*pw + pw*2/3}" y2="${y+H}" stroke="rgba(0,0,0,0.2)" stroke-width="${0.7*s}"/>
            `)}
            <line x1="${x}" y1="${y + ph/3}"   x2="${x+W}" y2="${y + ph/3}"   stroke="rgba(0,0,0,0.18)" stroke-width="${0.7*s}"/>
            <line x1="${x}" y1="${y + ph*2/3}" x2="${x+W}" y2="${y + ph*2/3}" stroke="rgba(0,0,0,0.18)" stroke-width="${0.7*s}"/>

            <!-- Outer panel border -->
            <rect x="${x}" y="${y}" width="${W}" height="${H}"
                  fill="none" stroke="#ff9800" stroke-width="${2*s}" rx="${1.5*s}" opacity="0.8"/>

            <!-- Reflective sheen overlay -->
            <rect x="${x}" y="${y}" width="${W}" height="${H * 0.45}"
                  fill="url(#panelReflect)" rx="${1.5*s}" opacity="0.5"/>

            <!-- Orange accent connector to inverter -->
            <circle cx="${cx}" cy="${y + H + frameH + 3*s}" r="${3*s}"
                    fill="#ff9800" opacity="0.6"/>
        `;
    }

    /**
     * Sun rays — 8 triangular rays around center
     */
    _sunRays(cx, cy, r) {
        const rays = [];
        for (let i = 0; i < 8; i++) {
            const angle = (i * 45) * Math.PI / 180;
            const inner = r + 3;
            const outer = r + r * 0.7;
            const spread = 0.18;
            const a1 = angle - spread, a2 = angle + spread;
            const x1 = cx + Math.cos(a1) * inner;
            const y1 = cy + Math.sin(a1) * inner;
            const x2 = cx + Math.cos(angle) * outer;
            const y2 = cy + Math.sin(angle) * outer;
            const x3 = cx + Math.cos(a2) * inner;
            const y3 = cy + Math.sin(a2) * inner;
            rays.push(svg`<polygon points="${x1},${y1} ${x2},${y2} ${x3},${y3}"
                                    fill="#FCD170" opacity="0.85"/>`);
        }
        return rays;
    }

    /**
     * Inverter — wall-mounted box with DC->AC label and status LED
     */
    _illustrationInverter(cx, cy, r) {
        const s = r / 20;
        const bw = 38 * s, bh = 28 * s;
        const x = cx - bw / 2, y = cy - bh / 2;
        return svg`
            <!-- Box body -->
            <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${4*s}"
                  fill="url(#invGrad)" stroke="#96CAEE" stroke-width="${1.5*s}" opacity="0.9"/>
            <!-- Top vent lines -->
            ${[0,1,2].map(i => svg`
                <line x1="${x + 4*s + i*5*s}" y1="${y + 3*s}" x2="${x + 4*s + i*5*s}" y2="${y + 7*s}"
                      stroke="#96CAEE" stroke-width="${1*s}" stroke-linecap="round" opacity="0.4"/>
            `)}
            <!-- DC arrow -->
            <text x="${cx - 8*s}" y="${cy + 2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">DC</text>
            <!-- Lightning bolt symbol -->
            <path d="M${cx - 1*s},${cy - 4*s} L${cx - 3*s},${cy + 1*s} L${cx},${cy + 1*s}
                     L${cx},${cy + 5*s} L${cx + 2*s},${cy} L${cx - 1*s},${cy}"
                  fill="#FCD170" opacity="0.85"/>
            <!-- AC label -->
            <text x="${cx + 8*s}" y="${cy + 2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">AC</text>
            <!-- Status LED -->
            <circle cx="${x + bw - 5*s}" cy="${y + 4*s}" r="${2.5*s}"
                    fill="#69f0ae" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.4;0.9" dur="2.5s" repeatCount="indefinite"/>
            </circle>
            <!-- Bottom connector nub -->
            <rect x="${cx - 3*s}" y="${y + bh}" width="${6*s}" height="${3*s}" rx="${1*s}"
                  fill="#96CAEE" opacity="0.4"/>
        `;
    }

    /**
     * Battery — tall storage unit with SOC fill bar
     * The batt-fill rect height is updated imperatively to show SOC level
     */
    _illustrationBattery(cx, cy, r) {
        const s = r / 50;
        const bw = 40 * s, bh = 64 * s;
        const x = cx - bw / 2, y = cy - bh / 2;
        const termH = 8 * s, termW = 16 * s;
        const innerW = bw - 8 * s, innerH = bh - 12 * s;
        const innerX = x + 4 * s, innerY = y + 8 * s;
        return svg`
            <!-- Outer glow halo -->
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#4db6ac" stroke-width="1.2" opacity="0.25"/>

            <!-- Terminal cap on top -->
            <rect x="${cx - termW/2}" y="${y - termH}" width="${termW}" height="${termH}"
                  rx="${3*s}" fill="#2a4a47" stroke="#4db6ac" stroke-width="${1.5*s}" opacity="0.85"/>
            <!-- Plus terminal -->
            <line x1="${cx - termW/4}" y1="${y - termH/2}"
                  x2="${cx + termW/4}" y2="${y - termH/2}"
                  stroke="#4db6ac" stroke-width="${2*s}" stroke-linecap="round" opacity="0.8"/>
            <line x1="${cx}" y1="${y - termH * 0.75}" x2="${cx}" y2="${y - termH * 0.25}"
                  stroke="#4db6ac" stroke-width="${2*s}" stroke-linecap="round" opacity="0.8"/>

            <!-- Main body -->
            <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${5*s}"
                  fill="url(#battBody)" stroke="#4db6ac" stroke-width="${2*s}" opacity="0.95"/>

            <!-- Fill level background (empty) -->
            <rect x="${innerX}" y="${innerY}" width="${innerW}" height="${innerH}"
                  rx="${3*s}" fill="rgba(0,0,0,0.4)"/>

            <!-- Fill level bar — height controlled imperatively via id="batt-fill" -->
            <!-- Initial height = 0 (bottom-anchored, y+height = bottom of inner area) -->
            <rect id="batt-fill"
                  x="${innerX}" y="${innerY + innerH}"
                  width="${innerW}" height="0"
                  rx="${3*s}" fill="url(#battFillGrad)" opacity="0.85"/>

            <!-- Cell segmentation lines (5 horizontal ticks) -->
            ${[1,2,3,4].map(i => svg`
                <line x1="${innerX}" y1="${innerY + innerH * i / 5}"
                      x2="${innerX + innerW}" y2="${innerY + innerH * i / 5}"
                      stroke="rgba(0,0,0,0.35)" stroke-width="${1.2*s}"/>
            `)}

            <!-- SOC percentage text centered in body (with dark outline for contrast) -->
            <text id="batt-soc-text" x="${cx}" y="${cy + 4*s}"
                  text-anchor="middle" font-family="'Segoe UI','Roboto',sans-serif"
                  font-size="${14*s}" font-weight="900" fill="#fff"
                  stroke="rgba(0,0,0,0.6)" stroke-width="${1.5*s}" paint-order="stroke">50%</text>

            <!-- Charging bolt icon (shown when charging) -->
            <g id="batt-bolt" style="display:none">
                <path d="M${cx - 4*s},${cy - 8*s} L${cx - 7*s},${cy + 2*s} L${cx - 1*s},${cy + 2*s}
                         L${cx - 1*s},${cy + 10*s} L${cx + 6*s},${cy - 2*s} L${cx + 1*s},${cy - 2*s} Z"
                      fill="#FCD170" opacity="0.9"/>
            </g>

            <!-- Bottom mount detail -->
            <rect x="${cx - 10*s}" y="${y + bh - 5*s}" width="${20*s}" height="${5*s}"
                  rx="${2*s}" fill="#4db6ac" opacity="0.25"/>
        `;
    }

    /**
     * House — roof + walls + windows + door + chimney
     * Adapted for dark background with lit window glow
     */
    _illustrationHouse(cx, cy, r) {
        const s = r / 62;
        // Wall bounds
        const ww = 80 * s, wh = 52 * s;
        const wx = cx - ww / 2, wy = cy - wh / 2 + 8 * s;
        // Roof apex
        const roofH = 38 * s;
        const rax = cx, ray = wy - roofH;
        // Chimney
        const chx = cx + 18 * s, chy = ray + 8 * s;
        const chw = 10 * s, chh = 18 * s;
        // Window dimensions
        const winW = 16 * s, winH = 14 * s;
        const winY = wy + 12 * s;
        const win1X = wx + 10 * s, win2X = wx + ww - 10 * s - winW;
        // Door
        const doorW = 14 * s, doorH = 24 * s;
        const doorX = cx - doorW / 2, doorY = wy + wh - doorH;
        return svg`
            <!-- Outer glow halo -->
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#5BC8D8" stroke-width="1.2" opacity="0.25"/>

            <!-- Chimney (behind roof) -->
            <rect x="${chx}" y="${chy - chh}" width="${chw}" height="${chh}"
                  rx="${2*s}" fill="#455A64" stroke="#546E7A" stroke-width="${1.2*s}"/>
            <!-- Chimney smoke puffs -->
            <circle cx="${chx + chw/2}" cy="${chy - chh - 5*s}" r="${3*s}"
                    fill="rgba(150,160,170,0.3)"/>
            <circle cx="${chx + chw/2 + 2*s}" cy="${chy - chh - 10*s}" r="${2.5*s}"
                    fill="rgba(150,160,170,0.2)"/>

            <!-- Roof -->
            <polygon points="${wx},${wy} ${wx + ww},${wy} ${rax},${ray}"
                     fill="url(#roofGrad)" stroke="#c62828" stroke-width="${1.5*s}"
                     stroke-linejoin="round"/>
            <!-- Roof ridge highlight -->
            <line x1="${rax - 18*s}" y1="${ray + 10*s}" x2="${rax + 18*s}" y2="${ray + 10*s}"
                  stroke="rgba(255,255,255,0.12)" stroke-width="${1*s}"/>
            <!-- Roof eaves overhang shadow -->
            <line x1="${wx - 3*s}" y1="${wy}" x2="${wx + ww + 3*s}" y2="${wy}"
                  stroke="#7f1010" stroke-width="${3*s}" opacity="0.5"/>

            <!-- Wall body -->
            <rect x="${wx}" y="${wy}" width="${ww}" height="${wh}"
                  rx="${2*s}" fill="url(#wallGrad)"
                  stroke="#546E7A" stroke-width="${1.5*s}"/>

            <!-- Window 1 — left -->
            <!-- Window frame -->
            <rect x="${win1X - 2*s}" y="${winY - 2*s}" width="${winW + 4*s}" height="${winH + 4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <!-- Window glass with glow -->
            <rect x="${win1X}" y="${winY}" width="${winW}" height="${winH}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <!-- Window pane dividers -->
            <line x1="${win1X + winW/2}" y1="${winY}" x2="${win1X + winW/2}" y2="${winY + winH}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${win1X}" y1="${winY + winH/2}" x2="${win1X + winW}" y2="${winY + winH/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <!-- Window 2 — right -->
            <rect x="${win2X - 2*s}" y="${winY - 2*s}" width="${winW + 4*s}" height="${winH + 4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${win2X}" y="${winY}" width="${winW}" height="${winH}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${win2X + winW/2}" y1="${winY}" x2="${win2X + winW/2}" y2="${winY + winH}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${win2X}" y1="${winY + winH/2}" x2="${win2X + winW}" y2="${winY + winH/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <!-- Door -->
            <rect x="${doorX}" y="${doorY}" width="${doorW}" height="${doorH}"
                  rx="${2*s}" fill="#506C7F" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <!-- Door window -->
            <rect x="${doorX + doorW * 0.15}" y="${doorY + 4*s}"
                  width="${doorW * 0.7}" height="${doorH * 0.35}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.6"/>
            <!-- Door knob -->
            <circle cx="${doorX + doorW * 0.75}" cy="${doorY + doorH * 0.62}" r="${1.5*s}"
                    fill="#FCD170" opacity="0.8"/>

            <!-- Wall corner highlights -->
            <line x1="${wx + 2*s}" y1="${wy + 4*s}" x2="${wx + 2*s}" y2="${wy + wh - 2*s}"
                  stroke="rgba(255,255,255,0.06)" stroke-width="${1.5*s}"/>
        `;
    }

    /**
     * Grid / Power transmission pole with drooping power lines
     */
    _illustrationGrid(cx, cy, r) {
        const s = r / 50;
        // Pole center
        const poleH = 72 * s;
        const poleW = 4 * s;
        const poleY = cy - poleH / 2 + 4 * s;
        const poleX = cx;
        // Cross arms Y positions
        const arm1Y = poleY + poleH * 0.22;
        const arm2Y = poleY + poleH * 0.42;
        const armW1 = 44 * s, armW2 = 32 * s;
        // Insulator radius
        const iR = 3 * s;
        return svg`
            <!-- Outer glow halo -->
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#488fc2" stroke-width="1.2" opacity="0.25"/>

            <!-- Main pole (tapered slightly) -->
            <polygon points="${poleX - poleW/2},${poleY + poleH}
                             ${poleX + poleW/2},${poleY + poleH}
                             ${poleX + poleW*0.35},${poleY}
                             ${poleX - poleW*0.35},${poleY}"
                     fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${1*s}"/>

            <!-- Ground footing -->
            <rect x="${poleX - 8*s}" y="${poleY + poleH - 4*s}"
                  width="${16*s}" height="${4*s}" rx="${2*s}"
                  fill="#5c7a9b" opacity="0.6"/>

            <!-- Upper cross-arm -->
            <rect x="${poleX - armW1/2}" y="${arm1Y - 3*s}" width="${armW1}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${0.8*s}"/>
            <!-- Upper arm support brace -->
            <line x1="${poleX}" y1="${arm1Y + 2*s}"
                  x2="${poleX - armW1 * 0.4}" y2="${arm1Y + 14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${poleX}" y1="${arm1Y + 2*s}"
                  x2="${poleX + armW1 * 0.4}" y2="${arm1Y + 14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>

            <!-- Lower cross-arm -->
            <rect x="${poleX - armW2/2}" y="${arm2Y - 3*s}" width="${armW2}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${0.8*s}"/>

            <!-- Insulators — upper arm (2 sides) -->
            <circle cx="${poleX - armW1/2}" cy="${arm1Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${poleX + armW1/2}" cy="${arm1Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <!-- Insulators — lower arm -->
            <circle cx="${poleX - armW2/2}" cy="${arm2Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${poleX + armW2/2}" cy="${arm2Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>

            <!-- Power line cables drooping from upper arm -->
            <path d="M${poleX - armW1/2},${arm1Y}
                     Q${poleX - armW1*0.7},${arm1Y + 18*s} ${poleX - armW1*0.95 - 15*s},${arm1Y + 12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>
            <path d="M${poleX + armW1/2},${arm1Y}
                     Q${poleX + armW1*0.7},${arm1Y + 18*s} ${poleX + armW1*0.95 + 15*s},${arm1Y + 12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>

            <!-- Lower wire cables -->
            <path d="M${poleX - armW2/2},${arm2Y}
                     Q${poleX - armW2*0.65},${arm2Y + 14*s} ${poleX - armW2*0.9 - 12*s},${arm2Y + 9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>
            <path d="M${poleX + armW2/2},${arm2Y}
                     Q${poleX + armW2*0.65},${arm2Y + 14*s} ${poleX + armW2*0.9 + 12*s},${arm2Y + 9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>

            <!-- Lightning bolt accent (center, decorative) -->
            <path d="M${cx - 3*s},${arm2Y + 8*s} L${cx - 5*s},${arm2Y + 14*s}
                     L${cx},${arm2Y + 14*s} L${cx},${arm2Y + 20*s}
                     L${cx + 4*s},${arm2Y + 11*s} L${cx},${arm2Y + 11*s} Z"
                  fill="#FCD170" opacity="0.6"/>
        `;
    }

    /**
     * EV Charger — charging station box + cable + sedan car silhouette
     */
    _illustrationEV(cx, cy, r) {
        const s = r / 44;
        // Charger box
        const bw = 22 * s, bh = 36 * s;
        // Position charger to left, car to right
        const chargerX = cx - 28 * s, chargerY = cy - bh / 2;
        // Car center
        const carCX = cx + 18 * s, carCY = cy + 4 * s;
        const carW = 52 * s, carH = 22 * s;
        const carX = carCX - carW / 2, carY = carCY - carH / 2;
        const wheelR = 6 * s;
        return svg`
            <!-- Outer glow halo -->
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#8DC892" stroke-width="1.2" opacity="0.25"/>

            <!-- Charger station box -->
            <rect x="${chargerX}" y="${chargerY}" width="${bw}" height="${bh}"
                  rx="${4*s}" fill="#1a2e22" stroke="#8DC892" stroke-width="${1.8*s}" opacity="0.95"/>
            <!-- Charger screen -->
            <rect x="${chargerX + 3*s}" y="${chargerY + 4*s}" width="${bw - 6*s}" height="${10*s}"
                  rx="${2*s}" fill="#0a1a12" stroke="#8DC892" stroke-width="${0.8*s}" opacity="0.8"/>
            <!-- Screen text (power reading) -->
            <text x="${chargerX + bw/2}" y="${chargerY + 4*s + 8*s}"
                  font-family="'Courier New',monospace" font-size="${5.5*s}"
                  fill="#8DC892" text-anchor="middle" opacity="0.8">AC</text>
            <!-- Charging bolt on charger -->
            <path d="M${chargerX + bw/2 - 3*s},${chargerY + 18*s}
                     L${chargerX + bw/2 - 5*s},${chargerY + 25*s}
                     L${chargerX + bw/2},${chargerY + 25*s}
                     L${chargerX + bw/2},${chargerY + 32*s}
                     L${chargerX + bw/2 + 4*s},${chargerY + 22*s}
                     L${chargerX + bw/2},${chargerY + 22*s} Z"
                  fill="#FCD170" opacity="0.9"/>
            <!-- Status LED -->
            <circle cx="${chargerX + bw - 5*s}" cy="${chargerY + 5*s}" r="${2.2*s}"
                    fill="#8DC892" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.3;0.9" dur="1.8s" repeatCount="indefinite"/>
            </circle>
            <!-- Cable from charger to car -->
            <path d="M${chargerX + bw},${chargerY + bh * 0.55}
                     C${chargerX + bw + 10*s},${chargerY + bh * 0.55}
                       ${carX - 10*s},${carCY}
                       ${carX},${carCY}"
                  fill="none" stroke="#8DC892" stroke-width="${2.5*s}"
                  stroke-linecap="round" opacity="0.7"/>
            <!-- Cable connector plug at car -->
            <circle cx="${carX}" cy="${carCY}" r="${3*s}"
                    fill="#8DC892" opacity="0.85"/>

            <!-- Car body — sedan profile -->
            <!-- Underbody -->
            <rect x="${carX + 5*s}" y="${carCY}" width="${carW - 10*s}" height="${carH/2}"
                  rx="${3*s}" fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <!-- Cabin (roofline) -->
            <path d="M${carX + 12*s},${carCY}
                     L${carX + 10*s},${carCY - carH * 0.7}
                     L${carX + 20*s},${carCY - carH * 0.85}
                     L${carX + carW - 18*s},${carCY - carH * 0.85}
                     L${carX + carW - 10*s},${carCY - carH * 0.7}
                     L${carX + carW - 8*s},${carCY} Z"
                  fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <!-- Windshield -->
            <path d="M${carX + 13*s},${carCY - 2*s}
                     L${carX + 11*s},${carCY - carH * 0.62}
                     L${carX + 22*s},${carCY - carH * 0.78}
                     L${carX + 24*s},${carCY - 2*s} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${0.8*s}"/>
            <!-- Rear window -->
            <path d="M${carX + carW - 14*s},${carCY - 2*s}
                     L${carX + carW - 22*s},${carCY - 2*s}
                     L${carX + carW - 20*s},${carCY - carH * 0.78}
                     L${carX + carW - 12*s},${carCY - carH * 0.62} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${0.8*s}"/>
            <!-- Wheels -->
            <circle cx="${carX + 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${carX + 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR * 0.4}"
                    fill="#8DC892" opacity="0.5"/>
            <circle cx="${carX + carW - 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${carX + carW - 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR * 0.4}"
                    fill="#8DC892" opacity="0.5"/>
            <!-- Headlight -->
            <ellipse cx="${carX + carW - 7*s}" cy="${carCY + carH/2 - 6*s}"
                     rx="${4*s}" ry="${2.5*s}"
                     fill="#FFF9C4" opacity="0.6"/>
        `;
    }

    // ══════════════════════════════════════════════════════════════════
    //  IMPERATIVE UPDATE PIPELINE
    // ══════════════════════════════════════════════════════════════════

    _updateFlowsImperative() {
        if (!this._hass) return;

        const solar      = this._getState('solar_power');
        const battery    = this._getState('battery_power');
        const gridImport = this._getState('grid_import_power');
        const gridExport = this._getState('grid_export_power');
        const ev         = this._getState('ev_power');
        const soc        = this._getState('battery_soc');

        const battCharge    = Math.max(0, battery);
        const battDischarge = Math.max(0, -battery);
        const home = Math.max(0, solar + gridImport + battDischarge - gridExport - battCharge - ev);

        const vals = { solar, battery, gridImport, gridExport, home, ev, soc };
        const key = JSON.stringify(vals);
        if (this._lastKey === key) return;
        this._lastKey = key;

        // Entity availability indicator
        const unavailable = [];
        for (const suffix of ['solar_power', 'battery_power', 'grid_import_power', 'grid_export_power', 'ev_power', 'battery_soc']) {
            const entity = this._hass.states[`${this.entityPrefix}${suffix}`];
            if (!entity || entity.state === 'unavailable' || entity.state === 'unknown') unavailable.push(suffix);
        }
        const statusEl = this.renderRoot.getElementById('entity-status');
        if (statusEl) {
            if (unavailable.length > 0) {
                statusEl.textContent = `\u26a0 ${unavailable.length} ${this._t('sensor_unavailable')}`;
                statusEl.style.display = 'block';
            } else {
                statusEl.style.display = 'none';
            }
        }

        // Animated power values
        this._animateValue('val-solar',     solar);
        this._animateValue('val-batt-power', Math.abs(battery), 800,
            v => battCharge > 10 ? `\u2191 ${semFormatPower(v)}` : battDischarge > 10 ? `\u2193 ${semFormatPower(v)}` : semFormatPower(v));
        this._animateValue('val-home',       home);
        this._animateValue('val-ev',         ev);

        // val-solar-kwh / val-home-kwh / val-ev-kwh / val-batt-kwh / val-grid-kwh (today totals)
        this._setText('val-solar-kwh',
            `${this._t('today')} ${this._getStateStr('daily_solar_energy')} kWh`);
        const forecast = this._getState('forecast_corrected_today');
        this._setText('val-solar-forecast',
            forecast > 0 ? `\u2600 ${forecast.toFixed(0)} kWh ${this._t('forecast') || 'Forecast'}` : '');
        this._setText('val-ev-kwh',
            `${this._t('today')} ${this._getStateStr('daily_ev_energy')} kWh`);
        this._setText('val-home-kwh',
            `${this._t('today')} ${this._getState('daily_home_energy').toFixed(1)} kWh`);
        const dailyCharge    = this._getState('daily_battery_charge_energy');
        const dailyDischarge = this._getState('daily_battery_discharge_energy');
        this._setText('val-batt-kwh',
            `+${dailyCharge.toFixed(1)} / -${dailyDischarge.toFixed(1)} kWh`);
        const dailyImport = this._getState('daily_grid_import_energy');
        const dailyExport = this._getState('daily_grid_export_energy');
        this._setText('val-grid-kwh',
            `\u2193${dailyImport.toFixed(1)} / \u2191${dailyExport.toFixed(1)} kWh`);

        // Grid display: always one direction (never both simultaneously)
        const gridSingleEl = this.renderRoot.getElementById('val-grid-single');
        if (gridExport > 10) {
            this._animateValue('val-grid-single', gridExport, 800, v => `\u2191 ${semFormatPower(v)}`);
            if (gridSingleEl) gridSingleEl.setAttribute('fill', '#8353d1');
        } else if (gridImport > 10) {
            this._animateValue('val-grid-single', gridImport, 800, v => `\u2193 ${semFormatPower(v)}`);
            if (gridSingleEl) gridSingleEl.setAttribute('fill', '#488fc2');
        } else {
            this._animateValue('val-grid-single', 0);
            if (gridSingleEl) gridSingleEl.setAttribute('fill', '#488fc2');
        }

        // Inverter: show temperature + SEM mode (abbreviated)
        const battTemp = this._getState('battery_temperature');
        this._setText('val-inv-temp', battTemp > 0 ? `${battTemp.toFixed(0)}\u00B0C` : '');
        const chargingState = this._getStateStr('charging_state');
        // Truncate long state text for compact
        const maxLen = this._compact ? 22 : 30;
        this._setText('val-inv-status', chargingState.length > maxLen ? chargingState.substring(0, maxLen - 1) + '\u2026' : chargingState);

        // Battery SOC fill bar (imperatively resize the batt-fill rect)
        this._updateBatterySOC(soc, battCharge, battDischarge);

        // Grid label + state
        const gridLabel = this.renderRoot.getElementById('label-grid');
        if (gridLabel) {
            gridLabel.textContent = this._t('grid');
            gridLabel.setAttribute('fill', gridExport > gridImport ? '#8353d1' : '#488fc2');
        }
        // Grid state — show direction label below value
        const gridState = this.renderRoot.getElementById('label-grid-state');
        if (gridState) {
            if (gridExport > 10 && gridExport > gridImport) {
                gridState.textContent = this._t('exporting');
                gridState.setAttribute('fill', '#8353d1');
            } else if (gridImport > 10) {
                gridState.textContent = this._t('importing');
                gridState.setAttribute('fill', '#488fc2');
            } else {
                gridState.textContent = '';
            }
        }

        // Battery state + value color (SEM color concept: pink=charge, teal=discharge)
        const battLabel = this.renderRoot.getElementById('label-batt-state');
        const battPowerEl = this.renderRoot.getElementById('val-batt-power');
        const battColor = battCharge > 10 ? '#f06292' : '#4db6ac';
        if (battLabel) {
            if (battCharge > 10) {
                battLabel.textContent = this._t('charging');
                battLabel.setAttribute('fill', '#f06292');
            } else if (battDischarge > 10) {
                battLabel.textContent = this._t('discharging');
                battLabel.setAttribute('fill', '#4db6ac');
            } else {
                battLabel.textContent = '';
            }
        }
        if (battPowerEl) battPowerEl.setAttribute('fill', battColor);

        // EV state label — uses SEM's own binary sensors
        const evState = this.renderRoot.getElementById('label-ev-state');
        if (evState) {
            const evConnected = this._hass?.states['binary_sensor.sem_ev_connected'];
            const evCharging = this._hass?.states['binary_sensor.sem_ev_charging'];
            const isPlugged = evConnected && evConnected.state === 'on';
            const isCharging = evCharging && evCharging.state === 'on';
            if (isCharging || ev > 10) {
                evState.textContent = this._t('charging');
                evState.setAttribute('fill', '#8DC892');
            } else if (isPlugged) {
                evState.textContent = this._t('connected') || 'Verbunden';
                evState.setAttribute('fill', 'rgba(141,200,146,0.6)');
            } else {
                evState.textContent = '';
            }
        }

        // Sun / moon day-night indicator
        this._updateSunPosition(solar);

        // Flow animations
        this._updateFlow('flow-solar',   solar > 10,               false,       semCalcDuration(solar));
        // Battery flow: pink when charging, teal when discharging
        const battFlowGroup = this.renderRoot.getElementById('flow-battery');
        if (battFlowGroup) battFlowGroup.dataset.color = battCharge > 10 ? '#f06292' : '#4db6ac';
        this._updateFlow('flow-battery', Math.abs(battery) > 10,   battery < 0, semCalcDuration(battery));
        // Grid flow: blue when importing, purple when exporting
        const gridFlowGroup = this.renderRoot.getElementById('flow-grid');
        if (gridFlowGroup) gridFlowGroup.dataset.color = gridExport > gridImport ? '#8353d1' : '#488fc2';
        this._updateFlow('flow-grid',    gridImport > 10 || gridExport > 10,
                         gridImport > gridExport, semCalcDuration(gridImport || gridExport));
        this._updateFlow('flow-home',    home > 10,  false, semCalcDuration(home));
        this._updateFlow('flow-ev',      ev > 10,    false, semCalcDuration(ev));

        // Top 3 devices by power — desktop only, bottom-right
        if (!this._compact) this._updateDeviceLabels();
    }

    /**
     * Update battery SOC fill bar and text imperatively.
     * The batt-fill rect is bottom-anchored inside the battery body.
     */
    _updateBatterySOC(soc, battCharge, battDischarge) {
        const L = this._getLayout();
        const r = L.B.r;
        const s = r / 50;
        const bh = 64 * s;
        const innerH = bh - 12 * s;
        const innerY = L.B.cy - bh / 2 + 8 * s;
        const fillH = Math.max(0, Math.min(innerH, innerH * (soc / 100)));
        const fillY = innerY + innerH - fillH;

        const fillEl = this.renderRoot.getElementById('batt-fill');
        if (fillEl) {
            fillEl.setAttribute('height', fillH.toFixed(1));
            fillEl.setAttribute('y', fillY.toFixed(1));
            // Color: pink when charging, teal otherwise
            if (battCharge > 10) {
                fillEl.setAttribute('fill', '#f06292');
            } else {
                fillEl.setAttribute('fill', 'url(#battFillGrad)');
            }
        }

        // SOC percentage text
        this._setText('batt-soc-text', `${soc.toFixed(0)}%`);

        // Charging bolt visibility
        const boltEl = this.renderRoot.getElementById('batt-bolt');
        if (boltEl) {
            boltEl.style.display = battCharge > 10 ? '' : 'none';
        }
    }

    /**
     * Update sun/moon position and day-night indicator based on solar power.
     * Sun position is fixed in render — only day/night state is toggled here.
     */
    _updateSunPosition(solar) {
        const sunEntity = this._hass?.states['sun.sun'];
        const elevation = sunEntity ? parseFloat(sunEntity.attributes?.elevation) || -90 : -90;
        const isNight = elevation < 0;

        const moonEl  = this.renderRoot.getElementById('moon-crescent');
        const starsEl = this.renderRoot.getElementById('stars');
        const sunGlowEl = this.renderRoot.getElementById('sun-glow');

        if (moonEl)   moonEl.style.display  = isNight ? 'block' : 'none';
        if (starsEl)  starsEl.style.display = isNight ? 'block' : 'none';
        if (sunGlowEl) sunGlowEl.style.opacity = isNight ? '0.3' : '0.9';

        // Sun-to-solar spark (visible when producing, path follows sun position)
        const sparkEl = this.renderRoot.getElementById('sun-spark');
        if (sparkEl) sparkEl.style.opacity = solar > 50 ? String(Math.min(1, 0.3 + solar / 5000)) : '0';

        // Sun power label
        this._setText('sun-power-label', solar > 10 ? semFormatPower(solar) : '');

        // Sunrise/sunset labels + time-based position
        const a = sunEntity?.attributes;
        if (a) {
            if (a.next_rising) {
                const d = new Date(a.next_rising);
                this._setText('sun-rising', `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`);
            }
            if (a.next_setting) {
                const d = new Date(a.next_setting);
                this._setText('sun-setting', `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`);
            }

            const nextRiseTs = a.next_rising ? new Date(a.next_rising).getTime() : 0;
            const nextSetTs = a.next_setting ? new Date(a.next_setting).getTime() : 0;
            const now = Date.now();
            let pos = 0.5;
            if (!isNight && nextRiseTs && nextSetTs) {
                const todaySunrise = nextRiseTs - 86400000;
                const dayLength = nextSetTs - todaySunrise;
                if (dayLength > 0) pos = (now - todaySunrise) / dayLength;
            } else {
                pos = (nextRiseTs && now < nextRiseTs) ? 0 : 1;
            }
            pos = Math.max(0.06, Math.min(0.94, pos));

            // Move sun/moon along arc using SVG transform (no CSS — avoids conflicts)
            const L = this._getLayout();
            const arcPath = this.renderRoot.querySelector('#sun-arc-path');
            if (arcPath) {
                try {
                    const len = arcPath.getTotalLength();
                    const pt = arcPath.getPointAtLength(pos * len);
                    const dx = pt.x - L.sunX;
                    const dy = pt.y - L.sunY;

                    // Scale sun based on solar production (0.7 at 0W, 1.3 at 10kW)
                    const scale = isNight ? 0.7 : (0.7 + 0.6 * Math.min(1, solar / 10000));

                    // SVG transform: translate to new pos, then scale around sun center
                    if (sunGlowEl) {
                        sunGlowEl.setAttribute('transform',
                            `translate(${dx.toFixed(1)},${dy.toFixed(1)}) translate(${L.sunX},${L.sunY}) scale(${scale.toFixed(2)}) translate(${(-L.sunX).toFixed(1)},${(-L.sunY).toFixed(1)})`);
                    }
                    if (moonEl && isNight) {
                        moonEl.setAttribute('transform', `translate(${dx.toFixed(1)},${dy.toFixed(1)})`);
                    }
                    const powerLabel = this.renderRoot.getElementById('sun-power-label');
                    if (powerLabel) {
                        powerLabel.setAttribute('x', pt.x.toFixed(1));
                        powerLabel.setAttribute('y', (pt.y + L.sunR * scale + 16).toFixed(1));
                    }

                    // Dynamic sine wave from sun to solar panels
                    const sparkGroup = this.renderRoot.getElementById('sun-spark');
                    if (solar > 50 && sparkGroup) {
                        const sx = pt.x, sy = pt.y;
                        const tx = L.S.cx, ty = L.S.cy - L.S.r;
                        const totalDx = tx - sx, totalDy = ty - sy;
                        const dist = Math.sqrt(totalDx * totalDx + totalDy * totalDy);
                        const waves = Math.max(2, Math.round(dist / 30));
                        const amp = 6 + Math.min(8, solar / 1000);
                        const angle = Math.atan2(totalDy, totalDx);
                        const perpX = -Math.sin(angle), perpY = Math.cos(angle);
                        const steps = waves * 8;
                        let sparkD = `M${sx.toFixed(1)},${sy.toFixed(1)}`;
                        for (let i = 1; i <= steps; i++) {
                            const frac = i / steps;
                            const cx2 = sx + totalDx * frac;
                            const cy2 = sy + totalDy * frac;
                            const wave = Math.sin(frac * waves * Math.PI * 2) * amp;
                            sparkD += ` L${(cx2 + perpX * wave).toFixed(1)},${(cy2 + perpY * wave).toFixed(1)}`;
                        }
                        // Very slow, calm particles — random timing for natural feel
                        // 12s at low power, 5s at 10kW peak
                        const baseDur = 12 - 7 * Math.min(1, solar / 10000);
                        const sparkSig = `${baseDur.toFixed(0)}:${sx.toFixed(0)}`;
                        if (sparkGroup.dataset.sig !== sparkSig) {
                            sparkGroup.dataset.sig = sparkSig;
                            // Generate 4-6 particles with random durations and start offsets
                            const count = 3 + Math.floor(Math.min(3, solar / 3000));
                            let particles = `
                                <path id="spark-wave" d="${sparkD}" fill="none"
                                      stroke="rgba(255,200,60,0.12)" stroke-width="2.5" stroke-linecap="round"
                                      filter="url(#glowSun)"/>`;
                            for (let i = 0; i < count; i++) {
                                // Each particle has a unique speed and random start
                                const dur = (baseDur * (0.7 + Math.random() * 0.6)).toFixed(1);
                                const delay = (Math.random() * baseDur).toFixed(1);
                                const r = 1.5 + Math.random() * 2;
                                const op = (0.4 + Math.random() * 0.5).toFixed(2);
                                // Alternate between golden and white-core particles
                                if (i % 2 === 0) {
                                    particles += `
                                        <circle r="${r.toFixed(1)}" fill="rgba(255,220,60,${op})" filter="url(#glowSun)">
                                            <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced" begin="-${delay}s">
                                                <mpath href="#spark-wave"/></animateMotion>
                                        </circle>`;
                                } else {
                                    particles += `
                                        <circle r="${(r * 0.6).toFixed(1)}" fill="rgba(255,255,230,${op})">
                                            <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced" begin="-${delay}s">
                                                <mpath href="#spark-wave"/></animateMotion>
                                        </circle>`;
                                }
                            }
                            sparkGroup.innerHTML = particles;
                        }
                    }
                } catch (_) { /* arc not ready */ }
            }
        }
    }

    // ── Flow animation helper ──
    _updateFlow(groupId, active, reverse, duration) {
        const group = this.renderRoot.getElementById(groupId);
        if (!group) return;
        group.style.opacity = active ? '1' : '0';
        if (!active) { group.dataset.sig = ''; return; }

        const pathId  = group.dataset.pathId;
        const pathD   = group.dataset.pathD;
        const color   = group.dataset.color;
        const count   = parseInt(group.dataset.count, 10) || 2;
        const newSig  = `${reverse ? 'r' : 'f'}:${duration.toFixed(1)}:${color}:${pathD}`;
        if (group.dataset.sig === newSig) return;
        group.dataset.sig = newSig;
        group.innerHTML = this._flowEffects(pathD, pathId, color, count, duration, reverse);
    }

    /**
     * K-Flow inspired multi-layer spark effect.
     * Layer 1: Background glow — wide stroke, low opacity, blurred
     * Layer 2: White highlight — thin stroke, medium opacity
     * Layer 3: Colored core — normal stroke, high opacity
     * Plus: Small animated dots traveling along the path
     */
    _flowEffects(pathD, pathId, color, count, duration, reverse) {
        const dur = duration.toFixed(1);
        const cycle = 28;
        const toOffset = reverse ? String(cycle) : String(-cycle);
        const reverseAttrs = reverse ? ' keyPoints="1;0" keyTimes="0;1"' : '';

        // Layer 1: background glow (wide, soft opacity — no blur filter to avoid artifacts)
        let result = `<path d="${pathD}" fill="none" stroke="${color}" stroke-width="5"
                           stroke-dasharray="8,${cycle - 8}" opacity="0.2" stroke-linecap="round">
                        <animate attributeName="stroke-dashoffset" from="0" to="${toOffset}"
                                 dur="${dur}s" repeatCount="indefinite"/>
                      </path>`;

        // Layer 2: white highlight (thin, semi-transparent)
        result += `<path d="${pathD}" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.2"
                         stroke-dasharray="6,${cycle - 6}" opacity="0.45" stroke-linecap="round">
                     <animate attributeName="stroke-dashoffset" from="0" to="${toOffset}"
                              dur="${dur}s" repeatCount="indefinite"/>
                   </path>`;

        // Layer 3: colored core (normal, high opacity)
        result += `<path d="${pathD}" fill="none" stroke="${color}" stroke-width="2.5"
                         stroke-dasharray="8,${cycle - 8}" opacity="0.65" stroke-linecap="round">
                     <animate attributeName="stroke-dashoffset" from="0" to="${toOffset}"
                              dur="${dur}s" repeatCount="indefinite"/>
                   </path>`;

        // Animated dots traveling along path
        for (let i = 0; i < count; i++) {
            const delay = (i / count) * duration;
            result += `
                <circle r="5" fill="${color}" opacity="0.12">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>
                <circle r="2.5" fill="${color}" opacity="0.95">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>
                <circle r="1" fill="rgba(255,255,255,0.9)" opacity="0.85">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>`;
        }
        return result;
    }

    // ── Device labels ──
    _updateDeviceLabels() {
        const container = this.renderRoot.getElementById('device-labels');
        if (!container) return;

        const devicesEntity = this._hass.states[`${this.entityPrefix}controllable_devices_count`];
        if (!devicesEntity?.attributes?.devices) { container.innerHTML = ''; return; }

        // Top 3 devices sorted by power consumption (exclude EV charger — already shown)
        const devices = Object.entries(devicesEntity.attributes.devices)
            .filter(([, info]) => info.device_type !== 'ev_charger')
            .map(([id, info]) => {
                const powerEntity = info.power_entity ? this._hass.states[info.power_entity] : null;
                const power = powerEntity ? parseFloat(powerEntity.state) || 0 : (info.current_power || 0);
                return { id, ...info, power };
            })
            .sort((a, b) => b.power - a.power)
            .slice(0, 3);

        if (!devices.length) { container.innerHTML = ''; return; }

        const F = "'Segoe UI','Roboto',sans-serif";
        const L = this._getLayout();
        const H = L.H;
        const colors = SEM_DEVICE_COLORS;
        // Position: bottom-right, stacked vertically
        const baseX = 540, baseY = 310;
        const spacing = 50;
        let svgHtml = '';

        devices.forEach((dev, idx) => {
            let name = (dev.name || dev.id).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            if (name.length > 22) name = name.substring(0, 21) + '\u2026';
            const color = colors[idx % colors.length];
            const isOn = dev.is_on || dev.power > 5;
            const cy = baseY + idx * spacing;
            const cx = baseX;

            // Arc connection from house to device (curves right to avoid other nodes)
            const pathD = `M${H.cx + H.r},${H.cy + 10 + idx * 8} C${H.cx + H.r + 40},${H.cy + 30 + idx * 15} ${cx - 30},${cy - 10} ${cx - 16},${cy}`;
            svgHtml += `<path d="${pathD}" fill="none" stroke="${color}" stroke-width="1"
                              stroke-dasharray="3,5" opacity="${isOn ? 0.3 : 0.1}"/>`;

            // Animated flow dot when device is consuming power
            if (dev.power > 5) {
                const dur = semCalcDuration(dev.power).toFixed(1);
                svgHtml += `<path id="dev-path-${idx}" d="${pathD}" fill="none" stroke="none"/>
                            <circle r="1.5" fill="${color}" opacity="0.8">
                                <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced">
                                    <mpath href="#dev-path-${idx}"/></animateMotion>
                            </circle>`;
            }

            // Device icon circle (small)
            const r = 14;
            svgHtml += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="rgba(128,128,128,${isOn ? 0.06 : 0.02})"
                                stroke="${color}" stroke-width="0.8" opacity="${isOn ? 0.7 : 0.3}"/>`;
            const icon = this._deviceIcon(dev.device_type, dev.name || dev.id);
            svgHtml += `<g transform="translate(${cx},${cy}) scale(0.7)" stroke="${color}" fill="none"
                           opacity="${isOn ? 0.6 : 0.25}" stroke-width="1.3" stroke-linecap="round">${icon}</g>`;

            // Name + power text
            svgHtml += `<text x="${cx + r + 6}" y="${cy - 2}" font-family="${F}" font-size="10"
                              font-weight="500" fill="${color}" opacity="0.7">${name}</text>`;
            svgHtml += `<text x="${cx + r + 6}" y="${cy + 11}" font-family="${F}" font-size="10"
                              font-weight="700" fill="${color}" opacity="${isOn ? 0.9 : 0.4}">${semFormatPower(dev.power)}</text>`;
        });

        container.innerHTML = svgHtml;
    }

    // ── Helpers ──
    _animateValue(id, newWatts, duration = 800, formatFn = null) {
        const el = this.renderRoot.getElementById(id);
        if (!el) return;
        if (this._animFrames[id]) cancelAnimationFrame(this._animFrames[id]);
        const fmt = formatFn || (v => semFormatPower(v));
        const oldWatts = this._currentValues[id] || 0;
        this._currentValues[id] = newWatts;
        if (Math.abs(oldWatts - newWatts) < 1) { el.textContent = fmt(newWatts); return; }
        const startTime = performance.now();
        const animate = (now) => {
            const progress = Math.min(1, (now - startTime) / duration);
            const eased = progress < 0.5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
            el.textContent = fmt(oldWatts + (newWatts - oldWatts) * eased);
            if (progress < 1) { this._animFrames[id] = requestAnimationFrame(animate); }
            else { delete this._animFrames[id]; }
        };
        this._animFrames[id] = requestAnimationFrame(animate);
    }

    _setText(id, text) {
        const el = this.renderRoot.getElementById(id);
        if (el && el.textContent !== text) el.textContent = text;
    }

    _getState(suffix) {
        if (!this._hass) return 0;
        const entity = this._hass.states[`${this.entityPrefix}${suffix}`];
        if (!entity) return 0;
        const val = parseFloat(entity.state);
        return isNaN(val) ? 0 : val;
    }

    _getStateStr(suffix) {
        if (!this._hass) return '';
        const entity = this._hass.states[`${this.entityPrefix}${suffix}`];
        return entity ? entity.state : '';
    }

    _glowFilter(id, color, blur) {
        return svg`<filter id="${id}" x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur stdDeviation="${blur}" result="blur"/>
            <feFlood flood-color="${color}" flood-opacity="0.28"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`;
    }

    _showMoreInfo(suffix) {
        const entityId = `${this.entityPrefix}${suffix}`;
        this.dispatchEvent(new CustomEvent('hass-more-info', {
            bubbles: true, composed: true,
            detail: { entityId },
        }));
    }

    // ── Layout ──
    _getLayout() {
        if (this._compact) {
            // viewBox 0 0 400 680 — vertical: Solar→Inv→Batt/Grid→House+EV
            return {
                vb: '0 0 400 680',
                S:  { cx: 200, cy: 100, r: 44, labelY: 154 },
                I:  { cx: 200, cy: 232, r: 20 },
                B:  { cx: 100, cy: 360, r: 44, labelY: 414 },
                G:  { cx: 300, cy: 360, r: 44, labelY: 414 },
                H:  { cx: 200, cy: 540, r: 48, labelY: 598 },
                E:  { cx: 84,  cy: 555, r: 34, labelY: 598 },
                paths: {
                    solar:   'M200,144 L200,212',
                    battery: 'M188,242 C155,278 120,315 100,316',
                    grid:    'M212,242 C245,278 280,315 300,316',
                    home:    'M200,252 C200,390 200,460 200,492',
                    ev:      'M200,252 C200,400 140,490 84,521',
                },
                sunArc:     'M30,68 Q200,6 370,68',
                sunX: 200, sunY: 20, sunR: 12,
                sunRisingX: 40, sunSettingX: 360, sunLabelY: 76,
                starX: [60, 120, 280, 330, 180],
                starY: [20, 12, 18, 24, 8],
                font: { label: 11, value: 15, sub: 10 },
                statusY: 660,
                wmX: 390, wmY: 676,
            };
        }
        // viewBox 0 0 660 480 — desktop left-to-right flow
        return {
            vb: '0 0 700 510',
            S:  { cx: 85,  cy: 140, r: 48, labelY: 200 },
            I:  { cx: 220, cy: 200, r: 20 },
            E:  { cx: 150, cy: 390, r: 42, labelY: 442 },
            B:  { cx: 340, cy: 390, r: 48, labelY: 448 },
            H:  { cx: 400, cy: 230, r: 52, labelY: 292 },
            G:  { cx: 570, cy: 140, r: 46, labelY: 198 },
            paths: {
                solar:   'M118,148 C158,165 192,188 208,200',
                home:    'M242,198 C300,200 350,210 360,218',
                battery: 'M228,215 C260,280 320,340 338,342',
                grid:    'M232,188 C320,130 450,110 524,130',
                ev:      'M210,215 C180,275 162,330 150,348',
            },
            sunArc:     'M20,52 Q330,2 640,52',
            sunX: 330, sunY: 12, sunR: 12,
            sunRisingX: 28, sunSettingX: 632, sunLabelY: 60,
            starX: [100, 200, 450, 550, 330],
            starY: [20, 12, 15, 28, 8],
            font: { label: 11, value: 16, sub: 10 },
            statusY: 495,
            wmX: 690, wmY: 506,
        };
    }

    _deviceIcon(type, name) {
        const n = (name || '').toLowerCase();
        const t = (type || '').toLowerCase();
        if (t === 'ev_charger' || n.includes('keba') || n.includes('charger') || n.includes('wallbox'))
            return `<rect x="-5" y="-9" width="10" height="14" rx="2"/>
                    <path d="M-1.5,-3.5 L0,1.5 L1.5,-3.5"/>
                    <line x1="0" y1="5" x2="0" y2="9"/>`;
        if (n.includes('heiz') || n.includes('heat') || n.includes('warm') || n.includes('boiler'))
            return `<path d="M-3,-9 C-3,-3 3,-3 3,-9"/>
                    <path d="M-3,-2 C-3,4 3,4 3,-2"/>
                    <path d="M-3,5 C-3,9 3,9 3,5"/>`;
        if (n.includes('wash') || n.includes('sp\u00FCl') || n.includes('geschirr') || n.includes('wasch'))
            return `<circle r="9"/><circle r="4.5"/><circle r="1.3" fill="currentColor" opacity="0.3" stroke="none"/>`;
        if (n.includes('pool') || n.includes('pump'))
            return `<circle r="7"/><path d="M-5,0 L5,0 M0,-5 L0,5" opacity="0.5"/>`;
        if (n.includes('klima') || n.includes('ac') || n.includes('cool') || n.includes('air'))
            return `<rect x="-9" y="-5" width="18" height="10" rx="2"/>
                    <path d="M-5,5 C-5,9 -2,9 -2,5" fill="none"/>
                    <path d="M2,5 C2,9 5,9 5,5" fill="none"/>`;
        if (n.includes('light') || n.includes('licht') || n.includes('lamp'))
            return `<path d="M-4,-9 C-7,-2 -2,3 -1.5,5 L1.5,5 C2,3 7,-2 4,-9 C2,-12 -2,-12 -4,-9Z"/>
                    <line x1="-1.5" y1="6" x2="1.5" y2="6"/>`;
        return `<path d="M-2.5,-9 L-2.5,0 L-5,0 L0,9 L0,0 L2.5,0 L-2.5,-9Z"/>`;
    }

    getCardSize() { return 7; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-system-diagram-card', SEMSystemDiagramCard, {
    type: 'sem-system-diagram-card',
    name: 'SEM System Diagram',
    description: 'Power flow visualization with inline SVG illustrations for each energy component',
});
