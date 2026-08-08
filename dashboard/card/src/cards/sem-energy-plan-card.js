/**
 * SEM Energy Plan Card — the energy-day ledger, made visible (#638)
 *
 * Renders sensor.sem_energy_plan: the joint planner's answer for the whole
 * energy day — daylight and the coming night in one ledger. One strip per demand over a shared hour axis, plus the
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

const DEFAULT_ENTITY = 'sensor.sem_energy_plan';

// Demand kind → icon + block colour. Colours are the SEM palette: EV soft
// green, generic load home-cyan, battery pre-charge pink (Battery-In),
// comfort banking teal (thermal mass as a battery — matches the goal
// editor's comfort section colour).
const KINDS = {
    ev:      { icon: 'mdi:ev-station',   color: '#8DC892', label: 'overnight_kind_ev' },
    load:    { icon: 'mdi:power-plug',   color: '#5BC8D8', label: 'overnight_kind_load' },
    battery: { icon: 'mdi:home-battery', color: '#f06292', label: 'overnight_kind_battery' },
    comfort: { icon: 'mdi:thermometer',  color: '#4db6ac', label: 'overnight_kind_comfort' },
};

// Deep links into the planner docs (guarded by tests/test_618_docs_anchors.py
// — the regex there matches these "docs:" literals, keep the shape).
const DOC_LINKS = {
    actuation: { docs: 'https://github.com/traktore-org/sem-community/blob/main/docs/OVERNIGHT_PLANNER.md#actuation-g4' },
    arbitrage: { docs: 'https://github.com/traktore-org/sem-community/blob/main/docs/OVERNIGHT_PLANNER.md#the-arbitrage-advisor' },
};

const STATUS = {
    fits:    { icon: 'mdi:check-circle',       color: '#8DC892' },
    partial: { icon: 'mdi:circle-slice-4',     color: '#ff9800' },
    yields:  { icon: 'mdi:alert-circle-outline', color: '#f06292' },
};

// Below this the slot's home draw is considered fully battery-covered. The
// backend rounds home_grid_w to 1 decimal, so anything under a watt is noise.
const GRID_EPS_W = 1.0;

class SEMEnergyPlanCard extends SEMLitBase {
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
        // (#638 G4 chips) The live chips depend on the CLOCK crossing block
        // boundaries, which no attribute change announces — fold the per-
        // demand live signature into the key. hass streams every few seconds,
        // so the card re-renders exactly when a demand's live state flips
        // (in-window → done, wait → in-window) and stays quiet otherwise.
        const liveSig = (a.actuation === true && Array.isArray(a.demands))
            ? a.demands.map(d => this._liveState(d, a.blocks)).join(',')
            : '';
        const key = [s?.state, a.computed_at, a.actuation, liveSig,
                     // pending-face chip reads the switch directly (attrs
                     // are empty then) — its flips must re-render too, as
                     // must the window-open time the face displays.
                     hass?.states['switch.sem_overnight_actuation']?.state,
                     hass?.states['sensor.sem_night_start_time']?.state,
                     hass?.language].join('|');
        const hasLocalize = typeof semLocalize === 'function';
        if (key !== this._lastKey || (hasLocalize && !this._localizeReady)) {
            this._lastKey = key;
            this._lang = hass?.language;
            this._localizeReady = hasLocalize;
            this.requestUpdate();
        }
    }
    get hass() { return this._hass; }

    // (#638 G4) One demand's live actuation state, from its blocks vs. the
    // clock — mirrors the backend trust rule's observable outcome without
    // any new payload: 'now' (inside a block), 'wait:<iso>' (next block
    // ahead), 'done' (all blocks past), 'reactive' (verdict not fits — the
    // trust rule falls back to the reactive layer), null (battery pre-charge
    // or malformed — no chip; G4 does not steer the scheduler).
    _liveState(d, blocks) {
        if (!d || d.kind === 'battery') return null;
        if (d.status !== 'fits') return 'reactive';
        const now = Date.now();
        let next = null;
        let sawValid = false;
        for (const b of (Array.isArray(blocks) ? blocks : [])) {
            if (b.id !== d.id) continue;
            const start = Date.parse(b.start);
            const end = Date.parse(b.end);
            if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
            sawValid = true;
            if (start <= now && now < end) return 'now';
            if (start > now && (next === null || start < next)) next = start;
        }
        if (next !== null) return 'wait:' + next;
        // fits with no blocks at all = zero-need demand; no chip either.
        return sawValid ? 'done' : null;
    }

    // (#638 G4) chip renderer for a live state string.
    _liveChip(live) {
        if (!live) return nothing;
        if (live === 'now') {
            return html`<span class="live now">▶ ${this._t('overnight_live_now')}</span>`;
        }
        if (live.startsWith('wait:')) {
            const t = this._hm(new Date(Number(live.slice(5))).toISOString());
            return html`<span class="live wait">${
                this._format('overnight_live_wait', { time: t }) || t}</span>`;
        }
        if (live === 'done') {
            return html`<span class="live done">${this._t('overnight_live_done')}</span>`;
        }
        return html`<span class="live react">${this._t('overnight_live_reactive')}</span>`;
    }

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

    _docsLink(key = 'actuation') {
        return html`<a class="docs-link" href="${DOC_LINKS[key].docs}" target="_blank"
            rel="noopener" title="${this._t('config_docs')}">
            <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:13px"></ha-icon>
        </a>`;
    }

    _renderIdle(act, textKey = 'overnight_idle', suffix = '') {
        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t('overnight_plan_title')}</span>
                        ${this._modeChip(act)}
                        ${this._docsLink()}
                    </div>
                    <div class="idle">${this._t(textKey)}${suffix}</div>
                </div>
            </ha-card>
        `;
    }

    render() {
        if (!this._hass || !this._config) return nothing;
        const st = this._hass.states[this._entity];
        const verdict = st?.state;
        // Truly gone (integration down / entity missing) → hide with the
        // rest of the dashboard's unavailable surfaces.
        if (!st || verdict === 'unavailable' || verdict === 'unknown') {
            this.style.display = 'none';
            return nothing;
        }
        this.style.display = '';

        const a = st.attributes || {};
        // The actuation flag rides on the plan attributes — absent while
        // ``pending`` (empty attrs). Fall back to the switch entity itself
        // so the chip never claims "shadow" while actuation is armed.
        const act = a.actuation === true || (a.actuation === undefined
            && this._hass.states['switch.sem_overnight_actuation']?.state === 'on');
        // ``pending`` used to self-hide entirely — fine as a System-tab
        // diagnostic, wrong on the Control tab: after a daytime restart
        // (the stash is in-memory, task #14) the card vanished until the
        // night-window stamp and read as broken — Guido hit exactly that
        // on 2026-08-05. Show a slim placeholder saying when the plan
        // comes — the REAL window-open time (sunset-anchored, config-
        // aware) from sensor.sem_night_start_time, never a hardcoded hour.
        if (verdict === 'pending') {
            const ns = this._hass.states['sensor.sem_night_start_time']?.state;
            const when = (ns && /^\d{1,2}:\d{2}$/.test(ns)) ? ` (~${ns})` : '';
            return this._renderIdle(act, 'overnight_pending', when);
        }
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
                                ${slots.map(s => {
                                    const sl = ((Date.parse(s.start) - t0) / span) * 100;
                                    const sw = ((Date.parse(s.end) - Date.parse(s.start)) / span) * 100;
                                    if (!Number.isFinite(sl) || !Number.isFinite(sw)) return nothing;
                                    const price = (s.price === null || s.price === undefined)
                                        ? '—' : `${s.price} ${currency}`;
                                    const tipS = `${this._hm(s.start)}–${this._hm(s.end)} · ${price}`
                                        + (s.cheap ? ` · ${this._t('overnight_legend_cheap')}` : '');
                                    return html`<div class="slotcell" title="${tipS}"
                                        style="left:${sl}%;width:${sw}%"></div>`;
                                })}
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
                            // (#638 G4) the row tooltip: everything the plan
                            // knows about this demand, composed from data the
                            // card already holds (windows, power, energy, est
                            // cost, the packer's note). Replaces the raw-id
                            // title the name used to carry.
                            const tip = [
                                name,
                                // A comfort row is a new idea on this card —
                                // its tooltip says what "banking" means before
                                // the numbers (the docs link in the head has
                                // the full story under #comfort-banking).
                                d.kind === 'comfort'
                                    ? this._t('overnight_comfort_tip') : null,
                                mine.map(b => `${this._hm(b.start)}–${this._hm(b.end)} · ${
                                    (b.power_w / 1000).toFixed(1)} kW`).join('\n') || null,
                                `${(d.planned_kwh || 0).toFixed(1)} / ${(d.needed_kwh || 0).toFixed(1)} kWh`
                                    + ` · ${this._t('overnight_est')} ${(d.est_cost || 0).toFixed(2)} ${currency}`,
                                d.note || null,
                            ].filter(Boolean).join('\n');
                            // (#638 G4) live chip while actuation is on.
                            const live = act ? this._liveState(d, blocks) : null;
                            // (#638 G4) a yielding demand always explains
                            // itself — the packer's note when it wrote one,
                            // the generic fallback line otherwise. An empty
                            // row used to be the only signal.
                            const reason = d.note || (d.status !== 'fits'
                                ? this._format('overnight_yield_reason', {
                                    planned: (d.planned_kwh || 0).toFixed(1),
                                    needed: (d.needed_kwh || 0).toFixed(1),
                                  })
                                : null);
                            return html`
                                <div class="lbl ${live ? 'col' : ''}" title="${tip}">
                                    <div class="lname">
                                        <ha-icon icon="${k.icon}" style="--mdc-icon-size:13px;color:${k.color}"></ha-icon>
                                        <span class="name">${name}</span>
                                    </div>
                                    ${this._liveChip(live)}
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
                                <div class="stat" title="${tip}">
                                    <ha-icon icon="${s.icon}" style="--mdc-icon-size:13px;color:${s.color}"></ha-icon>
                                    <span>${kwh}</span>
                                </div>
                                ${reason ? html`
                                    <div class="lbl"></div>
                                    <div class="note">${reason}</div>
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

                    ${a.arbitrage ? html`
                        <div class="arb" title="${this._t('overnight_arbitrage_tip')}">
                            <ha-icon icon="mdi:swap-vertical-bold"
                                     style="--mdc-icon-size:13px;color:${
                                         a.arbitrage.opportunity ? '#8DC892'
                                         : 'var(--secondary-text-color,#8a93a5)'}"></ha-icon>
                            <span class="arb-lbl">${this._t('overnight_arbitrage')}</span>
                            <span class="arb-txt">${a.arbitrage.reason || ''}</span>
                            ${this._docsLink('arbitrage')}
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
            /* (#638 G4) a row wearing a live chip stacks name over chip. */
            .lbl.col {
                flex-direction: column; align-items: flex-start; gap: 2px;
            }
            .lname {
                display: flex; align-items: center; gap: 4px; min-width: 0;
                max-width: 100%;
            }
            .live {
                font-size: 8.5px; letter-spacing: 0.05em; text-transform: uppercase;
                padding: 0 5px; border-radius: 7px; white-space: nowrap;
            }
            .live.now {
                background: rgba(141,200,146,0.20); color: #8DC892;
                border: 1px solid rgba(141,200,146,0.45);
            }
            .live.wait {
                background: rgba(91,200,216,0.12); color: #5BC8D8;
                border: 1px solid rgba(91,200,216,0.30);
                font-variant-numeric: tabular-nums;
            }
            .live.done {
                background: rgba(255,255,255,0.06); color: var(--secondary-text-color);
                border: 1px solid rgba(255,255,255,0.12);
            }
            .live.react {
                background: rgba(131,83,209,0.16); color: #b39ddb;
                border: 1px solid rgba(131,83,209,0.35);
            }
            /* (#638 G4) invisible hover cells on the axis: per-slot price. */
            .slotcell { position: absolute; top: 0; bottom: 0; }
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
            .arb {
                display: flex; align-items: center; gap: 5px;
                margin-top: 8px; font-size: 11px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .arb-lbl { font-weight: 600; white-space: nowrap; }
            .arb-txt {
                overflow: hidden; text-overflow: ellipsis;
                white-space: nowrap; flex: 1; min-width: 0;
            }
            .foot {
                margin-top: 8px; font-size: 10px; opacity: 0.5;
                color: var(--secondary-text-color);
            }
        `;
    }
}

semDefineCard('sem-energy-plan-card', SEMEnergyPlanCard, {
    name: 'SEM Energy Plan',
    description: 'The joint plan for the energy day — when each demand runs and where the battery hands over',
});
// Back-compat alias: dashboards generated before the rename still say
// custom:sem-overnight-plan-card — serve them the same card until the
// next generate_dashboard rewrites the YAML.
semDefineCard('sem-overnight-plan-card', class extends SEMEnergyPlanCard {});
