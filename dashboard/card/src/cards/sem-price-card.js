/**
 * SEM Price Card — dynamic electricity price visibility (#257)
 *
 * Shows the current import price, price level, today's min/avg/max, the next
 * cheap window, and an hourly price strip for the upcoming ~24h. Reads
 * everything from sensor.sem_tariff_current_import_rate (+ its attributes):
 *   state          = current import price
 *   price_level    = negative|very_cheap|cheap|normal|expensive|very_expensive
 *   currency, provider, is_dynamic
 *   today_min/avg/max, next_cheap_start/end
 *   upcoming       = [{t, price, level}, ...]  (dynamic tariffs only)
 *
 * Config:
 *   type: custom:sem-price-card
 *   entity: sensor.sem_tariff_current_import_rate   # default
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import { semDefineCard } from '../base/sem-shared.js';

const DEFAULT_ENTITY = 'sensor.sem_tariff_current_import_rate';
const LEVELS = {
    negative:       { color: '#4db6ac', key: 'price_negative' },
    very_cheap:     { color: '#8DC892', key: 'very_cheap' },
    cheap:          { color: '#8DC892', key: 'cheap' },
    normal:         { color: '#ff9800', key: 'normal' },
    expensive:      { color: '#f06292', key: 'expensive' },
    very_expensive: { color: '#e53935', key: 'very_expensive' },
};

class SEMPriceCard extends SEMLitBase {
    setConfig(config) {
        super.setConfig(config);
        this._entity = config.entity || DEFAULT_ENTITY;
    }

    set hass(hass) {
        this._hass = hass;
        const e = hass?.states[this._entity];
        const a = e?.attributes || {};
        // Re-render on price / level / window / curve / language change.
        const key = [
            e?.state, a.price_level, a.next_cheap_start,
            (a.upcoming || []).length, this._lang,
        ].join('|');
        const hasLocalize = typeof semLocalize === 'function';
        if (key !== this._lastKey || (hasLocalize && !this._localizeReady)) {
            this._lastKey = key;
            this._lang = hass?.language;
            this._localizeReady = hasLocalize;
            this.requestUpdate();
        }
    }
    get hass() { return this._hass; }

    _hm(iso) {
        if (!iso) return null;
        try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
        catch (e) { return null; }
    }

    _levelInfo(level) {
        return LEVELS[level] || { color: '#9e9e9e', key: 'normal' };
    }

    render() {
        if (!this._hass || !this._config) return nothing;
        const e = this._hass.states[this._entity];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') {
            return html`<ha-card><div class="wrap empty">${this._t('current_electricity_price')}: —</div></ha-card>`;
        }
        const a = e.attributes || {};
        const price = parseFloat(e.state);
        const cur = a.currency || '';
        const lvl = this._levelInfo(a.price_level);
        const fmt = (v) => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(2);

        const upcoming = Array.isArray(a.upcoming) ? a.upcoming : [];
        const nextCheap = this._hm(a.next_cheap_start);
        const nextCheapEnd = this._hm(a.next_cheap_end);

        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <span class="title">${this._t('current_electricity_price')}</span>
                        ${a.provider && a.provider !== 'unknown'
                            ? html`<span class="prov">${a.provider}</span>` : nothing}
                    </div>
                    <div class="now">
                        <span class="price" style="color:${lvl.color}">${fmt(price)}</span>
                        <span class="unit">${cur}/kWh</span>
                        <span class="badge" style="background:${lvl.color}22;color:${lvl.color};border-color:${lvl.color}55">
                            ${this._t(lvl.key)}
                        </span>
                    </div>
                    <div class="summary">
                        <span>${this._t('today')}: <b>min ${fmt(a.today_min)}</b> · avg ${fmt(a.today_avg)} · <b>max ${fmt(a.today_max)}</b></span>
                        ${nextCheap ? html`<span class="cheap">${this._t('price_next_cheap')}: <b>${nextCheap}${nextCheapEnd ? '–' + nextCheapEnd : ''}</b></span>` : nothing}
                    </div>
                    ${upcoming.length >= 2 ? this._renderStrip(upcoming) : (a.is_dynamic === false
                        ? html`<div class="static-note">${this._t('price_level')}: ${this._t(lvl.key)}</div>`
                        : nothing)}
                </div>
            </ha-card>
        `;
    }

    /** Hourly price strip: bar height ∝ price, colored by level, "now" outlined. */
    _renderStrip(upcoming) {
        const now = Date.now();
        // next ~24 points from now-ish
        const pts = upcoming
            .map(p => ({ t: new Date(p.t).getTime(), price: p.price, level: p.level }))
            .filter(p => !isNaN(p.t))
            .sort((x, y) => x.t - y.t)
            .filter(p => p.t >= now - 3600_000)
            .slice(0, 24);
        if (pts.length < 2) return nothing;
        const prices = pts.map(p => p.price);
        const lo = Math.min(...prices), hi = Math.max(...prices);
        const span = hi - lo || 1;
        const W = 320, H = 64, n = pts.length;
        const gap = 2;
        const bw = (W - gap * (n - 1)) / n;
        const bars = pts.map((p, i) => {
            const norm = (p.price - lo) / span;      // 0..1
            const bh = 6 + norm * (H - 12);
            const x = i * (bw + gap);
            const y = H - bh;
            const col = this._levelInfo(p.level).color;
            const isNow = p.t <= now && now < p.t + 3600_000;
            return svg`<rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="1.5"
                fill="${col}" opacity="${isNow ? '1' : '0.65'}"
                stroke="${isNow ? '#fff' : 'none'}" stroke-width="${isNow ? '1' : '0'}"/>`;
        });
        // hour labels every 6 bars
        const labels = pts.map((p, i) => {
            if (i % 6 !== 0) return nothing;
            const x = i * (bw + gap) + bw / 2;
            const hh = new Date(p.t).getHours();
            return svg`<text x="${x}" y="${H + 11}" text-anchor="middle"
                fill="var(--secondary-text-color,#999)" font-size="9">${String(hh).padStart(2, '0')}</text>`;
        });
        return html`
            <svg class="strip" viewBox="0 0 ${W} ${H + 14}" width="100%" preserveAspectRatio="none">
                ${bars}${labels}
            </svg>
        `;
    }

    getCardSize() { return 2; }
    static getStubConfig() { return { entity: DEFAULT_ENTITY }; }

    static get styles() {
        return css`
            ha-card { background: var(--ha-card-background, var(--card-background-color)); }
            .wrap { padding: 12px 14px; }
            .wrap.empty { color: var(--secondary-text-color,#999); }
            .head { display: flex; align-items: baseline; gap: 8px; }
            .title { font-size: 13px; font-weight: 600; color: var(--primary-text-color,#e0e0e0); }
            .prov { margin-left: auto; font-size: 10px; color: var(--secondary-text-color,#999); text-transform: capitalize; }
            .now { display: flex; align-items: baseline; gap: 8px; margin: 4px 0 6px; }
            .price { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
            .unit { font-size: 12px; color: var(--secondary-text-color,#999); }
            .badge { margin-left: auto; font-size: 11px; font-weight: 600; padding: 2px 9px;
                     border-radius: 10px; border: 1px solid; text-transform: capitalize; }
            .summary { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 11.5px;
                       color: var(--secondary-text-color,#aaa); margin-bottom: 8px; }
            .summary b { color: var(--primary-text-color,#e0e0e0); font-variant-numeric: tabular-nums; }
            .summary .cheap b { color: #8DC892; }
            .strip { display: block; overflow: visible; }
            .static-note { font-size: 11.5px; color: var(--secondary-text-color,#999); padding-top: 2px; }
        `;
    }
}

semDefineCard('sem-price-card', SEMPriceCard, {
    type: 'custom:sem-price-card',
    name: 'SEM Price Card',
    description: 'Dynamic electricity price: current price, level, today range, next cheap window, and an hourly price strip (#257)',
    preview: false,
});
