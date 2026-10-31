/**
 * SEM Simulation Card (#1083)
 *
 * The Simulation tab: pick a period (the last 30 / 90 / 365 days, a month,
 * or the most recent days), change a few values (battery size, power and
 * reserve, peak limit, prices, solar size, battery mode, the car's charge
 * mode and whether the battery may help the car) or tap a scenario, replay
 * the period on your own Home Assistant and see the cost per day, per day
 * type and per month. A battery carries its charge from one day to the
 * next, so a run is always one continuous period; the day types filter the
 * result afterwards. Every simulated number is marked "est.": after a
 * changed decision the flows come from the energy balance, not from a meter.
 *
 * Talks only over the websocket commands
 * `solar_energy_management/simulation/{days,defaults,start,status,cancel,result,xlsx}`.
 * Polls `status` every 2 s while a run is running, and only then.
 *
 * Config:
 *   type: custom:sem-simulation-card
 *   header: true    # the title block with the day counts (default on)
 */

import { SEMLitBase, semGlassCss, html, css, nothing } from '../base/sem-lit-base.js';
import { semGetCurrency, semDefineCard } from '../base/sem-shared.js';
import { downloadBase64 } from '../util/download.js';
import {
    tagGlyphs, PERIOD_PICKS, periodOf, activePeriod, periodDays, monthsOf, monthPeriod, periodGaps,
    recentMax, recentPeriod, recentAt, chipDate, rowDate, money, formatDelta, needsEst,
    visibleRows, filterRows, tagTiles, totalFor, totalLine, dayDetail, monthRows, energyRows,
    initialForm, isChanged, canRun, buildStart, PRESETS, applyPreset, minutesLeft,
    progressShare, fill, calibration, BATTERY_MODES, EV_MODES, SIM_CAPACITY_MAX_KWH,
} from '../util/simulation-rows.js';

const WS = 'solar_energy_management/simulation';
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const POLL_MS = 2000;
const C = '#8353d1';
const TAG_WORD = {
    sunny: 'sim_tag_sunny', mixed: 'sim_tag_mixed', grey: 'sim_tag_grey', car: 'sim_tag_car',
    cheap: 'sim_tag_cheap', negative: 'sim_tag_cheap', gap: 'sim_tag_gap',
};
const PICK_WORD = {
    last30: 'sim_pick_last30', last90: 'sim_pick_last90', last365: 'sim_pick_last365',
};
const PRESET_WORD = (p) => `sim_preset_${p}`;
// SEM's own words for its modes (the battery and charger selects)
const BATTERY_MODE_WORD = (m) => `battery_mode_${m}`;
const EV_MODE_WORD = (m) => (m === 'recorded' ? 'sim_as_recorded_opt' : `charge_mode_${m}`);
const TILE_WORD = {
    sunny: 'sim_tile_sunny', mixed: 'sim_tile_mixed', grey: 'sim_tile_grey',
    car: 'sim_tile_car', cheap: 'sim_tile_cheap',
};

class SEMSimulationCard extends SEMLitBase {
    static get properties() {
        return {
            ...super.properties,
            _days: { state: true },
            _defaults: { state: true },
            _form: { state: true },
            _period: { state: true },
            _status: { state: true },
            _result: { state: true },
            _expanded: { state: true },
            _filter: { state: true },
            _openDay: { state: true },
            _error: { state: true },
        };
    }

    constructor() {
        super();
        this._days = null;          // the `days` answer
        this._defaults = null;      // the `defaults` answer
        this._form = null;          // the what-if values
        this._period = null;        // { from, to } — the period to replay
        this._status = null;        // the `status` answer
        this._result = null;        // the `result` answer
        this._expanded = false;
        this._filter = null;        // a day type the result shows, or null
        this._openDay = null;       // the result row whose details are open
        this._error = null;         // { kind: 'busy'|'failed'|'invalid'|'download', text }
        this._pollTimer = null;
        this._loading = false;
    }

    set hass(hass) {
        const first = !this._hass;
        super.hass = hass;
        if (first && this.isConnected) this._load();
    }

    get hass() {
        return this._hass;
    }

    connectedCallback() {
        super.connectedCallback();
        // HA puts the same card back when you return to the tab: read the
        // run's state again, and poll again if it still runs.
        if (this._hass) this._load();
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        this._stopPolling();
    }

    // ── Websocket ────────────────────────────────────────────────────
    async _ws(cmd, extra = {}) {
        return this._hass.callWS({ type: `${WS}/${cmd}`, ...extra });
    }

    async _load() {
        if (this._loading || !this._hass?.callWS) return;
        this._loading = true;
        try {
            const [days, defaults, status] = await Promise.all([
                this._ws('days').catch(() => null),
                this._ws('defaults').catch(() => null),
                this._ws('status').catch(() => null),
            ]);
            if (days) this._days = days;
            if (defaults) {
                this._defaults = defaults;
                if (!this._form) this._form = initialForm(defaults);
            }
            this._onStatus(status);
            if (!status?.running && !this._result) await this._loadResult();
        } finally {
            this._loading = false;
        }
    }

    _onStatus(status) {
        if (!status) return;
        this._status = status;
        if (status.running) {
            this._schedulePoll();
        } else {
            this._stopPolling();
            if (status.status === 'failed') {
                this._error = { kind: 'failed', text: status.error || '' };
            }
        }
    }

    _schedulePoll() {
        if (this._pollTimer || !this.isConnected) return;
        this._pollTimer = setTimeout(() => this._poll(), POLL_MS);
    }

    _stopPolling() {
        if (this._pollTimer) clearTimeout(this._pollTimer);
        this._pollTimer = null;
    }

    async _poll() {
        this._pollTimer = null;
        if (!this.isConnected || !this._hass?.callWS) return;
        let status = null;
        try {
            status = await this._ws('status');
        } catch (_err) {
            status = null;
        }
        if (!this.isConnected) return;
        if (!status) { this._schedulePoll(); return; }
        const wasRunning = this._status?.running;
        this._onStatus(status);
        if (wasRunning && !status.running) await this._loadResult(status.run_id);
    }

    async _loadResult(runId) {
        try {
            const res = await this._ws('result', runId ? { run_id: runId } : {});
            this._result = res || null;
            this._expanded = false;
            this._filter = null;
            this._openDay = null;
        } catch (_err) {
            // no stored run yet: nothing to show
        }
    }

    async _start() {
        if (!canRun(this._period, this._form, this._status)) return;
        const msg = buildStart(this._period, this._form);
        this._error = null;
        try {
            await this._ws('start', msg);
        } catch (err) {
            const code = err?.code || '';
            this._error = code === 'busy'
                ? { kind: 'busy' }
                : { kind: code === 'invalid' ? 'invalid' : 'failed', text: err?.message || '' };
            // another run is going: follow it
            if (code === 'busy') this._poll();
            return;
        }
        this._status = { running: true, status: 'running', done: 0,
            total: periodDays(this._days?.days, this._period), started_at: new Date().toISOString() };
        this._schedulePoll();
    }

    async _cancel() {
        try {
            await this._ws('cancel');
        } catch (_err) {
            // the next status read says what happened
        }
        this._stopPolling();
        this._poll();
    }

    async _download() {
        try {
            const res = await this._ws('xlsx', this._result?.run_id ? { run_id: this._result.run_id } : {});
            if (res?.base64) {
                downloadBase64(res.filename || 'sem-simulation.xlsx', res.base64, XLSX_MIME);
                if (this._error?.kind === 'download') this._error = null;
            }
        } catch (err) {
            console.warn('SEM: simulation download failed', err);
            this._error = { kind: 'download' };
        }
    }

    // ── Form ─────────────────────────────────────────────────────────
    _setForm(patch) {
        this._form = { ...(this._form || initialForm(this._defaults)), ...patch };
    }

    _pickPeriod(pick) {
        this._period = periodOf(this._days?.days || [], pick);
    }

    _pickMonth(month) {
        if (!month) return;
        this._period = monthPeriod(this._days?.days || [], month);
    }

    _pickRecent(n) {
        this._period = recentPeriod(this._days?.days || [], n);
    }

    _preset(preset) {
        let extra = null;
        if (preset === 'plus_pv') {
            const kwp = !!this._defaults?.system_size_kwp;
            const answer = globalThis.prompt?.(this._t(kwp ? 'sim_preset_pv_ask_kwp' : 'sim_preset_pv_ask_factor'));
            if (answer === null || answer === undefined || String(answer).trim() === '') return;
            extra = Number(String(answer).replace(',', '.'));
            if (!Number.isFinite(extra)) return;
        }
        this._form = applyPreset(this._form, this._defaults, preset, extra);
    }

    _setFilter(tag) {
        this._filter = this._filter === tag ? null : tag;
        this._expanded = false;
        this._openDay = null;
    }

    _toggleDay(date) {
        this._openDay = this._openDay === date ? null : date;
    }

    _currency() {
        return this._result?.currency || this._defaults?.currency || semGetCurrency(this._hass) || '';
    }

    // ── Render ───────────────────────────────────────────────────────
    _est() {
        return html`<em class="est">${this._t('sim_est')}</em>`;
    }

    _tagTitle(tags) {
        return (tags || []).map((t) => (TAG_WORD[t] ? this._t(TAG_WORD[t]) : t)).join(' · ');
    }

    _renderHeader() {
        if (this._config?.header === false) return nothing;
        const d = this._days || {};
        return html`
            <ha-card><div class="header-wrap">
                <div class="icon-ring">
                    <svg viewBox="-34 -34 68 68"><circle r="28" fill="none" stroke="${C}" stroke-width="1.2" opacity=".25"></circle><circle r="24" fill="${C}0F" stroke="${C}" stroke-width="1.5"></circle></svg>
                    <ha-icon icon="mdi:flask-outline"></ha-icon>
                </div>
                <div class="title-area">
                    <div class="tab-title">${this._t('sim_title')}</div>
                    <div class="tab-subtitle">${this._t('sim_sub')}</div>
                </div>
                <div class="stats">
                    <div class="stat"><div class="stat-value">${d.stored ?? '—'}</div><div class="stat-label">${this._t('sim_days_stored')}</div></div>
                    <div class="stat"><div class="stat-value">${periodDays(d.days, this._period)}</div><div class="stat-label">${this._t('sim_in_period')}</div></div>
                    <div class="stat"><div class="stat-value">${d.gaps ?? '—'}</div><div class="stat-label">${this._t('sim_data_gaps')}</div></div>
                </div>
            </div></ha-card>`;
    }

    // One continuous period: a battery carries its charge from day to day,
    // so a run never takes single days.
    _renderPeriod() {
        const days = this._days?.days || [];
        const active = activePeriod(days, this._period);
        const p = this._period;
        const n = periodDays(days, p);
        const g = periodGaps(days, p);
        return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:calendar-range"></ha-icon>${this._t('sim_period')}</div>
                ${days.length ? html`
                    <div class="picks">
                        ${PERIOD_PICKS.map((pick) => html`<span class="chip ${active === pick ? 'on' : ''}" role="button" tabindex="0"
                            @click=${() => this._pickPeriod(pick)}>${this._t(PICK_WORD[pick])}</span>`)}
                        <select class="sel-ctl" aria-label="${this._t('sim_pick_month')}"
                            @change=${(e) => { this._pickMonth(e.target.value); e.target.value = ''; }}>
                            <option value="">${this._t('sim_pick_month')}</option>
                            ${monthsOf(days).map((m) => html`<option value="${m}">${m}</option>`)}
                        </select>
                    </div>
                    ${this._renderRecentSlider(days)}
                    <div class="span">${p ? fill(this._t('sim_period_span'), { from: rowDate(p.from, this._hass?.language || 'en'), to: rowDate(p.to, this._hass?.language || 'en'), n }) : this._t('sim_pick_period_hint')}</div>
                    ${g > 0 ? html`<div class="legend">${fill(this._t('sim_period_gaps'), { n: g })}</div>` : nothing}
                    <div class="legend">${this._t('sim_period_note')}</div>` : html`
                    <div class="legend">${this._days ? this._t('sim_no_days') : this._t('sim_loading')}</div>`}
            </div></ha-card>`;
    }

    // A slider over the newest days: one drag on a phone. It shows where it
    // stands only while the period is exactly the newest N stored days.
    _renderRecentSlider(days) {
        const max = recentMax(days);
        if (max < 2) return nothing;
        const at = recentAt(days, this._period);
        const n = at ?? 0;
        const p = n ? recentPeriod(days, n) : null;
        const span = p ? `${chipDate(p.from)} – ${chipDate(p.to)}` : '';
        return html`
            <div class="recent">
                <label for="sim-recent">${n ? fill(this._t('sim_recent_n'), { n }) : this._t('sim_recent_label')}</label>
                <input id="sim-recent" type="range" min="0" max="${max}" step="1" .value=${String(n)}
                    aria-valuetext="${n ? fill(this._t('sim_recent_n'), { n }) : this._t('sim_recent_label')}"
                    @input=${(e) => this._pickRecent(e.target.value)}>
                <small>${span}</small>
            </div>`;
    }

    _renderNumberRow(field, label, unit, current, max = null) {
        const f = this._form || {};
        const changed = isChanged(field, f, this._defaults);
        return html`
            <div class="ct-row">
                <span class="lbl">${this._t(label)}</span>
                <span class="cur">${current}</span><span class="arrow">→</span>
                <span class="inp ${changed ? 'changed' : ''}"><input type="number" min="0" max="${max ?? nothing}" step="any"
                    .value=${String(f[field] ?? '')}
                    @change=${(e) => this._setForm({ [field]: e.target.value })}><small>${unit}</small></span>
            </div>`;
    }

    _renderRateRow(key, label) {
        const f = this._form || {};
        const mode = f[`${key}_mode`] || 'recorded';
        const field = `${key}_rate`;
        const changed = isChanged(field, f, this._defaults);
        return html`
            <div class="ct-row">
                <span class="lbl">${this._t(label)}</span>
                <span class="cur">${this._t('sim_as_recorded')}</span><span class="arrow">→</span>
                <select class="sel-ctl" .value=${mode}
                    @change=${(e) => this._setForm({ [`${key}_mode`]: e.target.value })}>
                    <option value="recorded" ?selected=${mode === 'recorded'}>${this._t('sim_as_recorded_opt')}</option>
                    <option value="flat" ?selected=${mode === 'flat'}>${this._t('sim_flat')}</option>
                </select>
                ${mode === 'flat' ? html`<span class="inp ${changed ? 'changed' : ''}"><input type="number" step="any"
                    .value=${String(f[field] ?? '')}
                    @change=${(e) => this._setForm({ [field]: e.target.value })}><small>${this._currency()}/kWh</small></span>` : nothing}
            </div>`;
    }

    _renderModeRow(field, label, modes, word, current) {
        const f = this._form || {};
        const val = f[field] || modes[0];
        const changed = isChanged(field, f, this._defaults);
        return html`
            <div class="ct-row">
                <span class="lbl">${this._t(label)}</span>
                <span class="cur">${this._t(word(current))}</span><span class="arrow">→</span>
                <select class="sel-ctl ${changed ? 'changed' : ''}" .value=${val}
                    @change=${(e) => this._setForm({ [field]: e.target.value })}>
                    ${modes.map((m) => html`<option value="${m}" ?selected=${m === val}>${this._t(word(m))}</option>`)}
                </select>
            </div>`;
    }

    // More panels: extra kWp over the install's size, or a factor when the
    // size is not known (the backend turns kWp into the same factor).
    _renderPvRow() {
        const f = this._form || {};
        const d = this._defaults || {};
        const kwp = f.pv_mode === 'kwp' && d.system_size_kwp;
        const changed = isChanged('pv', f, d);
        return html`
            <div class="ct-row">
                <span class="lbl">${this._t('sim_pv')}</span>
                <span class="cur">${d.system_size_kwp ? `${d.system_size_kwp} kWp` : this._t('sim_as_recorded')}</span><span class="arrow">→</span>
                ${d.system_size_kwp ? html`<select class="sel-ctl" .value=${f.pv_mode || 'kwp'}
                    @change=${(e) => this._setForm({ pv_mode: e.target.value })}>
                    <option value="kwp" ?selected=${f.pv_mode === 'kwp'}>${this._t('sim_pv_kwp')}</option>
                    <option value="factor" ?selected=${f.pv_mode !== 'kwp'}>${this._t('sim_pv_factor')}</option>
                </select>` : nothing}
                <span class="inp ${changed ? 'changed' : ''}"><input type="number" min="0" step="any"
                    .value=${String((kwp ? f.pv_extra_kwp : f.pv_factor) ?? '')}
                    @change=${(e) => this._setForm(kwp ? { pv_extra_kwp: e.target.value } : { pv_factor: e.target.value })}><small>${kwp ? 'kWp' : '×'}</small></span>
            </div>`;
    }

    _renderEvAssistRow() {
        const f = this._form || {};
        const d = this._defaults || {};
        const val = f.battery_to_ev === false ? 'no' : 'yes';
        const changed = isChanged('battery_to_ev', f, d);
        return html`
            <div class="ct-row">
                <span class="lbl">${this._t('sim_battery_to_ev')}</span>
                <span class="cur">${this._t(d.battery_to_ev === false ? 'sim_no' : 'sim_yes')}</span><span class="arrow">→</span>
                <select class="sel-ctl ${changed ? 'changed' : ''}" .value=${val}
                    @change=${(e) => this._setForm({ battery_to_ev: e.target.value !== 'no' })}>
                    <option value="yes" ?selected=${val === 'yes'}>${this._t('sim_yes')}</option>
                    <option value="no" ?selected=${val === 'no'}>${this._t('sim_no')}</option>
                </select>
            </div>`;
    }

    _renderWhatIf() {
        const d = this._defaults;
        if (!d) return nothing;
        const peak = d.peak_limit_kw ? `${d.peak_limit_kw} kW` : this._t('sim_none');
        const watts = (w) => (w ? `${w} W` : '—');
        return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:tune-variant"></ha-icon>${this._t('sim_what_if')}</div>
                <div class="picks" aria-label="${this._t('sim_presets')}">
                    <span class="lbl-small">${this._t('sim_presets')}</span>
                    ${PRESETS.map((p) => html`<span class="chip" role="button" tabindex="0"
                        @click=${() => this._preset(p)}>${this._t(PRESET_WORD(p))}</span>`)}
                </div>
                <div class="group">
                    ${this._renderNumberRow('capacity_kwh', 'sim_battery_size', 'kWh', `${d.capacity_kwh ?? '—'} kWh`, SIM_CAPACITY_MAX_KWH)}
                    ${this._renderNumberRow('max_charge_w', 'sim_charge_power', 'W', watts(d.max_charge_w))}
                    ${this._renderNumberRow('max_discharge_w', 'sim_discharge_power', 'W', watts(d.max_discharge_w))}
                    ${this._renderNumberRow('reserve_pct', 'sim_battery_reserve', '%', `${d.reserve_pct ?? '—'} %`)}
                    ${this._renderNumberRow('peak_limit_kw', 'sim_peak_limit', 'kW', peak)}
                    ${this._renderPvRow()}
                    ${this._renderRateRow('import', 'sim_import_price')}
                    ${this._renderRateRow('export', 'sim_export_value')}
                    ${this._renderModeRow('battery_mode', 'sim_battery_mode', BATTERY_MODES, BATTERY_MODE_WORD, d.battery_mode || 'auto')}
                    ${this._renderModeRow('ev_mode', 'sim_ev_mode', EV_MODES, EV_MODE_WORD, 'recorded')}
                    ${this._renderEvAssistRow()}
                </div>
            </div></ha-card>`;
    }

    _renderRun() {
        const st = this._status || {};
        const running = !!st.running;
        const can = canRun(this._period, this._form, st);
        const left = running ? minutesLeft(st) : null;
        const n = periodDays(this._days?.days, this._period);
        let line = '';
        if (running) {
            line = fill(this._t('sim_running'), { x: Math.min((st.done || 0) + 1, st.total || 0), y: st.total || 0 });
            if (left !== null) line += ' · ' + fill(this._t('sim_minutes_left'), { n: left });
        }
        const err = this._error;
        let errLine = '';
        if (err?.kind === 'busy') errLine = this._t('sim_busy');
        else if (err?.kind === 'failed' || err?.kind === 'invalid') {
            errLine = fill(this._t('sim_failed'), { error: err.text || '' });
        }
        return html`
            <ha-card><div class="wrap">
                <div class="runrow">
                    <button class="btn" ?disabled=${!can} @click=${() => this._start()}>
                        <ha-icon icon="mdi:play"></ha-icon>${this._t('sim_run')}</button>
                    <div class="prog">
                        ${running ? html`
                            <div class="bar"><i style="width:${Math.round(progressShare(st) * 100)}%"></i></div>
                            <small>${line}</small>` : html`
                            <small>${n ? fill(this._t('sim_n_days'), { n }) : this._t('sim_pick_period_hint')}</small>`}
                    </div>
                    ${running ? html`<button class="btn sec" @click=${() => this._cancel()}>
                        <ha-icon icon="mdi:stop"></ha-icon>${this._t('sim_stop')}</button>` : nothing}
                </div>
                ${errLine ? html`<div class="err">${errLine}</div>` : nothing}
            </div></ha-card>`;
    }

    _renderDetail(r) {
        const d = dayDetail(r);
        return html`
            <div class="detail">
                ${d.lines.map((l) => html`<div class="dl"><span>${this._t(l.key)}</span>
                    <span class="num">${l.actual} → ${l.simulated} kWh ${this._est()}</span></div>`)}
                ${d.net ? html`<div class="dl"><span>${fill(this._t('sim_day_net'), { d: '' })}</span>
                    <span class="num delta ${d.net.cls}">${d.net.text}</span></div>` : nothing}
                ${d.story.length ? html`<div class="why">${d.story.join(' · ')}</div>` : nothing}
            </div>`;
    }

    _renderRow(r, lang) {
        const delta = formatDelta(r.delta);
        const reasons = (r.reasons || []).join(' · ');
        const open = this._openDay === r.date;
        return html`
            <div class="trow tap ${open ? 'open' : ''}" role="button" tabindex="0" aria-expanded="${open ? 'true' : 'false'}"
                @click=${() => this._toggleDay(r.date)}>
                <span class="c1">${rowDate(r.date, lang)}${r.indicative ? html` <span class="warn"
                    title="${this._t('sim_indicative')}${reasons ? ': ' + reasons : ''}">⚠️</span>` : nothing}</span>
                <span class="c2" title="${this._tagTitle(r.tags)}">${tagGlyphs(r.tags)}</span>
                <span class="num">${money(r.actual_cost)}${needsEst('actual') ? this._est() : nothing}</span>
                <span class="num">${money(r.simulated_cost)} ${needsEst('simulated') ? this._est() : nothing}</span>
                <span class="num delta ${delta.cls}">${delta.text} ${needsEst('delta') ? this._est() : nothing}</span>
            </div>
            ${open ? this._renderDetail(r) : nothing}`;
    }

    _renderMonths(res) {
        const { rows, helps } = monthRows(res.months);
        if (rows.length < 2) return nothing;
        return html`
            <div class="ct-title sub"><ha-icon icon="mdi:calendar-month"></ha-icon>${this._t('sim_months')}</div>
            ${rows.map((m) => html`
                <div class="mrow"><span>${m.month}</span>
                    <span class="mbar"><i class="${m.delta.cls}" style="width:${Math.round(m.share * 100)}%"></i></span>
                    <span class="num delta ${m.delta.cls}">${m.delta.text}</span></div>`)}
            <div class="legend">${helps.length ? fill(this._t('sim_months_helps'), { months: helps.join(', ') }) : this._t('sim_months_none')} ${this._est()}</div>`;
    }

    _renderEnergy(res) {
        const rows = energyRows(res.energy);
        if (!rows.length) return nothing;
        return html`
            <div class="ct-title sub"><ha-icon icon="mdi:lightning-bolt"></ha-icon>${this._t('sim_energy')}
                <span class="right muted">${this._t('sim_actual_word')} → ${this._t('sim_simulated_word')}</span></div>
            ${rows.map((r) => html`<div class="dl"><span>${this._t(r.key)}</span>
                <span class="num">${r.actual} → ${r.simulated}${r.unit ? ' ' + r.unit : ''} ${this._est()}</span></div>`)}`;
    }

    _renderResults() {
        const res = this._result;
        if (!res) return nothing;
        const lang = this._hass?.language || 'en';
        const cur = this._currency();
        const tag = this._filter;
        const { rows, more } = visibleRows(filterRows(res.days, tag), this._expanded);
        const tiles = tagTiles(res.per_tag, res.total, tag);
        const tot = totalLine(totalFor(res, tag));
        const all = totalLine(res.total);
        const skipped = res.skipped || [];
        const calib = calibration(res);
        if (!calib.ok) {
            return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:chart-box-outline"></ha-icon>${this._t('sim_results')} · ${fill(this._t('sim_last_run'), { n: all.days })}</div>
                <div class="err">${fill(this._t('sim_cant_simulate'), { pct: calib.pct === null ? '?' : calib.pct })}</div>
                ${this._renderCalibLines(calib)}
                <div class="legend">${this._t('sim_limits')}</div>
            </div></ha-card>`;
        }
        const stored = res.stored_energy || null;
        const ev = res.ev || null;
        const evShort = Number(ev?.not_delivered_kwh) || 0;
        return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:chart-box-outline"></ha-icon>${this._t('sim_results')} · ${fill(this._t('sim_last_run'), { n: all.days })}
                    <span class="right" role="button" tabindex="0" @click=${() => this._download()}>
                        <ha-icon icon="mdi:download"></ha-icon>${this._t('sessions_xlsx')}</span></div>
                ${res.cancelled ? html`<div class="note">${this._t('sim_cancelled')}</div>` : nothing}
                ${this._error?.kind === 'download' ? html`<div class="err">${this._t('sessions_download_failed')}</div>` : nothing}
                ${all.net ? html`<div class="headline">
                    <span>${this._t('sim_net_total')}</span>
                    <b class="delta ${all.net.cls}">${all.net.text} ${cur} ${this._est()}</b>
                    <small>${this._t('sim_col_diff')} ${all.delta.text} ${cur}</small></div>` : nothing}
                <div class="tiles">
                    <div class="tile tap ${tag ? '' : 'on'}" role="button" tabindex="0" @click=${() => this._setFilter(null)}>
                        <div class="v ${all.delta.cls}">${all.delta.text}</div>
                        <div class="l">${this._t('sim_filter_all')} · ${fill(this._t('sim_n_days'), { n: all.days })}</div>
                    </div>
                    ${tiles.map((t) => html`
                        <div class="tile tap ${t.on ? 'on' : ''} ${t.days ? '' : 'empty'}" role="button" tabindex="0"
                            @click=${() => t.days && this._setFilter(t.tag)}>
                            <div class="v ${t.delta ? t.delta.cls : 'none'}">${t.delta ? t.delta.text : '—'}</div>
                            <div class="l">${t.glyph} ${this._t(TILE_WORD[t.tag])} · ${!t.days
                                ? this._t('sim_none_in_period')
                                : t.of === null ? fill(this._t('sim_n_days'), { n: t.days })
                                    : fill(this._t('sim_n_of'), { n: t.days, m: t.of })}</div>
                        </div>`)}
                </div>
                <div class="legend">${this._t('sim_filter_hint')}</div>
                <div class="thead"><span>${this._t('sim_col_day')}</span><span>${this._t('sim_col_tags')}</span>
                    <span class="num">${this._t('sim_col_actual')}${calib.repriced ? '*' : ''} ${cur}</span>
                    <span class="num">${this._t('sim_col_simulated')} ${cur}</span>
                    <span class="num">${this._t('sim_col_diff')}</span></div>
                ${rows.map((r) => this._renderRow(r, lang))}
                ${more > 0 ? html`<div class="more" role="button" tabindex="0"
                    @click=${() => { this._expanded = true; }}>${fill(this._t('sim_more_days'), { n: more })} ▾</div>` : nothing}
                ${this._expanded && filterRows(res.days, tag).length > 8 ? html`<div class="more" role="button" tabindex="0"
                    @click=${() => { this._expanded = false; }}>${this._t('sim_fewer')} ▴</div>` : nothing}
                <div class="total">
                    <span>${tag ? html`${TILE_WORD[tag] ? this._t(TILE_WORD[tag]) : tag} · ` : nothing}${fill(this._t('sim_n_days'), { n: tot.days })} · ${this._t('sim_actual_word')} <b>${tot.actual}</b> → ${this._t('sim_simulated_word')} <b>${tot.simulated} ${this._est()}</b> ${cur}</span>
                    <span class="delta ${tot.delta.cls}">${tot.delta.text} ${cur}${tot.pct ? ' · ' + tot.pct : ''}</span>
                </div>
                ${tag && tot.net ? html`<div class="legend">${fill(this._t('sim_day_net'), { d: tot.net.text + ' ' + cur })} ${this._est()}</div>` : nothing}
                ${stored && Math.abs(Number(stored.kwh) || 0) >= 0.05 ? html`<div class="legend">${fill(this._t('sim_stored_sum'), { kwh: (Number(stored.kwh) >= 0 ? '+' : '') + Number(stored.kwh).toFixed(1), value: money(stored.value) + ' ' + cur })} ${this._est()}</div>` : nothing}
                ${this._renderMonths(res)}
                ${this._renderEnergy(res)}
                ${ev && ((Number(ev.moved_kwh) || 0) > 0 || (Number(ev.not_delivered_kwh) || 0) > 0) ? html`<div class="legend">${fill(this._t('sim_ev_moved'), { moved: Number(ev.moved_kwh).toFixed(1), short: Number(ev.not_delivered_kwh).toFixed(1) })} ${this._est()}</div>` : nothing}
                ${evShort > 0 && all.net ? html`<div class="legend">${fill(this._t('sim_net_ev_note'), { kwh: evShort.toFixed(1), value: money(ev.not_delivered_value) + ' ' + cur })} ${this._est()}</div>` : nothing}
                ${calib.repriced ? html`<div class="legend">${this._t('sim_repriced_note')}</div>` : nothing}
                ${this._renderCalibLines(calib)}
                ${all.kwhOverLimit > 0 ? html`<div class="legend">${fill(this._t('sim_over_limit'), { n: all.kwhOverLimit.toFixed(1) })} ${this._est()}</div>` : nothing}
                ${skipped.length ? html`<div class="legend" title="${skipped.map((s) => `${s.date}: ${s.reason}`).join('\n')}">${fill(this._t('sim_skipped'), { n: skipped.length })}</div>` : nothing}
                <div class="legend">${this._est()} ${this._t('sim_est_legend')}</div>
                <div class="legend">${this._t('sim_limits')}</div>
            </div></ha-card>`;
    }

    _renderCalibLines(calib) {
        return html`
            ${calib.caution ? html`<div class="warn">${fill(this._t('sim_caution'), { pct: calib.pct })}</div>` : nothing}
            ${calib.days === null ? nothing : html`<div class="legend">${fill(this._t('sim_days_checked'), { n: calib.days, m: calib.leftOut })}</div>`}
            ${calib.carDays > 0 && calib.carPct !== null ? html`<div class="legend">${fill(this._t('sim_car_error'), { pct: calib.carPct, n: calib.carDays })}</div>` : nothing}`;
    }

    render() {
        return html`
            <div class="sim">
                ${this._renderHeader()}
                ${this._renderPeriod()}
                ${this._renderWhatIf()}
                ${this._renderRun()}
                ${this._renderResults()}
            </div>`;
    }


    getCardSize() {
        return 12;
    }

    static get styles() {
        return [semGlassCss, css`
            :host { display: block; }
            .sim { color: var(--primary-text-color); }
            ha-card { display: block; margin: 8px 0; overflow: hidden; }
            .wrap {
                padding: 14px 20px; position: relative;
                background: radial-gradient(ellipse 70% 60% at 50% 25%, #8353d10f 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }
            .header-wrap {
                display: flex; align-items: center; gap: 16px; padding: 16px 20px;
                background: radial-gradient(ellipse 80% 70% at 20% 50%, #8353d10d 0%, transparent 70%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }
            .icon-ring { position: relative; flex-shrink: 0; width: 64px; height: 64px; }
            .icon-ring svg { width: 100%; height: 100%; }
            .icon-ring ha-icon {
                position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
                color: #8353d1; --mdc-icon-size: 26px; opacity: .85;
            }
            .title-area { flex: 1 1 auto; min-width: 140px; }
            .tab-title { font-size: 20px; font-weight: 700; color: #8353d1; letter-spacing: .5px; text-shadow: 0 0 12px #8353d140; }
            .tab-subtitle { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; font-weight: 500; }
            .stats { display: flex; gap: 16px; flex-shrink: 0; }
            .stat { text-align: center; min-width: 50px; }
            .stat-value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .stat-label { font-size: 11px; color: var(--secondary-text-color); font-weight: 500; margin-top: 1px; }
            .ct-title {
                font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--secondary-text-color);
                display: flex; align-items: center; gap: 5px; margin-bottom: 6px;
            }
            .ct-title ha-icon { --mdc-icon-size: 14px; color: #8353d1; }
            .ct-title .right {
                margin-left: auto; text-transform: none; letter-spacing: 0; font-size: 12px; font-weight: 600;
                color: #5BC8D8; display: flex; gap: 4px; align-items: center; cursor: pointer;
            }
            .ct-title .right ha-icon { color: #5BC8D8; }
            .chip {
                display: inline-flex; align-items: center; gap: 4px; background: var(--secondary-background-color);
                border: 1px solid var(--divider-color); border-radius: 12px; padding: 3px 10px; font-size: 11px;
                font-weight: 500; font-variant-numeric: tabular-nums; cursor: pointer; user-select: none;
            }
            .chip.on { background: #8353d122; border-color: #8353d1; color: #8353d1; font-weight: 700; }
            .picks { display: flex; gap: 6px; flex-wrap: wrap; margin: 2px 0 10px; }
            .recent { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; align-items: center; margin: 0 0 10px; font-size: 12px; }
            .recent label { font-weight: 600; }
            .recent small { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
            .recent input { grid-column: 1 / -1; width: 100%; min-height: 36px; accent-color: #8353d1; }
            .span { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
            .lbl-small { font-size: 11px; color: var(--secondary-text-color); align-self: center; }
            .legend { font-size: 11px; color: var(--secondary-text-color); margin-top: 8px; }
            .note { font-size: 12px; color: var(--secondary-text-color); margin: 2px 0 6px; }
            .err { font-size: 12px; color: var(--error-color, #db4437); margin-top: 8px; }
            .warn { font-size: 12px; color: var(--warning-color, #ff9800); margin-top: 8px; }
            .group {
                margin-top: 8px; padding: 6px 12px; border: 1px solid var(--divider-color);
                border-radius: 10px; background: rgba(255,255,255,0.025);
            }
            .ct-row { display: flex; align-items: center; min-height: 34px; gap: 8px; border-bottom: 1px solid var(--divider-color); }
            .ct-row:last-child { border-bottom: 0; }
            .ct-row .lbl { flex: 1 1 auto; font-size: 12px; font-weight: 500; }
            .cur { font-size: 11px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
            .arrow { color: var(--secondary-text-color); font-size: 12px; }
            .inp {
                display: inline-flex; align-items: center; gap: 4px; background: var(--secondary-background-color);
                border: 1px solid var(--divider-color); border-radius: 8px; padding: 3px 8px; font-size: 12px;
                font-weight: 700; font-variant-numeric: tabular-nums; min-width: 56px; justify-content: flex-end;
            }
            .inp input {
                width: 48px; border: 0; background: transparent; color: inherit; font: inherit; text-align: right;
                padding: 0; -moz-appearance: textfield;
            }
            .inp input::-webkit-outer-spin-button, .inp input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
            .inp input:focus { outline: none; }
            .inp.changed, .sel-ctl.changed { border-color: #8353d1; color: #8353d1; }
            .inp small { font-weight: 500; color: var(--secondary-text-color); }
            .sel-ctl {
                appearance: none; -webkit-appearance: none; background-color: var(--secondary-background-color);
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat; background-position: right 6px center; background-size: 14px;
                color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 8px;
                padding: 4px 24px 4px 10px; font-size: 12px; font-weight: 700; font-family: inherit;
            }
            .runrow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
            .btn {
                display: inline-flex; align-items: center; gap: 6px; border-radius: 10px; padding: 8px 16px;
                font-size: 13px; font-weight: 700; border: 1px solid #8353d1; background: #8353d1; color: #fff;
                cursor: pointer; font-family: inherit;
            }
            .btn[disabled] { opacity: .45; cursor: not-allowed; }
            .btn.sec { background: transparent; color: var(--primary-text-color); border-color: var(--divider-color); }
            .btn ha-icon { --mdc-icon-size: 16px; }
            .prog { flex: 1 1 220px; display: flex; flex-direction: column; gap: 4px; }
            .bar { height: 6px; border-radius: 3px; background: var(--secondary-background-color); overflow: hidden; }
            .bar i { display: block; height: 100%; background: linear-gradient(90deg, #8353d1, #5BC8D8); transition: width .4s; }
            .prog small { font-size: 11px; color: var(--secondary-text-color); }
            .trow, .thead {
                display: grid; grid-template-columns: 1.5fr 1fr .9fr 1.1fr 1.1fr; gap: 6px; align-items: center;
                min-height: 28px; border-bottom: 1px solid var(--divider-color); font-size: 12px;
                font-variant-numeric: tabular-nums;
            }
            .thead { font-size: 11px; font-weight: 500; color: var(--secondary-text-color); min-height: 22px; }
            .num { text-align: right; }
            .warn { font-size: 11px; cursor: help; }
            .delta { font-weight: 700; }
            .cheaper { color: #8DC892; }
            .dearer { color: #ff9800; }
            .same, .none { color: var(--secondary-text-color); }
            .est {
                font-style: normal; font-size: 9px; font-weight: 600; color: #8353d1; border: 1px solid #8353d166;
                border-radius: 6px; padding: 0 4px; vertical-align: middle;
            }
            .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin-top: 10px; }
            .tile { border: 1px solid var(--divider-color); border-radius: 10px; padding: 8px 10px; background: rgba(255,255,255,0.025); }
            .tile .v { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .tile .l { font-size: 11px; color: var(--secondary-text-color); font-weight: 500; }
            .total { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
            .total b { font-size: 14px; }
            .more { font-size: 11px; color: var(--secondary-text-color); padding: 6px 0 0; cursor: pointer; }
            .tap { cursor: pointer; }
            .tile.on { border-color: #8353d1; background: #8353d11c; }
            .tile.empty { opacity: .55; cursor: default; }
            .trow.open { background: #8353d10f; }
            .detail { padding: 6px 8px 8px; border-bottom: 1px solid var(--divider-color); background: #8353d108; }
            .dl { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; min-height: 22px; align-items: center; font-variant-numeric: tabular-nums; }
            .why { font-size: 11px; color: var(--secondary-text-color); margin-top: 4px; }
            .headline { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 4px 0 8px; font-size: 13px; }
            .headline b { font-size: 18px; }
            .headline small { color: var(--secondary-text-color); }
            .ct-title.sub { margin-top: 14px; }
            .ct-title .right.muted { color: var(--secondary-text-color); cursor: default; font-weight: 500; }
            .mrow { display: grid; grid-template-columns: 80px 1fr auto; gap: 8px; align-items: center; font-size: 12px; min-height: 22px; font-variant-numeric: tabular-nums; }
            .mbar { height: 6px; border-radius: 3px; background: var(--secondary-background-color); overflow: hidden; }
            .mbar i { display: block; height: 100%; }
            .mbar i.cheaper { background: #8DC892; }
            .mbar i.dearer { background: #ff9800; }
            .mbar i.same { background: var(--divider-color); }
            @media (max-width: 600px) {
                .header-wrap { flex-wrap: wrap; }
                .trow, .thead { grid-template-columns: 1.3fr .8fr .9fr 1.1fr 1.1fr; font-size: 11px; }
                .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .mrow { grid-template-columns: 64px 1fr auto; }
            }
        `];
    }
}

semDefineCard('sem-simulation-card', SEMSimulationCard, {
    type: 'sem-simulation-card',
    name: 'SEM Simulation',
    description: 'Replay a recorded period with another battery, solar size, peak limit or price; estimated cost per day type and month',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-simulation-card',
});
