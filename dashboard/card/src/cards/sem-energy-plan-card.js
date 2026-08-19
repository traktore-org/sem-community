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
 * was to grep the log for ENERGY-PLAN or call the diagnose service.
 *
 * Self-hides while the verdict is ``pending`` (before the night window, or
 * while the world is still warming up) so it costs nothing during the day.
 *
 * Config:
 *   type: custom:sem-energy-plan-card
 *   entity: sensor.sem_energy_plan   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard, semFormatTime, semGetCurrency } from '../base/sem-shared.js';

const DEFAULT_ENTITY = 'sensor.sem_energy_plan';

// Demand kind → icon + block colour. Colours are the SEM palette: EV soft
// green, generic load home-cyan, battery pre-charge pink (Battery-In),
// comfort banking teal (thermal mass as a battery — matches the goal
// editor's comfort section colour).
const KINDS = {
    ev:      { icon: 'mdi:ev-station',   color: '#8DC892', label: 'energy_plan_kind_ev' },
    load:    { icon: 'mdi:power-plug',   color: '#5BC8D8', label: 'energy_plan_kind_load' },
    battery: { icon: 'mdi:home-battery', color: '#f06292', label: 'energy_plan_kind_battery' },
    comfort: { icon: 'mdi:thermometer',  color: '#4db6ac', label: 'energy_plan_kind_comfort' },
};

// Deep links into the planner docs (guarded by tests/test_618_docs_anchors.py
// — the regex there matches these "docs:" literals, keep the shape).
const DOC_LINKS = {
    actuation: { docs: 'https://github.com/traktore-org/sem-community/blob/main/docs/ENERGY_PLANNER.md#actuation-g4' },
    arbitrage: { docs: 'https://github.com/traktore-org/sem-community/blob/main/docs/ENERGY_PLANNER.md#the-arbitrage-advisor' },
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
        // (#722 consolidation) the Tomorrow view re-renders when the books
        // change — the price status flip (preliminary → final, mid-
        // afternoon) is the one users watch for.
        const t = a.tomorrow || {};
        const covSig = a.coverage
            ? Object.entries(a.coverage).map(([k, v]) => k + '=' + v).join(',')
            : '';
        const key = [s?.state, a.computed_at, a.actuation, liveSig, covSig,
                     this._view || 'today',
                     t.prices, t.forecast_kwh, t.stamps_at,
                     // pending-face chip reads the switch directly (attrs
                     // are empty then) — its flips must re-render too, as
                     // must the window-open time the face displays.
                     hass?.states['switch.sem_energy_plan_actuation']?.state,
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

    // (#638 C7) the gate's named doubt, translated — never internal
    // jargon on a rendered surface.
    _covKey(reason) {
        if (!reason || reason === 'covered') return null;
        if (reason.startsWith('verdict')) return 'energy_plan_cov_yields';
        const m = {
            'no plan': 'energy_plan_cov_no_plan',
            'stale stamp': 'energy_plan_cov_stale',
            'outside span': 'energy_plan_cov_outside',
            'not in plan': 'energy_plan_cov_not_in_plan',
            'actuation off': 'energy_plan_cov_actuation_off',
            'nothing planned': 'energy_plan_cov_nothing_planned',
        };
        return m[reason] || 'energy_plan_cov_unreadable';
    }

    // (#638 C7) the reactive-fallback chip — the user-facing twin of the
    // "#638 coverage" log line: a demand the plan does not cover right now
    // is visibly reactive, never silently so.
    _covChip(reason) {
        const key = this._covKey(reason);
        if (!key) return nothing;
        return html`<span class="chip chip-reactive"
            title="${this._t('energy_plan_reactive_tip')} — ${this._t(key)}"
            >${this._t('energy_plan_reactive')} · ${this._t(key)}</span>`;
    }

    // (#638 G4) chip renderer for a live state string.
    _liveChip(live) {
        if (!live) return nothing;
        if (live === 'now') {
            return html`<span class="live now">▶ ${this._t('energy_plan_live_now')}</span>`;
        }
        if (live.startsWith('wait:')) {
            const t = this._hm(new Date(Number(live.slice(5))).toISOString());
            return html`<span class="live wait">${
                this._format('energy_plan_live_wait', { time: t }) || t}</span>`;
        }
        if (live === 'done') {
            return html`<span class="live done">${this._t('energy_plan_live_done')}</span>`;
        }
        return html`<span class="live react">${this._t('energy_plan_live_reactive')}</span>`;
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
            title="${this._t(act ? 'energy_plan_active_note' : 'energy_plan_shadow_note')}">${
            this._t(act ? 'energy_plan_active' : 'energy_plan_shadow')}</span>`;
    }

    _docsLink(key = 'actuation') {
        return html`<a class="docs-link" href="${DOC_LINKS[key].docs}" target="_blank"
            rel="noopener" title="${this._t('config_docs')}">
            <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:13px"></ha-icon>
        </a>`;
    }

    // (#722, tintinz's idea adopted) the horizon selector. Rendered only
    // when a tomorrow preview exists — a card without the attr behaves
    // exactly as before the consolidation.
    _viewToggle(hasTomorrow) {
        if (!hasTomorrow) return nothing;
        const v = this._view || 'today';
        const btn = (id, label) => html`
            <button class="vbtn ${v === id ? 'vbtn-on' : ''}"
                @click=${() => { this._view = id; this.requestUpdate(); }}>
                ${this._t(label)}</button>`;
        return html`<span class="vtoggle">
            ${btn('today', 'energy_plan_today')}${btn('tomorrow', 'energy_plan_tomorrow')}
        </span>`;
    }

    // The NEXT energy day, in the SAME layout as Today (Guido, 08-08:
    // "a line for each device is clean — and the house battery should
    // have a spot, we know the rhythm"): one row per known ask with its
    // provisional windows as track segments, the battery's predicted
    // path as its own row — pink while the sun fills it, teal otherwise.
    // Everything on this face is provisional and the chip says so.
    _renderTomorrow(t) {
        const prov = t.provisional || null;
        const axis0 = Date.parse(t.stamps_at);
        const axis1 = Date.parse(t.night_open);
        const span = axis1 - axis0;
        const hasStrip = Number.isFinite(span) && span > 0;
        const pct = (iso) => ((Date.parse(iso) - axis0) / span) * 100;
        const seg = (w, cls, color) => {
            const left = Math.max(0, pct(w.start));
            const width = Math.min(100, pct(w.end)) - left;
            if (!Number.isFinite(left) || !Number.isFinite(width) || width <= 0) return nothing;
            return html`<div class="seg ${cls}" style="left:${left}%;width:${Math.max(width, 1.2)}%${color ? `;background:${color}` : ''}"></div>`;
        };
        const bandLayer = html`
            <div class="band">
                ${(t.surplus_windows || []).map(w => seg(w, 'tmw-sun'))}
                ${(t.cheap_windows || []).map(w => seg(w, 'cheap'))}
            </div>
        `;
        const bandLayerAxis = html`
            <div class="band">
                ${(t.cheap_windows || []).map(w => seg(w, 'cheap'))}
            </div>
        `;
        // Hour ticks every ~3 h across the day axis.
        const ticks = [];
        if (hasStrip) {
            const first = new Date(axis0);
            first.setMinutes(0, 0, 0);
            if (first.getTime() < axis0) first.setHours(first.getHours() + 1);
            const stepH = Math.max(2, Math.ceil(span / 3600000 / 5));
            for (let d = new Date(first); d.getTime() < axis1; d.setHours(d.getHours() + stepH)) {
                const left = ((d.getTime() - axis0) / span) * 100;
                if (left > 94) break;
                ticks.push({ left, text: this._hm(d.toISOString()) });
            }
        }
        // Battery rhythm: segments between soc waypoints, pink while rising.
        const curve = (prov && Array.isArray(prov.soc_curve)) ? prov.soc_curve : [];
        const battSegs = [];
        for (let i = 0; i + 1 < curve.length; i++) {
            battSegs.push({
                start: curve[i].t, end: curve[i + 1].t,
                rising: curve[i + 1].kwh > curve[i].kwh + 0.01,
            });
        }
        const asks = t.known_asks || [];
        const blocksFor = (kind, i) => (prov && Array.isArray(prov.blocks))
            ? prov.blocks.filter(b => b.id === `${kind}:${i}`) : [];
        const prelim = t.prices !== 'final';
        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t('energy_plan_title')}</span>
                        ${this._viewToggle(true)}
                        <span class="chip" title="${this._t('energy_plan_provisional_tip')}">${this._t('energy_plan_provisional')}</span>
                        <span class="chip ${prelim ? '' : 'chip-active'}"
                              title="${this._t(prelim ? 'energy_plan_prices_preliminary_tip' : 'energy_plan_prices_final_tip')}">
                            ${this._t(prelim ? 'energy_plan_prices_preliminary' : 'energy_plan_prices_final')}</span>
                        ${this._docsLink()}
                    </div>
                    <div class="strip ${hasStrip ? '' : 'nostrip'}">
                        ${hasStrip ? html`
                            <div class="lbl axis"></div>
                            <div class="track axis">
                                ${bandLayerAxis}
                                ${ticks.map(k => html`
                                    <span class="tick ${k.left < 4 ? 'first' : ''}" style="left:${k.left}%">${k.text}</span>
                                `)}
                            </div>
                            <div class="stat axis"></div>
                        ` : nothing}
                        ${curve.length > 1 ? html`
                            <div class="lbl" title="${this._t('energy_plan_provisional_tip')}">
                                <div class="lname">
                                    <ha-icon icon="mdi:home-battery" style="--mdc-icon-size:13px;color:#4db6ac"></ha-icon>
                                    <span class="name">${this._t('energy_plan_kind_battery')}</span>
                                </div>
                            </div>
                            ${hasStrip ? html`
                                <div class="track">
                                    ${bandLayer}
                                    ${battSegs.map(b => seg(b, 'run', b.rising ? '#f06292' : '#4db6ac'))}
                                </div>
                            ` : nothing}
                            <div class="stat">
                                <span>${curve[0].kwh.toFixed(1)} → ${curve[curve.length - 1].kwh.toFixed(1)} kWh</span>
                            </div>
                        ` : nothing}
                        ${asks.map((a, i) => {
                            const k = KINDS[a.kind] || KINDS.load;
                            const mine = blocksFor(a.kind, i);
                            const tip = [a.label,
                                mine.map(b => `${this._hm(b.start)}–${this._hm(b.end)}`).join('\n') || null,
                                this._t('energy_plan_provisional_tip')].filter(Boolean).join('\n');
                            return html`
                                <div class="lbl" title="${tip}">
                                    <div class="lname">
                                        <ha-icon icon="${k.icon}" style="--mdc-icon-size:13px;color:${k.color}"></ha-icon>
                                        <span class="name">${a.label}</span>
                                    </div>
                                </div>
                                ${hasStrip ? html`
                                    <div class="track">
                                        ${bandLayer}
                                        ${mine.map(b => seg(b, 'run', k.color))}
                                    </div>
                                ` : nothing}
                                <div class="stat">
                                    <span>${(a.kwh || 0).toFixed(1)} kWh</span>
                                </div>
                            `;
                        })}
                    </div>
                    <div class="legend">
                        <span class="key"><i class="sw tmw-sun-key"></i>${this._t('energy_plan_legend_surplus')}</span>
                        <span class="key"><i class="sw cheapkey"></i>${this._t('energy_plan_legend_cheap')}</span>
                        <span class="key"><i class="sw" style="background:#f06292"></i>${this._t('energy_plan_legend_battery_charge')}</span>
                    </div>
                    <div class="idle">
                        ☀ ${(t.forecast_kwh || 0).toFixed(1)} kWh ·
                        ${this._format('energy_plan_stamps_at', { time: this._hm(t.stamps_at) })}
                    </div>
                </div>
            </ha-card>
        `;
    }

    // (#755) What the record shows — the closed night's per-demand verdict.
    // It reads its OWN attribute, not the plan's, because the plan empties
    // out in daylight and daylight is exactly when somebody reads what the
    // night taught. Codes in, sentences out: the module never ships prose.
    _renderReview() {
        const rv = this._hass?.states?.[this._entity]?.attributes?.review;
        if (!rv) return nothing;
        const rows = [];
        for (const d of (rv.demands || [])) {
            const text = this._format('energy_plan_review_' + d.code, {
                nights: d.nights,
                asked: (d.asked_kwh || 0).toFixed(1),
                suggested: (d.suggested_kwh == null
                    ? '' : Number(d.suggested_kwh).toFixed(1)),
                actual: (d.last_kwh || 0).toFixed(1),
            });
            if (text) rows.push({ d, text, k: KINDS[d.kind] || KINDS.load });
        }
        // (#800) The battery's night, one row: codes in, sentences out;
        // the epoch formats HERE because only the browser owns the
        // viewer's clock.
        const bn = rv.battery;
        const bnText = bn ? this._format('energy_plan_review_' + bn.code, {
            drained: (bn.drained || 0).toFixed(1),
            clipped: (bn.clipped_h || 0).toFixed(1),
            full_at: bn.full_at_ts
                ? new Date(bn.full_at_ts * 1000).toLocaleTimeString(
                    [], { hour: '2-digit', minute: '2-digit' })
                : '',
        }) : null;
        const sc = rv.self_consumption;
        const scText = sc ? this._format('energy_plan_review_' + sc.code, {
            actual: Math.round((sc.actual_share || 0) * 100),
            predicted: Math.round((sc.predicted_share || 0) * 100),
        }) : null;
        if (!rows.length && !scText && !bnText) return nothing;
        return html`
            <div class="review">
                <div class="rev-h">${this._t('energy_plan_review_title')}</div>
                ${rows.map(r => html`
                    <div class="rev-row">
                        <ha-icon icon="${r.k.icon}"
                                 style="--mdc-icon-size:12px;color:${r.k.color}"></ha-icon>
                        <span class="rev-name">${(r.d.demand_id || '').split(':').pop()}</span>
                        <span class="rev-txt">${r.text}</span>
                    </div>
                `)}
                ${bnText ? html`
                    <div class="rev-row">
                        <ha-icon icon="mdi:battery-arrow-down"
                                 style="--mdc-icon-size:12px;color:#4db6ac"></ha-icon>
                        <span class="rev-name">${this._t('battery')}</span>
                        <span class="rev-txt">${bnText}</span>
                    </div>` : nothing}
                ${scText ? html`
                    <div class="rev-row">
                        <ha-icon icon="mdi:solar-power-variant"
                                 style="--mdc-icon-size:12px;color:#ff9800"></ha-icon>
                        <span class="rev-txt wide">${scText}</span>
                    </div>
                ` : nothing}
            </div>
        `;
    }

    // The advisor's verdict, drawn the same way on every face of the card.
    // (15.08) It used to live inline in the busy face only, so a night with
    // nothing to schedule — the night a user has time to read it — showed no
    // verdict at all. One renderer, two callers: two copies is how the busy
    // and the quiet night came to disagree.
    _renderArb(arb) {
        // (16.08, Guido's PROD) The advisor runs on every stamp as a ledger
        // audit, but a verdict for a feature that cannot act is not an
        // answer — it reads as "SEM wanted to trade and the battery was in
        // the way". Render only where arbitrage is actually open: the
        // global toggle, or a battery in allow_arbitrage. The plan carries
        // that gate; an older payload without it stays silent.
        if (!arb || !arb.enabled) return nothing;
        return html`
            <div class="arb" title="${this._t('energy_plan_arbitrage_tip')}">
                <ha-icon icon="mdi:swap-vertical-bold"
                         style="--mdc-icon-size:13px;color:${
                             arb.opportunity ? '#8DC892'
                             : 'var(--secondary-text-color,#8a93a5)'}"></ha-icon>
                <span class="arb-lbl">${this._t('energy_plan_arbitrage')}</span>
                <span class="arb-txt">${arb.reason || ''}</span>
                ${this._docsLink('arbitrage')}
            </div>
        `;
    }

    _renderIdle(act, textKey = 'energy_plan_idle', suffix = '', hasTomorrow = false,
                why = '', whyCodes = [], notSched = [], arb = null) {
        // (#638 C7) translated sentences from the machine codes; the raw
        // diagnostic prose survives only as the hover tooltip. Rendering
        // it verbatim read as an unfinished placeholder (Guido, first
        // live look at the one-gate card).
        const sentences = (whyCodes || [])
            .map(c => this._t('energy_plan_whyc_' + c))
            .filter(Boolean).join(' · ');
        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t('energy_plan_title')}</span>
                        ${this._viewToggle(hasTomorrow)}
                        ${this._modeChip(act)}
                        ${this._docsLink()}
                    </div>
                    <div class="idle">${this._t(textKey)}${suffix}</div>
                    ${sentences
                        ? html`<div class="why" title="${why}">${sentences}</div>`
                        : (why ? html`<div class="why" title="${why}">${why}</div>` : nothing)}
                    ${(notSched || []).length ? html`
                        <div class="notsched">
                            <div class="notsched-h">${this._t('energy_plan_not_scheduled')}</div>
                            ${notSched.map(r => html`
                                <div class="notsched-row">
                                    <ha-icon icon="mdi:sleep"
                                             style="--mdc-icon-size:12px;color:var(--secondary-text-color,#8a93a5)"></ha-icon>
                                    <span class="nsname">${r.label || (r.id || '').split(':').pop()}</span>
                                    <span class="nswhy">${this._t('energy_plan_why_' + r.why)}</span>
                                </div>
                            `)}
                        </div>
                    ` : nothing}
                    ${this._renderArb(arb)}
                    ${this._renderReview()}
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
            && this._hass.states['switch.sem_energy_plan_actuation']?.state === 'on');
        // ``pending`` used to self-hide entirely — fine as a System-tab
        // diagnostic, wrong on the Control tab: after a daytime restart
        // (the stash is in-memory, task #14) the card vanished until the
        // night-window stamp and read as broken — Guido hit exactly that
        // on 2026-08-05. Show a slim placeholder saying when the plan
        // comes — the REAL window-open time (sunset-anchored, config-
        // aware) from sensor.sem_night_start_time, never a hardcoded hour.
        if ((this._view || 'today') === 'tomorrow' && a.tomorrow) {
            return this._renderTomorrow(a.tomorrow);
        }
        if (verdict === 'pending') {
            const ns = this._hass.states['sensor.sem_night_start_time']?.state;
            const when = (ns && /^\d{1,2}:\d{2}$/.test(ns)) ? ` (~${ns})` : '';
            return this._renderIdle(act, 'energy_plan_pending', when, !!a.tomorrow);
        }
        const demands = Array.isArray(a.demands) ? a.demands : [];
        const slots = Array.isArray(a.slots) ? a.slots : [];
        const blocks = Array.isArray(a.blocks) ? a.blocks : [];
        if (verdict === 'idle' || !demands.length) {
            return this._renderIdle(act, 'energy_plan_idle', '', !!a.tomorrow,
                a.why || '', a.why_codes || [], a.not_scheduled || [],
                a.arbitrage);
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
        // (consolidation) night-window shading + now marker — the context
        // the retired schedule card used to draw, computed from the same
        // sensor the pending face already reads. The night runs from the
        // window-open time to the axis end (the axis IS night-end-bounded).
        let nightLeft = null;
        const ns = this._hass.states['sensor.sem_night_start_time']?.state;
        if (hasStrip && ns && /^\d{1,2}:\d{2}$/.test(ns)) {
            const [nh, nm] = ns.split(':').map(Number);
            for (const dayOff of [0, 1]) {
                const d = new Date(t0);
                d.setDate(d.getDate() + dayOff);
                d.setHours(nh, nm, 0, 0);
                const ms = d.getTime();
                if (ms >= t0 && ms < t1) { nightLeft = ((ms - t0) / span) * 100; break; }
            }
        }
        const nowMs = Date.now();
        const nowLeft = (hasStrip && nowMs >= t0 && nowMs < t1)
            ? ((nowMs - t0) / span) * 100 : null;
        const cheapLayer = html`
            <div class="band">
                ${cheap.map(r => html`
                    <div class="cheap" style="left:${r.left}%;width:${r.width}%"></div>
                `)}
                ${nightLeft !== null ? html`
                    <div class="nightband" style="left:${nightLeft}%;width:${100 - nightLeft}%"></div>` : nothing}
                ${nowLeft !== null ? html`
                    <div class="nowline" style="left:${nowLeft}%"></div>` : nothing}
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
            ? this._format('energy_plan_takeover', { time: this._hm(a.takeover) })
            : this._t('energy_plan_all_night');
        const takeoverCell = a.takeover
            ? html`
                <ha-icon icon="mdi:transmission-tower"
                         style="--mdc-icon-size:12px;color:#488fc2"></ha-icon>
                <span>${this._hm(a.takeover)}</span>
              `
            : html`
                <ha-icon icon="mdi:home-battery-outline"
                         style="--mdc-icon-size:12px;color:#4db6ac"></ha-icon>
                <span>${this._t('energy_plan_all_night_short')}</span>
              `;

        const currency = semGetCurrency(this._hass);
        const cost = Number(a.total_cost);
        const costText = Number.isFinite(cost)
            ? `${this._t('energy_plan_est')} ${cost.toFixed(2)} ${currency}`
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
                        <span class="title">${this._t('energy_plan_title')}</span>
                        ${this._viewToggle(!!a.tomorrow)}
                        ${this._modeChip(act)}
                        ${this._docsLink()}
                        <span class="stamp">${this._hm(a.computed_at)}</span>
                    </div>

                    <div class="verdict">
                        <ha-icon
                            icon="${fits ? 'mdi:check-circle' : 'mdi:alert-circle-outline'}"
                            style="--mdc-icon-size:15px;color:${fits ? '#8DC892' : '#f06292'}"></ha-icon>
                        <span class="vtext">
                            ${fits ? this._t('energy_plan_fits') : this._t('energy_plan_yields')}
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
                                        + (s.cheap ? ` · ${this._t('energy_plan_legend_cheap')}` : '');
                                    return html`<div class="slotcell" title="${tipS}"
                                        style="left:${sl}%;width:${sw}%"></div>`;
                                })}
                            </div>
                            <div class="stat axis"></div>
                        ` : nothing}

                        <div class="lbl">
                            <ha-icon icon="mdi:home-battery" style="--mdc-icon-size:13px;color:#4db6ac"></ha-icon>
                            <span class="name">${this._t('energy_plan_home')}</span>
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
                                    ? this._t('energy_plan_comfort_tip') : null,
                                mine.map(b => `${this._hm(b.start)}–${this._hm(b.end)} · ${
                                    (b.power_w / 1000).toFixed(1)} kW${
                                    b.price != null ? ` · ${b.price}` : ''}`).join('\n') || null,
                                `${(d.planned_kwh || 0).toFixed(1)} / ${(d.needed_kwh || 0).toFixed(1)} kWh`
                                    + ` · ${this._t('energy_plan_est')} ${(d.est_cost || 0).toFixed(2)} ${currency}`,
                                d.note || null,
                            ].filter(Boolean).join('\n');
                            // (#638 G4) live chip while actuation is on.
                            const live = act ? this._liveState(d, blocks) : null;
                            // (#638 G4) a yielding demand always explains
                            // itself — the packer's note when it wrote one,
                            // the generic fallback line otherwise. An empty
                            // row used to be the only signal.
                            const reason = d.note || (d.status !== 'fits'
                                ? this._format('energy_plan_yield_reason', {
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
                                    ${act ? this._covChip((a.coverage || {})[d.id]) : nothing}
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
                            <span class="key"><i class="sw batt"></i>${this._t('energy_plan_legend_battery')}</span>
                            <span class="key"><i class="sw grid"></i>${this._t('energy_plan_legend_grid')}</span>
                            <span class="key"><i class="sw cheapkey"></i>${this._t('energy_plan_legend_cheap')}</span>
                        </div>
                    ` : html`
                        <div class="warn">
                            <ha-icon icon="mdi:chart-timeline-variant"
                                     style="--mdc-icon-size:13px;color:#ff9800"></ha-icon>
                            <span>${this._t('energy_plan_strip_omitted')}</span>
                        </div>
                    `}

                    ${a.battery_fleet_partial ? html`
                        <div class="warn">
                            <ha-icon icon="mdi:alert-outline" style="--mdc-icon-size:13px;color:#ff9800"></ha-icon>
                            <span>${this._t('energy_plan_fleet_partial')}</span>
                        </div>
                    ` : nothing}

                    ${(a.not_scheduled || []).length ? html`
                        <div class="notsched">
                            <div class="notsched-h">${this._t('energy_plan_not_scheduled')}</div>
                            ${a.not_scheduled.map(r => html`
                                <div class="notsched-row">
                                    <ha-icon icon="mdi:sleep"
                                             style="--mdc-icon-size:12px;color:var(--secondary-text-color,#8a93a5)"></ha-icon>
                                    <span class="nsname">${r.label || (r.id || '').split(':').pop()}</span>
                                    <span class="nswhy">${this._t('energy_plan_why_' + r.why)}</span>
                                </div>
                            `)}
                        </div>
                    ` : nothing}

                    ${this._renderArb(a.arbitrage)}

                    ${this._renderReview()}

                    <div class="foot">${this._t(act
                        ? 'energy_plan_active_note' : 'energy_plan_shadow_note')}</div>
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
            .chip-reactive {
                border-color: rgba(255, 152, 0, 0.6);
                color: #ff9800;
            }
            .notsched {
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 255, 255, 0.06);
            }
            .notsched-h {
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--secondary-text-color, #8a93a5);
                margin-bottom: 2px;
            }
            /* (#744) The name column is a NAME now, not an entity slug, so
               it no longer eats the row — but min-width:0 keeps a long one
               from pushing the reason into a two-words-per-line ribbon on a
               phone (Guido's 23:50 card). The reason takes what is left and
               sits right. */
            .notsched-row {
                display: flex;
                align-items: baseline;
                gap: 6px;
                font-size: 11px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .notsched-row .nsname {
                color: var(--primary-text-color, #e1e1e1);
                min-width: 0;
                flex: 0 1 auto;
                overflow-wrap: anywhere;
            }
            .notsched-row .nswhy {
                min-width: 0;
                flex: 1 1 auto;
                text-align: right;
            }
            /* (#755) the record's verdict — same visual weight as the
               not-scheduled list: a footnote, not a headline. */
            .review {
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 255, 255, 0.06);
            }
            .rev-h {
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--secondary-text-color, #8a93a5);
                margin-bottom: 2px;
            }
            .rev-row {
                display: flex;
                align-items: baseline;
                gap: 6px;
                font-size: 11px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .rev-row ha-icon { align-self: center; }
            .rev-name {
                color: var(--primary-text-color, #e1e1e1);
                white-space: nowrap;
            }
            .rev-txt { min-width: 0; }
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
            .head { flex-wrap: wrap; row-gap: 4px; }
            .why {
                margin-top: 4px; font-size: 10px; opacity: 0.55;
                color: var(--secondary-text-color);
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .asks {
                display: flex; flex-wrap: wrap; gap: 6px 10px;
                align-items: center; margin-top: 8px; font-size: 11px;
            }
            .asks-lbl {
                font-weight: 600; color: var(--secondary-text-color, #8a93a5);
            }
            .ask { display: inline-flex; align-items: center; gap: 3px; }
            .prov { opacity: 0.85; }
            .vtoggle {
                display: inline-flex; border: 1px solid rgba(255,255,255,0.14);
                border-radius: 8px; overflow: hidden; margin-left: 2px;
            }
            .vbtn {
                background: none; border: none; cursor: pointer;
                font-size: 10px; padding: 2px 7px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .vbtn-on {
                background: rgba(131,83,209,0.25); color: var(--primary-text-color, #fff);
            }
            .tmw-track { position: relative; height: 18px; margin-top: 8px; }
            .tmw-sun {
                position: absolute; top: 0; height: 100%;
                background: rgba(255,152,0,0.20); border-radius: 3px;
            }
            .tmw-cheap {
                position: absolute; top: 30%; height: 40%;
                background: rgba(141,200,146,0.5); border-radius: 3px;
            }
            .tmw-sun-key { background: rgba(255,152,0,0.45); }
            .nightband {
                position: absolute; top: 0; height: 100%;
                background: rgba(131,83,209,0.10);
            }
            .nowline {
                position: absolute; top: -2px; height: calc(100% + 4px);
                width: 2px; background: #5BC8D8; opacity: 0.8;
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
    type: 'sem-energy-plan-card',
    name: 'SEM Energy Plan',
    description: 'The joint plan for the energy day — when each demand runs and where the battery hands over',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/main/docs/DASHBOARD_GUIDE.md#sem-energy-plan-card',
});
// Back-compat alias: dashboards generated before the rename still say
// custom:sem-overnight-plan-card — serve them the same card until the
// next generate_dashboard rewrites the YAML.
semDefineCard('sem-overnight-plan-card', class extends SEMEnergyPlanCard {});
