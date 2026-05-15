(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Battery Zones Card — Reactive SOC zone configuration
 *
 * Uses SEMReactiveCard base: entity-reference comparison for shouldUpdate,
 * freeze/thaw for optimistic service calls, no innerHTML on updates.
 */

const ZONES = [
    { id: 'priority', entity: 'number.sem_battery_priority_soc', icon: 'mdi:shield-alert', labelKey: 'priority_soc', color: '#f44336' },
    { id: 'buffer', entity: 'number.sem_battery_buffer_soc', icon: 'mdi:shield-half-full', labelKey: 'buffer_soc', color: '#ff9800' },
    { id: 'autostart', entity: 'number.sem_battery_auto_start_soc', icon: 'mdi:play-circle', labelKey: 'auto_start_soc', color: '#4db6ac' },
    { id: 'floor', entity: 'number.sem_battery_assist_floor_soc', icon: 'mdi:arrow-collapse-down', labelKey: 'assist_floor', color: '#488fc2' },
];

class SEMBatteryZonesCard extends SEMReactiveCard {
    static get watchedEntities() {
        return ZONES.map(z => z.entity);
    }

    setConfig(config) {
        super.setConfig(config);
    }

    _buildTemplate() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const isDark = T.isDark !== false;

        const steppersHTML = ZONES.map(z => `
            <div class="z-${z.id} stepper-row" data-entity="${z.entity}">
                <ha-icon icon="${z.icon}" style="--mdc-icon-size:18px;color:${z.color}"></ha-icon>
                <span class="stepper-label"></span>
                <div class="stepper-controls">
                    <button class="stepper-minus" data-entity="${z.entity}" data-delta="-1" aria-label="Decrease">−</button>
                    <span class="stepper-value">—</span>
                    <button class="stepper-plus" data-entity="${z.entity}" data-delta="1" aria-label="Increase">+</button>
                </div>
            </div>`).join('');

        return `
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(77,182,172,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }
                .header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
                .header-title { font-size: 14px; font-weight: 600; color: #4db6ac; }
                .subtitle {
                    flex: 1; text-align: right;
                    font-size: 11px; color: var(--secondary-text-color, ${textSecCol});
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .zone-bar-wrap { margin: 0 0 14px; padding: 0 4px; }
                .zone-bar {
                    position: relative; height: 8px; border-radius: 4px;
                    background: linear-gradient(90deg, #f44336 0%, #ff9800 30%, #4db6ac 60%, #488fc2 80%, #8DC892 100%);
                    opacity: 0.6;
                }
                .zone-marker {
                    position: absolute; top: -6px; transform: translateX(-50%);
                    display: flex; flex-direction: column; align-items: center;
                    transition: left 0.3s ease;
                }
                .zone-dot {
                    width: 10px; height: 10px; border-radius: 50%;
                    border: 2px solid ${isDark ? '#1e232d' : '#fff'};
                    box-shadow: 0 0 4px rgba(0,0,0,0.3);
                }
                .zone-marker-label {
                    font-size: 9px; font-weight: 600; margin-top: 2px;
                    color: var(--secondary-text-color, ${textSecCol});
                    font-variant-numeric: tabular-nums;
                }
                .stepper-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; }
                .stepper-row { display: flex; align-items: center; gap: 6px; padding: 6px 0; }
                .stepper-label {
                    font-size: 12px; font-weight: 500; flex: 1;
                    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 28px; height: 28px; border-radius: 7px;
                    border: 1px solid ${surfBorder}; background: ${surfaceCol};
                    color: var(--primary-text-color, ${textCol});
                    font-size: 15px; font-weight: 600; cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s;
                    user-select: none; -webkit-user-select: none;
                    touch-action: manipulation; padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${T.surfaceHover || 'rgba(255,255,255,0.10)'};
                }
                .stepper-value {
                    font-size: 13px; font-weight: 600; min-width: 48px;
                    text-align: center; font-variant-numeric: tabular-nums;
                }
                @media (max-width: 480px) { .stepper-grid { grid-template-columns: 1fr; } }
            </style>
            <div class="wrap">
                <div class="header">
                    <ha-icon icon="mdi:battery-charging-medium" style="--mdc-icon-size:18px;color:#4db6ac"></ha-icon>
                    <span class="header-title">${this._t('soc_zones')}</span>
                    <span class="subtitle">—</span>
                </div>
                <div class="zone-bar-wrap">
                    <div class="zone-bar">
                        ${ZONES.map(z => `
                            <div class="zone-marker" data-zone="${z.id}">
                                <div class="zone-dot" style="background:${z.color}"></div>
                                <span class="zone-marker-label">—</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="stepper-grid">${steppersHTML}</div>
            </div>`;
    }

    _bindEvents() {
        // Delegate click events on the stepper grid
        const grid = this.$('.stepper-grid');
        if (!grid) return;

        grid.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-entity][data-delta]');
            if (!btn) return;
            const entity = btn.dataset.entity;
            const delta = parseInt(btn.dataset.delta);
            this._stepNumber(entity, delta);
        });

        grid.addEventListener('pointerdown', (e) => {
            const btn = e.target.closest('[data-entity][data-delta]');
            if (!btn) return;
            this._startHold(btn.dataset.entity, parseInt(btn.dataset.delta));
        });

        grid.addEventListener('pointerup', (e) => {
            const btn = e.target.closest('[data-entity][data-delta]');
            if (btn) this._stopHold(btn.dataset.entity);
        });

        grid.addEventListener('pointerleave', (e) => {
            const btn = e.target.closest('[data-entity][data-delta]');
            if (btn) this._stopHold(btn.dataset.entity);
        }, true);
    }

    _applyState(root) {
        if (!this._hass) return;

        // Update stepper values + labels
        for (const z of ZONES) {
            const val = this._state(z.entity);
            const entity = this._hass.states[z.entity];
            const step = entity ? parseFloat(entity.attributes.step) || 1 : 1;
            const decimals = step < 1 ? 1 : 0;
            this._setText(`.z-${z.id} .stepper-value`, val.toFixed(decimals) + '%');
            this._setText(`.z-${z.id} .stepper-label`, this._t(z.labelKey));
        }

        // Update zone bar markers
        const vals = ZONES.map(z => ({ ...z, val: this._state(z.entity) }));
        const sorted = [...vals].sort((a, b) => a.val - b.val);
        for (const z of sorted) {
            const marker = root.querySelector(`.zone-marker[data-zone="${z.id}"]`);
            if (marker) {
                this._setStyle(marker, 'left', z.val + '%');
                const label = marker.querySelector('.zone-marker-label');
                if (label) {
                    const text = z.val.toFixed(0) + '%';
                    if (label.textContent !== text) label.textContent = text;
                }
            }
        }

        // Subtitle
        const priority = this._state(ZONES[0].entity);
        const buffer = this._state(ZONES[1].entity);
        const autostart = this._state(ZONES[2].entity);
        this._setText('.subtitle', `${this._t('priority_soc')} < ${priority.toFixed(0)}% · Buffer ${buffer.toFixed(0)}% · Auto-start ${autostart.toFixed(0)}%`);
    }

    getCardSize() { return 4; }
    static getStubConfig() { return {}; }
}

semDefineCard('sem-battery-zones-card', SEMBatteryZonesCard, {
    type: 'custom:sem-battery-zones-card',
    name: 'SEM Battery Zones Card',
    description: 'SOC zone configuration for Solar Energy Management',
    preview: false,
});

});
