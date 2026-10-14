/**
 * SEM Simulation Card (#1083)
 *
 * The Simulation tab: pick recorded days by tag, change a few values
 * (battery size, reserve, peak limit, prices), replay the days on your own
 * Home Assistant and see the cost per day and per day type. Every simulated
 * number is marked "est.": after a changed decision the flows come from
 * the energy balance, not from a meter.
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
    tagGlyphs, isSelectable, QUICK_PICKS, PICK_GLYPH, pickDays, activePick, toggleDay,
    chipDate, rowDate, money, formatDelta, needsEst, visibleRows, tagTiles, totalLine,
    initialForm, isChanged, buildParams, canRun, minutesLeft, progressShare, fill,
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
    sunny: 'sim_pick_sunny', grey: 'sim_pick_grey', car: 'sim_pick_car',
    last30: 'sim_pick_last30', clear: 'sim_pick_clear',
};
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
            _selected: { state: true },
            _status: { state: true },
            _result: { state: true },
            _expanded: { state: true },
            _error: { state: true },
        };
    }

    constructor() {
        super();
        this._days = null;          // the `days` answer
        this._defaults = null;      // the `defaults` answer
        this._form = null;          // the what-if values
        this._selected = new Set(); // picked ISO dates
        this._status = null;        // the `status` answer
        this._result = null;        // the `result` answer
        this._expanded = false;
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
        } catch (_err) {
            // no stored run yet: nothing to show
        }
    }

    async _start() {
        if (!canRun(this._selected, this._form, this._status)) return;
        const days = [...this._selected].sort();
        this._error = null;
        try {
            await this._ws('start', { days, params: buildParams(this._form) });
        } catch (err) {
            const code = err?.code || '';
            this._error = code === 'busy'
                ? { kind: 'busy' }
                : { kind: code === 'invalid' ? 'invalid' : 'failed', text: err?.message || '' };
            // another run is going: follow it
            if (code === 'busy') this._poll();
            return;
        }
        this._status = { running: true, status: 'running', done: 0, total: days.length,
            started_at: new Date().toISOString() };
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

    _pick(pick) {
        const days = this._days?.days || [];
        this._selected = new Set(pickDays(days, pick));
    }

    _toggle(day) {
        this._selected = toggleDay(this._selected, day);
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
                    <div class="stat"><div class="stat-value">${this._selected.size}</div><div class="stat-label">${this._t('sim_selected')}</div></div>
                    <div class="stat"><div class="stat-value">${d.gaps ?? '—'}</div><div class="stat-label">${this._t('sim_data_gaps')}</div></div>
                </div>
            </div></ha-card>`;
    }

    _renderDays() {
        const days = this._days?.days || [];
        const active = activePick(days, this._selected);
        const legend = ['sunny', 'mixed', 'grey', 'car', 'cheap', 'gap']
            .map((t) => `${tagGlyphs([t])} ${this._t(TAG_WORD[t])}`).join(' · ');
        return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:calendar-month"></ha-icon>${this._t('sim_days')}</div>
                ${days.length ? html`
                    <div class="picks">
                        ${QUICK_PICKS.map((p) => {
                            const n = p === 'clear' ? 0 : pickDays(days, p).length;
                            const count = p === 'sunny' || p === 'grey' || p === 'car' ? ` · ${n}` : '';
                            return html`<span class="chip ${active === p ? 'on' : ''}" role="button" tabindex="0"
                                @click=${() => this._pick(p)}>${PICK_GLYPH[p] ? PICK_GLYPH[p] + ' ' : ''}${this._t(PICK_WORD[p])}${count}</span>`;
                        })}
                    </div>
                    <div class="grid">
                        ${days.map((d) => {
                            const ok = isSelectable(d);
                            const sel = ok && this._selected.has(d.date);
                            return html`<span class="day ${sel ? 'sel' : ''} ${ok ? '' : 'gap'}"
                                title="${d.date} · ${this._tagTitle(d.tags)}"
                                @click=${() => this._toggle(d)}><b>${chipDate(d.date)}</b><span>${tagGlyphs(d.tags)}</span></span>`;
                        })}
                    </div>
                    <div class="legend">${legend}</div>` : html`
                    <div class="legend">${this._days ? this._t('sim_no_days') : this._t('sim_loading')}</div>`}
            </div></ha-card>`;
    }

    _renderNumberRow(field, label, unit, current) {
        const f = this._form || {};
        const changed = isChanged(field, f, this._defaults);
        return html`
            <div class="ct-row">
                <span class="lbl">${this._t(label)}</span>
                <span class="cur">${current}</span><span class="arrow">→</span>
                <span class="inp ${changed ? 'changed' : ''}"><input type="number" min="0" step="any"
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

    _renderWhatIf() {
        const d = this._defaults;
        if (!d) return nothing;
        const peak = d.peak_limit_kw ? `${d.peak_limit_kw} kW` : this._t('sim_none');
        return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:tune-variant"></ha-icon>${this._t('sim_what_if')}</div>
                <div class="group">
                    ${this._renderNumberRow('capacity_kwh', 'sim_battery_size', 'kWh', `${d.capacity_kwh ?? '—'} kWh`)}
                    ${this._renderNumberRow('reserve_pct', 'sim_battery_reserve', '%', `${d.reserve_pct ?? '—'} %`)}
                    ${this._renderNumberRow('peak_limit_kw', 'sim_peak_limit', 'kW', peak)}
                    ${this._renderRateRow('import', 'sim_import_price')}
                    ${this._renderRateRow('export', 'sim_export_value')}
                </div>
            </div></ha-card>`;
    }

    _renderRun() {
        const st = this._status || {};
        const running = !!st.running;
        const can = canRun(this._selected, this._form, st);
        const left = running ? minutesLeft(st) : null;
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
                            <small>${this._selected.size ? fill(this._t('sim_n_days'), { n: this._selected.size }) : this._t('sim_pick_hint')}</small>`}
                    </div>
                    ${running ? html`<button class="btn sec" @click=${() => this._cancel()}>
                        <ha-icon icon="mdi:stop"></ha-icon>${this._t('sim_stop')}</button>` : nothing}
                </div>
                ${errLine ? html`<div class="err">${errLine}</div>` : nothing}
            </div></ha-card>`;
    }

    _renderRow(r, lang) {
        const delta = formatDelta(r.delta);
        const reasons = (r.reasons || []).join(' · ');
        return html`
            <div class="trow">
                <span class="c1">${rowDate(r.date, lang)}${r.indicative ? html` <span class="warn"
                    title="${this._t('sim_indicative')}${reasons ? ': ' + reasons : ''}">⚠️</span>` : nothing}</span>
                <span class="c2" title="${this._tagTitle(r.tags)}">${tagGlyphs(r.tags)}</span>
                <span class="num">${money(r.actual_cost)}${needsEst('actual') ? this._est() : nothing}</span>
                <span class="num">${money(r.simulated_cost)} ${needsEst('simulated') ? this._est() : nothing}</span>
                <span class="num delta ${delta.cls}">${delta.text} ${needsEst('delta') ? this._est() : nothing}</span>
            </div>`;
    }

    _renderResults() {
        const res = this._result;
        if (!res) return nothing;
        const lang = this._hass?.language || 'en';
        const cur = this._currency();
        const { rows, more } = visibleRows(res.days, this._expanded);
        const tiles = tagTiles(res.per_tag, res.total);
        const tot = totalLine(res.total);
        const skipped = res.skipped || [];
        return html`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:chart-box-outline"></ha-icon>${this._t('sim_results')} · ${fill(this._t('sim_last_run'), { n: tot.days })}
                    <span class="right" role="button" tabindex="0" @click=${() => this._download()}>
                        <ha-icon icon="mdi:download"></ha-icon>${this._t('sessions_xlsx')}</span></div>
                ${res.cancelled ? html`<div class="note">${this._t('sim_cancelled')}</div>` : nothing}
                ${this._error?.kind === 'download' ? html`<div class="err">${this._t('sessions_download_failed')}</div>` : nothing}
                <div class="thead"><span>${this._t('sim_col_day')}</span><span>${this._t('sim_col_tags')}</span>
                    <span class="num">${this._t('sim_col_actual')} ${cur}</span>
                    <span class="num">${this._t('sim_col_simulated')} ${cur}</span>
                    <span class="num">${this._t('sim_col_diff')}</span></div>
                ${rows.map((r) => this._renderRow(r, lang))}
                ${more > 0 ? html`<div class="more" role="button" tabindex="0"
                    @click=${() => { this._expanded = true; }}>${fill(this._t('sim_more_days'), { n: more })} ▾</div>` : nothing}
                ${this._expanded && (res.days || []).length > 8 ? html`<div class="more" role="button" tabindex="0"
                    @click=${() => { this._expanded = false; }}>${this._t('sim_fewer')} ▴</div>` : nothing}
                <div class="tiles">
                    ${tiles.map((t) => html`
                        <div class="tile">
                            <div class="v ${t.delta ? t.delta.cls : 'none'}">${t.delta ? t.delta.text : '—'}</div>
                            <div class="l">${t.glyph} ${this._t(TILE_WORD[t.tag])} · ${!t.days
                                ? this._t('sim_not_selected')
                                : t.of === null ? fill(this._t('sim_n_days'), { n: t.days })
                                    : fill(this._t('sim_n_of'), { n: t.days, m: t.of })}</div>
                        </div>`)}
                </div>
                <div class="total">
                    <span>${fill(this._t('sim_n_days'), { n: tot.days })} · ${this._t('sim_actual_word')} <b>${tot.actual}</b> → ${this._t('sim_simulated_word')} <b>${tot.simulated} ${this._est()}</b> ${cur}</span>
                    <span class="delta ${tot.delta.cls}">${tot.delta.text} ${cur}${tot.pct ? ' · ' + tot.pct : ''}</span>
                </div>
                ${tot.kwhOverLimit > 0 ? html`<div class="legend">${fill(this._t('sim_over_limit'), { n: tot.kwhOverLimit.toFixed(1) })} ${this._est()}</div>` : nothing}
                ${skipped.length ? html`<div class="legend" title="${skipped.map((s) => `${s.date}: ${s.reason}`).join('\n')}">${fill(this._t('sim_skipped'), { n: skipped.length })}</div>` : nothing}
                <div class="legend">${this._est()} ${this._t('sim_est_legend')}</div>
                <div class="legend">${this._t('sim_limits')}</div>
            </div></ha-card>`;
    }

    render() {
        return html`
            <div class="sim">
                ${this._renderHeader()}
                ${this._renderDays()}
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
            .grid { display: flex; flex-wrap: wrap; gap: 4px; }
            .day {
                display: inline-flex; flex-direction: column; align-items: center; width: 58px; padding: 3px 0 2px;
                border: 1px solid var(--divider-color); border-radius: 8px; font-size: 10px; line-height: 1.25;
                background: var(--secondary-background-color); font-variant-numeric: tabular-nums; cursor: pointer;
                user-select: none;
            }
            .day b { font-weight: 600; }
            .day span { font-size: 11px; min-height: 14px; }
            .day.sel { border-color: #8353d1; background: #8353d11c; }
            .day.gap { opacity: .38; border-style: dashed; cursor: not-allowed; }
            .legend { font-size: 11px; color: var(--secondary-text-color); margin-top: 8px; }
            .note { font-size: 12px; color: var(--secondary-text-color); margin: 2px 0 6px; }
            .err { font-size: 12px; color: var(--error-color, #db4437); margin-top: 8px; }
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
            .inp.changed { border-color: #8353d1; color: #8353d1; }
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
            @media (max-width: 600px) {
                .header-wrap { flex-wrap: wrap; }
                .trow, .thead { grid-template-columns: 1.3fr .8fr .9fr 1.1fr 1.1fr; font-size: 11px; }
                .day { width: 52px; }
            }
        `];
    }
}

semDefineCard('sem-simulation-card', SEMSimulationCard, {
    type: 'sem-simulation-card',
    name: 'SEM Simulation',
    description: 'Replay recorded days with another battery, reserve, peak limit or price; estimated cost per day type',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-simulation-card',
});
