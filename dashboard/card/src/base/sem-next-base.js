/**
 * (#1321) What every SEM Next screen shares: the header with the observer
 * pill, the lead line, the source colours, the card chrome, and the
 * readers for the entities the screens draw from.
 *
 * Reactivity: each screen lists the entity ids it reads in `_watchIds()`;
 * the hass setter re-renders when one of their states changes.
 */

import { SEMLitBase, html, css, nothing } from './sem-lit-base.js';
import { readNumber } from '../util/missing-value.js';
import { fill } from '../util/next-lead.js';

export { html, css, nothing };

export const NEXT_COLORS = {
    solar: '#ff9800', grid: '#488fc2', export: '#8353d1',
    battery_in: '#f06292', battery_out: '#4db6ac', home: '#5BC8D8', ev: '#8DC892',
    accent: '#1F7A8C', good: '#2E9E5B', warn: '#E09A1A', bad: '#D64545',
};

export const nextCss = css`
    :host { display: block; }
    ha-card { background: var(--card-background-color); border-radius: 16px; padding: 0; overflow: hidden; }
    .wrap { padding: 12px 14px 18px; display: grid; gap: 12px; }
    .head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .brand { display: flex; align-items: center; gap: 8px; font-weight: 800; font-size: 1rem; letter-spacing: -0.01em; }
    .brand ha-icon { color: #ff9800; --mdc-icon-size: 22px; }
    .pill { display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; font-weight: 600;
            padding: 4px 10px; border-radius: 999px; border: 1px solid var(--divider-color);
            background: var(--secondary-background-color); }
    .pill i { width: 8px; height: 8px; border-radius: 50%; background: #2E9E5B; display: inline-block; }
    .pill.observe i { background: #E09A1A; }
    .lead { font-weight: 700; font-size: 1.2rem; line-height: 1.3; letter-spacing: -0.01em; }
    .lead small { display: block; font-weight: 500; font-size: 0.85rem; line-height: 1.4; color: var(--secondary-text-color); margin-top: 4px; }
    .sec { background: var(--secondary-background-color); border-radius: 14px; padding: 12px; display: grid; gap: 10px; min-width: 0; }
    .sec h3 { margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
    .num { font-variant-numeric: tabular-nums; }
    .kv { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; font-size: 0.9rem; margin: 0; }
    .kv dt { color: var(--secondary-text-color); } .kv dd { margin: 0; text-align: right; font-weight: 600; }
    .src { display: inline-flex; align-items: center; gap: 6px; }
    .src i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    .tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .tile { background: var(--card-background-color); border-radius: 12px; padding: 10px 12px; display: grid; gap: 2px; }
    .tile b { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; }
    .tile b small { font-size: 0.8rem; font-weight: 600; }
    .tile span { font-size: 0.75rem; color: var(--secondary-text-color); }
    .bar { height: 5px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
    .bar i { display: block; height: 100%; border-radius: 3px; }
    .why { display: grid; gap: 8px; }
    .why .row { display: grid; grid-template-columns: 28px 1fr; gap: 10px; align-items: start; }
    .why .dot { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 0.75rem; }
    .why b { display: block; font-weight: 600; } .why span { color: var(--secondary-text-color); font-size: 0.85rem; }
    .list { display: grid; gap: 8px; }
    .item { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 12px; background: var(--card-background-color); }
    .item i { width: 10px; height: 10px; border-radius: 50%; background: #2E9E5B; }
    .item i.warn { background: #E09A1A; } .item i.off { background: var(--divider-color); } .item i.bad { background: #D64545; }
    .item span { font-size: 0.78rem; color: var(--secondary-text-color); display: block; }
    .btns { display: flex; flex-wrap: wrap; gap: 8px; }
    .btn { border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color);
           font: 600 0.85rem inherit; padding: 9px 14px; border-radius: 12px; cursor: pointer; min-height: 40px; }
    .btn.primary { background: #1F7A8C; color: #fff; border-color: transparent; }
    .btn[disabled] { opacity: 0.5; cursor: default; }
    .btn:focus-visible { outline: 2px solid #1F7A8C; outline-offset: 1px; }
    .hint { font-size: 0.78rem; color: var(--secondary-text-color); }
    .sub { display: inline-flex; gap: 4px; background: var(--card-background-color); border-radius: 10px; padding: 3px; }
    .sub button { border: 0; background: transparent; color: var(--secondary-text-color); font: 600 0.8rem inherit; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
    .sub button[aria-pressed="true"] { background: var(--secondary-background-color); color: var(--primary-text-color); }
    select, input[type="time"], input[type="number"] { font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
           border: 1px solid var(--divider-color); border-radius: 8px; padding: 4px 8px; max-width: 150px; }
    .toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 0.85rem; }
    .toggle input { appearance: none; width: 40px; height: 24px; border-radius: 999px; background: var(--divider-color); position: relative; cursor: pointer; margin: 0; }
    .toggle input::after { content: ""; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: var(--card-background-color); transition: left .15s; }
    .toggle input:checked { background: #1F7A8C; } .toggle input:checked::after { left: 19px; }
    .grid2 { display: grid; gap: 12px; }
    @media (min-width: 760px) { .grid2 { grid-template-columns: repeat(2, minmax(0, 1fr)); } .grid2 > .wide { grid-column: 1 / -1; } }
    @media (min-width: 1100px) { .grid2 { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
    :host(.observe) .sec { opacity: 0.85; }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
`;

export class SEMNextBase extends SEMLitBase {
    constructor() {
        super();
        this._prefix = 'sensor.sem_';
        this._key = '';
        this._chargers = [];
    }

    setConfig(config) {
        super.setConfig(config || {});
    }

    /** Entity ids whose state drives a re-render. Screens extend it. */
    _watchIds() {
        return ['switch.sem_observer_mode', 'sensor.sem_night_start_time', 'sensor.sem_night_end_time'];
    }

    set hass(hass) {
        this._hass = hass;
        if (!hass) return;
        const lang = hass.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang; this._localizeReady = hasLocalize; localeChanged = true;
        }
        this._discover(hass);
        const ids = this._watchIds();
        const key = ids.map((id) => {
            const st = hass.states[id];
            return st ? st.state + '|' + (st.last_updated || '') : '';
        }).join('§') + '§' + this._chargers.join(',');
        if (key !== this._key || localeChanged) {
            this._key = key;
            if (this.classList) this.classList.toggle('observe', this._observer());
            this._scheduleUpdate();
        }
    }
    get hass() { return this._hass; }

    /** Chargers from the per-charger power sensors (the same trap as the status card: skip flow sensors). */
    _discover(hass) {
        const found = [];
        for (const eid of Object.keys(hass.states)) {
            if (eid.includes('_flow_')) continue;
            const m = eid.match(/^sensor\.sem_charger_(.+)_power$/);
            if (m) found.push(m[1]);
        }
        found.sort();
        this._chargers = found;
    }

    _num(id) { return readNumber(this._hass?.states[id]); }
    _str(id) {
        const e = this._hass?.states[id];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }
    _attrs(id) { return this._hass?.states[id]?.attributes || {}; }
    _name(id) {
        const n = this._hass?.states[id]?.attributes?.friendly_name;
        return n ? String(n).replace(/^SEM\s+/i, '') : id;
    }
    _observer() { return this._str('switch.sem_observer_mode') === 'on'; }
    _clock() {
        const d = new Date();
        return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }
    _night() {
        const s = this._str('sensor.sem_night_start_time'), e = this._str('sensor.sem_night_end_time');
        if (!s || !e) return false;
        const now = this._clock();
        return s > e ? (now >= s || now < e) : (now >= s && now < e);
    }
    _chargerName(cid) {
        const n = this._hass?.states[`sensor.sem_charger_${cid}_power`]?.attributes?.friendly_name || '';
        const m = /^(?:SEM\s+)?(.*?)\s+Power$/i.exec(n);
        return (m && m[1]) ? m[1] : cid.replace(/_/g, ' ');
    }
    _chargerEntity(domain, cid, suffix) {
        const id = `${domain}.sem_charger_${cid}_${suffix}`;
        return this._hass?.states[id] ? id : null;
    }
    _powerW(id) {
        const v = this._num(id);
        if (v === null) return null;
        return (this._unitOf(id) || '').toLowerCase() === 'kw' ? v * 1000 : v;
    }
    _fmtKw(w, d = 1) { return w === null || !Number.isFinite(w) ? '—' : (w / 1000).toFixed(d); }
    _fmt(v, d = 1) { return v === null || !Number.isFinite(v) ? '—' : Number(v).toFixed(d); }
    _tf(key, params) { return fill(this._t(key), params, (k) => this._t(k)); }
    _currency() {
        const c = this._hass?.config?.currency;
        return c || 'CHF';
    }

    _renderHead() {
        const obs = this._observer();
        return html`
            <div class="head">
                <div class="brand"><ha-icon icon="mdi:white-balance-sunny"></ha-icon><span>SEM</span></div>
                <span class="pill ${obs ? 'observe' : ''}"><i></i>${obs ? this._t('next_pill_observing') : this._t('next_pill_live')}</span>
            </div>`;
    }

    _renderLead(main, sub) {
        return html`<div class="lead">${main}${sub ? html`<small>${sub}</small>` : nothing}</div>`;
    }

    getCardSize() { return 8; }
    static getStubConfig() { return {}; }
}
