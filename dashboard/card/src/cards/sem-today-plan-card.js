/**
 * SEM Today's Plan Card — forward-looking schedule (#282)
 *
 * Reads sensor.sem_charging_state.attributes.today_plan (computed by the
 * coordinator's compose_today_plan helper) and renders 4-6 transitions
 * for the next ~24h: solar peak, price windows, night opening, EV charge
 * start, Min reached, deadline.
 *
 * Self-hides when the plan is empty (e.g. all rows clipped past horizon
 * or coordinator hasn't computed one yet — keeps the card from showing
 * a hollow shell on first install).
 *
 * Config:
 *   type: custom:sem-today-plan-card
 *   entity: sensor.sem_charging_state   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard, semFormatTime } from '../base/sem-shared.js';

const DEFAULT_ENTITY = 'sensor.sem_charging_state';

// Map row kinds to icon + color. Kinds are stable strings from today_plan.py.
const KINDS = {
    now:                { icon: 'mdi:clock-outline',     color: '#5BC8D8' },
    solar_peak:         { icon: 'mdi:weather-sunny',     color: '#ff9800' },
    solar_end:          { icon: 'mdi:weather-sunset',    color: '#ff9800' },
    cheap_start:        { icon: 'mdi:arrow-down-bold',   color: '#8DC892' },
    cheap_end:          { icon: 'mdi:arrow-up-bold',     color: '#ff9800' },
    expensive_start:    { icon: 'mdi:flash-alert',       color: '#f06292' },
    expensive_end:      { icon: 'mdi:flash-off',         color: '#8DC892' },
    night_open:         { icon: 'mdi:weather-night',     color: '#8353d1' },
    night_end:          { icon: 'mdi:weather-sunset-up', color: '#ff9800' },
    ev_charge_start:    { icon: 'mdi:ev-station',        color: '#8DC892' },
    ev_min_reached:     { icon: 'mdi:battery-charging-80', color: '#4db6ac' },
    ev_target_reached:  { icon: 'mdi:car-electric',      color: '#8DC892' },
    ev_deadline:        { icon: 'mdi:clock-end',         color: '#f06292' },
    ev_wait:            { icon: 'mdi:pause-circle',      color: '#8353d1' },
    // #298 — home battery live ETAs. Pink = charge (matches the SEM
    // colour palette for Battery-In on the diagrams); teal = discharge
    // (Battery-Out). Empty icon is "battery-low" to signal "approaching
    // the floor", not "literally zero".
    battery_full:       { icon: 'mdi:battery-charging-100', color: '#f06292' },
    battery_empty:      { icon: 'mdi:battery-low',       color: '#4db6ac' },
};

class SEMTodayPlanCard extends SEMLitBase {
    setConfig(config) {
        super.setConfig(config);
        this._entity = config.entity || DEFAULT_ENTITY;
    }

    set hass(hass) {
        this._hass = hass;
        const a = hass?.states[this._entity]?.attributes || {};
        const plan = a.today_plan || [];
        // Re-render on plan length / first row time / language change.
        const key = [plan.length, plan[0]?.when, plan.at(-1)?.when, this._lang].join('|');
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
        // Date-aware time formatter. Bug pre-this-fix: stripped to HH:MM
        // only — a tomorrow event for the "Night charging window opens"
        // at 21:33 rendered identically to a past event from today at
        // 21:33. Confusing once today's window is already open and the
        // backend bumps ``night_start`` to the next day's window.
        //
        // Today: ``21:33``
        // Tomorrow: ``Tomorrow 21:33`` (localized via ``_t('tomorrow')``)
        // Further out: ``Wed 21:33`` (HA's locale weekday short)
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            const tz = this._hass?.config?.time_zone || undefined;
            const time = semFormatTime(iso, tz);  // shared locale-aware HH:MM (#485 K6)

            // Compare calendar days only — ignore time-of-day.
            const dDay = d.toDateString();
            const today = new Date();
            if (dDay === today.toDateString()) return time;

            const tomorrow = new Date(today);
            tomorrow.setDate(today.getDate() + 1);
            if (dDay === tomorrow.toDateString()) {
                const label = this._t('tomorrow') || 'Tomorrow';
                return `${label} ${time}`;
            }

            // 2+ days out — show weekday for context.
            const weekday = d.toLocaleDateString([], { weekday: 'short', timeZone: tz });
            return `${weekday} ${time}`;
        } catch (e) {
            return '—';
        }
    }

    _format(key, values) {
        // Pull the localized template, substitute {placeholders}.
        let template = this._t(key);
        if (!template || template === key) return null;
        for (const [k, v] of Object.entries(values || {})) {
            template = template.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
        }
        return template;
    }

    render() {
        if (!this._hass || !this._config) return nothing;
        const e = this._hass.states[this._entity];
        const plan = e?.attributes?.today_plan || [];
        // Empty plan ⇒ self-hide so the card doesn't take space until there's
        // something forward-looking to say.
        if (!Array.isArray(plan) || plan.length <= 1) {
            this.style.display = 'none';
            return nothing;
        }
        this.style.display = '';

        return html`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:calendar-clock" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                        <span class="title">${this._t('today_plan_title')}</span>
                    </div>
                    <ul class="rows">
                        ${plan.map(row => {
                            const k = KINDS[row.kind] || KINDS.now;
                            const label = this._format(row.label, row.values) || row.label;
                            const detail = row.detail ? this._format(row.detail, row.values) : null;
                            return html`
                                <li class="row ${row.kind === 'now' ? 'now' : ''}">
                                    <span class="time">${this._hm(row.when)}</span>
                                    <ha-icon icon="${k.icon}" style="--mdc-icon-size:14px;color:${k.color}"></ha-icon>
                                    <div class="text">
                                        <span class="label">${label}</span>
                                        ${detail ? html`<span class="detail">${detail}</span>` : nothing}
                                    </div>
                                </li>
                            `;
                        })}
                    </ul>
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
                margin-bottom: 8px;
                opacity: 0.85;
            }
            .title {
                font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
                color: var(--primary-text-color);
            }
            .rows { list-style: none; padding: 0; margin: 0; }
            .row {
                display: grid;
                grid-template-columns: 64px 18px 1fr;
                align-items: center; gap: 10px;
                padding: 5px 0;
                font-size: 13px;
                color: var(--primary-text-color);
                border-bottom: 1px dashed rgba(255,255,255,0.04);
            }
            .row:last-child { border-bottom: none; }
            .row.now {
                background: linear-gradient(90deg, rgba(91,200,216,0.10), transparent);
                margin-left: -4px; padding-left: 4px;
                border-radius: 4px;
            }
            .time {
                font-variant-numeric: tabular-nums;
                font-weight: 600;
                color: var(--secondary-text-color);
                font-size: 12px;
            }
            .text { display: flex; flex-direction: column; min-width: 0; }
            .label { font-weight: 500; line-height: 1.2; }
            .detail {
                font-size: 11px; opacity: 0.65; line-height: 1.2;
            }
        `;
    }
}

semDefineCard('sem-today-plan-card', SEMTodayPlanCard, {
    name: "SEM Today's Plan",
    description: 'Forward-looking schedule combining tariff, solar, and EV',
});
