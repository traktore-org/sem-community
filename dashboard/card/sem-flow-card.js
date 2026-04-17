/**
 * SEM Flow Card — Animated energy flow diagram for Home Assistant
 *
 * Standalone Lovelace card for visualizing solar, battery, grid, EV,
 * and up to 6 individual devices with animated power flows.
 *
 * Works with ANY Home Assistant entities — not just SEM.
 *
 * Config:
 *   type: custom:sem-flow-card
 *   entities:
 *     solar:
 *       entity: sensor.solar_power
 *       name: Solar              # optional
 *       color: "#ff9800"         # optional
 *       daily_energy: sensor.solar_daily   # optional
 *       tap_action:              # optional
 *         action: more-info
 *       hold_action:             # optional
 *         action: navigate
 *         navigation_path: /energy
 *     grid:
 *       consumption: sensor.grid_import_power
 *       production: sensor.grid_export_power
 *       daily_import_energy: sensor.grid_daily_import  # optional
 *       daily_export_energy: sensor.grid_daily_export  # optional
 *       color_import: "#488fc2"  # optional
 *       color_export: "#8353d1"  # optional
 *     battery:
 *       entity: sensor.battery_power
 *       state_of_charge: sensor.battery_soc
 *       daily_energy: sensor.battery_daily  # optional
 *     home:
 *       entity: sensor.home_consumption
 *       autarky: sensor.autarky_rate        # optional
 *       daily_energy: sensor.home_daily     # optional
 *     individual:
 *       - entity: sensor.ev_power
 *         name: EV Charger
 *         icon: mdi:car-electric
 *         daily_energy: sensor.ev_daily     # optional
 *         tap_action:
 *           action: more-info
 *       - entity: sensor.heat_pump_power
 *         name: Heat Pump
 *         icon: mdi:heat-pump
 *   # OR backward compatible with SEM:
 *   entity_prefix: sensor.sem_
 */

const SFC_DEFAULTS = {
    solar: { name: 'Solar', color: '#ff9800' },
    grid: { name: 'Grid', color_import: '#488fc2', color_export: '#8353d1' },
    battery: { name: 'Battery', color: '#4db6ac' },
    home: { name: 'Home', color: '#5BC8D8' },
    ev: { name: 'EV Charger', color: '#8DC892' },
    inverter: { name: 'Inverter', color: '#96CAEE' },
};

const SFC_DEVICE_COLORS = ['#FF8A65', '#AED581', '#CE93D8', '#64B5F6', '#ff9800', '#96CAEE'];

const SFC_ACTION_OPTIONS = [
    { value: 'more-info', label: 'More Info' },
    { value: 'toggle', label: 'Toggle' },
    { value: 'navigate', label: 'Navigate' },
    { value: 'url', label: 'Open URL' },
    { value: 'call-service', label: 'Call Service' },
    { value: 'none', label: 'None' },
];

const SFC_ACTION_SCHEMAS = [
    { name: 'tap_action', label: 'Tap Action', selector: { select: { options: SFC_ACTION_OPTIONS } } },
    { name: 'hold_action', label: 'Hold Action', selector: { select: { options: SFC_ACTION_OPTIONS } } },
    { name: 'double_tap_action', label: 'Double Tap Action', selector: { select: { options: SFC_ACTION_OPTIONS } } },
];

class SEMFlowCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._lastKey = '';
        this._animFrames = {};
        this._currentValues = {};
        this._compact = false;
        this._rendered = false;
        this._visible = true;
        this._deviceConfigSig = '';
        this._devicePositions = [];
    }

    setConfig(config) {
        this.config = config;

        if (config.entity_prefix) {
            this._mode = 'prefix';
            this._prefix = config.entity_prefix;
        } else if (config.entities) {
            this._mode = 'entities';
            this._entities = config.entities;
        } else {
            throw new Error('sem-flow-card requires either "entities" or "entity_prefix" config');
        }

        this._showLabels = config.show_labels !== false;
        this._showValues = config.show_values !== false;
        this._showGlow = config.show_glow !== false;
        this._showInverter = config.show_inverter !== false;
    }

    connectedCallback() {
        let resizeTimeout = null;
        this._resizeObserver = new ResizeObserver(entries => {
            if (resizeTimeout) clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                for (const entry of entries) {
                    const w = entry.contentRect.width;
                    const compact = w < 400;
                    if (compact !== this._compact) {
                        this._compact = compact;
                        this._rendered = false;
                        this._deviceConfigSig = '';
                        this._render();
                        this._rendered = true;
                        if (this._hass) this._updateFlows();
                    }
                }
            }, 100);
        });
        this._resizeObserver.observe(this);

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
        // Clean up animation frames to prevent memory leaks
        for (const id of Object.keys(this._animFrames)) {
            cancelAnimationFrame(this._animFrames[id]);
        }
        this._animFrames = {};
    }

    set hass(hass) {
        this._hass = hass;
        if (!this._rendered) {
            const w = this.clientWidth || this.offsetWidth;
            const compact = w > 0 ? w < 400 : false;
            if (compact !== this._compact) this._compact = compact;
            this._render();
            this._rendered = true;
        }
        if (!this._visible) return;
        this._updateFlows();
    }

    _getState(key) {
        if (!this._hass) return 0;
        let entityId;
        if (this._mode === 'prefix') {
            entityId = `${this._prefix}${key}`;
        } else {
            entityId = this._resolveEntity(key);
        }
        if (!entityId) return 0;
        const entity = this._hass.states[entityId];
        if (!entity) return 0;
        const val = parseFloat(entity.state);
        return isNaN(val) ? 0 : val;
    }

    _getStateStr(key) {
        if (!this._hass) return '';
        let entityId;
        if (this._mode === 'prefix') {
            entityId = `${this._prefix}${key}`;
        } else {
            entityId = this._resolveEntity(key);
        }
        if (!entityId) return '';
        const entity = this._hass.states[entityId];
        return entity ? entity.state : '';
    }

    _resolveEntity(key) {
        const e = this._entities;
        if (!e) return null;
        switch (key) {
            case 'solar_power': return e.solar?.entity;
            case 'battery_power': return e.battery?.entity;
            case 'battery_charge_power': return e.battery?.charge;
            case 'battery_discharge_power': return e.battery?.discharge;
            case 'grid_power': return e.grid?.entity;
            case 'grid_import_power': return e.grid?.consumption;
            case 'grid_export_power': return e.grid?.production;
            case 'ev_power': return e.ev?.entity || e.individual?.[0]?.entity;
            case 'battery_soc': return e.battery?.state_of_charge;
            case 'home_consumption_power': return e.home?.entity;
            case 'charging_state': return e.inverter?.entity;
            case 'daily_solar_energy': return e.solar?.daily_energy;
            case 'daily_ev_energy': return e.ev?.daily_energy || e.individual?.[0]?.daily_energy;
            case 'daily_grid_import_energy': return e.grid?.daily_import_energy;
            case 'daily_grid_export_energy': return e.grid?.daily_export_energy;
            case 'daily_battery_energy': return e.battery?.daily_energy;
            case 'daily_home_energy': return e.home?.daily_energy;
            case 'autarky_rate': return e.home?.autarky;
            default: return null;
        }
    }

    _getNodeColor(node) {
        const e = this._entities;
        if (!e) return SFC_DEFAULTS[node]?.color || '#888';
        switch (node) {
            case 'solar': return e.solar?.color || SFC_DEFAULTS.solar.color;
            case 'battery': return e.battery?.color || SFC_DEFAULTS.battery.color;
            case 'grid': return e.grid?.color_import || SFC_DEFAULTS.grid.color_import;
            case 'grid_import': return e.grid?.color_import || SFC_DEFAULTS.grid.color_import;
            case 'grid_export': return e.grid?.color_export || SFC_DEFAULTS.grid.color_export;
            case 'home': return e.home?.color || SFC_DEFAULTS.home.color;
            case 'ev': return e.ev?.color || e.individual?.[0]?.color || SFC_DEFAULTS.ev.color;
            case 'inverter': return SFC_DEFAULTS.inverter.color;
            default: return '#888';
        }
    }

    _getNodeName(node) {
        const e = this._entities;
        if (!e) return SFC_DEFAULTS[node]?.name || node;
        switch (node) {
            case 'solar': return e.solar?.name || SFC_DEFAULTS.solar.name;
            case 'battery': return e.battery?.name || SFC_DEFAULTS.battery.name;
            case 'grid': return e.grid?.name || SFC_DEFAULTS.grid.name;
            case 'home': return e.home?.name || SFC_DEFAULTS.home.name;
            case 'ev': return e.ev?.name || e.individual?.[0]?.name || SFC_DEFAULTS.ev.name;
            default: return node;
        }
    }

    _getEntityId(key) {
        if (this._mode === 'prefix') return `${this._prefix}${key}`;
        return this._resolveEntity(key);
    }

    _hasNode(node) {
        if (this._mode === 'prefix') return true;
        const e = this._entities;
        if (!e) return false;
        switch (node) {
            case 'solar': return !!e.solar?.entity;
            case 'battery': return !!(e.battery?.entity || e.battery?.charge || e.battery?.discharge);
            case 'grid': return !!(e.grid?.consumption || e.grid?.entity);
            case 'home': return true; // always show — auto-calculated if no entity
            case 'ev': return !!(e.ev?.entity || e.individual?.[0]?.entity);
            case 'inverter': return !!e.inverter?.entity || this._hasNode('solar');
            default: return false;
        }
    }

    _getActionConfig(node, actionType) {
        const e = this._entities;
        if (!e) return { action: actionType === 'tap_action' ? 'more-info' : 'none' };

        let nodeConfig;
        if (node.startsWith('device_')) {
            const idx = parseInt(node.split('_')[1]);
            nodeConfig = e.individual?.[idx];
        } else {
            switch (node) {
                case 'solar': nodeConfig = e.solar; break;
                case 'battery': nodeConfig = e.battery; break;
                case 'grid': nodeConfig = e.grid; break;
                case 'home': nodeConfig = e.home; break;
                case 'ev': nodeConfig = e.ev || e.individual?.[0]; break;
            }
        }

        const action = nodeConfig?.[actionType];
        if (!action) return { action: actionType === 'tap_action' ? 'more-info' : 'none' };
        return typeof action === 'string' ? { action } : action;
    }

    _fireMoreInfo(entityId) {
        if (!entityId) return;
        this.dispatchEvent(new CustomEvent('hass-more-info', {
            detail: { entityId },
            bubbles: true,
            composed: true,
        }));
    }

    _handleAction(config, entityId) {
        if (!config) config = { action: 'more-info' };
        switch (config.action) {
            case 'more-info':
                this._fireMoreInfo(config.entity || entityId);
                break;
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
            case 'none':
            default:
                break;
        }
    }

    _setupNodeActions(el, node, entityId) {
        let holdTimer = null;
        let held = false;
        let lastTap = 0;
        let tapTimeout = null;

        el.style.cursor = 'pointer';

        el.addEventListener('pointerdown', () => {
            held = false;
            holdTimer = setTimeout(() => {
                held = true;
                const action = this._getActionConfig(node, 'hold_action');
                if (action.action !== 'none') {
                    this._handleAction(action, entityId);
                }
            }, 500);
        });

        el.addEventListener('pointerup', () => clearTimeout(holdTimer));
        el.addEventListener('pointercancel', () => { clearTimeout(holdTimer); held = false; });

        el.addEventListener('click', () => {
            if (held) { held = false; return; }

            const doubleTapAction = this._getActionConfig(node, 'double_tap_action');
            if (!doubleTapAction || doubleTapAction.action === 'none') {
                this._handleAction(this._getActionConfig(node, 'tap_action'), entityId);
                return;
            }

            const now = Date.now();
            if (now - lastTap < 300) {
                clearTimeout(tapTimeout);
                lastTap = 0;
                this._handleAction(doubleTapAction, entityId);
            } else {
                lastTap = now;
                tapTimeout = setTimeout(() => {
                    lastTap = 0;
                    this._handleAction(this._getActionConfig(node, 'tap_action'), entityId);
                }, 300);
            }
        });
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

    _animateValue(id, newVal, duration = 800, formatFn = null) {
        const el = this.shadowRoot.getElementById(id);
        if (!el) return;

        if (this._animFrames[id]) {
            cancelAnimationFrame(this._animFrames[id]);
        }

        const fmt = formatFn || ((v) => this._formatPower(v));
        const oldVal = this._currentValues[id] || 0;
        this._currentValues[id] = newVal;

        if (Math.abs(oldVal - newVal) < 0.5) {
            el.textContent = fmt(newVal);
            return;
        }

        const startTime = performance.now();
        const animate = (now) => {
            const progress = Math.min(1, (now - startTime) / duration);
            const eased = progress < 0.5
                ? 2 * progress * progress
                : 1 - Math.pow(-2 * progress + 2, 2) / 2;
            const current = oldVal + (newVal - oldVal) * eased;
            el.textContent = fmt(current);
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

    _autarkyColor(pct) {
        pct = Math.max(0, Math.min(100, pct));
        if (pct <= 50) {
            const t = pct / 50;
            return `rgb(220,${Math.round(50 + 150 * t)},50)`;
        }
        const t = (pct - 50) / 50;
        return `rgb(${Math.round(220 - 170 * t)},200,50)`;
    }

    _hexToRgba(hex, alpha) {
        const m = hex.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
        if (!m) return `rgba(128,128,128,${alpha})`;
        return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${alpha})`;
    }

    _updateFlows() {
        let solar = this._getState('solar_power');
        if (this._entities?.solar?.reverse) solar = -solar;

        // Battery: support two-sensor mode (charge + discharge) or single entity with reverse
        let battery;
        if (this._mode === 'entities' && (this._entities?.battery?.charge || this._entities?.battery?.discharge)) {
            const charge = this._getState('battery_charge_power');
            const discharge = this._getState('battery_discharge_power');
            battery = charge - discharge;
        } else {
            let rawBattery = this._getState('battery_power');
            battery = this._entities?.battery?.reverse ? -rawBattery : rawBattery;
        }

        // Grid: support single-entity mode (entity + optional reverse)
        let gridImport, gridExport;
        if (this._mode === 'entities' && this._entities?.grid?.entity) {
            const gridPower = this._getState('grid_power');
            const reverse = this._entities.grid.reverse;
            if (reverse) {
                gridImport = Math.max(0, -gridPower);
                gridExport = Math.max(0, gridPower);
            } else {
                gridImport = Math.max(0, gridPower);
                gridExport = Math.max(0, -gridPower);
            }
        } else {
            gridImport = this._getState('grid_import_power');
            gridExport = this._getState('grid_export_power');
        }

        let ev = this._getState('ev_power');
        if (this._entities?.ev?.invert) ev = -ev;
        const soc = this._getState('battery_soc');
        const autarky = this._getState('autarky_rate');

        const battCharge = Math.max(0, battery);
        const battDischarge = Math.max(0, -battery);

        // Home: use entity if configured, otherwise auto-calculate
        const homeEntity = this._getEntityId('home_consumption_power');
        let home;
        if (homeEntity && this._hass?.states[homeEntity]) {
            home = this._getState('home_consumption_power');
            if (this._entities?.home?.invert) home = -home;
        } else {
            home = Math.max(0, solar + gridImport + battDischarge - gridExport - battCharge - ev);
        }

        // Daily energy strings
        const dailySolar = this._getStateStr('daily_solar_energy');
        const dailyEv = this._getStateStr('daily_ev_energy');
        const dailyGridImport = this._getStateStr('daily_grid_import_energy');
        const dailyGridExport = this._getStateStr('daily_grid_export_energy');
        const dailyBattery = this._getStateStr('daily_battery_energy');
        const dailyHome = this._getStateStr('daily_home_energy');

        const vals = { solar, battery, gridImport, gridExport, home, ev, soc, autarky,
                       dailySolar, dailyEv, dailyGridImport, dailyGridExport, dailyBattery, dailyHome };
        const key = JSON.stringify(vals);
        if (this._lastKey === key) return;
        this._lastKey = key;

        // Animated power values
        this._animateValue('val-solar', solar);

        // Battery with direction arrow
        const battPrefix = battery > 10 ? '\u25BC ' : (battery < -10 ? '\u25B2 ' : '');
        this._animateValue('val-battery-power', Math.abs(battery), 800,
            (w) => battPrefix + this._formatPower(w));

        // Grid with direction arrow
        const isImport = gridImport > gridExport;
        const gridPrefix = isImport ? '\u2193 ' : (gridExport > 10 ? '\u2191 ' : '');
        this._animateValue('val-grid', isImport ? gridImport : gridExport, 800,
            (w) => gridPrefix + this._formatPower(w));

        this._animateValue('val-home', home);
        this._animateValue('val-ev', ev);

        // Animated SOC percentage
        this._animateValue('val-battery-soc', soc, 800, (v) => `${v.toFixed(0)}%`);

        // Animated autarky
        const autarkyEntity = this._getEntityId('autarky_rate');
        if (autarkyEntity) {
            this._animateValue('val-autarky', autarky, 800, (v) => `\u26A1 ${v.toFixed(0)}% self`);
        }

        // Inverter status
        this._setText('val-inverter-status', this._getStateStr('charging_state'));

        // Daily energy texts
        this._setText('val-today-solar', dailySolar ? `Today ${dailySolar} kWh` : '');
        this._setText('val-today-ev', dailyEv ? `Today ${dailyEv} kWh` : '');
        this._setText('val-today-battery', dailyBattery ? `Today ${dailyBattery} kWh` : '');
        this._setText('val-today-home', dailyHome ? `Today ${dailyHome} kWh` : '');

        // Grid daily: show import, export, and net on one line
        const gridDailyParts = [];
        if (dailyGridImport) gridDailyParts.push(`\u2193${dailyGridImport}`);
        if (dailyGridExport) gridDailyParts.push(`\u2191${dailyGridExport}`);
        if (dailyGridImport && dailyGridExport) {
            const net = (parseFloat(dailyGridImport) - parseFloat(dailyGridExport)).toFixed(1);
            gridDailyParts.push(`Net ${net > 0 ? '+' : ''}${net}`);
        }
        this._setText('val-today-grid', gridDailyParts.length ? gridDailyParts.join(' ') + ' kWh' : '');

        // Battery SOC arc
        const L = this._getLayout();
        const socArc = this.shadowRoot.getElementById('soc-arc');
        if (socArc) {
            const circumference = 2 * Math.PI * L.socR;
            socArc.style.strokeDashoffset = (circumference * (1 - soc / 100)).toFixed(1);
            if (battCharge > 10) {
                socArc.style.animation = 'socPulse 2s ease-in-out infinite';
            } else if (battDischarge > 10) {
                socArc.style.animation = 'socDrain 2.5s ease-in-out infinite';
            } else {
                socArc.style.animation = 'none';
            }
        }

        // Autarky arc
        const autarkyArc = this.shadowRoot.getElementById('autarky-arc');
        if (autarkyArc) {
            if (autarkyEntity && autarky > 0) {
                const circumference = 2 * Math.PI * L.autarkyR;
                autarkyArc.style.strokeDashoffset = (circumference * (1 - autarky / 100)).toFixed(1);
                autarkyArc.style.stroke = this._autarkyColor(autarky);
                autarkyArc.style.opacity = '0.75';
            } else {
                autarkyArc.style.opacity = '0';
            }
        }

        // Grid dynamic color based on direction
        const gridColor = isImport
            ? this._getNodeColor('grid_import')
            : (gridExport > 10 ? this._getNodeColor('grid_export') : this._getNodeColor('grid_import'));
        this._updateGridColor(gridColor, isImport);

        // Grid label
        const gridLabel = this.shadowRoot.getElementById('label-grid');
        if (gridLabel) {
            gridLabel.textContent = isImport ? 'IMPORT' : (gridExport > 10 ? 'EXPORT' : 'GRID');
        }

        // Battery label + dynamic color (pink=#f06292 charge, teal=#4db6ac discharge)
        const battLabel = this.shadowRoot.getElementById('label-battery-state');
        if (battLabel) {
            battLabel.textContent = battCharge > 10 ? 'CHARGING' : (battDischarge > 10 ? 'DISCHARGE' : '');
        }

        // Dynamic battery color based on direction
        const battColor = battCharge > 10 ? '#f06292' : (battDischarge > 10 ? '#4db6ac' : this._getNodeColor('battery'));
        const battEls = ['val-battery-soc', 'val-battery-power', 'label-battery-state', 'val-today-battery'];
        for (const id of battEls) {
            const el = this.shadowRoot.getElementById(id);
            if (el) el.setAttribute('fill', battColor);
        }
        const socArcEl = this.shadowRoot.getElementById('soc-arc');
        if (socArcEl && (battCharge > 10 || battDischarge > 10)) {
            socArcEl.style.stroke = battColor;
        }

        // Flow animations
        this._updateFlow('flow-solar', solar > 10, false, this._calcDuration(solar));
        const battActive = Math.abs(battery) > 10;
        const battReverse = battery < 0;
        this._updateFlow('flow-battery', battActive, battReverse, this._calcDuration(battery));
        const gridActive = gridImport > 10 || gridExport > 10;
        const gridReverse = gridImport > gridExport;
        this._updateFlow('flow-grid', gridActive, gridReverse, this._calcDuration(gridImport || gridExport), gridColor);
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

    _updateGridColor(color, isImport) {
        const nodeGrid = this.shadowRoot.getElementById('node-grid');
        if (nodeGrid) nodeGrid.setAttribute('filter', `url(#glowGrid${isImport ? 'Import' : 'Export'})`);

        const gridCircle = this.shadowRoot.getElementById('grid-circle');
        if (gridCircle) {
            gridCircle.setAttribute('stroke', color);
            gridCircle.setAttribute('fill', this._hexToRgba(color, 0.07));
        }

        const glowRing = this.shadowRoot.querySelector('#node-grid .glow-ring');
        if (glowRing) glowRing.setAttribute('stroke', color);

        const gridIcon = this.shadowRoot.getElementById('grid-icon');
        if (gridIcon) gridIcon.setAttribute('stroke', color);

        for (const id of ['val-grid', 'label-grid', 'val-today-grid']) {
            const el = this.shadowRoot.getElementById(id);
            if (el) el.setAttribute('fill', color);
        }

        const gridTrack = this.shadowRoot.getElementById('track-grid');
        if (gridTrack) gridTrack.setAttribute('stroke', color);
    }

    _updateFlow(groupId, active, reverse, duration, dynamicColor) {
        const group = this.shadowRoot.getElementById(groupId);
        if (!group) return;

        group.style.opacity = active ? '1' : '0';
        if (!active) {
            group.dataset.sig = '';
            return;
        }

        const color = dynamicColor || group.dataset.color;
        if (dynamicColor) group.dataset.color = dynamicColor;

        const pathId = group.dataset.pathId;
        const pathD = group.dataset.pathD;
        const count = parseInt(group.dataset.count, 10) || 2;
        const newSig = `${reverse ? 'r' : 'f'}:${duration.toFixed(1)}:${color}`;
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

    _getDeviceList() {
        let devices = [];
        if (this._mode === 'entities' && this._entities?.individual) {
            devices = this._entities.individual.map((dev, idx) => [
                dev.entity || `device_${idx}`,
                {
                    name: dev.name || dev.entity?.split('.').pop() || `Device ${idx + 1}`,
                    power_entity: dev.entity,
                    device_type: dev.device_type || 'appliance',
                    is_on: false,
                    current_power: 0,
                    color: dev.color,
                    icon_override: dev.icon,
                    daily_energy_entity: dev.daily_energy,
                }
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

    _updateDeviceLabels() {
        const container = this.shadowRoot.getElementById('device-labels');
        if (!container) return;

        const devices = this._getDeviceList();

        const configSig = devices.map(([id, info], idx) =>
            `${info.power_entity}:${info.name}:${info.color || SFC_DEVICE_COLORS[idx % SFC_DEVICE_COLORS.length]}:${info.icon_override || ''}:${info.daily_energy_entity || ''}`
        ).join('|');

        if (this._deviceConfigSig !== configSig) {
            this._deviceConfigSig = configSig;
            this._buildDeviceDOM(container, devices);
        }

        this._updateDeviceValues(devices);
    }

    _buildDeviceDOM(container, devices) {
        if (devices.length === 0) {
            container.innerHTML = '';
            this._devicePositions = [];
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
        const fs = 11;
        let html = '';
        this._devicePositions = [];

        devices.forEach(([id, info], idx) => {
            let name = (info.name || id);
            if (name.length > maxChars) name = name.substring(0, maxChars - 1) + '\u2026';
            const color = info.color || SFC_DEVICE_COLORS[idx % SFC_DEVICE_COLORS.length];
            const icon = this._deviceIcon(info.device_type, info.name || id);

            const col = idx % cols;
            const row = Math.floor(idx / cols);
            const cx = margin + (col * colWidth) + (colWidth / 2);
            const cy = baseY + (row * (compact ? 100 : 90));

            this._devicePositions.push({ cx, cy, nodeR, color });

            // Static connection line
            html += `<path id="dev-conn-${idx}" d="M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${cx},${cy - 40} ${cx},${cy - nodeR}"
                           fill="none" stroke="${color}" stroke-width="1.2" stroke-dasharray="3,5" opacity="0.1"/>`;

            // Flow animation container
            html += `<g id="dev-flow-${idx}"></g>`;

            // Hidden reference path for animateMotion
            html += `<path id="dev-path-${idx}" d="M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${cx},${cy - 40} ${cx},${cy - nodeR}" fill="none" stroke="none"/>`;

            // Clickable device group
            const entityAttr = info.power_entity ? ` data-entity="${info.power_entity}"` : '';
            html += `<g id="dev-group-${idx}" class="device-clickable"${entityAttr} data-idx="${idx}">`;

            // Device circle node
            html += `<circle id="dev-circle-${idx}" cx="${cx}" cy="${cy}" r="${nodeR}" fill="rgba(128,128,128,0.03)" stroke="${color}" stroke-width="1.2" opacity="0.4"/>`;

            // Device icon
            html += `<g transform="translate(${cx},${cy})" stroke="${color}" fill="none" opacity="0.35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">`;
            html += icon;
            html += `</g>`;

            // Name
            html += `<text x="${cx}" y="${cy + nodeR + 14}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="500" fill="${color}" opacity="0.8">${name}</text>`;

            // Power value (animated via ID)
            html += `<text id="dev-val-${idx}" x="${cx}" y="${cy + nodeR + 14 + fs + 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="600" fill="${color}" opacity="0.5">0 W</text>`;

            // Daily energy (updated via ID)
            html += `<text id="dev-daily-${idx}" x="${cx}" y="${cy + nodeR + 14 + (fs + 2) * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${color}" opacity="0.45"></text>`;

            html += `</g>`;
        });

        container.innerHTML = html;

        // Wire up click handlers with tap action support
        container.querySelectorAll('.device-clickable[data-entity]').forEach(el => {
            const idx = parseInt(el.dataset.idx);
            this._setupNodeActions(el, `device_${idx}`, el.dataset.entity);
        });

        // Reset animation state for device values
        devices.forEach((_, idx) => {
            delete this._currentValues[`dev-val-${idx}`];
        });
    }

    _updateDeviceValues(devices) {
        const L = this._getLayout();
        const H = L.home;

        devices.forEach(([id, info], idx) => {
            const powerEntity = info.power_entity ? this._hass.states[info.power_entity] : null;
            const power = powerEntity ? parseFloat(powerEntity.state) || 0 : (info.current_power || 0);
            const isOn = power > 5;
            const color = info.color || SFC_DEVICE_COLORS[idx % SFC_DEVICE_COLORS.length];
            const pos = this._devicePositions[idx];
            if (!pos) return;

            // Animate power value
            this._animateValue(`dev-val-${idx}`, power);

            // Daily energy text
            if (info.daily_energy_entity) {
                const de = this._hass.states[info.daily_energy_entity];
                this._setText(`dev-daily-${idx}`, de ? `Today ${de.state} kWh` : '');
            }

            // Update connection line opacity
            const conn = this.shadowRoot.getElementById(`dev-conn-${idx}`);
            if (conn) conn.setAttribute('opacity', isOn ? '0.3' : '0.1');

            // Update node visual state
            const circle = this.shadowRoot.getElementById(`dev-circle-${idx}`);
            if (circle) {
                circle.setAttribute('fill', `rgba(128,128,128,${isOn ? 0.08 : 0.03})`);
                circle.setAttribute('opacity', isOn ? '1' : '0.4');
            }

            // Update power text opacity
            const valEl = this.shadowRoot.getElementById(`dev-val-${idx}`);
            if (valEl) valEl.setAttribute('opacity', isOn ? '1' : '0.5');

            // Update icon opacity
            const group = this.shadowRoot.getElementById(`dev-group-${idx}`);
            if (group) {
                const iconG = group.querySelector('g[transform]');
                if (iconG) iconG.setAttribute('opacity', isOn ? '0.7' : '0.35');
            }

            // Update flow animation
            const flowGroup = this.shadowRoot.getElementById(`dev-flow-${idx}`);
            if (flowGroup) {
                if (power > 5) {
                    const dur = this._calcDuration(power).toFixed(1);
                    const newSig = dur;
                    if (flowGroup.dataset.sig !== newSig) {
                        flowGroup.dataset.sig = newSig;
                        const pathD = `M${H.cx},${H.cy + H.r} C${H.cx},${H.cy + H.r + 30} ${pos.cx},${pos.cy - 40} ${pos.cx},${pos.cy - pos.nodeR}`;
                        flowGroup.innerHTML = `
                            <path d="${pathD}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">
                                <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${dur}s" repeatCount="indefinite"/>
                            </path>
                            <circle r="2" fill="${color}" opacity="0.8">
                                <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced" begin="-${(idx * 0.3).toFixed(1)}s">
                                    <mpath href="#dev-path-${idx}"/>
                                </animateMotion>
                            </circle>`;
                    }
                } else {
                    if (flowGroup.dataset.sig !== '') {
                        flowGroup.dataset.sig = '';
                        flowGroup.innerHTML = '';
                    }
                }
            }
        });
    }

    _deviceIcon(type, name) {
        const n = (name || '').toLowerCase();
        const t = (type || '').toLowerCase();

        if (t === 'ev_charger' || n.includes('keba') || n.includes('charger') || n.includes('wallbox')) {
            return `<rect x="-6" y="-10" width="12" height="16" rx="2"/>
                    <path d="M-2,-4 L0,2 L2,-4"/>
                    <line x1="0" y1="6" x2="0" y2="10"/>`;
        }
        if (n.includes('heiz') || n.includes('heat') || n.includes('warm') || n.includes('boiler')) {
            return `<path d="M-4,-10 C-4,-4 4,-4 4,-10"/>
                    <path d="M-4,-3 C-4,3 4,3 4,-3"/>
                    <path d="M-4,4 C-4,10 4,10 4,4"/>`;
        }
        if (n.includes('wash') || n.includes('sp\u00FCl') || n.includes('geschirr') || n.includes('wasch')) {
            return `<circle r="10" fill="none"/>
                    <circle r="5" fill="none"/>
                    <circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>`;
        }
        if (n.includes('dryer') || n.includes('trockn')) {
            return `<circle r="10" fill="none"/>
                    <path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>`;
        }
        if (n.includes('pool') || n.includes('pump')) {
            return `<circle r="8" fill="none"/>
                    <path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/>
                    <path d="M-4,-4 L4,4 M4,-4 L-4,4"/>`;
        }
        if (n.includes('klima') || n.includes('ac') || n.includes('cool') || n.includes('air')) {
            return `<rect x="-10" y="-6" width="20" height="12" rx="2"/>
                    <path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/>
                    <path d="M2,6 C2,10 6,10 6,6" fill="none"/>`;
        }
        if (n.includes('light') || n.includes('licht') || n.includes('lamp')) {
            return `<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/>
                    <line x1="-2" y1="8" x2="2" y2="8"/>`;
        }
        if (n.includes('shelly') || n.includes('plug') || n.includes('switch') || n.includes('steckdose')) {
            return `<rect x="-8" y="-10" width="16" height="20" rx="3"/>
                    <circle cx="-3" cy="-2" r="2" fill="none"/>
                    <circle cx="3" cy="-2" r="2" fill="none"/>
                    <line x1="0" y1="4" x2="0" y2="7"/>`;
        }
        return `<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>`;
    }

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
                socR: 33,
                autarkyR: 48,
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
            socR: 40,
            autarkyR: 50,
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

    _render() {
        this._lastKey = '';
        this._deviceConfigSig = '';
        const F = "'Segoe UI','Roboto',sans-serif";
        const L = this._getLayout();
        const S = L.solar, I = L.inverter, B = L.battery, G = L.grid, H = L.home, E = L.ev;
        const socCirc = (2 * Math.PI * L.socR).toFixed(1);
        const autarkyCirc = (2 * Math.PI * L.autarkyR).toFixed(1);
        const fl = L.font.label, fv = L.font.value, fs = L.font.sub, fhv = L.font.homeVal;

        const gridImportColor = this._getNodeColor('grid_import');
        const gridExportColor = this._getNodeColor('grid_export');
        const solarColor = this._getNodeColor('solar');
        const batteryColor = this._getNodeColor('battery');
        const homeColor = this._getNodeColor('home');
        const evColor = this._getNodeColor('ev');
        const inverterColor = SFC_DEFAULTS.inverter.color;

        // Node visibility
        const hasSolar = this._hasNode('solar');
        const hasBattery = this._hasNode('battery');
        const hasGrid = this._hasNode('grid');
        const hasEv = this._hasNode('ev');
        const hasInverter = this._showInverter && this._hasNode('inverter');

        this.shadowRoot.innerHTML = `
            <style>
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
            </style>
            <ha-card>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${L.vb}" style="background:transparent">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="45%" r="60%">
                            <stop offset="0%" style="stop-color: var(--primary-text-color, #c8dcf0); stop-opacity: 0.04"/>
                            <stop offset="100%" style="stop-color: transparent; stop-opacity: 0"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                            <circle cx="25" cy="25" r="0.7" fill="var(--secondary-text-color, #808080)" opacity="0.12"/>
                        </pattern>
                        <filter id="textGlow" x="-20%" y="-20%" width="140%" height="140%">
                            <feGaussianBlur stdDeviation="2" result="blur"/>
                            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                        </filter>
                        ${this._glowFilter('glowSolar',      solarColor, 8)}
                        ${this._glowFilter('glowBattery',    batteryColor, 8)}
                        ${this._glowFilter('glowGridImport', gridImportColor, 8)}
                        ${this._glowFilter('glowGridExport', gridExportColor, 8)}
                        ${this._glowFilter('glowHome',       homeColor, 10)}
                        ${this._glowFilter('glowEV',         evColor, 8)}
                        ${this._glowFilter('glowInverter',   inverterColor, 6)}

                        <path id="path-solar"   d="${L.paths.solar}"/>
                        <path id="path-home"    d="${L.paths.home}"/>
                        <path id="path-battery" d="${L.paths.battery}"/>
                        <path id="path-grid"    d="${L.paths.grid}"/>
                        <path id="path-ev"      d="${L.paths.ev}"/>
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%" fill="url(#dotGrid)"/>

                    <!-- Static flow tracks -->
                    ${hasSolar ? this._track(L.paths.solar, solarColor) : ''}
                    ${hasSolar || hasInverter ? this._track(L.paths.home, homeColor) : ''}
                    ${hasBattery ? this._track(L.paths.battery, batteryColor) : ''}
                    ${hasGrid ? `<path id="track-grid" d="${L.paths.grid}" fill="none" stroke="${gridImportColor}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>` : ''}
                    ${hasEv ? this._track(L.paths.ev, evColor) : ''}

                    <!-- Animated flow groups -->
                    ${hasSolar ? `<g id="flow-solar" class="flow-group" style="opacity:0"
                       data-path-id="path-solar" data-path-d="${L.paths.solar}" data-color="${solarColor}" data-count="2"></g>` : ''}
                    ${hasBattery ? `<g id="flow-battery" class="flow-group" style="opacity:0"
                       data-path-id="path-battery" data-path-d="${L.paths.battery}" data-color="${batteryColor}" data-count="3"></g>` : ''}
                    ${hasGrid ? `<g id="flow-grid" class="flow-group" style="opacity:0"
                       data-path-id="path-grid" data-path-d="${L.paths.grid}" data-color="${gridImportColor}" data-count="3"></g>` : ''}
                    ${hasSolar || hasInverter ? `<g id="flow-home" class="flow-group" style="opacity:0"
                       data-path-id="path-home" data-path-d="${L.paths.home}" data-color="${homeColor}" data-count="2"></g>` : ''}
                    ${hasEv ? `<g id="flow-ev" class="flow-group" style="opacity:0"
                       data-path-id="path-ev" data-path-d="${L.paths.ev}" data-color="${evColor}" data-count="3"></g>` : ''}

                    ${hasSolar ? `<!-- SOLAR -->
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
                    <text x="${S.cx}" y="${S.cy + S.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${solarColor}">${this._getNodeName('solar')}</text>
                    <text id="val-solar" x="${S.cx}" y="${S.cy + S.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${solarColor}">0 W</text>
                    <text id="val-today-solar" x="${S.cx}" y="${S.cy + S.r + 18 + fv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${solarColor}" opacity="0.55">\u00A0</text>` : ''}

                    ${hasInverter ? `<!-- INVERTER -->
                    <g id="node-inverter" filter="url(#glowInverter)">
                        <circle cx="${I.cx}" cy="${I.cy}" r="${I.r}" fill="${this._hexToRgba(inverterColor, 0.07)}" stroke="${inverterColor}" stroke-width="1"/>
                        <path d="M${I.cx - 10},${I.cy} Q${I.cx - 4},${I.cy - 8} ${I.cx},${I.cy} Q${I.cx + 4},${I.cy + 8} ${I.cx + 10},${I.cy}" fill="none" stroke="${inverterColor}" stroke-width="1.8" opacity="0.7"/>
                    </g>
                    <text id="val-inverter-status" x="${I.cx}" y="${I.cy + I.r + 14}" text-anchor="middle" font-family="${F}" font-size="${this._compact ? 11 : 10}" fill="var(--secondary-text-color, #5a7a9a)" opacity="0.7">\u00A0</text>` : ''}

                    ${hasBattery ? `<!-- BATTERY -->
                    <g id="node-battery" filter="url(#glowBattery)">
                        ${this._glowRing(B, batteryColor)}
                        <circle cx="${B.cx}" cy="${B.cy}" r="${B.r}" fill="${this._hexToRgba(batteryColor, 0.07)}" stroke="${batteryColor}" stroke-width="1.8"/>
                        <circle cx="${B.cx}" cy="${B.cy}" r="${L.socR}" fill="none" stroke="${this._hexToRgba(batteryColor, 0.1)}" stroke-width="5"/>
                        <circle id="soc-arc" cx="${B.cx}" cy="${B.cy}" r="${L.socR}" fill="none" stroke="${batteryColor}" stroke-width="5"
                                stroke-dasharray="${socCirc}" stroke-dashoffset="${socCirc}"
                                transform="rotate(-90 ${B.cx} ${B.cy})" stroke-linecap="round" opacity="0.75"/>
                        <g transform="translate(${B.cx},${B.cy})" stroke="${batteryColor}" fill="none" opacity="0.7">
                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>
                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="${batteryColor}" opacity="0.5" stroke="none"/>
                        </g>
                    </g>
                    <text x="${B.cx}" y="${B.cy + B.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${batteryColor}">${this._getNodeName('battery')}</text>
                    <text id="val-battery-soc" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${batteryColor}">0%</text>
                    <text id="val-battery-power" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="500" fill="${batteryColor}" opacity="0.7">0 W</text>
                    <text id="label-battery-state" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${batteryColor}" opacity="0.5"></text>
                    <text id="val-today-battery" x="${B.cx}" y="${B.cy + B.r + 18 + fv * 0.9 + fl * 2 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${batteryColor}" opacity="0.45">\u00A0</text>` : ''}

                    ${hasGrid ? `<!-- GRID -->
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
                    <text x="${G.cx}" y="${G.cy + G.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${gridImportColor}">${this._getNodeName('grid')}</text>
                    <text id="val-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${gridImportColor}">0 W</text>
                    <text id="label-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9 + fl}" text-anchor="middle" font-family="${F}" font-size="${fs}" font-weight="500" fill="${gridImportColor}" opacity="0.5">GRID</text>
                    <text id="val-today-grid" x="${G.cx}" y="${G.cy + G.r + 18 + fv * 0.9 + fl + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${gridImportColor}" opacity="0.45">\u00A0</text>` : ''}

                    <!-- HOME (central hub — always visible) -->
                    <g id="node-home" filter="url(#glowHome)">
                        ${this._glowRing(H, homeColor, 1.4)}
                        <circle cx="${H.cx}" cy="${H.cy}" r="${H.r}" fill="${this._hexToRgba(homeColor, 0.06)}" stroke="${homeColor}" stroke-width="2"/>
                        <!-- Autarky arc gauge -->
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
                    <text x="${H.cx}" y="${H.cy + H.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl + 1}" font-weight="600" fill="${homeColor}">${this._getNodeName('home')}</text>
                    <text id="val-home" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fhv}" font-weight="700" fill="${homeColor}">0 W</text>
                    <text id="val-autarky" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${homeColor}" opacity="0.5">\u00A0</text>
                    <text id="val-today-home" x="${H.cx}" y="${H.cy + H.r + 18 + fhv * 0.9 + (fs + 4) * 2}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${homeColor}" opacity="0.45">\u00A0</text>

                    ${hasEv ? `<!-- EV -->
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
                    <text x="${E.cx}" y="${E.cy + E.r + 18}" text-anchor="middle" font-family="${F}" font-size="${fl}" font-weight="600" fill="${evColor}">${this._getNodeName('ev')}</text>
                    <text id="val-ev" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9}" text-anchor="middle" font-family="${F}" font-size="${fv}" font-weight="700" fill="${evColor}">0 W</text>
                    <text id="val-today-ev" x="${E.cx}" y="${E.cy + E.r + 18 + fv * 0.9 + fs + 4}" text-anchor="middle" font-family="${F}" font-size="${fs}" fill="${evColor}" opacity="0.5">\u00A0</text>` : ''}

                    <!-- Device labels -->
                    <g id="device-labels"></g>

                    <!-- SEM watermark -->
                    <text x="${this._compact ? 470 : 960}" y="${this._compact ? 1050 : 770}" text-anchor="end" font-family="${F}" font-size="10" font-weight="300" letter-spacing="2" fill="var(--secondary-text-color, #808080)" opacity="0.15">SEM</text>
                </svg>
            </ha-card>
        `;
        this._setupClickHandlers();
    }

    _setupClickHandlers() {
        const nodes = [
            // Every element opens the entity it displays
            // Solar
            { ids: ['node-solar', 'val-solar'], node: 'solar', key: 'solar_power' },
            { ids: ['val-today-solar'], node: 'solar', key: 'daily_solar_energy' },
            // Battery
            { ids: ['node-battery', 'val-battery-soc'], node: 'battery', key: 'battery_soc' },
            { ids: ['val-battery-power', 'label-battery-state'], node: 'battery', key: 'battery_power' },
            { ids: ['val-today-battery'], node: 'battery', key: 'daily_battery_energy' },
            // Grid
            { ids: ['node-grid', 'val-grid', 'label-grid'], node: 'grid', key: 'grid_import_power' },
            { ids: ['val-today-grid'], node: 'grid', key: 'daily_grid_import_energy' },
            // Home
            { ids: ['node-home', 'val-home'], node: 'home', key: 'home_consumption_power' },
            { ids: ['val-autarky'], node: 'home', key: 'autarky_rate' },
            { ids: ['val-today-home'], node: 'home', key: 'daily_home_energy' },
            // EV
            { ids: ['node-ev', 'val-ev'], node: 'ev', key: 'ev_power' },
            { ids: ['val-today-ev'], node: 'ev', key: 'daily_ev_energy' },
            // Inverter
            { ids: ['val-inverter-status'], node: 'home', key: 'charging_state' },
        ];

        for (const { ids, node, key } of nodes) {
            const entityId = this._getEntityId(key);
            if (!entityId) continue;
            for (const id of ids) {
                const el = this.shadowRoot.getElementById(id);
                if (el) {
                    el.classList.add('clickable-node');
                    this._setupNodeActions(el, node, entityId);
                }
            }
        }
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

    static async getConfigElement() {
        return document.createElement('sem-flow-card-editor');
    }

    static getStubConfig(hass) {
        const states = hass ? Object.keys(hass.states) : [];

        const findEntity = (patterns) => {
            for (const pattern of patterns) {
                const match = states.find(id => id.includes(pattern));
                if (match) return match;
            }
            return null;
        };

        return {
            entities: {
                solar: {
                    entity: findEntity(['solar_power', 'pv_power', 'solar_production', 'pv_production']) || 'sensor.solar_power',
                },
                grid: {
                    consumption: findEntity(['grid_import', 'grid_consumption', 'grid_power_import']) || 'sensor.grid_import_power',
                    production: findEntity(['grid_export', 'grid_feed', 'grid_return', 'grid_power_export']) || 'sensor.grid_export_power',
                },
                battery: {
                    entity: findEntity(['battery_power', 'batt_power', 'battery_charging_power']) || 'sensor.battery_power',
                    state_of_charge: findEntity(['battery_soc', 'battery_level', 'batt_soc', 'battery_state_of_charge']) || 'sensor.battery_soc',
                },
                home: {
                    entity: findEntity(['home_consumption', 'house_power', 'home_power', 'total_consumption']) || 'sensor.home_consumption_power',
                },
            },
        };
    }
}

/* ================================================================
 * SEM Flow Card Editor — Configuration UI
 * Uses HA native ha-form with entity selectors, icon pickers,
 * and color pickers. Panel-based navigation like power-flow-card-plus.
 * ================================================================ */

class SEMFlowCardEditor extends HTMLElement {
    _config = {};
    _hass = null;
    _page = 'main';
    _editDeviceIdx = -1;
    _rendered = false;
    _internalChange = false;

    set hass(hass) {
        this._hass = hass;
        if (!this._rendered) {
            this._render();
        } else {
            const form = this.querySelector('ha-form');
            if (form) form.hass = hass;
        }
    }

    setConfig(config) {
        this._config = JSON.parse(JSON.stringify(config || {}));
        if (!this._config.entities) this._config.entities = {};
        if (this._internalChange) {
            this._internalChange = false;
            return;
        }
        if (this._hass) {
            this._rendered = false;
            this._render();
        }
    }

    _fire() {
        this._internalChange = true;
        this.dispatchEvent(new CustomEvent('config-changed', {
            detail: { config: this._config }, bubbles: true, composed: true,
        }));
    }

    _hexToRgb(hex) {
        if (!hex) return undefined;
        const m = hex.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
        return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : undefined;
    }

    _rgbToHex(rgb) {
        if (!rgb || !Array.isArray(rgb)) return undefined;
        return '#' + rgb.map(c => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, '0')).join('');
    }

    static SCHEMAS = {
        solar: [
            { name: 'entity', label: 'Power Sensor (W)', selector: { entity: { domain: 'sensor' } } },
            { name: 'reverse', label: 'Reverse (sensor reports negative)', selector: { boolean: {} } },
            { name: 'name', label: 'Name', selector: { text: {} } },
            { name: 'daily_energy', label: 'Daily Energy Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'color', label: 'Color', selector: { color_rgb: {} } },
            ...SFC_ACTION_SCHEMAS,
        ],
        grid: [
            { name: 'entity', label: 'Grid Power Sensor (single entity)', selector: { entity: { domain: 'sensor' } } },
            { name: 'reverse', label: 'Reverse (positive = export)', selector: { boolean: {} } },
            { name: 'consumption', label: 'Import Power Sensor (or leave empty if using single entity above)', selector: { entity: { domain: 'sensor' } } },
            { name: 'production', label: 'Export Power Sensor (or leave empty if using single entity above)', selector: { entity: { domain: 'sensor' } } },
            { name: 'daily_import_energy', label: 'Daily Import Energy', selector: { entity: { domain: 'sensor' } } },
            { name: 'daily_export_energy', label: 'Daily Export Energy', selector: { entity: { domain: 'sensor' } } },
            { name: 'name', label: 'Name', selector: { text: {} } },
            { name: 'color_import', label: 'Import Color', selector: { color_rgb: {} } },
            { name: 'color_export', label: 'Export Color', selector: { color_rgb: {} } },
            ...SFC_ACTION_SCHEMAS,
        ],
        battery: [
            { name: 'entity', label: 'Power Sensor (single entity, W)', selector: { entity: { domain: 'sensor' } } },
            { name: 'reverse', label: 'Reverse (positive = discharge)', selector: { boolean: {} } },
            { name: 'charge', label: 'Charge Power Sensor (or leave empty if using single entity above)', selector: { entity: { domain: 'sensor' } } },
            { name: 'discharge', label: 'Discharge Power Sensor (or leave empty if using single entity above)', selector: { entity: { domain: 'sensor' } } },
            { name: 'state_of_charge', label: 'State of Charge Sensor (%)', selector: { entity: { domain: 'sensor' } } },
            { name: 'daily_energy', label: 'Daily Energy Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'name', label: 'Name', selector: { text: {} } },
            { name: 'color', label: 'Color', selector: { color_rgb: {} } },
            ...SFC_ACTION_SCHEMAS,
        ],
        home: [
            { name: 'entity', label: 'Consumption Sensor (W) — leave empty to auto-calculate', selector: { entity: { domain: 'sensor' } } },
            { name: 'invert', label: 'Invert Value (sensor reports negative)', selector: { boolean: {} } },
            { name: 'autarky', label: 'Autarky Rate Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'daily_energy', label: 'Daily Consumption Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'name', label: 'Name', selector: { text: {} } },
            { name: 'color', label: 'Color', selector: { color_rgb: {} } },
            ...SFC_ACTION_SCHEMAS,
        ],
        ev: [
            { name: 'entity', label: 'Power Sensor (W)', selector: { entity: { domain: 'sensor' } } },
            { name: 'invert', label: 'Invert Value (sensor reports negative)', selector: { boolean: {} } },
            { name: 'name', label: 'Name', selector: { text: {} } },
            { name: 'daily_energy', label: 'Daily Energy Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'color', label: 'Color', selector: { color_rgb: {} } },
            ...SFC_ACTION_SCHEMAS,
        ],
        display: [
            { name: 'show_labels', label: 'Show Labels', selector: { boolean: {} } },
            { name: 'show_values', label: 'Show Values', selector: { boolean: {} } },
            { name: 'show_glow', label: 'Show Glow Effects', selector: { boolean: {} } },
            { name: 'show_inverter', label: 'Show Inverter Node', selector: { boolean: {} } },
        ],
        device: [
            { name: 'entity', label: 'Power Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'name', label: 'Name', selector: { text: {} } },
            { name: 'icon', label: 'Icon', selector: { icon: {} } },
            { name: 'daily_energy', label: 'Daily Energy Sensor', selector: { entity: { domain: 'sensor' } } },
            { name: 'color', label: 'Color', selector: { color_rgb: {} } },
            ...SFC_ACTION_SCHEMAS,
        ],
    };

    static COLOR_FIELDS = {
        solar: ['color'],
        grid: ['color_import', 'color_export'],
        battery: ['color'],
        home: ['color'],
        ev: ['color'],
    };

    static COLOR_DEFAULTS = {
        solar: { color: '#ff9800' },
        grid: { color_import: '#488fc2', color_export: '#8353d1' },
        battery: { color: '#4db6ac' },
        home: { color: '#5BC8D8' },
        ev: { color: '#8DC892' },
    };

    static SECTION_TITLES = { solar: 'Solar', grid: 'Grid', battery: 'Battery', home: 'Home', ev: 'EV Charger' };
    static SECTION_ICONS = { solar: 'mdi:solar-power', grid: 'mdi:transmission-tower', battery: 'mdi:battery-medium', home: 'mdi:home', ev: 'mdi:car-electric' };

    _getSectionData(section) {
        const data = { ...(this._config.entities?.[section] || {}) };
        const colorFields = SEMFlowCardEditor.COLOR_FIELDS[section];
        if (colorFields) {
            const defaults = SEMFlowCardEditor.COLOR_DEFAULTS[section] || {};
            for (const field of colorFields) {
                const hex = data[field] || defaults[field];
                if (hex) data[field] = this._hexToRgb(hex);
                else delete data[field];
            }
        }
        // Ensure boolean fields have explicit values for ha-form
        if (data.reverse === undefined) data.reverse = false;
        // Convert action objects to strings for form display
        for (const field of ['tap_action', 'hold_action', 'double_tap_action']) {
            if (data[field] && typeof data[field] === 'object') {
                data[field] = data[field].action || (field === 'tap_action' ? 'more-info' : 'none');
            }
        }
        return data;
    }

    _getDisplayData() {
        return {
            show_labels: this._config.show_labels !== false,
            show_values: this._config.show_values !== false,
            show_glow: this._config.show_glow !== false,
            show_inverter: this._config.show_inverter !== false,
        };
    }

    _getDeviceData(idx) {
        const dev = { ...(this._config.entities?.individual?.[idx] || {}) };
        if (dev.color) dev.color = this._hexToRgb(dev.color);
        for (const field of ['tap_action', 'hold_action', 'double_tap_action']) {
            if (dev[field] && typeof dev[field] === 'object') {
                dev[field] = dev[field].action || (field === 'tap_action' ? 'more-info' : 'none');
            }
        }
        return dev;
    }

    _cleanData(data, colorFields) {
        const result = { ...data };
        if (colorFields) {
            for (const field of colorFields) {
                if (Array.isArray(result[field])) result[field] = this._rgbToHex(result[field]);
            }
        }
        // Convert action strings to objects
        for (const field of ['tap_action', 'hold_action', 'double_tap_action']) {
            if (typeof result[field] === 'string') {
                const isDefault = (field === 'tap_action' && result[field] === 'more-info') ||
                                 (field !== 'tap_action' && (result[field] === 'none' || result[field] === ''));
                if (isDefault) {
                    delete result[field];
                } else {
                    result[field] = { action: result[field] };
                }
            }
        }
        for (const k of Object.keys(result)) {
            if (result[k] === '' || result[k] === undefined || result[k] === null) delete result[k];
        }
        // Don't store default-false booleans
        if (result.reverse === false) delete result.reverse;
        return result;
    }

    _updateSectionConfig(section, newData) {
        if (!this._config.entities) this._config.entities = {};
        this._config.entities[section] = this._cleanData(newData, SEMFlowCardEditor.COLOR_FIELDS[section]);
        this._fire();
    }

    _updateDisplayConfig(newData) {
        this._config.show_labels = newData.show_labels;
        this._config.show_values = newData.show_values;
        this._config.show_glow = newData.show_glow;
        this._config.show_inverter = newData.show_inverter;
        this._fire();
    }

    _updateDeviceConfig(idx, newData) {
        if (!this._config.entities) this._config.entities = {};
        if (!this._config.entities.individual) this._config.entities.individual = [];
        this._config.entities.individual[idx] = this._cleanData(newData, ['color']);
        this._fire();
    }

    _navigate(page, deviceIdx) {
        this._page = page;
        if (deviceIdx !== undefined) this._editDeviceIdx = deviceIdx;
        this._rendered = false;
        this._render();
    }

    _createHeader(title, backPage, backDeviceIdx) {
        const header = document.createElement('div');
        header.className = 'sfc-subpage-header';
        const icon = document.createElement('ha-icon');
        icon.setAttribute('icon', 'mdi:arrow-left');
        header.appendChild(icon);
        const span = document.createElement('span');
        span.textContent = title;
        header.appendChild(span);
        header.addEventListener('click', () => this._navigate(backPage, backDeviceIdx));
        return header;
    }

    _createForm(schema, data, onChange) {
        const wrap = document.createElement('div');
        wrap.className = 'sfc-form-container';
        const form = document.createElement('ha-form');
        form.hass = this._hass;
        form.data = data;
        form.schema = schema;
        form.computeLabel = (s) => s.label || s.name;
        form.addEventListener('value-changed', (ev) => {
            ev.stopPropagation();
            onChange(ev.detail.value);
        });
        wrap.appendChild(form);
        return wrap;
    }

    _render() {
        if (!this._hass) return;
        this.innerHTML = '';
        this._rendered = true;

        const style = document.createElement('style');
        style.textContent = `
            .sfc-editor { font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
            .sfc-nav-item {
                display: flex; align-items: center; padding: 14px 16px;
                cursor: pointer; border-bottom: 1px solid var(--divider-color, #e0e0e0);
                transition: background-color 0.15s;
            }
            .sfc-nav-item:hover { background: var(--secondary-background-color, #f5f5f5); }
            .sfc-nav-item > ha-icon:first-child {
                color: var(--primary-color, #03a9f4); margin-right: 16px; --mdc-icon-size: 24px;
            }
            .sfc-nav-label { flex: 1; font-size: 14px; font-weight: 500; color: var(--primary-text-color); }
            .sfc-nav-sublabel { font-size: 12px; color: var(--secondary-text-color, #666); margin-right: 8px; }
            .sfc-nav-check { color: var(--success-color, #4caf50) !important; --mdc-icon-size: 18px !important; margin-right: 8px; }
            .sfc-nav-arrow { color: var(--secondary-text-color, #999) !important; --mdc-icon-size: 20px !important; }
            .sfc-subpage-header {
                display: flex; align-items: center; padding: 14px 16px;
                cursor: pointer; border-bottom: 1px solid var(--divider-color, #e0e0e0); margin-bottom: 8px;
            }
            .sfc-subpage-header:hover { background: var(--secondary-background-color, #f5f5f5); }
            .sfc-subpage-header ha-icon { color: var(--primary-color, #03a9f4); margin-right: 12px; --mdc-icon-size: 20px; }
            .sfc-subpage-header span { font-size: 16px; font-weight: 600; color: var(--primary-text-color); }
            .sfc-form-container { padding: 0 16px 16px; }
            .sfc-device-item {
                display: flex; align-items: center; padding: 12px 16px;
                border-bottom: 1px solid var(--divider-color, #e0e0e0);
            }
            .sfc-device-info { flex: 1; cursor: pointer; }
            .sfc-device-info:hover { opacity: 0.8; }
            .sfc-device-dot { width: 12px; height: 12px; border-radius: 50%; margin-right: 12px; flex-shrink: 0; }
            .sfc-device-name { font-size: 14px; font-weight: 500; color: var(--primary-text-color); }
            .sfc-device-entity { font-size: 12px; color: var(--secondary-text-color, #666); }
            .sfc-device-actions { display: flex; gap: 4px; }
            .sfc-btn-icon {
                background: none; border: none; cursor: pointer; padding: 6px; border-radius: 50%;
                color: var(--secondary-text-color, #666); display: flex; align-items: center;
            }
            .sfc-btn-icon:hover { background: var(--secondary-background-color, #f5f5f5); }
            .sfc-btn-icon.delete { color: var(--error-color, #d33); }
            .sfc-btn-icon.delete:hover { background: rgba(211,51,51,0.1); }
            .sfc-btn-add {
                display: flex; align-items: center; justify-content: center; width: calc(100% - 32px);
                margin: 16px 16px; padding: 12px; border: 1px dashed var(--divider-color, #ccc);
                border-radius: 8px; background: none; color: var(--primary-color, #03a9f4);
                cursor: pointer; font-size: 14px; font-weight: 500; gap: 8px; box-sizing: border-box;
            }
            .sfc-btn-add:hover { background: var(--secondary-background-color, #f5f5f5); }
        `;
        this.appendChild(style);

        const container = document.createElement('div');
        container.className = 'sfc-editor';

        switch (this._page) {
            case 'main':
                this._buildMainPage(container);
                break;
            case 'individual':
                this._buildIndividualPage(container);
                break;
            case 'edit-device':
                this._buildDeviceEditPage(container);
                break;
            case 'display':
                container.appendChild(this._createHeader('Display Options', 'main'));
                container.appendChild(this._createForm(
                    SEMFlowCardEditor.SCHEMAS.display,
                    this._getDisplayData(),
                    (v) => this._updateDisplayConfig(v)
                ));
                break;
            default:
                if (SEMFlowCardEditor.SCHEMAS[this._page]) {
                    container.appendChild(this._createHeader(
                        SEMFlowCardEditor.SECTION_TITLES[this._page] || this._page, 'main'
                    ));
                    container.appendChild(this._createForm(
                        SEMFlowCardEditor.SCHEMAS[this._page],
                        this._getSectionData(this._page),
                        (v) => this._updateSectionConfig(this._page, v)
                    ));
                }
                break;
        }

        this.appendChild(container);
    }

    _buildMainPage(container) {
        const e = this._config.entities || {};
        const navItems = [
            { id: 'solar', name: 'Solar', icon: 'mdi:solar-power', configured: !!e.solar?.entity },
            { id: 'grid', name: 'Grid', icon: 'mdi:transmission-tower', configured: !!(e.grid?.consumption || e.grid?.entity) },
            { id: 'battery', name: 'Battery', icon: 'mdi:battery-medium', configured: !!(e.battery?.entity || e.battery?.charge || e.battery?.discharge) },
            { id: 'home', name: 'Home', icon: 'mdi:home', configured: !!e.home?.entity },
            { id: 'ev', name: 'EV Charger', icon: 'mdi:car-electric', configured: !!e.ev?.entity },
            { id: 'individual', name: 'Individual Devices', icon: 'mdi:devices', count: (e.individual || []).length },
            { id: 'display', name: 'Display Options', icon: 'mdi:cog' },
        ];

        for (const item of navItems) {
            const row = document.createElement('div');
            row.className = 'sfc-nav-item';

            const icon = document.createElement('ha-icon');
            icon.setAttribute('icon', item.icon);
            row.appendChild(icon);

            const label = document.createElement('span');
            label.className = 'sfc-nav-label';
            label.textContent = item.name;
            row.appendChild(label);

            if (item.count !== undefined) {
                const sub = document.createElement('span');
                sub.className = 'sfc-nav-sublabel';
                sub.textContent = `${item.count} device${item.count !== 1 ? 's' : ''}`;
                row.appendChild(sub);
            }

            if (item.configured) {
                const check = document.createElement('ha-icon');
                check.setAttribute('icon', 'mdi:check-circle');
                check.className = 'sfc-nav-check';
                row.appendChild(check);
            }

            const arrow = document.createElement('ha-icon');
            arrow.setAttribute('icon', 'mdi:chevron-right');
            arrow.className = 'sfc-nav-arrow';
            row.appendChild(arrow);

            row.addEventListener('click', () => this._navigate(item.id));
            container.appendChild(row);
        }
    }

    _buildIndividualPage(container) {
        container.appendChild(this._createHeader('Individual Devices', 'main'));

        const devs = this._config.entities?.individual || [];
        for (let i = 0; i < devs.length; i++) {
            const dev = devs[i];
            const row = document.createElement('div');
            row.className = 'sfc-device-item';

            const dot = document.createElement('div');
            dot.className = 'sfc-device-dot';
            dot.style.backgroundColor = dev.color || SFC_DEVICE_COLORS[i % SFC_DEVICE_COLORS.length];
            row.appendChild(dot);

            const info = document.createElement('div');
            info.className = 'sfc-device-info';
            const nameEl = document.createElement('div');
            nameEl.className = 'sfc-device-name';
            nameEl.textContent = dev.name || 'Device ' + (i + 1);
            info.appendChild(nameEl);
            const entityEl = document.createElement('div');
            entityEl.className = 'sfc-device-entity';
            entityEl.textContent = dev.entity || 'Not configured';
            info.appendChild(entityEl);
            info.addEventListener('click', () => this._navigate('edit-device', i));
            row.appendChild(info);

            const actions = document.createElement('div');
            actions.className = 'sfc-device-actions';

            const editBtn = document.createElement('button');
            editBtn.className = 'sfc-btn-icon';
            const editIcon = document.createElement('ha-icon');
            editIcon.setAttribute('icon', 'mdi:pencil');
            editIcon.style.setProperty('--mdc-icon-size', '20px');
            editBtn.appendChild(editIcon);
            editBtn.addEventListener('click', (ev) => { ev.stopPropagation(); this._navigate('edit-device', i); });
            actions.appendChild(editBtn);

            const delBtn = document.createElement('button');
            delBtn.className = 'sfc-btn-icon delete';
            const delIcon = document.createElement('ha-icon');
            delIcon.setAttribute('icon', 'mdi:delete');
            delIcon.style.setProperty('--mdc-icon-size', '20px');
            delBtn.appendChild(delIcon);
            delBtn.addEventListener('click', (ev) => {
                ev.stopPropagation();
                this._config.entities.individual.splice(i, 1);
                if (this._config.entities.individual.length === 0) delete this._config.entities.individual;
                this._fire();
                this._rendered = false;
                this._render();
            });
            actions.appendChild(delBtn);

            row.appendChild(actions);
            container.appendChild(row);
        }

        if (devs.length < 6) {
            const addBtn = document.createElement('button');
            addBtn.className = 'sfc-btn-add';
            const addIcon = document.createElement('ha-icon');
            addIcon.setAttribute('icon', 'mdi:plus');
            addIcon.style.setProperty('--mdc-icon-size', '20px');
            addBtn.appendChild(addIcon);
            const addText = document.createTextNode(' Add Device');
            addBtn.appendChild(addText);
            addBtn.addEventListener('click', () => {
                if (!this._config.entities) this._config.entities = {};
                if (!this._config.entities.individual) this._config.entities.individual = [];
                this._config.entities.individual.push({ entity: '', name: '' });
                this._fire();
                this._navigate('edit-device', this._config.entities.individual.length - 1);
            });
            container.appendChild(addBtn);
        }
    }

    _buildDeviceEditPage(container) {
        const idx = this._editDeviceIdx;
        const dev = this._config.entities?.individual?.[idx];
        if (!dev) { this._navigate('individual'); return; }

        container.appendChild(this._createHeader(dev.name || 'Device ' + (idx + 1), 'individual'));
        container.appendChild(this._createForm(
            SEMFlowCardEditor.SCHEMAS.device,
            this._getDeviceData(idx),
            (v) => this._updateDeviceConfig(idx, v)
        ));
    }
}

customElements.define('sem-flow-card-editor', SEMFlowCardEditor);

customElements.define('sem-flow-card', SEMFlowCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-flow-card',
    name: 'SEM Flow Card',
    description: 'Animated energy flow diagram with solar, battery, grid, EV, and individual devices',
    preview: true,
});
