/**
 * SEM Period Selector Card — glassmorphism date-range picker
 *
 * Dispatches 'sem-period-change' CustomEvent on document so that
 * all sem-chart-card instances on the same page react to the selection.
 *
 * Event detail: { start: Date, end: Date, granularity: 'hour'|'day'|'month', label: string }
 */

class SEMPeriodSelectorCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._active = 'week'; // default
    }

    setConfig(config) {
        this.config = config;
        if (config.default_period) this._active = config.default_period;
    }

    set hass(hass) {
        this._hass = hass;
        if (!this.shadowRoot.querySelector('.sem-period')) {
            this._render();
            // Fire initial period on first render
            this._dispatchPeriod(this._active);
        }
    }

    _getPeriod(key) {
        const now = new Date();
        const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
        const today = startOfDay(now);

        switch (key) {
            case 'today':
                return { start: today, end: now, granularity: 'hour', label: 'Today' };
            case 'yesterday': {
                const yd = new Date(today);
                yd.setDate(yd.getDate() - 1);
                return { start: yd, end: today, granularity: 'hour', label: 'Yesterday' };
            }
            case 'week': {
                // Monday-based week
                const dow = now.getDay() || 7; // Sunday=7
                const mon = new Date(today);
                mon.setDate(mon.getDate() - (dow - 1));
                return { start: mon, end: now, granularity: 'day', label: 'This Week' };
            }
            case 'month':
                return {
                    start: new Date(now.getFullYear(), now.getMonth(), 1),
                    end: now, granularity: 'day', label: 'This Month',
                };
            case 'year':
                return {
                    start: new Date(now.getFullYear(), 0, 1),
                    end: now, granularity: 'month', label: 'This Year',
                };
            default:
                return this._getPeriod('week');
        }
    }

    _dispatchPeriod(key) {
        this._active = key;
        const period = this._getPeriod(key);
        document.dispatchEvent(new CustomEvent('sem-period-change', {
            detail: { ...period, key },
        }));
        // Update button styling
        this.shadowRoot.querySelectorAll('.btn').forEach(b => {
            b.classList.toggle('active', b.dataset.key === key);
        });
    }

    _render() {
        const buttons = [
            { key: 'today', label: 'Today' },
            { key: 'yesterday', label: 'Yesterday' },
            { key: 'week', label: 'This Week' },
            { key: 'month', label: 'This Month' },
            { key: 'year', label: 'This Year' },
        ];

        this.shadowRoot.innerHTML = `
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
                        radial-gradient(circle at 2px 2px, rgba(128,128,128,0.04) 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }
                .btn {
                    border: 1px solid rgba(255,255,255,0.08);
                    background: rgba(255,255,255,0.05);
                    color: #9e9e9e;
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
                    background: rgba(255,255,255,0.08);
                    color: #e0e0e0;
                    border-color: rgba(255,255,255,0.14);
                }
                .btn.active {
                    background: rgba(66,165,245,0.18);
                    border-color: rgba(66,165,245,0.40);
                    color: #42a5f5;
                    box-shadow: 0 0 16px rgba(66,165,245,0.12), 0 0 4px rgba(66,165,245,0.08);
                    font-weight: 600;
                }
            </style>
            <ha-card>
                <div class="sem-period">
                    ${buttons.map(b =>
                        `<button class="btn${b.key === this._active ? ' active' : ''}" data-key="${b.key}">${b.label}</button>`
                    ).join('')}
                </div>
            </ha-card>
        `;

        this.shadowRoot.querySelectorAll('.btn').forEach(btn => {
            btn.addEventListener('click', () => this._dispatchPeriod(btn.dataset.key));
        });
    }

    getCardSize() { return 1; }

    static getStubConfig() { return {}; }
}

customElements.define('sem-period-selector-card', SEMPeriodSelectorCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-period-selector-card',
    name: 'SEM Period Selector',
    description: 'Glassmorphism period picker for SEM chart cards',
});
