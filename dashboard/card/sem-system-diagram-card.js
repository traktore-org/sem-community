/**
 * SEM System Diagram Card - Lumina-inspired power flow visualization
 *
 * Features:
 * - Responsive layout: compact on mobile, spread on desktop
 * - Circular hub-spoke layout with Home as central hub
 * - Pulsing glow rings with power-proportional intensity
 * - Shimmer dashes + animated dot flow along curved bezier paths
 * - Battery SOC arc with charging pulse animation
 * - Animated number transitions with easing
 * - Light-theme compatible with soft tinted fills
 */

class SEMSystemDiagramCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._lastKey = '';
        this._animFrames = {};
        this._currentValues = {};
        this._compact = false;
        this._rendered = false;
        this._visible = true;
        this._updateTimer = null;
    }

    setConfig(config) {
        this.config = config;
        this.entityPrefix = config.entity_prefix || 'sensor.sem_';
    }

    connectedCallback() {
        this._resizeObserver = new ResizeObserver(entries => {
            for (const entry of entries) {
                const w = entry.contentRect.width;
                const compact = w < 500;
                if (compact !== this._compact) {
                    this._compact = compact;
                    this._rendered = false;
                    this._render();
                    this._rendered = true;
                    if (this._hass) this._updateFlows();
                }
            }
        });
        this._resizeObserver.observe(this);

        // Pause animations when card is off-screen
        this._visible = true;
        this._intersectionObserver = new IntersectionObserver(entries => {
            this._visible = entries[0].isIntersecting;
            const svg = this.shadowRoot.querySelector('svg');
            if (svg) svg.style.animationPlayState = this._visible ? 'running' : 'paused';
        }, { threshold: 0.01 });
        this._intersectionObserver.observe(this);
    }

    disconnectedCallback() {
        if (this._resizeObserver) this._resizeObserver.disconnect();
        if (this._intersectionObserver) this._intersectionObserver.disconnect();
        clearTimeout(this._updateTimer);
        for (const id of Object.keys(this._animFrames)) {
            cancelAnimationFrame(this._animFrames[id]);
        }
        this._animFrames = {};
    }

    set hass(hass) {
        this._hass = hass;
        // Initial render only — check layout once
        if (!this._rendered) {
            const w = this.clientWidth || this.offsetWidth;
            const compact = w > 0 ? w < 500 : false;
            if (compact !== this._compact) this._compact = compact;
            this._render();
            this._rendered = true;
        }
        // Skip update if card is not visible (off-screen tab)
        if (!this._visible) return;
        // Debounce flow updates (#30)
        clearTimeout(this._updateTimer);
        this._updateTimer = setTimeout(() => this._updateFlows(), 100);
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

    _formatPower(watts) {
        const abs = Math.abs(watts);
        if (abs >= 1000) return `${(watts / 1000).toFixed(1)} kW`;
        return `${Math.round(watts)} W`;
    }

    _calcDuration(watts) {
        const abs = Math.abs(watts);
        if (abs <= 0) return 4;
        const dur = 4 - Math.log10(Math.max(abs, 1)) * 0.9;
        return Math.max(0.5, Math.min(4, dur));
    }

    _setText(id, text) {
        const el = this.shadowRoot.getElementById(id);
        if (el) el.textContent = text;
    }

    _animateValue(id, newWatts, duration = 800) {
        const el = this.shadowRoot.getElementById(id);
        if (!el) return;

        if (this._animFrames[id]) {
            cancelAnimationFrame(this._animFrames[id]);
        }

        const oldWatts = this._currentValues[id] || 0;
        this._currentValues[id] = newWatts;

        if (Math.abs(oldWatts - newWatts) < 1) {
            el.textContent = this._formatPower(newWatts);
            return;
        }

        const startTime = performance.now();
        const animate = (now) => {
            const progress = Math.min(1, (now - startTime) / duration);
            const eased = progress < 0.5
                ? 2 * progress * progress
                : 1 - Math.pow(-2 * progress + 2, 2) / 2;
            const current = oldWatts + (newWatts - oldWatts) * eased;
            el.textContent = this._formatPower(current);
            if (progress < 1) {
                this._animFrames[id] = requestAnimationFrame(animate);
            } else {
                delete this._animFrames[id];
            }
        };
        this._animFrames[id] = requestAnimationFrame(animate);
    }

    _setGlowIntensity(nodeId, watts, maxWatts) {
        const ring = this.shadowRoot.querySelector(`#${nodeId} .glow-ring`);
        if (!ring) return;
        const ratio = Math.min(1, Math.abs(watts) / maxWatts);
        ring.style.opacity = (0.15 + ratio * 0.85).toFixed(2);
    }

    _updateFlows() {
        const solar = this._getState('solar_power');
        const battery = this._getState('battery_power');
        const gridImport = this._getState('grid_import_power');
        const gridExport = this._getState('grid_export_power');
        const ev = this._getState('ev_power');
        const soc = this._getState('battery_soc');

        const battCharge = Math.max(0, battery);
        const battDischarge = Math.max(0, -battery);
        const home = Math.max(
            0,
            solar + gridImport + battDischarge - gridExport - battCharge - ev
        );

        const vals = { solar, battery, gridImport, gridExport, home, ev, soc };
        const key = JSON.stringify(vals);
        if (this._lastKey === key) return;
        this._lastKey = key;

        // Track entity availability for visual feedback (#38)
        const unavailable = [];
        for (const suffix of ['solar_power', 'battery_power', 'grid_import_power', 'grid_export_power', 'ev_power', 'battery_soc']) {
            const entity = this._hass.states[`${this.entityPrefix}${suffix}`];
            if (!entity || entity.state === 'unavailable' || entity.state === 'unknown') {
                unavailable.push(suffix);
            }
        }
        const statusEl = this.shadowRoot.getElementById('entity-status');
        if (statusEl) {
            if (unavailable.length > 0) {
                statusEl.textContent = `⚠ ${unavailable.length} sensor${unavailable.length > 1 ? 's' : ''} unavailable`;
                statusEl.style.display = 'block';
            } else {
                statusEl.style.display = 'none';
            }
        }

        // Animated power values
        this._animateValue('val-solar', solar);
        this._animateValue('val-battery-power', battery);
        this._animateValue('val-grid', gridImport > 0 ? gridImport : gridExport);
        this._animateValue('val-home', home);
        this._animateValue('val-ev', ev);

        // Non-animated text
        this._setText('val-battery-soc', `${soc.toFixed(0)}%`);
        this._setText('val-inverter-status', this._getStateStr('charging_state'));
        this._setText('val-today-solar', `Today ${this._getStateStr('daily_solar_energy')} kWh`);
        this._setText('val-today-ev', `Today ${this._getStateStr('daily_ev_energy')} kWh`);
        this._setText('val-autarky', `Autarky ${this._getStateStr('autarky_rate')}%`);

        // Battery SOC arc
        const socArc = this.shadowRoot.getElementById('soc-arc');
        if (socArc) {
            const circumference = this._compact ? 207.3 : 282.7;
            socArc.style.strokeDashoffset = (circumference * (1 - soc / 100)).toFixed(1);
            socArc.style.animation = battCharge > 10 ? 'socPulse 2s ease-in-out infinite' : 'none';
        }

        // Grid label
        const gridLabel = this.shadowRoot.getElementById('label-grid');
        if (gridLabel) {
            gridLabel.textContent = gridImport > gridExport ? 'IMPORT' : (gridExport > 10 ? 'EXPORT' : 'GRID');
        }

        // Battery label
        const battLabel = this.shadowRoot.getElementById('label-battery-state');
        if (battLabel) {
            battLabel.textContent = battCharge > 10 ? 'CHARGING' : (battDischarge > 10 ? 'DISCHARGE' : '');
        }

        // Flow animations
        this._updateFlow('flow-solar', solar > 10, false, this._calcDuration(solar));
        const battActive = Math.abs(battery) > 10;
        const battReverse = battery < 0;
        this._updateFlow('flow-battery', battActive, battReverse, this._calcDuration(battery));
        const gridActive = gridImport > 10 || gridExport > 10;
        const gridReverse = gridImport > gridExport;
        this._updateFlow('flow-grid', gridActive, gridReverse, this._calcDuration(gridImport || gridExport));
        this._updateFlow('flow-home', home > 10, false, this._calcDuration(home));
        this._updateFlow('flow-ev', ev > 10, false, this._calcDuration(ev));

        // Power-proportional glow
        this._setGlowIntensity('node-solar', solar, 10000);
        this._setGlowIntensity('node-battery', Math.abs(battery), 5000);
        this._setGlowIntensity('node-grid', Math.max(gridImport, gridExport), 10000);
        this._setGlowIntensity('node-home', home, 8000);
        this._setGlowIntensity('node-ev', ev, 11000);

        this._updateDeviceLabels();
    }

    _updateFlow(groupId, active, reverse, duration) {
        const group = this.shadowRoot.getElementById(groupId);
        if (!group) return;

        group.style.opacity = active ? '1' : '0';
        if (!active) {
            group.dataset.sig = '';
            return;
        }

        const pathId = group.dataset.pathId;
        const pathD = group.dataset.pathD;
        const color = group.dataset.color;
        const count = parseInt(group.dataset.count, 10) || 2;
        const newSig = `${reverse ? 'r' : 'f'}:${duration.toFixed(1)}`;
        if (group.dataset.sig === newSig) return;
        group.dataset.sig = newSig;
        group.innerHTML = this._flowEffects(pathD, pathId, color, count, duration, reverse);
    }

    _flowEffects(pathD, pathId, color, count, duration, reverse) {
        const dur = duration.toFixed(1);
        const dashOffset = reverse ? '32' : '-32';
        const reverseAttrs = reverse ? ' keyPoints="1;0" keyTimes="0;1"' : '';

        let svg = `<path d="${pathD}" fill="none" stroke="${color}" stroke-width="3"
                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">
                     <animate attributeName="stroke-dashoffset" from="0" to="${dashOffset}"
                              dur="${dur}s" repeatCount="indefinite"/>
                   </path>`;

        for (let i = 0; i < count; i++) {
            const delay = (i / count) * duration;
            svg += `
                <circle r="5" fill="${color}" opacity="0.12">
                    <animateMotion dur="${dur}s" repeatCount="indefinite"
                        calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>
                <circle r="2.5" fill="${color}" opacity="0.9">
                    <animateMotion dur="${dur}s" repeatCount="indefinite"
                        calcMode="paced"${reverseAttrs} begin="-${delay.toFixed(2)}s">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>`;
        }
        return svg;
    }

    _updateDeviceLabels() {
        const container = this.shadowRoot.getElementById('device-labels');
        if (!container) return;

        const devicesEntity = this._hass.states[`${this.entityPrefix}controllable_devices_count`];
        if (!devicesEntity || !devicesEntity.attributes || !devicesEntity.attributes.devices) {
            container.innerHTML = '';
            return;
        }

        const colors = ['#FF8A65', '#AED581', '#CE93D8', '#64B5F6', '#ff9800', '#96CAEE'];
        const devices = Object.entries(devicesEntity.attributes.devices)
            .filter(([, info]) => info.power_entity || info.current_power > 0)
            .sort((a, b) => (a[1].priority || 5) - (b[1].priority || 5))
            .slice(0, 6);

        if (devices.length === 0) {
            container.innerHTML = '';
            return;
        }

        const F = "'Segoe UI','Roboto',sans-serif";
        const compact = this._compact;
        const L = this._getLayout();
        const H = L.home;
        const nodeR = compact ? 26 : 24;
        const cols = compact ? 2 : Math.min(devices.length, 3);
        const vbW = compact ? 500 : 1000;
        const margin = compact ? 30 : 60;
        const colWidth = (vbW - margin * 2) / cols;
        const baseY = L.deviceY;
        const maxChars = compact ? 18 : 20;
        let html = '';

        devices.forEach(([id, info], idx) => {
            let name = (info.name || id);
            if (name.length > maxChars) name = name.substring(0, maxChars - 1) + '\u2026';
            const powerEntity = info.power_entity ? this._hass.states[info.power_entity] : null;
            const power = powerEntity ? parseFloat(powerEntity.state) || 0 : (info.current_power || 0);
            const color = colors[idx % colors.length];
            const isOn = info.is_on || power > 5;

            const col = idx % cols;
            const row = Math.floor(idx / cols);
            const cx = margin + (col * colWidth) + (colWidth / 2);
            const cy = baseY + (row * (compact ? 100 : 90));
            const fs = compact ? 11 : 11;
            const icon = this._deviceIcon(info.device_type, info.name || id);

            // Connection line from Home to device
            const opacity = isOn ? 0.3 : 0.1;
            html += `<path d="M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${cx},${cy - 40} ${cx},${cy - nodeR}"
                           fill="none" stroke="${color}" stroke-width="1.2" stroke-dasharray="3,5" opacity="${opacity}"/>`;

            // Animated flow when device is consuming
            if (power > 5) {
                const dur = this._calcDuration(power).toFixed(1);
                html += `<path d="M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${cx},${cy - 40} ${cx},${cy - nodeR}"
                               fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">
                             <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${dur}s" repeatCount="indefinite"/>
                           </path>`;
                html += `<circle r="2" fill="${color}" opacity="0.8">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced" begin="-${(idx * 0.3).toFixed(1)}s">
                        <mpath href="#dev-path-${idx}"/>
                    </animateMotion>
                </circle>`;
                html += `<path id="dev-path-${idx}" d="M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${cx},${cy - 40} ${cx},${cy - nodeR}" fill="none" stroke="none"/>`;
            }

            // Device circle node
            const fillOpacity = isOn ? 0.08 : 0.03;
            const strokeOpacity = isOn ? 1 : 0.4;
            html += `<circle cx="${cx}" cy="${cy}" r="${nodeR}" fill="rgba(128,128,128,${fillOpacity})" stroke="${color}" stroke-width="1.2" opacity="${strokeOpacity}"/>`;

            // Device icon
            html += `<g transform="translate(${cx},${cy})" stroke="${color}" fill="none" opacity="${isOn ? 0.7 : 0.35}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">`;
            html += icon;
            html += `</g>`;

            // Name + power
            html += `<text x="${cx}" y="${cy + nodeR + 14}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="500" fill="${color}" opacity="0.8">${name}</text>`;
            html += `<text x="${cx}" y="${cy + nodeR + 14 + fs + 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="600" fill="${color}" opacity="${isOn ? 1 : 0.5}">${this._formatPower(power)}</text>`;
        });
        container.innerHTML = html;
    }

    _deviceIcon(type, name) {
        const n = (name || '').toLowerCase();
        const t = (type || '').toLowerCase();

        // EV charger
        if (t === 'ev_charger' || n.includes('keba') || n.includes('charger') || n.includes('wallbox')) {
            return `<rect x="-6" y="-10" width="12" height="16" rx="2"/>
                    <path d="M-2,-4 L0,2 L2,-4"/>
                    <line x1="0" y1="6" x2="0" y2="10"/>`;
        }
        // Heater / heating band / hot water
        if (n.includes('heiz') || n.includes('heat') || n.includes('warm') || n.includes('boiler')) {
            return `<path d="M-4,-10 C-4,-4 4,-4 4,-10"/>
                    <path d="M-4,-3 C-4,3 4,3 4,-3"/>
                    <path d="M-4,4 C-4,10 4,10 4,4"/>`;
        }
        // Washing machine / dishwasher
        if (n.includes('wash') || n.includes('spül') || n.includes('geschirr') || n.includes('wasch')) {
            return `<circle r="10" fill="none"/>
                    <circle r="5" fill="none"/>
                    <circle r="1.5" fill="${'currentColor'}" opacity="0.3" stroke="none"/>`;
        }
        // Dryer
        if (n.includes('dryer') || n.includes('trockn')) {
            return `<circle r="10" fill="none"/>
                    <path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>`;
        }
        // Pool / pump
        if (n.includes('pool') || n.includes('pump')) {
            return `<circle r="8" fill="none"/>
                    <path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/>
                    <path d="M-4,-4 L4,4 M4,-4 L-4,4"/>`;
        }
        // AC / climate
        if (n.includes('klima') || n.includes('ac') || n.includes('cool') || n.includes('air')) {
            return `<rect x="-10" y="-6" width="20" height="12" rx="2"/>
                    <path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/>
                    <path d="M2,6 C2,10 6,10 6,6" fill="none"/>`;
        }
        // Light
        if (n.includes('light') || n.includes('licht') || n.includes('lamp')) {
            return `<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/>
                    <line x1="-2" y1="8" x2="2" y2="8"/>`;
        }
        // Shelly / smart switch / plug
        if (n.includes('shelly') || n.includes('plug') || n.includes('switch') || n.includes('steckdose')) {
            return `<rect x="-8" y="-10" width="16" height="20" rx="3"/>
                    <circle cx="-3" cy="-2" r="2" fill="none"/>
                    <circle cx="3" cy="-2" r="2" fill="none"/>
                    <line x1="0" y1="4" x2="0" y2="7"/>`;
        }
        // Default: generic power device
        return `<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>`;
    }

    /** Layout coordinates for desktop (wide) and mobile (compact) */
    _getLayout() {
        if (this._compact) {
            // Mobile: 500x1060 viewBox, vertical stack, nodes centered
            return {
                vb: '0 0 500 1060',
                solar:    { cx: 250, cy: 70,  r: 48 },
                inverter: { cx: 250, cy: 195, r: 20 },
                battery:  { cx: 100, cy: 310, r: 48 },
                grid:     { cx: 400, cy: 310, r: 48 },
                home:     { cx: 250, cy: 480, r: 60 },
                ev:       { cx: 100, cy: 630, r: 42 },
                socR: 33,
                paths: {
                    solar:   'M250,118 L250,175',
                    home:    'M250,215 L250,420',
                    battery: 'M230,200 C180,230 120,260 100,262',
                    grid:    'M270,200 C320,230 380,260 400,262',
                    ev:      'M230,210 C180,350 130,530 100,588',
                },
                font: { label: 14, value: 22, sub: 12, homeVal: 26 },
                deviceY: 780,
            };
        }
        // Desktop: 1000x780 viewBox, wide spread
        return {
            vb: '0 0 1000 780',
            solar:    { cx: 500, cy: 65,  r: 50 },
            inverter: { cx: 500, cy: 185, r: 20 },
            battery:  { cx: 150, cy: 240, r: 50 },
            grid:     { cx: 850, cy: 240, r: 50 },
            home:     { cx: 500, cy: 355, r: 62 },
            ev:       { cx: 150, cy: 430, r: 44 },
            socR: 40,
            paths: {
                solar:   'M500,115 L500,165',
                home:    'M500,205 L500,293',
                battery: 'M480,190 C380,200 250,215 200,240',
                grid:    'M520,190 C620,200 750,215 800,240',
                ev:      'M480,198 C380,300 250,380 195,430',
            },
            font: { label: 13, value: 20, sub: 11, homeVal: 24 },
            deviceY: 560,
        };
    }

    _render() {
        // Reset flow cache so _updateFlows() repopulates after re-render
        this._lastKey = '';
        const F = "'Segoe UI','Roboto',sans-serif";
        const L = this._getLayout();
        const S = L.solar, I = L.inverter, B = L.battery, G = L.grid, H = L.home, E = L.ev;
        const socCirc = (2 * Math.PI * L.socR).toFixed(1);
        const fl = L.font.label, fv = L.font.value, fs = L.font.sub, fhv = L.font.homeVal;

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                ha-card { overflow: hidden; padding: 0; background: transparent !important; }
                svg { width: 100%; display: block; }
                .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
                .glow-ring { transition: opacity 1s ease; }
                #soc-arc { transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1); }
                text { font-variant-numeric: tabular-nums; }
                @keyframes socPulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
            </style>
            <ha-card>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${L.vb}" style="background:transparent" role="img" aria-label="Solar energy system diagram showing power flows between solar, battery, grid, home and EV charger">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="45%" r="60%">
                            <stop offset="0%" stop-color="rgba(200,220,240,0.08)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                            <circle cx="25" cy="25" r="0.7" fill="rgba(128,128,128,0.08)"/>
                        </pattern>
                        <filter id="textGlow" x="-20%" y="-20%" width="140%" height="140%">
                            <feGaussianBlur stdDeviation="2" result="blur"/>
                            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                        </filter>
                        ${this._glowFilter('glowSolar',   '#ff9800', 8)}
                        ${this._glowFilter('glowBattery', '#4db6ac', 8)}
                        ${this._glowFilter('glowGrid',    '#488fc2', 8)}
                        ${this._glowFilter('glowHome',    '#5BC8D8', 10)}
                        ${this._glowFilter('glowEV',      '#8DC892', 8)}
                        ${this._glowFilter('glowInverter','#96CAEE', 6)}

                        <path id="path-solar"   d="${L.paths.solar}"/>
                        <path id="path-home"    d="${L.paths.home}"/>
                        <path id="path-battery" d="${L.paths.battery}"/>
                        <path id="path-grid"    d="${L.paths.grid}"/>
                        <path id="path-ev"      d="${L.paths.ev}"/>
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%" fill="url(#dotGrid)"/>

                    <!-- Static flow tracks -->
                    ${this._track(L.paths.solar,   '#ff9800')}
                    ${this._track(L.paths.home,    '#5BC8D8')}
                    ${this._track(L.paths.battery, '#4db6ac')}
                    ${this._track(L.paths.grid,    '#488fc2')}
                    ${this._track(L.paths.ev,      '#8DC892')}

                    <!-- Animated flow groups -->
                    <g id="flow-solar" class="flow-group" style="opacity:0"
                       data-path-id="path-solar" data-path-d="${L.paths.solar}" data-color="#ff9800" data-count="2"></g>
                    <g id="flow-battery" class="flow-group" style="opacity:0"
                       data-path-id="path-battery" data-path-d="${L.paths.battery}" data-color="#4db6ac" data-count="3"></g>
                    <g id="flow-grid" class="flow-group" style="opacity:0"
                       data-path-id="path-grid" data-path-d="${L.paths.grid}" data-color="#488fc2" data-count="3"></g>
                    <g id="flow-home" class="flow-group" style="opacity:0"
                       data-path-id="path-home" data-path-d="${L.paths.home}" data-color="#5BC8D8" data-count="2"></g>
                    <g id="flow-ev" class="flow-group" style="opacity:0"
                       data-path-id="path-ev" data-path-d="${L.paths.ev}" data-color="#8DC892" data-count="3"></g>

                    <!-- SOLAR -->
                    <g id="node-solar" filter="url(#glowSolar)">
                        ${this._glowRing(S, '#ff9800')}
                        <circle cx="${S.cx}" cy="${S.cy}" r="${S.r}" fill="rgba(255,152,0,0.07)" stroke="#ff9800" stroke-width="1.8"/>
                        <g transform="translate(${S.cx},${S.cy - 8})" stroke="#ff9800" fill="none" opacity="0.75">
                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>
                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>
                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>
                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>
                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>
                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>
                        </g>
                    </g>
                    <text x="${S.cx}" y="${S.cy + S.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="#ff9800">Solar</text>
                    <text id="val-solar" x="${S.cx}" y="${S.cy + S.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="#ff9800">0 W</text>
                    <text id="val-today-solar" x="${S.cx}" y="${S.cy + S.r + 18 + fv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="#ff9800" opacity="0.55"></text>

                    <!-- INVERTER -->
                    <g id="node-inverter" filter="url(#glowInverter)">
                        <circle cx="${I.cx}" cy="${I.cy}" r="${I.r}" fill="rgba(150,202,238,0.07)" stroke="#96CAEE" stroke-width="1"/>
                        <path d="M${I.cx - 10},${I.cy} Q${I.cx - 4},${I.cy - 8} ${I.cx},${I.cy} Q${I.cx + 4},${I.cy + 8} ${I.cx + 10},${I.cy}" fill="none" stroke="#96CAEE" stroke-width="1.8" opacity="0.7"/>
                    </g>
                    <text id="val-inverter-status" x="${I.cx}" y="${I.cy + I.r + 14}" text-anchor="middle" font-family="${F}" font-size="${this._compact ? 11 : 10}" fill="#5a7a9a" opacity="0.7"></text>

                    <!-- BATTERY -->
                    <g id="node-battery" filter="url(#glowBattery)">
                        ${this._glowRing(B, '#4db6ac')}
                        <circle cx="${B.cx}" cy="${B.cy}" r="${B.r}" fill="rgba(77,182,172,0.07)" stroke="#4db6ac" stroke-width="1.8"/>
                        <circle cx="${B.cx}" cy="${B.cy}" r="${L.socR}" fill="none" stroke="rgba(77,182,172,0.1)" stroke-width="5"/>
                        <circle id="soc-arc" cx="${B.cx}" cy="${B.cy}" r="${L.socR}" fill="none" stroke="#4db6ac" stroke-width="5"
                                stroke-dasharray="${socCirc}" stroke-dashoffset="${socCirc}"
                                transform="rotate(-90 ${B.cx} ${B.cy})" stroke-linecap="round" opacity="0.75"/>
                        <g transform="translate(${B.cx},${B.cy})" stroke="#4db6ac" fill="none" opacity="0.7">
                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>
                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="#4db6ac" opacity="0.5" stroke="none"/>
                        </g>
                    </g>
                    <text x="${B.cx}" y="${B.cy + B.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="#4db6ac">Battery</text>
                    <text id="val-battery-soc" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="#4db6ac">0%</text>
                    <text id="val-battery-power" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="500" fill="#4db6ac" opacity="0.7">0 W</text>
                    <text id="label-battery-state" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="#4db6ac" opacity="0.5"></text>

                    <!-- GRID -->
                    <g id="node-grid" filter="url(#glowGrid)">
                        ${this._glowRing(G, '#488fc2')}
                        <circle cx="${G.cx}" cy="${G.cy}" r="${G.r}" fill="rgba(72,143,194,0.07)" stroke="#488fc2" stroke-width="1.8"/>
                        <g transform="translate(${G.cx},${G.cy})" stroke="#488fc2" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">
                            <line x1="0" y1="-16" x2="0" y2="14"/>
                            <line x1="-10" y1="-8" x2="10" y2="-8"/>
                            <line x1="-7" y1="-1" x2="7" y2="-1"/>
                            <line x1="-10" y1="-8" x2="-5" y2="14"/>
                            <line x1="10" y1="-8" x2="5" y2="14"/>
                        </g>
                    </g>
                    <text x="${G.cx}" y="${G.cy + G.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="#488fc2">Grid</text>
                    <text id="val-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="#488fc2">0 W</text>
                    <text id="label-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9 + fl}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="500" fill="#488fc2" opacity="0.5">GRID</text>

                    <!-- HOME (central hub) -->
                    <g id="node-home" filter="url(#glowHome)">
                        ${this._glowRing(H, '#5BC8D8', 1.4)}
                        <circle cx="${H.cx}" cy="${H.cy}" r="${H.r}" fill="rgba(91,200,216,0.06)" stroke="#5BC8D8" stroke-width="2"/>
                        <g transform="translate(${H.cx},${H.cy - 5})" stroke="#5BC8D8" fill="none" opacity="0.6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M-20,2 L0,-14 L20,2"/>
                            <rect x="-14" y="2" width="28" height="20" rx="2"/>
                            <rect x="-4" y="10" width="8" height="12"/>
                        </g>
                    </g>
                    <text x="${H.cx}" y="${H.cy + H.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl + 1}" font-weight="600" fill="#5BC8D8">Home</text>
                    <text id="val-home" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fhv}" font-weight="700" fill="#5BC8D8">0 W</text>
                    <text id="val-autarky" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="#5BC8D8" opacity="0.5"></text>

                    <!-- EV -->
                    <g id="node-ev" filter="url(#glowEV)">
                        ${this._glowRing(E, '#8DC892')}
                        <circle cx="${E.cx}" cy="${E.cy}" r="${E.r}" fill="rgba(141,200,146,0.07)" stroke="#8DC892" stroke-width="1.8"/>
                        <g transform="translate(${E.cx},${E.cy})" stroke="#8DC892" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>
                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>
                            <path d="M-1,-1 L0,3 L1,-1"/>
                            <line x1="0" y1="9" x2="0" y2="13"/>
                            <circle cx="0" cy="15" r="1.5" fill="#8DC892" opacity="0.4" stroke="none"/>
                        </g>
                    </g>
                    <text x="${E.cx}" y="${E.cy + E.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="#8DC892">EV Charger</text>
                    <text id="val-ev" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="#8DC892">0 W</text>
                    <text id="val-today-ev" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="#8DC892" opacity="0.5"></text>

                    <!-- Device labels -->
                    <g id="device-labels"></g>

                    <!-- Entity status indicator (#38) -->
                    <foreignObject x="10" y="${this._compact ? 1030 : 750}" width="200" height="20">
                        <div xmlns="http://www.w3.org/1999/xhtml" id="entity-status" style="display:none;font-family:'Segoe UI','Roboto',sans-serif;font-size:10px;color:#ef5350;opacity:0.7"></div>
                    </foreignObject>

                    <!-- SEM watermark -->
                    <text x="${this._compact ? 470 : 960}" y="${this._compact ? 1050 : 770}" text-anchor="end" font-family="${F}" font-size="10" font-weight="300" letter-spacing="2" fill="rgba(0,0,0,0.1)">SEM</text>
                </svg>
            </ha-card>
        `;
    }

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

    getCardSize() {
        return 8;
    }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

customElements.define('sem-system-diagram-card', SEMSystemDiagramCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-system-diagram-card',
    name: 'SEM System Diagram',
    description: 'Responsive power flow visualization with circular nodes and shimmer animations',
});
