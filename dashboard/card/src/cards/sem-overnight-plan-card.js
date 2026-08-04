/**
 * SEM Overnight Plan Card — the Night Ledger, made visible (#638)
 *
 * Renders sensor.sem_overnight_plan: the joint overnight planner's answer
 * for tonight. One strip per demand over a shared hour axis, plus the
 * battery's own row showing where it hands the house over to the meter
 * (the "takeover").
 *
 * SHADOW: the planner does not actuate. This card says what SEM WOULD do,
 * which is exactly why it exists — before #638 the only way to see a plan
 * was to grep the log for OVERNIGHT-PLAN or call the diagnose service.
 *
 * Self-hides while the verdict is ``pending`` (before the night window, or
 * while the world is still warming up) so it costs nothing during the day.
 *
 * Config:
 *   type: custom:sem-overnight-plan-card
 *   entity: sensor.sem_overnight_plan   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard, semFormatTime, semGetCurrency } from '../base/sem-shared.js';

const DEFAULT_ENTITY = 'sensor.sem_overnight_plan';

// Demand kind → icon + block colour. Colours are the SEM palette: EV soft
// green, generic load home-cyan, battery pre-charge pink (Battery-In).
const KINDS = {
    ev:      { icon: 'mdi:ev-station',   color: '#8DC892', label: 'overnight_kind_ev' },
    load:    { icon: 'mdi:power-plug',   color: '#5BC8D8', label: 'overnight_kind_load' },
    battery: { icon: 'mdi:home-battery', color: '#f06292', label: 'overnight_kind_battery' },
};

const STATUS = {
    fits:    { icon: 'mdi:check-circle',       color: '#8DC892' },
    partial: { icon: 'mdi:circle-slice-4',     color: '#ff9800' },
    yields:  { icon: 'mdi:alert-circle-outline', color: '#f06292' },
};

// Below this the slot's home draw is considered fully battery-covered. The
// backend rounds home_grid_w to 1 decimal, so anything under a watt is noise.
const GRID_EPS_W = 1.0;

class SEMOvernightPlanCard extends SEMLitBase {
    setConfig(config) {
        super.setConfig(config);
        this._entity = config.entity || DEFAULT_ENTITY;
    }

    set hass(hass) {
        this._hass = hass;
        const s = hass?.states[this._entity];
        const a = s?.attributes || {};
        // The plan is stamped ONCE per night — computed_at is the only field
        // that moves when it changes. Keying on it (rather than on the state
        // alone) means a re-plan re-renders and a quiet night does not.
        const key = [s?.state, a.computed_at, hass?.language].join('|');
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
        if (!iso) return '—';
        return semFormatTime(iso, this._hass?.config?.time_zone || undefined);
    }

    _format(key, values) {
        let template = this._t(key);
        if (!template || template === key) return null;
        for (const [k, v] of Object.entries(values || {})) {
            template = template.replace(new RegExp('\\{' + k + '\\}', 'g'), v);
        }
        return template;
    }

    // Merge consecutive slots that share a predicate into % runs on the axis.
    _runs(slots, t0, span, pick) {
        const out = [];
        for (const s of slots) {
            const v = pick(s);
            const start = Date.parse(s.start);
            const end = Date.parse(s.end);
            if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
            const prev = out[out.length - 1];
            if (prev && prev.v === v && Math.abs(prev.endMs - start) < 1000) {
                prev.endMs = end;
            } else {
                out.push({ v, startMs: start, endMs: end });
            }
        }
        return out.map(r => ({
            v: r.v,
            left: ((r.startMs - t0) / span) * 100,
            width: ((r.endMs - r.startMs) / span) * 100,
        }));
    }

    // (#638 G4) the chip is the mode made visible: purple "shadow" while the
    // plan is log-only, green "active" while the actuation switch feeds it
    // into the night signals. Same for the footer note; the tooltip repeats
    // the note so the idle render (which has no footer) still explains itself.
    _modeChip(act) {
        return html`<span class="chip ${act ? 'chip-active' : ''}"
            title="${this._t(act ? 'overnight_active_note' : 'overnight_shadow_note')}">${
            this._t(act ? 'overnight_active' : 'overnight_shadow')}</span>`;
    }

    // Deep link into the planner docs (guarded by tests/test_618_docs_anchors.py
    // — the regex there matches this "docs:" literal, keep the shape).
    _docsLink() {
        const url = {
            docs: 'https://github.com/traktore-org/sem-community/blob/main/docs/OVERNIGHT_PLANNER.md#actuation-g4',
        };
        return html`<a class="docs-link" href="${url.docs}" target="_blank"
            rel="noopener" title="${this._t('config_docs')}">
            <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:13px"></ha-icon>
        </a>`;
    }

    _renderIdle(act) {
        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t('overnight_plan_title')}</span>
                        ${this._modeChip(act)}
                        ${this._docsLink()}
                    </div>
                    <div class="idle">${this._t('overnight_idle')}</div>
                </div>
            </ha-card>
        `;
    }

    render() {
        if (!this._hass || !this._config) return nothing;
        const st = this._hass.states[this._entity];
        const verdict = st?.state;
        if (!st || verdict === 'pending' || verdict === 'unavailable'
            || verdict === 'unknown') {
            this.style.display = 'none';
            return nothing;
        }
        this.style.display = '';

        const a = st.attributes || {};
        const act = a.actuation === true;
        const demands = Array.isArray(a.demands) ? a.demands : [];
        const slots = Array.isArray(a.slots) ? a.slots : [];
        const blocks = Array.isArray(a.blocks) ? a.blocks : [];
        if (verdict === 'idle' || !demands.length) {
            return this._renderIdle(act);
        }

        const t0 = slots.length ? Date.parse(slots[0].start) : NaN;
        const t1 = slots.length ? Date.parse(slots[slots.length - 1].end) : NaN;
        const span = t1 - t0;
        // HA's recorder stores NO attributes at all above 16 KiB, so on a very
        // large night the sensor drops the timeline — and only the timeline.
        // The demands ARE the answer; render them as a list and say the chart
        // is missing rather than claiming nothing needs the night.
        const hasStrip = slots.length > 0 && Number.isFinite(span) && span > 0;

        // Cheap-price band: one shared layer, repeated behind every track so
        // the price context lines up with the runs without a second axis.
        const cheap = this._runs(slots, t0, span, s => !!s.cheap)
            .filter(r => r.v);
        const cheapLayer = html`
            <div class="band">
                ${cheap.map(r => html`
                    <div class="cheap" style="left:${r.left}%;width:${r.width}%"></div>
                `)}
            </div>
        `;

        // Hour ticks — every slot boundary that lands on a whole hour, thinned
        // so a 15-minute curve does not print 48 labels.
        let hourStarts = slots.filter(s => new Date(s.start).getMinutes() === 0);
        // A tariff whose slots never land on a whole hour (or a viewer in a
        // :30 offset zone) would otherwise get an axis with no labels at all.
        if (!hourStarts.length) hourStarts = slots;
        const step = Math.max(1, Math.ceil(hourStarts.length / 8));
        const ticks = hourStarts.filter((_, i) => i % step === 0).map(s => ({
            left: ((Date.parse(s.start) - t0) / span) * 100,
            text: this._hm(s.start),
        // A label centred past ~94% spills over the status column, which
        // sits outside the track's clip. Drop it — the axis reads fine
        // without its last tick.
        })).filter(t => t.left <= 94);

        const battRuns = this._runs(slots, t0, span,
                                    s => (s.home_grid_w || 0) <= GRID_EPS_W);
        // The status cell is narrow by design (the track is the point), so
        // the takeover reads as icon + hour there and carries the full
        // localized sentence as its tooltip.
        const takeoverFull = a.takeover
            ? this._format('overnight_takeover', { time: this._hm(a.takeover) })
            : this._t('overnight_all_night');
        const takeoverCell = a.takeover
            ? html`
                <ha-icon icon="mdi:transmission-tower"
                         style="--mdc-icon-size:12px;color:#488fc2"></ha-icon>
                <span>${this._hm(a.takeover)}</span>
              `
            : html`
                <ha-icon icon="mdi:home-battery-outline"
                         style="--mdc-icon-size:12px;color:#4db6ac"></ha-icon>
                <span>${this._t('overnight_all_night_short')}</span>
              `;

        const currency = semGetCurrency(this._hass);
        const cost = Number(a.total_cost);
        const costText = Number.isFinite(cost)
            ? `${this._t('overnight_est')} ${cost.toFixed(2)} ${currency}`
            : null;
        const fits = a.fits !== false;

        const byDemand = {};
        for (const b of blocks) {
            (byDemand[b.id] = byDemand[b.id] || []).push(b);
        }

        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t('overnight_plan_title')}</span>
                        ${this._modeChip(act)}
                        ${this._docsLink()}
                        <span class="stamp">${this._hm(a.computed_at)}</span>
                    </div>

                    <div class="verdict">
                        <ha-icon
                            icon="${fits ? 'mdi:check-circle' : 'mdi:alert-circle-outline'}"
                            style="--mdc-icon-size:15px;color:${fits ? '#8DC892' : '#f06292'}"></ha-icon>
                        <span class="vtext">
                            ${fits ? this._t('overnight_fits') : this._t('overnight_yields')}
                        </span>
                        ${costText ? html`<span class="cost">${costText}</span>` : nothing}
                    </div>

                    <div class="strip ${hasStrip ? '' : 'nostrip'}">
                        ${hasStrip ? html`
                            <div class="lbl axis"></div>
                            <div class="track axis">
                                ${cheapLayer}
                                ${ticks.map(t => html`
                                    <span class="tick ${t.left < 4 ? 'first' : ''}"
                                          style="left:${t.left}%">${t.text}</span>
                                `)}
                            </div>
                            <div class="stat axis"></div>
                        ` : nothing}

                        <div class="lbl">
                            <ha-icon icon="mdi:home-battery" style="--mdc-icon-size:13px;color:#4db6ac"></ha-icon>
                            <span class="name">${this._t('overnight_home')}</span>
                        </div>
                        ${hasStrip ? html`
                            <div class="track">
                                ${cheapLayer}
                                ${battRuns.map(r => html`
                                    <div class="seg ${r.v ? 'batt' : 'grid'}"
                                         style="left:${r.left}%;width:${r.width}%"></div>
                                `)}
                            </div>
                        ` : nothing}
                        <div class="stat" title="${takeoverFull}">${takeoverCell}</div>

                        ${demands.map(d => {
                            const k = KINDS[d.kind] || KINDS.load;
                            const s = STATUS[d.status] || STATUS.yields;
                            const mine = byDemand[d.id] || [];
                            const name = d.label || this._t(k.label);
                            const kwh = d.status === 'fits'
                                ? `${(d.planned_kwh || 0).toFixed(1)} kWh`
                                : `${(d.planned_kwh || 0).toFixed(1)}/${(d.needed_kwh || 0).toFixed(1)} kWh`;
                            return html`
                                <div class="lbl">
                                    <ha-icon icon="${k.icon}" style="--mdc-icon-size:13px;color:${k.color}"></ha-icon>
                                    <span class="name" title="${d.id}">${name}</span>
                                </div>
                                ${hasStrip ? html`
                                    <div class="track">
                                        ${cheapLayer}
                                        ${mine.map(b => {
                                            const left = ((Date.parse(b.start) - t0) / span) * 100;
                                            const width = ((Date.parse(b.end) - Date.parse(b.start)) / span) * 100;
                                            return html`
                                                <div class="seg run"
                                                     title="${this._hm(b.start)}–${this._hm(b.end)} · ${Math.round(b.power_w)} W"
                                                     style="left:${left}%;width:${Math.max(width, 1.2)}%;background:${k.color}"></div>
                                            `;
                                        })}
                                    </div>
                                ` : nothing}
                                <div class="stat">
                                    <ha-icon icon="${s.icon}" style="--mdc-icon-size:13px;color:${s.color}"></ha-icon>
                                    <span>${kwh}</span>
                                </div>
                                ${d.note ? html`
                                    <div class="lbl"></div>
                                    <div class="note">${d.note}</div>
                                    ${hasStrip ? html`<div class="stat"></div>` : nothing}
                                ` : nothing}
                            `;
                        })}
                    </div>

                    ${hasStrip ? html`
                        <div class="legend">
                            <span class="key"><i class="sw batt"></i>${this._t('overnight_legend_battery')}</span>
                            <span class="key"><i class="sw grid"></i>${this._t('overnight_legend_grid')}</span>
                            <span class="key"><i class="sw cheapkey"></i>${this._t('overnight_legend_cheap')}</span>
                        </div>
                    ` : html`
                        <div class="warn">
                            <ha-icon icon="mdi:chart-timeline-variant"
                                     style="--mdc-icon-size:13px;color:#ff9800"></ha-icon>
                            <span>${this._t('overnight_strip_omitted')}</span>
                        </div>
                    `}

                    ${a.battery_fleet_partial ? html`
                        <div class="warn">
                            <ha-icon icon="mdi:alert-outline" style="--mdc-icon-size:13px;color:#ff9800"></ha-icon>
                            <span>${this._t('overnight_fleet_partial')}</span>
                        </div>
                    ` : nothing}

                    <div class="foot">${this._t(act
                        ? 'overnight_active_note' : 'overnight_shadow_note')}</div>
                </div>
            </ha-card>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            ha-card {
                background: var(--card-background-color, #1e232d);
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
            }
            .wrap { padding: 12px 14px; }
            .head {
                display: flex; align-items: center; gap: 6px;
                margin-bottom: 6px; opacity: 0.9;
            }
            .title {
                font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
                color: var(--primary-text-color);
            }
            .chip {
                font-size: 9px; letter-spacing: 0.06em; text-transform: uppercase;
                padding: 1px 6px; border-radius: 8px;
                background: rgba(131,83,209,0.18); color: #b39ddb;
                border: 1px solid rgba(131,83,209,0.35);
            }
            .chip-active {
                background: rgba(141,200,146,0.18); color: #8DC892;
                border-color: rgba(141,200,146,0.40);
            }
            .docs-link {
                display: inline-flex; align-items: center;
                color: var(--secondary-text-color);
                opacity: 0.6; transition: opacity 0.15s;
            }
            .docs-link:hover { opacity: 1; color: #8353d1; }
            .stamp {
                margin-left: auto; font-size: 11px;
                color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
            }
            .verdict {
                display: flex; align-items: center; gap: 6px;
                font-size: 13px; font-weight: 500;
                color: var(--primary-text-color);
                margin-bottom: 10px;
            }
            .cost {
                margin-left: auto; font-size: 12px; font-weight: 400;
                color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
            }
            .idle {
                font-size: 13px; color: var(--secondary-text-color);
                padding: 2px 0 2px;
            }
            .strip {
                display: grid;
                /* The label column grows with the card: on a panel-width
                   System tab a fixed 82px truncated "Sim Pool Pump" to
                   "Sim Pool P…" with 700px going spare. */
                grid-template-columns: minmax(82px, 16%) 1fr 92px;
                align-items: center;
                row-gap: 4px; column-gap: 8px;
            }
            /* No timeline (the recorder dropped it) — the label takes the
               track's room so the demand names still read in full. */
            .strip.nostrip { grid-template-columns: 1fr auto; }
            .lbl {
                display: flex; align-items: center; gap: 4px;
                min-width: 0; font-size: 11px;
                color: var(--primary-text-color);
            }
            .name {
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .track {
                position: relative; height: 14px; border-radius: 4px;
                background: rgba(255,255,255,0.04);
                overflow: hidden;
            }
            .track.axis {
                height: 13px; background: transparent; overflow: visible;
            }
            .band {
                position: absolute; inset: 0; pointer-events: none;
            }
            .cheap {
                position: absolute; top: 0; bottom: 0;
                background: rgba(141,200,146,0.17);
                box-shadow: inset 1px 0 0 rgba(141,200,146,0.30),
                            inset -1px 0 0 rgba(141,200,146,0.30);
            }
            .seg {
                position: absolute; top: 2px; bottom: 2px; border-radius: 3px;
            }
            .seg.batt { background: #4db6ac; }
            .seg.grid { background: #488fc2; }
            .seg.run { top: 1px; bottom: 1px; }
            .tick {
                position: absolute; top: 0;
                transform: translateX(-50%);
                font-size: 9px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            /* The first tick sits at 0% — centring it would hang half the
               label off the left edge of the track. Left-align that one. */
            .tick.first {
                transform: none;
                font-size: 9px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            .stat {
                display: flex; align-items: center; gap: 4px;
                justify-content: flex-end;
                font-size: 11px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            .note {
                font-size: 10px; opacity: 0.6; line-height: 1.2;
                color: var(--secondary-text-color);
            }
            .legend {
                display: flex; flex-wrap: wrap; gap: 10px;
                margin-top: 9px; font-size: 10px;
                color: var(--secondary-text-color);
            }
            .key { display: inline-flex; align-items: center; gap: 4px; }
            .sw {
                width: 10px; height: 8px; border-radius: 2px; display: inline-block;
            }
            .sw.batt { background: #4db6ac; }
            .sw.grid { background: #488fc2; }
            .sw.cheapkey { background: rgba(141,200,146,0.35); }
            .warn {
                display: flex; align-items: center; gap: 5px;
                margin-top: 8px; font-size: 11px; color: #ffb74d;
            }
            .foot {
                margin-top: 8px; font-size: 10px; opacity: 0.5;
                color: var(--secondary-text-color);
            }
        `;
    }
}

semDefineCard('sem-overnight-plan-card', SEMOvernightPlanCard, {
    name: 'SEM Overnight Plan',
    description: "Tonight's joint plan — when each demand runs and where the battery hands over",
});
