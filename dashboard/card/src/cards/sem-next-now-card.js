/**
 * SEM Next · Now (#1321)
 *
 * What SEM does right now and why, in one line and then the detail: the
 * power bar (sources above, sinks below, tap for every number), today's
 * totals with sparklines and the two share rings, the Today list from the
 * backend's plan rows, why each device does what it does, money, and the
 * signals (tip, surplus window, peak, CO2, score, weather). Every number
 * comes from an SEM entity; a missing entity leaves its row out.
 *
 * Config:
 *   type: custom:sem-next-now-card
 */

import { SEMNextBase, html, css, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import { nowLead } from '../util/next-lead.js';
import { powerBar } from '../util/next-power-bar.js';
import { todayRows } from '../util/next-today-rows.js';
import { priceLevelKey, isAbsence } from '../util/price-level.js';
import { shedReasonKey } from '../util/shed-reason.js';
import { splitStrategyReason } from '../util/next-strategy-reason.js';
import { plainReason } from '../util/why-rows.js';
import { newestUpdate } from '../util/next-freshness.js';
import { isUncapped, peakLimitText } from '../util/peak-slot.js';

const IDS = [
    'sensor.sem_solar_power', 'sensor.sem_grid_power', 'sensor.sem_battery_power', 'sensor.sem_battery_soc',
    'sensor.sem_home_consumption_power', 'sensor.sem_ev_power', 'sensor.sem_charging_strategy',
    'sensor.sem_charging_state', 'sensor.sem_energy_plan', 'sensor.sem_controllable_devices_count',
    'sensor.sem_battery_dynamic_floor_pct', 'number.sem_battery_buffer_soc', 'number.sem_battery_priority_soc',
    'switch.sem_battery_may_assist_ev', 'sensor.sem_consecutive_peak_15min', 'sensor.sem_target_peak_limit',
    'sensor.sem_battery_spendable_kwh', 'sensor.sem_daily_battery_savings', 'sensor.sem_monthly_battery_savings',
    'sensor.sem_daily_solar_energy', 'sensor.sem_forecast_today_kwh', 'sensor.sem_forecast_remaining_today_kwh',
    'sensor.sem_daily_grid_import_energy', 'sensor.sem_daily_grid_export_energy', 'sensor.sem_daily_home_energy',
    'sensor.sem_daily_ev_energy', 'sensor.sem_daily_battery_charge_energy', 'sensor.sem_daily_battery_discharge_energy',
    'sensor.sem_flow_solar_to_home_energy', 'sensor.sem_energy_ev_solar_percentage',
    'sensor.sem_self_consumption_rate', 'sensor.sem_autarky_rate',
    'sensor.sem_daily_co2_avoided', 'sensor.sem_lifetime_co2_avoided', 'sensor.sem_lifetime_trees_equivalent',
    'sensor.sem_daily_costs', 'sensor.sem_daily_savings', 'sensor.sem_daily_export_revenue',
    'sensor.sem_monthly_costs', 'sensor.sem_monthly_savings',
    'sensor.sem_tariff_current_import_rate', 'sensor.sem_tariff_current_export_rate', 'sensor.sem_tariff_price_level',
    'sensor.sem_energy_tip', 'sensor.sem_best_surplus_window', 'sensor.sem_energy_optimization_score',
];

/** The power sensors whose hourly means draw today's sparklines. */
const HIST_IDS = ['sensor.sem_solar_power', 'sensor.sem_home_consumption_power', 'sensor.sem_ev_power', 'sensor.sem_grid_power'];
const HIST_EVERY_MS = 5 * 60 * 1000;
const FORECAST_EVERY_MS = 30 * 60 * 1000;
const TICK_MS = 10 * 1000;
const HINT_KEY = 'sem_next_hint_v1';
const IO_KEY = 'sem_next_io_v1';

/** HA weather conditions → icon + the classic card's label key. */
const WEATHER = {
    'clear-night':     { icon: 'mdi:weather-night',           key: 'weather_clear' },
    'cloudy':          { icon: 'mdi:weather-cloudy',          key: 'weather_cloudy' },
    'fog':             { icon: 'mdi:weather-fog',             key: 'weather_fog' },
    'hail':            { icon: 'mdi:weather-hail',            key: 'weather_hail' },
    'lightning':       { icon: 'mdi:weather-lightning',       key: 'weather_thunder' },
    'lightning-rainy': { icon: 'mdi:weather-lightning-rainy', key: 'weather_thunderstorm' },
    'partlycloudy':    { icon: 'mdi:weather-partly-cloudy',   key: 'weather_partly_cloudy' },
    'pouring':         { icon: 'mdi:weather-pouring',         key: 'weather_pouring' },
    'rainy':           { icon: 'mdi:weather-rainy',           key: 'weather_rain' },
    'snowy':           { icon: 'mdi:weather-snowy',           key: 'weather_snow' },
    'snowy-rainy':     { icon: 'mdi:weather-snowy-rainy',     key: 'weather_sleet' },
    'sunny':           { icon: 'mdi:weather-sunny',           key: 'weather_sunny' },
    'windy':           { icon: 'mdi:weather-windy',           key: 'weather_windy' },
    'windy-variant':   { icon: 'mdi:weather-windy-variant',   key: 'weather_windy' },
    'exceptional':     { icon: 'mdi:alert-circle-outline',    key: 'weather_exceptional' },
};

/** Bar segment and list row looks per power-bar key. */
const META = {
    solar:       { icon: 'mdi:white-balance-sunny', color: C.solar,       dark: false },
    battery_out: { icon: 'mdi:battery-charging',    color: C.battery_out, dark: false },
    grid_in:     { icon: 'mdi:transmission-tower',  color: C.grid,        dark: true },
    home:        { icon: 'mdi:home',                color: C.home,        dark: false },
    ev:          { icon: 'mdi:car-electric',        color: C.ev,          dark: false },
    battery_in:  { icon: 'mdi:battery-charging',    color: C.battery_in,  dark: false },
    grid_out:    { icon: 'mdi:transmission-tower',  color: C.export,      dark: true },
};

function readLocal(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
}
function writeLocal(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private window: nothing kept */ }
}

const nowCss = css`
    .hintrow { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
    .io .hd .k { font-weight: 600; }
    .io .hd .v { font-weight: 600; }
    .v .late { color: var(--n-bad); }
    .tile.ring { display: flex; align-items: center; gap: 10px; cursor: pointer; }
    .ebar:focus-visible { outline: 2px solid var(--n-accent); outline-offset: 4px; border-radius: 8px; }
    .fc { display: inline-flex; flex-wrap: wrap; gap: 2px 8px; }
    .fc span { white-space: nowrap; }
`;

class SEMNextNowCard extends SEMNextBase {
    static get styles() { return [nextCss, nowCss]; }
    static get properties() {
        return { _house: { state: true }, _io: { state: true }, _hint: { state: true }, _hist: { state: true }, _fc: { state: true }, _tick: { state: true } };
    }

    constructor() {
        super();
        this._io = readLocal(IO_KEY) !== '0';
        this._house = false;
        this._hint = readLocal(HINT_KEY) !== '1';
        this._hist = null;
        this._histAt = 0;
        this._fc = [];
        this._fcAt = 0;
        this._fcId = null;
        this._wid = null;
        this._tick = Date.now();
        this._timer = null;
    }

    connectedCallback() {
        super.connectedCallback();
        this._timer = setInterval(() => { this._tick = Date.now(); }, TICK_MS);
    }

    disconnectedCallback() {
        if (this._timer) { clearInterval(this._timer); this._timer = null; }
        super.disconnectedCallback();
    }

    _watchIds() {
        const per = [];
        for (const cid of this._chargers) {
            per.push(`sensor.sem_charger_${cid}_power`, `sensor.sem_charger_${cid}_commanded_current`,
                     `sensor.sem_charger_${cid}_daily_energy`, `sensor.sem_charger_${cid}_session_solar_share`,
                     `number.sem_charger_${cid}_daily_ev_target`, `time.sem_charger_${cid}_target_time`,
                     `sensor.sem_charger_${cid}_vehicle_soc`, `number.sem_charger_${cid}_target_soc`,
                     `select.sem_charger_${cid}_ev_target_type`, `number.sem_charger_${cid}_ev_battery_capacity_kwh`);
        }
        const wid = this._weatherId();
        return [...super._watchIds(), ...IDS, ...per, ...(wid ? [wid] : [])];
    }

    updated(changed) {
        super.updated(changed);
        this._fetchHist();
        this._fetchForecast(this._weatherId());
    }

    // ── the lead ──

    /** The first charger with a car, as the lead's car fact. */
    _carFact() {
        for (const cid of this._chargers) {
            const powerW = this._powerW(`sensor.sem_charger_${cid}_power`);
            const amps = this._num(`sensor.sem_charger_${cid}_commanded_current`);
            const remaining = this._remainingKwh(cid);
            const present = powerW !== null && (powerW > 50 || (remaining !== null && remaining > 0.1));
            if (!present) continue;
            return { present: true, charging: powerW > 50, powerW, amps, remainingKwh: remaining,
                     targetTime: (this._str(`time.sem_charger_${cid}_target_time`) || '').slice(0, 5), cid };
        }
        return null;
    }

    _remainingKwh(cid) {
        const type = this._str(`select.sem_charger_${cid}_ev_target_type`) || 'kwh';
        if (type === 'soc') {
            const soc = this._num(`sensor.sem_charger_${cid}_vehicle_soc`);
            const target = this._num(`number.sem_charger_${cid}_target_soc`);
            const cap = this._num(`number.sem_charger_${cid}_ev_battery_capacity_kwh`);
            if (soc === null || target === null || cap === null) return null;
            return Math.max(0, (target - soc) / 100 * cap);
        }
        const target = this._num(`number.sem_charger_${cid}_daily_ev_target`);
        const done = this._num(`sensor.sem_charger_${cid}_daily_energy`);
        if (target === null || done === null) return null;
        return Math.max(0, target - done);
    }

    _lead() {
        const soc = this._num('sensor.sem_battery_soc');
        const f = {
            night: this._night(), observer: this._observer(),
            solarW: this._powerW('sensor.sem_solar_power'), gridW: this._powerW('sensor.sem_grid_power'),
            batteryW: this._powerW('sensor.sem_battery_power'),
            car: this._carFact(),
            battery: soc === null ? null : { soc, floorPct: this._spending() ? this._num('sensor.sem_battery_dynamic_floor_pct') : null,
                                             bufferPct: this._num('number.sem_battery_buffer_soc') },
            sunAt: this._str('sensor.sem_night_end_time'), nightStart: this._str('sensor.sem_night_start_time'),
        };
        const r = nowLead(f);
        const main = (r.prefix ? this._t(r.prefix) + ' ' : '') + this._tf(r.main.key, r.main.params);
        const parts = [];
        const b = this._nextBlock();
        if (b) parts.push(this._tf('next_sub_next_block', { who: b.who, time: b.time, kwh: b.kwh }));
        const floor = this._spending() ? this._num('sensor.sem_battery_dynamic_floor_pct') : null;
        if (floor !== null) parts.push(this._tf('next_why_batt_floor_short', { floor: Math.round(floor) }));
        else if (soc !== null && this._holding()) parts.push(this._t('next_batt_holds_house'));
        const sub = parts.length ? parts.join(' ') : (r.sub ? this._tf(r.sub.key, r.sub.params) : '');
        return { main, sub };
    }

    /** Tonight's floor is a limit only while SEM spends the battery; while it holds,
     *  the battery serves the house and lends nothing to the car. */
    _spendPhase() { return String(this._attrs('sensor.sem_battery_spendable_kwh').phase || ''); }
    _spending() { return this._spendPhase() === 'spending'; }
    _holding() { return this._spendPhase() === 'holding'; }

    // ── plan and device readers ──

    _planBlocks() {
        const plan = this._attrs('sensor.sem_energy_plan');
        return Array.isArray(plan.blocks) ? plan.blocks : [];
    }

    /** The first planned block that has not started, or null. */
    _nextBlock(pick = null) {
        const now = Date.now();
        const blocks = this._planBlocks()
            .filter((b) => Date.parse(b.start) > now && (!pick || pick(String(b.id))))
            .sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
        if (!blocks.length) return null;
        const b = blocks[0];
        const s = Date.parse(b.start), e = Date.parse(b.end);
        const kwh = Number.isFinite(e) && e > s ? (Number(b.power_w) || 0) * (e - s) / 3.6e9 : 0;
        return { id: String(b.id), who: this._whoName(String(b.id)), time: this._hhmm(b.start), kwh: this._fmt(kwh, 1), start: s };
    }

    /** A plan id as a name: the charger's, the battery's, or the load's. */
    _whoName(id) {
        if (id.startsWith('ev:')) return this._chargerName(id.slice(3));
        if (id.startsWith('battery')) return this._t('next_src_battery');
        const lid = id.replace(/^load:/, '');
        const dev = this._devices().find((d) => d.id === lid);
        return dev?.name || lid;
    }

    /** Every entry of the devices map as [{id, ...}]. */
    _devices() {
        const raw = this._attrs('sensor.sem_controllable_devices_count').devices;
        if (!raw || typeof raw !== 'object') return [];
        if (Array.isArray(raw)) return raw.filter((d) => d && typeof d === 'object').map((d) => ({ id: String(d.id || d.device_id || ''), ...d }));
        return Object.entries(raw).filter(([, d]) => d && typeof d === 'object').map(([id, d]) => ({ id, ...d }));
    }

    _loads() {
        return this._devices().filter((d) => d.device_type !== 'ev_charger' && d.device_type !== 'battery');
    }

    // ── history (sparklines) and the weather forecast ──

    async _fetchHist() {
        if (!this._hass || typeof this._hass.callWS !== 'function') return;
        const ids = HIST_IDS.filter((id) => this._has(id));
        if (!ids.length) return;
        const now = Date.now();
        if (now - this._histAt < HIST_EVERY_MS) return;
        this._histAt = now;
        const start = new Date(); start.setHours(0, 0, 0, 0);
        const msg = { type: 'recorder/statistics_during_period', start_time: start.toISOString(), end_time: new Date().toISOString(),
                      statistic_ids: ids, period: 'hour', types: ['mean'], units: { power: 'W' } };
        let stats = null;
        try { stats = await this._hass.callWS(msg); }
        catch (e1) {
            try { stats = await this._hass.callWS({ ...msg, type: 'history/statistics_during_period', units: msg.units }); }
            catch (e2) { stats = null; }
        }
        if (!stats || typeof stats !== 'object') return;
        const out = {};
        for (const id of ids) out[id] = (stats[id] || []).map((p) => Number(p.mean ?? p.state ?? 0));
        this._hist = out;
    }

    /** A weather entity with a real temperature, never a forecast_* subentity (classic #516). */
    _weatherId() {
        const states = this._hass?.states;
        if (!states) return null;
        const ok = (id) => {
            const s = states[id];
            return !!s && s.state !== 'unavailable' && s.state !== 'unknown' && s.attributes && s.attributes.temperature != null;
        };
        if (this._wid && ok(this._wid)) return this._wid;
        const usable = Object.keys(states).filter((id) => id.startsWith('weather.') && ok(id));
        const real = usable.filter((id) => !id.startsWith('weather.forecast_'));
        this._wid = real[0] || usable[0] || null;
        return this._wid;
    }

    async _fetchForecast(id) {
        if (!id || !this._hass || typeof this._hass.callWS !== 'function') return;
        const now = Date.now();
        if (this._fcId === id && now - this._fcAt < FORECAST_EVERY_MS) return;
        this._fcAt = now; this._fcId = id;
        let list = null;
        try {
            const r = await this._hass.callWS({ type: 'call_service', domain: 'weather', service: 'get_forecasts',
                                                service_data: { type: 'daily' }, target: { entity_id: id }, return_response: true });
            list = r?.response?.[id]?.forecast;
        } catch (e) { list = null; }
        if (!Array.isArray(list)) list = this._attrs(id).forecast;
        this._fc = Array.isArray(list) ? list : [];
    }

    // ── sections ──

    _hintBox() {
        if (!this._hint) return nothing;
        const dismiss = () => { this._hint = false; writeLocal(HINT_KEY, '1'); };
        return html`<div class="card flat span2 hintrow"><span class="sm muted">${this._t('next_hint_first')}</span>
            ${this._btn(this._t('next_hint_ok'), dismiss, { small: true })}</div>`;
    }

    _updatedPill() {
        const lu = newestUpdate(this._hass?.states);
        const ago = this._ago(lu, this._tick);
        return ago ? this._pill(this._tf('next_updated_ago', { ago })) : nothing;
    }

    _powerNow() {
        const bar = powerBar({
            solarW: this._powerW('sensor.sem_solar_power'), gridW: this._powerW('sensor.sem_grid_power'),
            batteryW: this._powerW('sensor.sem_battery_power'), homeW: this._powerW('sensor.sem_home_consumption_power'),
            evW: this._powerW('sensor.sem_ev_power'),
        });
        if (!bar.sources.length && !bar.sinks.length && !bar.idle) return html`<p class="help">${this._t('next_lead_unknown')}</p>`;
        if (bar.idle) return html`<p class="help">${this._t('next_bar_idle')}</p>${this._io ? this._ioList(bar) : nothing}`;
        const mk = (s) => html`<div class="mk" style="--c:${META[s.key].color};flex:${s.w} 1 0">${this._icon(META[s.key].icon)}${s.label ? html`<span>${this._kw(s.w)}</span>` : nothing}</div>`;
        const sg = (s) => html`<div class="sg ${META[s.key].dark ? 'dark' : ''}" style="flex:${s.w} 1 0;background:${META[s.key].color}">${s.label ? this._kw(s.w) : ''}</div>`;
        const toggle = () => { this._io = !this._io; writeLocal(IO_KEY, this._io ? '1' : '0'); };
        const self = this._num('sensor.sem_self_consumption_rate');
        return html`
            <div class="ebar" role="button" tabindex="0" aria-expanded="${this._io}" aria-label="${this._t('next_bar_aria')}"
                 @click=${toggle} @keydown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } }}>
                <div class="lane top">${bar.sources.map(mk)}</div>
                <div class="bar">${bar.sources.map(sg)}</div>
                <div class="lane bot">${bar.sinks.map(mk)}</div>
            </div>
            <p class="help" style="margin-top:8px">${this._io ? this._t('next_bar_fold') : this._t('next_bar_unfold')}${self === null ? '' : ' · ' + this._tf('next_self_use_pct', { pct: Math.round(self) })} · ${this._t('next_tap_row_history')}</p>
            ${this._io ? this._ioList(bar) : nothing}`;
    }

    /** The three loads drawing most right now (chargers and the battery have their own rows). */
    _topConsumers() {
        const devices = this._attrs('sensor.sem_controllable_devices_count').devices || {};
        const list = [];
        for (const [id, d] of Object.entries(devices)) {
            if (!d || d.device_type === 'battery' || d.device_type === 'ev_charger') continue;
            // Same read as the classic Home tab: the load's own power entity, else the figure SEM holds.
            const pe = d.power_entity && this._has(d.power_entity) ? d.power_entity : null;
            const w = pe ? this._powerW(pe) : (Number(d.current_power) || 0);
            list.push({ id, name: d.name || id, w, entity: pe });
        }
        list.sort((a, b) => (b.w ?? -1) - (a.w ?? -1));
        const top = list.slice(0, 3);
        if (!top.length) return html`<p class="help" style="margin:4px 0 8px">${this._t('next_no_loads')}</p>`;
        return html`<div style="margin:0 0 6px 12px;border-left:2px solid ${C.home};padding-left:8px">
            <div class="lbl" style="margin-top:6px">${this._t('next_top_title')}</div>
            ${top.map((d, i) => this._row('mdi:numeric-' + (i + 1) + '-circle-outline', d.name, d.w === null ? '—' : this._kw(d.w), '',
                { color: C.home, onClick: d.entity ? () => this._moreInfo(d.entity) : null }))}</div>`;
    }

    /** One row per source and sink: kW now, the daily kWh and one more fact. */
    _ioList(bar) {
        const kwhToday = (id) => { const v = this._num(id); return v === null ? '' : this._tf('next_kwh_today', { kwh: this._fmt(v, 1) }); };
        const sub = (...parts) => parts.filter(Boolean).join(' · ');
        const row = (key, text, w, subText, entity) => this._row(META[key].icon, text, w === null ? '—' : this._kw(w), subText,
            { color: META[key].color, onClick: entity ? () => this._moreInfo(entity) : null });
        const posOf = (id) => { const v = this._powerW(id); return v === null ? null : Math.max(0, v); };
        const negOf = (id) => { const v = this._powerW(id); return v === null ? null : Math.max(0, -v); };
        const ins = [], outs = [];
        if (this._has('sensor.sem_solar_power')) {
            const solar = this._num('sensor.sem_daily_solar_energy'), fc = this._num('sensor.sem_forecast_today_kwh');
            const pct = (solar !== null && fc !== null && fc > 0) ? this._tf('next_pct_forecast', { pct: Math.round(solar / fc * 100) }) : '';
            ins.push(row('solar', this._t('next_src_solar'), posOf('sensor.sem_solar_power'), sub(kwhToday('sensor.sem_daily_solar_energy'), pct), 'sensor.sem_solar_power'));
        }
        if (this._has('sensor.sem_battery_power')) {
            ins.push(row('battery_out', this._t('next_battery_out'), negOf('sensor.sem_battery_power'), kwhToday('sensor.sem_daily_battery_discharge_energy'), 'sensor.sem_battery_power'));
        }
        if (this._has('sensor.sem_grid_power')) {
            const cost = this._num('sensor.sem_daily_costs');
            ins.push(row('grid_in', this._t('next_grid_import'), negOf('sensor.sem_grid_power'), sub(kwhToday('sensor.sem_daily_grid_import_energy'), cost === null ? '' : this._money(cost)), 'sensor.sem_grid_power'));
        }
        if (this._has('sensor.sem_home_consumption_power')) {
            const hw = posOf('sensor.sem_home_consumption_power');
            // The number opens the history chart as before; the rest of the row opens the top 3.
            const hv = html`<button type="button" class="val" @click=${(e) => { e.stopPropagation(); this._moreInfo('sensor.sem_home_consumption_power'); }}>${hw === null ? '—' : this._kw(hw)}</button>`;
            const hr = this._row(META.home.icon, this._t('next_src_house'), hv,
                sub(kwhToday('sensor.sem_daily_home_energy'), this._t(this._house ? 'next_top_fold' : 'next_top_unfold')),
                { color: META.home.color, onClick: () => { this._house = !this._house; } });
            outs.push(hr);
            if (this._house) outs.push(this._topConsumers());
        }
        if (this._chargers.length) {
            for (const cid of this._chargers) {
                const pid = `sensor.sem_charger_${cid}_power`;
                const share = this._num(`sensor.sem_charger_${cid}_session_solar_share`);
                outs.push(row('ev', this._tf('next_car_of', { name: this._chargerName(cid) }), posOf(pid),
                    sub(kwhToday(`sensor.sem_charger_${cid}_daily_energy`), share === null ? '' : this._tf('next_pct_sun', { pct: Math.round(share) })), pid));
            }
        } else if (this._has('sensor.sem_ev_power')) {
            outs.push(row('ev', this._t('next_src_car'), posOf('sensor.sem_ev_power'), kwhToday('sensor.sem_daily_ev_energy'), 'sensor.sem_ev_power'));
        }
        if (this._has('sensor.sem_battery_power')) {
            outs.push(row('battery_in', this._t('next_battery_in'), posOf('sensor.sem_battery_power'), kwhToday('sensor.sem_daily_battery_charge_energy'), 'sensor.sem_battery_power'));
        }
        if (this._has('sensor.sem_grid_power')) {
            const rev = this._num('sensor.sem_daily_export_revenue');
            outs.push(row('grid_out', this._t('next_grid_export'), posOf('sensor.sem_grid_power'), sub(kwhToday('sensor.sem_daily_grid_export_energy'), rev === null ? '' : this._money(rev)), 'sensor.sem_grid_power'));
        }
        const head = (label, w) => html`<div class="row hd"><div class="k">${label}</div><div class="v">${this._kw(w)}</div></div>`;
        return html`<div class="io">
            <div class="rows">${head(this._t('next_in_title'), bar.inW)}${ins}</div>
            <div class="rows">${head(this._t('next_out_title'), bar.outW)}${outs}</div>
        </div>`;
    }

    _todayTiles() {
        const solar = this._num('sensor.sem_daily_solar_energy'), fc = this._num('sensor.sem_forecast_today_kwh');
        const home = this._num('sensor.sem_daily_home_energy'), ev = this._num('sensor.sem_daily_ev_energy');
        const imp = this._num('sensor.sem_daily_grid_import_energy'), exp = this._num('sensor.sem_daily_grid_export_energy');
        const spark = (id, color, conv) => {
            const v = this._hist?.[id];
            return v && v.length >= 2 ? this._spark(conv ? v.map(conv) : v, color, 120, 22) : nothing;
        };
        const items = [];
        if (solar !== null) {
            items.push({ label: this._t('next_src_solar'), value: this._fmt(solar, 1), unit: 'kWh', color: C.solar,
                sub: (fc !== null && fc > 0) ? this._tf('next_of_forecast', { pct: Math.round(solar / fc * 100), kwh: this._fmt(fc, 1) }) : '',
                extra: spark('sensor.sem_solar_power', C.solar) });
        }
        if (home !== null) {
            const fromSun = this._num('sensor.sem_flow_solar_to_home_energy');
            items.push({ label: this._t('next_src_house'), value: this._fmt(home, 1), unit: 'kWh', color: C.home,
                sub: fromSun === null ? '' : this._tf('next_kwh_from_sun', { kwh: this._fmt(fromSun, 1) }),
                extra: spark('sensor.sem_home_consumption_power', C.home) });
        }
        if (ev !== null) {
            const pct = this._num('sensor.sem_energy_ev_solar_percentage');
            items.push({ label: this._t('next_src_car'), value: this._fmt(ev, 1), unit: 'kWh', color: C.ev,
                sub: pct === null ? '' : this._tf('next_pct_from_sun', { pct: Math.round(pct) }),
                extra: spark('sensor.sem_ev_power', C.ev) });
        }
        if (imp !== null) {
            const rev = this._num('sensor.sem_daily_export_revenue');
            const outText = exp === null ? '' : (rev === null ? `${this._fmt(exp, 1)} ${this._t('next_out')}` : this._tf('next_grid_out_earned', { kwh: this._fmt(exp, 1), money: this._money(rev) }));
            items.push({ label: this._t('next_src_grid'), value: this._fmt(imp, 1), unit: this._t('next_kwh_in'), color: C.grid,
                sub: outText, extra: spark('sensor.sem_grid_power', C.grid, (w) => Math.max(0, -w)) });
        }
        const self = this._num('sensor.sem_self_consumption_rate'), aut = this._num('sensor.sem_autarky_rate');
        if (!items.length && self === null && aut === null) return nothing;
        const ring = (id, pct, color, label, subKey) => html`<div class="tile ring" role="button" tabindex="0" @click=${() => this._moreInfo(id)}
            @keydown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._moreInfo(id); } }}>
            ${this._ring(pct, color, 52, label)}<div><span class="lbl">${label}</span><div class="xs dim">${this._t(subKey)}</div></div></div>`;
        const rings = (self === null && aut === null) ? nothing : html`<div class="tiles" style="margin-top:8px">
            ${self === null ? nothing : ring('sensor.sem_self_consumption_rate', self, C.solar, this._t('next_self_use'), 'next_self_use_sub')}
            ${aut === null ? nothing : ring('sensor.sem_autarky_rate', aut, C.home, this._t('next_own_supply'), 'next_own_supply_sub')}
        </div>`;
        return this._sec(this._t('next_today'), html`${items.length ? this._tiles(items) : nothing}${rings}`);
    }

    _todayList() {
        if (!this._has('sensor.sem_charging_state')) return nothing;
        const rows = todayRows(this._attrs('sensor.sem_charging_state'), { now: this._tick });
        const lang = this._hass?.language || 'en';
        const when = (r) => {
            const t = this._hhmm(new Date(r.when));
            if (r.day === 1) return `${this._t('tomorrow')} ${t}`;
            if (r.day >= 2) return `${new Date(r.when).toLocaleDateString(lang, { weekday: 'short' })} ${t}`;
            return t;
        };
        const body = rows.length
            ? html`<div class="rows">${rows.map((r) => this._row(r.icon, this._tf(r.label === 'plan_battery_empty' ? 'next_battery_reserve_reached' : r.label, r.values),
                r.late ? html`<span class="late">${when(r)}</span>` : when(r),
                r.detail ? this._tf(r.detail, r.values) : '', { color: C[r.color] || C.home }))}</div>`
            : html`<p class="help">${this._t('next_nothing_planned')}</p>`;
        return this._sec(this._t('next_today'), body, { extra: this._link(this._t('next_plan_link'), () => this._go('/sem-next/plan')) });
    }

    _why() {
        const rows = [];
        const strat = this._hass?.states['sensor.sem_charging_strategy'];
        if (strat && strat.state && strat.state !== 'unavailable' && strat.state !== 'unknown') {
            const reason = String(strat.attributes?.reason || strat.state);
            const { mode, head, detail } = splitStrategyReason(reason);
            const label = mode ? this._t('charge_mode_' + mode) : '';
            const title = label && label !== 'charge_mode_' + mode ? label : head;
            const said = plainReason({ reason_code: strat.attributes?.reason_code, params: strat.attributes?.reason_params }, (k) => this._t(k));
            const evW = this._powerW('sensor.sem_ev_power');
            rows.push(this._row('mdi:car-electric', title, evW === null ? '' : this._kw(evW), this._all ? reason : (said || detail), { color: C.ev }));
        }
        const soc = this._num('sensor.sem_battery_soc');
        const floor = this._spending() ? this._num('sensor.sem_battery_dynamic_floor_pct') : null;
        const holding = this._holding();
        const prio = this._num('number.sem_battery_priority_soc');
        const batt = this._powerW('sensor.sem_battery_power');
        if (soc !== null) {
            const title = batt !== null && batt < -50 ? this._t('next_why_batt_house')
                : (batt !== null && batt > 50 ? this._t('next_why_batt_charging') : this._t('next_why_batt_rest'));
            const parts = [];
            if (holding) parts.push(this._t('next_batt_holds_house'));
            else if (floor !== null && soc < floor) parts.push(this._tf('next_why_batt_floor', { soc: Math.round(soc), floor: Math.round(floor) }));
            else if (prio !== null) parts.push(this._tf(soc >= prio ? 'next_why_batt_above_prio' : 'next_why_batt_below_prio', { soc: Math.round(soc), prio: Math.round(prio) }));
            else parts.push(this._tf('next_sub_battery_at', { soc: Math.round(soc) }));
            if (!holding && this._str('switch.sem_battery_may_assist_ev') === 'on' && !(floor !== null && soc < floor)) parts.push(this._t('next_why_batt_assist'));
            rows.push(this._row('mdi:battery-charging', title, batt === null ? `${Math.round(soc)} %` : this._kw(Math.abs(batt)), parts.join(' '), { color: batt !== null && batt > 50 ? C.battery_in : C.battery_out }));
        }
        const peak = this._num('sensor.sem_consecutive_peak_15min');
        const limit = this._hass?.states['sensor.sem_target_peak_limit'];
        const grid = this._powerW('sensor.sem_grid_power');
        if (grid !== null) {
            const title = grid < -50 ? this._t('next_grid_import') : (grid > 50 ? this._t('next_grid_export') : this._t('next_why_grid_quiet'));
            const text = peak === null ? '' : (limit && !isUncapped(limit) && Number.isFinite(parseFloat(limit.state))
                ? this._tf('next_why_peak', { kw: this._fmt(peak, 1), limit: this._fmt(parseFloat(limit.state), 1) })
                : this._tf('next_why_peak_nolimit', { kw: this._fmt(peak, 1) }));
            rows.push(this._row('mdi:transmission-tower', title, this._kw(Math.abs(grid)), text, { color: grid > 50 ? C.export : C.grid }));
        }
        for (const d of this._loads()) {
            const name = d.name || d.id;
            if (d.is_shed) {
                rows.push(this._row('mdi:power-plug-off', this._tf('next_why_load_held', { name }), '', this._t(shedReasonKey(d.shed_reason)), { color: C.home }));
            } else if (d.blocked_by) {
                const parent = this._devices().find((x) => x.id === String(d.blocked_by));
                rows.push(this._row('mdi:power-plug', this._tf('next_why_load_waits', { name }), '', this._tf('next_waits_for', { name: parent?.name || String(d.blocked_by) }), { color: C.home }));
            } else {
                const b = this._nextBlock((id) => id === `load:${d.id}`);
                if (b) {
                    const demand = (this._attrs('sensor.sem_energy_plan').demands || []).find((x) => x && x.id === `load:${d.id}`);
                    rows.push(this._row('mdi:power-plug', this._tf('next_why_load_waits', { name }), b.time, demand?.note ? String(demand.note) : '', { color: C.home }));
                }
            }
        }
        if (!rows.length) return nothing;
        return this._sec(this._t('next_why_now'), html`<div class="rows">${rows}</div>`,
            { extra: this._link(this._t('next_decisions_link'), () => this._go('/sem-next/plan')) });
    }

    /** Named apart from the base's _money(v) formatter, which the tiles use. */
    _moneySec() {
        const both = (a, b) => (a === null && b === null ? null : (a || 0) + (b || 0));
        const cost = this._num('sensor.sem_daily_costs');
        const saved = both(this._num('sensor.sem_daily_savings'), this._num('sensor.sem_daily_battery_savings'));
        const mcost = this._num('sensor.sem_monthly_costs');
        const msaved = both(this._num('sensor.sem_monthly_savings'), this._num('sensor.sem_monthly_battery_savings'));
        const rateEntity = this._hass?.states['sensor.sem_tariff_current_import_rate'];
        const imp = this._num('sensor.sem_tariff_current_import_rate'), exp = this._num('sensor.sem_tariff_current_export_rate');
        const level = this._str('sensor.sem_tariff_price_level') || String(rateEntity?.attributes?.price_level || '');
        const a = rateEntity?.attributes || {};
        const flat = !level || isAbsence(level) || a.is_dynamic === false;
        if (cost === null && saved === null && mcost === null && imp === null) return nothing;
        const cur = this._currency();
        const tiles = [];
        if (cost !== null) tiles.push({ label: this._t('next_today'), value: this._fmt(cost, 2), unit: cur, sub: this._t('next_bought') });
        if (saved !== null) tiles.push({ label: this._t('next_saved'), value: this._fmt(saved, 2), unit: cur, valueColor: C.good, sub: this._t('next_sun_and_battery') });
        if (mcost !== null) tiles.push({ label: this._t('next_period_month'), value: mcost >= 100 ? String(Math.round(mcost)) : this._fmt(mcost, 2), unit: cur,
            sub: msaved === null ? '' : this._tf('next_saved_month', { money: this._money(msaved) }) });
        const sum = [];
        if (imp !== null && !flat) {
            sum.push(html`<span>${this._t('next_price_now')} <b>${this._fmt(imp, 2)}</b> · ${this._t(priceLevelKey(level))}</span>`);
            const start = a.next_cheap_start ? this._hhmm(a.next_cheap_start) : '';
            if (start) {
                const t0 = Date.parse(a.next_cheap_start);
                const pt = (Array.isArray(a.upcoming) ? a.upcoming : []).find((p) => p && Date.parse(p.t) === t0);
                const price = pt && Number.isFinite(Number(pt.price)) ? ` · ${this._fmt(Number(pt.price), 2)}` : '';
                sum.push(html`<span>${this._t('next_next_cheap')} <b>${start}</b>${price}</span>`);
            }
        } else if (imp !== null) {
            sum.push(html`<span>${this._t('next_price_now')} <b>${this._fmt(imp, 2)}</b> · ${this._t('next_one_rate')}</span>`);
        }
        if (exp !== null) sum.push(html`<span>${this._t('next_export')} <b>${this._fmt(exp, 2)}</b></span>`);
        return this._sec(this._t('next_money'), html`${tiles.length ? this._tiles(tiles, { three: tiles.length === 3 }) : nothing}
            ${sum.length ? html`<div class="sumrow">${sum}</div>` : nothing}`,
            { extra: this._link(this._t('next_insights_link'), () => this._go('/sem-next/insights')) });
    }

    _signals() {
        const rows = [];
        const tip = this._str('sensor.sem_energy_tip');
        if (tip) rows.push(this._row('mdi:lightbulb-outline', this._t('next_tip'), '', tip, { onClick: () => this._moreInfo('sensor.sem_energy_tip') }));
        const win = this._str('sensor.sem_best_surplus_window');
        const rem = this._num('sensor.sem_forecast_remaining_today_kwh');
        // The window is today's: once no sun is left today it has passed.
        if (win && !(rem !== null && rem < 0.05)) {
            rows.push(this._row('mdi:weather-sunset', this._t('next_best_surplus'), win, rem === null ? '' : this._tf('next_kwh_remaining', { kwh: this._fmt(rem, 1) }),
                { color: C.solar, onClick: () => this._moreInfo('sensor.sem_best_surplus_window') }));
        }
        const peak = this._num('sensor.sem_consecutive_peak_15min');
        if (peak !== null) {
            const limit = this._hass?.states['sensor.sem_target_peak_limit'];
            // %, margin and "x of y" all on the 15-minute average.
            const lim = limit && !isUncapped(limit) ? parseFloat(limit.state) : NaN;
            const pct = Number.isFinite(lim) && lim > 0 ? peak / lim * 100 : null;
            const margin = Number.isFinite(lim) ? Math.max(0, lim - peak) : null;
            const value = limit ? this._tf('next_of_limit', { kw: this._fmt(peak, 1), limit: peakLimitText(limit, this._t('uncapped')) }) : `${this._fmt(peak, 1)} kW`;
            const sub = (pct === null || isUncapped(limit)) ? '' : (margin === null ? this._pct(pct) : this._tf('next_pct_margin', { pct: Math.round(pct), kw: this._fmt(margin, 1) }));
            rows.push(this._row('mdi:speedometer', this._t('next_peak_quarter'), pct !== null && pct > 90 ? html`<span class="bad">${value}</span>` : value, sub,
                { onClick: () => this._moreInfo('sensor.sem_consecutive_peak_15min') }));
        }
        const co2 = this._num('sensor.sem_daily_co2_avoided');
        if (co2 !== null) {
            const life = this._num('sensor.sem_lifetime_co2_avoided'), trees = this._num('sensor.sem_lifetime_trees_equivalent');
            const unit = this._kgUnit('daily_co2_avoided');
            const lifeText = life === null ? '' : `${life >= 100 ? Math.round(life) : this._fmt(life, 1)} ${this._kgUnit('lifetime_co2_avoided')}`;
            const sub = life === null ? '' : (trees === null ? this._tf('next_co2_sub_notrees', { life: lifeText })
                : this._tf('next_co2_sub', { life: lifeText, trees: Math.round(trees) }));
            rows.push(this._row('mdi:leaf', this._t('next_co2_avoided'), `${this._fmt(co2, 1)} ${unit}`, sub, { color: C.ev, onClick: () => this._moreInfo('sensor.sem_daily_co2_avoided') }));
        }
        const score = this._num('sensor.sem_energy_optimization_score');
        if (score !== null) rows.push(this._row('mdi:star-outline', this._t('next_score'), String(Math.round(score)), this._t('next_score_sub'), { onClick: () => this._moreInfo('sensor.sem_energy_optimization_score') }));
        const wid = this._weatherId();
        if (wid) rows.push(this._weatherRow(wid));
        if (!rows.length) return nothing;
        return this._sec(this._t('next_signals'), html`<div class="rows">${rows}</div>`);
    }

    _weatherRow(id) {
        const a = this._attrs(id);
        const cond = WEATHER[this._str(id)] || null;
        const unit = a.temperature_unit || '°C';
        const temp = a.temperature != null ? `${Math.round(a.temperature)} ${unit}` : '';
        const value = [temp, cond ? this._t(cond.key) : ''].filter(Boolean).join(' · ');
        const lang = this._hass?.language || 'en';
        const today = new Date().toDateString();
        const days = (this._fc || []).filter((f) => f && f.datetime && new Date(f.datetime).toDateString() !== today).slice(0, 4);
        const sub = days.length ? html`<span class="fc">${days.map((f) => {
            const c = WEATHER[f.condition] || null;
            const t = f.temperature != null ? `${Math.round(f.temperature)} °` : '';
            return html`<span>${new Date(f.datetime).toLocaleDateString(lang, { weekday: 'short' })} ${t}${c ? this._icon(c.icon, 's') : nothing}</span>`;
        })}</span>` : '';
        return this._row(cond ? cond.icon : 'mdi:weather-partly-cloudy', this._t('next_weather'), value, sub, { onClick: () => this._moreInfo(id) });
    }

    render() {
        if (!this._hass) return nothing;
        const lead = this._lead();
        return this._frame(lead, html`<div class="grid">
            ${this._hintBox()}
            ${this._sec(this._t('next_power_now'), this._powerNow(), { cls: 'span2', extra: this._updatedPill() })}
            ${this._todayTiles()}
            ${this._todayList()}
            ${this._why()}
            ${this._moneySec()}
            ${this._signals()}
        </div>`);
    }
}

semDefineCard('sem-next-now-card', SEMNextNowCard, {
    type: 'sem-next-now-card',
    name: 'SEM · Now',
    description: 'What SEM does right now and why: power bar, today, reasons, money, signals',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-now-card',
    preview: true,
});
