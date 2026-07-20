/**
 * SEM Period Selector Card — LitElement date-range picker
 *
 * Dispatches 'sem-period-change' CustomEvent on document so that
 * all sem-chart-card instances on the same page react to the selection.
 *
 * Event detail: { start: Date, end: Date, granularity: 'hour'|'day'|'month', key: string }
 */

import { SEMLitBase, html, css, nothing, semGlassCss } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

const PERIODS = [
    { key: 'today',     labelKey: 'period_today' },
    { key: 'yesterday', labelKey: 'period_yesterday' },
    { key: 'week',      labelKey: 'period_this_week' },
    { key: 'month',     labelKey: 'period_this_month' },
    { key: 'year',      labelKey: 'period_this_year' },
];

class SEMPeriodSelectorCard extends SEMLitBase {
    // #617 — glass chrome baked in (was card-mod *glass_card)
    static get styles() { return [semGlassCss]; }

    static get watchedEntities() { return []; }

    constructor() {
        super();
        this._active = 'week';
        this._firstRender = true;
    }

    setConfig(config) {
        super.setConfig(config);
        if (config.default_period) {
            this._active = config.default_period;
        }
    }

    // Override hass setter — only check locale changes; no entity comparison needed
    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            this.requestUpdate();
        }
    }

    get hass() {
        return this._hass;
    }

    firstUpdated() {
        // Dispatch the default period on first render
        this._dispatchPeriod(this._active);
    }

    _getPeriod(key) {
        const now = new Date();
        const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
        const today = startOfDay(now);

        switch (key) {
            case 'today':
                return { start: today, end: now, granularity: 'hour' };
            case 'yesterday': {
                const yd = new Date(today);
                yd.setDate(yd.getDate() - 1);
                return { start: yd, end: today, granularity: 'hour' };
            }
            case 'week': {
                const dow = now.getDay() || 7; // Sunday=7
                const mon = new Date(today);
                mon.setDate(mon.getDate() - (dow - 1));
                return { start: mon, end: now, granularity: 'day' };
            }
            case 'month':
                return {
                    start: new Date(now.getFullYear(), now.getMonth(), 1),
                    end: now,
                    granularity: 'day',
                };
            case 'year':
                return {
                    start: new Date(now.getFullYear(), 0, 1),
                    end: now,
                    granularity: 'month',
                };
            default:
                return this._getPeriod('week');
        }
    }

    _dispatchPeriod(key) {
        this._active = key;
        this.requestUpdate();
        const period = this._getPeriod(key);
        document.dispatchEvent(new CustomEvent('sem-period-change', {
            detail: { ...period, key },
        }));
    }

    render() {
        if (!this._config) return nothing;

        const T = this._theme();

        return html`
            <style>
                :host { display: block; }
                .sem-period {
                    display: flex;
                    gap: 8px;
                    padding: 12px 16px;
                    justify-content: center;
                    flex-wrap: wrap;
                    background:
                        radial-gradient(ellipse 80% 60% at 50% 50%, rgba(200,220,240,0.04) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }
                .btn {
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    background: var(--secondary-background-color, ${T.surface});
                    color: var(--secondary-text-color, ${T.textSec});
                    padding: 8px 18px;
                    border-radius: 12px;
                    font-size: 13px;
                    font-weight: 500;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    font-variant-numeric: tabular-nums;
                    cursor: pointer;
                    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    user-select: none;
                }
                .btn:hover {
                    background: var(--secondary-background-color, ${T.surfaceHover});
                    color: var(--primary-text-color, ${T.text});
                    border-color: var(--divider-color, ${T.surfaceBorder});
                }
                .btn.active {
                    background: rgba(66,165,245,0.18);
                    border-color: rgba(66,165,245,0.40);
                    color: ${T.accent};
                    box-shadow: 0 0 16px rgba(66,165,245,0.12), 0 0 4px rgba(66,165,245,0.08);
                    font-weight: 600;
                }
            </style>
            <ha-card>
                <div class="sem-period">
                    ${PERIODS.map(p => html`
                        <button
                            class="btn ${this._active === p.key ? 'active' : ''}"
                            role="button"
                            aria-label=${this._t(p.labelKey)}
                            aria-pressed=${this._active === p.key}
                            @click=${() => this._dispatchPeriod(p.key)}
                        >${this._t(p.labelKey)}</button>
                    `)}
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return {}; }
}

semDefineCard('sem-period-selector-card', SEMPeriodSelectorCard, {
    type: 'custom:sem-period-selector-card',
    name: 'SEM Period Selector',
    description: 'Glassmorphism period picker for SEM chart cards',
    preview: false,
});
