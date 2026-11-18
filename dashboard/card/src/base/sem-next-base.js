/**
 * (#1321) What every SEM Next screen shares: the chrome (tokens mapped to the
 * HA theme, one column under 720 px, two above), the header with its chips
 * and the All-settings switch, the lead line, and the small render helpers
 * the five screens are built from (section, row, segmented control, pill,
 * ring, sparkline, stats, tiles, track, tappable value, button, icon).
 *
 * Reactivity: each screen lists the entity ids it reads in `_watchIds()`;
 * the hass setter re-renders when one of their states or attributes changes
 * (`last_updated` moves for both).
 *
 * Readers: `_num`, `_str`, `_attrs`, `_powerW` give null for an entity that
 * is missing or out; the formatters print an em dash for null. A screen
 * leaves a row out when its entity is missing, never invents a value.
 */

import { SEMLitBase, html, css, svg, nothing } from './sem-lit-base.js';
import { readNumber } from '../util/missing-value.js';
import { fill } from '../util/next-lead.js';
import { plainReason } from '../util/why-rows.js';
import { batterySentence } from '../util/next-battery-line.js';
import { hhmmIn } from '../util/next-time.js';
import { clockWithDay, dayOffset, windowText } from '../util/plan-facts.js';
import { getAllSettings, setAllSettings, VIEW_MODE_EVENT } from '../util/view-mode.js';
import { priceLevelKey, isAbsence } from '../util/price-level.js';
import { fmtPrice } from '../util/next-format.js';
import { fmtNum, setNumberLocale } from '../util/next-number.js';
import { displayName } from '../util/next-names.js';
import { rowText } from '../util/next-settings.js';
import { chargerNameOf } from '../util/charger-name.js';
import { sibling } from '../util/setup-checklist.js';
import { ensureHaElements, haDefined } from '../util/ha-elements.js';
import { renderButton, renderAlert } from '../util/ha-ui.js';

export { html, css, svg, nothing };

// the HA elements these screens draw when they exist
/** (#1321) a phone-width screen: a long row of mode buttons does not fit. */
export function segNarrow() {
    try { return !!globalThis.matchMedia && globalThis.matchMedia('(max-width: 600px)').matches; } catch (_) { return false; }
}

const HA_DRAWN = ['ha-switch', 'ha-control-select', 'ha-button-toggle-group', 'ha-button', 'ha-selector', 'ha-textfield', 'ha-dialog', 'ha-alert'];

// (#1321) the SEM services and entities that move a device: refused while SEM only watches
const WATCH_BLOCKED_SERVICES = new Set(['plan_override', 'plan_override_clear', 'start_battery_boost', 'stop_battery_boost',
    'schedule_appliance', 'cancel_appliance_schedule']);
const WATCH_BLOCKED_ENTITY = /^select\.sem_battery(_.+)?_mode$|_pause_charging$/;

export const NEXT_COLORS = {
    solar: 'var(--energy-solar-color, #ff9800)', grid: 'var(--energy-grid-consumption-color, #488fc2)',
    export: 'var(--energy-grid-return-color, #8353d1)', battery_in: 'var(--energy-battery-in-color, #f06292)',
    battery_out: 'var(--energy-battery-out-color, #4db6ac)', home: 'var(--sem-home-color, #5bc8d8)',
    ev: 'var(--sem-ev-color, #8dc892)',
    accent: 'var(--n-accent)', good: 'var(--n-ok)', warn: 'var(--n-warn)', bad: 'var(--n-bad)',
    fg: 'var(--n-fg)', fg2: 'var(--n-fg2)', fg3: 'var(--n-fg3)',
};

export const nextCss = css`
    :host {
        display: block;
        --n-card: var(--ha-card-background, var(--card-background-color, #ffffff));
        --n-card2: var(--secondary-background-color, #f5f5f5);
        --n-line: var(--divider-color, #e0e0e0);
        --n-fg: var(--primary-text-color, #212121);
        --n-fg2: var(--secondary-text-color, #6b6b6b);
        --n-fg3: var(--secondary-text-color, #6b6b6b);
        --n-accent: var(--primary-color, #03a9f4);
        --n-accent-fg: var(--text-primary-color, #ffffff);
        --n-ok: var(--success-color, #43a047);
        --n-warn: var(--warning-color, #ffa600);
        --n-bad: var(--error-color, #db4437);
        --n-sol: var(--energy-solar-color, #ff9800);
        --n-gin: var(--energy-grid-consumption-color, #488fc2);
        --n-gout: var(--energy-grid-return-color, #8353d1);
        --n-bin: var(--energy-battery-in-color, #f06292);
        --n-bout: var(--energy-battery-out-color, #4db6ac);
        --n-home: var(--sem-home-color, #5bc8d8);
        --n-ev: var(--sem-ev-color, #8dc892);
        /* a panel view zeroes HA's card radius and border: the cards here take the theme's own (read in _themeCards) */
        --n-r: var(--sem-card-radius, 12px);
        --n-bw: var(--sem-card-border-width, 1px);
        --n-bc: var(--sem-card-border-color, var(--divider-color, #e0e0e0));
        --n-ink: var(--sem-on-energy, #10161c);
        --n-ink-dark: var(--sem-on-energy-dark, #ffffff);
        font-size: var(--ha-font-size-m, 14px); line-height: 1.45; color: var(--n-fg);
    }
    * { box-sizing: border-box; }
    ha-card {
        display: block; color: var(--n-fg); background: var(--n-card); border-radius: var(--n-r);
        border: var(--n-bw) solid var(--n-bc);
        box-shadow: var(--ha-card-box-shadow, none);
    }
    .app { container-type: inline-size; max-width: 1180px; margin: 0 auto; padding: 8px 16px 40px; }
    button { font: inherit; color: inherit; }
    :focus-visible { outline: 2px solid var(--n-accent); outline-offset: 2px; }
    /* (#1321) touch: every control is at least 40 px */
    @media (pointer: coarse) {
        .chip, .seg button, .seg.sm button, .btn, .btn.sm, .lnk, button.pill, .dev .gear, .dev .fold { min-height: 40px; }
        .chip { height: 40px; }
        .sw { min-height: 40px; min-width: 40px; }
        select, input[type="time"], input[type="number"], input[type="text"], input.txt { min-height: 40px; }
        ha-control-select, ha-control-select.sm, ha-button-toggle-group { --control-select-thickness: 40px; }
        .dev .rank { width: 40px; height: 40px; }
        .dev .gear, .dev .fold { min-width: 40px; }
    }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
    ha-icon { --mdc-icon-size: 20px; vertical-align: -5px; }
    ha-icon.s { --mdc-icon-size: 16px; vertical-align: -3px; }
    ha-icon.l { --mdc-icon-size: 24px; vertical-align: -6px; }

    /* header: compact pills and the All settings switch, no second title bar */
    .hdr { display: flex; align-items: center; gap: 8px; padding: 4px 0 12px; flex-wrap: wrap; }
    .hdr .sp { margin-right: auto; }
    button.chip { cursor: pointer; }
    /* (#1321) a switcher chip on a phone: looks like the header chips, the phone's own picker opens */
    .pickchip { position: relative; display: inline-flex; align-items: center; height: 40px; border-radius: 20px; background: var(--n-card); border: 1px solid var(--n-line); color: var(--n-fg); max-width: 100%; }
    .pickchip select { appearance: none; -webkit-appearance: none; background: transparent; border: 0; color: inherit; font: inherit; font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500); padding: 0 34px 0 16px; height: 100%; border-radius: 20px; cursor: pointer; max-width: 100%; text-overflow: ellipsis; }
    .pickchip select:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
    .pickchip ha-icon, .pickchip .i { position: absolute; right: 10px; pointer-events: none; color: var(--n-fg2); }
    /* (#1321) choices in a dialog: one row each, the chosen one ticked */
    .choices { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; }
    .choice { display: flex; align-items: center; min-height: 44px; padding: 0 16px 0 44px; border-radius: 12px; border: 1px solid var(--n-line); background: var(--n-card); color: var(--n-fg); font: inherit; font-size: var(--ha-font-size-m, 14px); text-align: left; cursor: pointer; position: relative; }
    .choice::before { content: ""; position: absolute; left: 14px; width: 18px; height: 18px; border-radius: 50%; border: 2px solid var(--n-fg2); box-sizing: border-box; }
    .choice.on { border-color: var(--primary-color, #03a9f4); background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, var(--n-card)); }
    .choice.on::before { border-color: var(--primary-color, #03a9f4); background: radial-gradient(circle, var(--primary-color, #03a9f4) 0 4px, transparent 5px); }
    .choice:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
    select.chip-select { appearance: none; -webkit-appearance: none; height: 40px; border-radius: 20px; border: 1px solid var(--n-line); background: var(--n-card) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E%3Cpath fill='%23888' d='M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z'/%3E%3C/svg%3E") no-repeat right 10px center / 20px; color: var(--n-fg); font: inherit; font-size: var(--ha-font-size-m, 14px); padding: 0 36px 0 16px; max-width: 100%; }
    .chip { display: inline-flex; align-items: center; gap: 6px; padding: 0 12px; height: 32px; border-radius: 16px; background: var(--n-card); border: 1px solid var(--n-line); font-size: var(--ha-font-size-s, 13px); font-weight: var(--ha-font-weight-medium, 500); white-space: nowrap; }
    .chip .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--n-ok); }
    .chip.obs .dot { background: var(--n-warn); }
    .chip ha-icon { --mdc-icon-size: 16px; vertical-align: -3px; }
    .allsw { display: inline-flex; align-items: center; gap: 8px; font-size: var(--ha-font-size-m, 14px); color: var(--n-fg); cursor: pointer; user-select: none; }
    .sw i { width: 36px; height: 14px; border-radius: 7px; background: color-mix(in srgb, var(--n-fg2) 45%, transparent); position: relative; display: inline-block; transition: background .15s; flex: none; }
    .sw i::after { content: ""; position: absolute; top: -3px; left: 0; width: 20px; height: 20px; border-radius: 50%; background: var(--n-fg2); transition: left .15s, background .15s; }
    .sw[aria-checked="true"] i { background: color-mix(in srgb, var(--n-accent) 50%, transparent); }
    .sw[aria-checked="true"] i::after { left: 16px; background: var(--n-accent); }
    .sw { background: none; border: 0; padding: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; font-size: var(--ha-font-size-m, 14px); color: var(--n-fg); user-select: none; }
    .sw[disabled] { opacity: .6; cursor: default; }

    /* screen */
    .lead { font-size: var(--ha-font-size-xl, 20px); font-weight: var(--ha-font-weight-medium, 500); line-height: 1.3; text-wrap: balance; margin: 2px 0; }
    .sub { color: var(--n-fg2); font-size: var(--ha-font-size-m, 14px); margin: 0 0 16px; }
    .grid { display: grid; gap: 16px; grid-template-columns: 1fr; }
    @container (min-width: 720px) { .grid { grid-template-columns: 1fr 1fr; } .span2 { grid-column: 1 / -1; } }
    ha-card.card { padding: 16px; min-width: 0; }
    .card.flat { background: var(--n-card2); }
    .ct { display: flex; align-items: center; gap: 8px; margin: 0 0 12px; flex-wrap: wrap; }
    .ct h3 { font-size: var(--ha-font-size-l, 16px); font-weight: var(--ha-font-weight-medium, 500); color: var(--n-fg); margin: 0; flex: 1 1 auto; min-width: min(100%, max-content); line-height: 1.4; }
    .lnk { font-size: var(--ha-font-size-m, 14px); color: var(--n-accent); font-weight: var(--ha-font-weight-medium, 500); background: none; border: 0; cursor: pointer; padding: 4px 2px; }
    .lbl { font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); font-weight: var(--ha-font-weight-normal, 400); }
    .big { font-size: 22px; font-weight: var(--ha-font-weight-medium, 500); font-variant-numeric: tabular-nums; line-height: 1.1; }
    .big small { white-space: nowrap; font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); font-weight: var(--ha-font-weight-normal, 400); margin-left: 3px; }
    .num { font-variant-numeric: tabular-nums; }
    .muted { color: var(--n-fg2); } .dim { color: var(--n-fg3); } .sm { font-size: var(--ha-font-size-s, 12px); } .xs { font-size: var(--ha-font-size-s, 12px); }
    .ok { color: var(--n-ok); } .warn { color: var(--n-warn); } .bad { color: var(--n-bad); }
    .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .tiles.t3 { grid-template-columns: 1fr 1fr 1fr; }
    .tiles.stack { grid-template-columns: 1fr; }
    .tile { background: transparent; border: 1px solid var(--n-line); border-radius: 8px; padding: 8px 12px; min-width: 0; }
    .tile .lbl { display: block; margin-bottom: 4px; }
    .tile svg { display: block; margin-top: 6px; max-width: 100%; }
    .mark { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; vertical-align: 1px; }
    .seg { display: inline-flex; background: color-mix(in srgb, var(--disabled-color, var(--n-fg2)) 20%, transparent); border-radius: 16px; padding: 2px; gap: 2px; max-width: 100%; overflow-x: auto; scrollbar-width: none; }
    .seg button { border: 0; background: transparent; color: var(--n-fg); font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500); padding: 6px 14px; border-radius: 16px; cursor: pointer; min-height: 32px; white-space: nowrap; display: inline-flex; align-items: center; gap: 4px; }
    .seg button.on { background: var(--n-accent); color: var(--n-accent-fg); }
    .seg button[disabled] { opacity: .6; cursor: default; }
    .seg.off { background: var(--n-card2); }
    .seg.off button { color: var(--n-fg2); cursor: default; }
    .seg.off button.on { background: var(--n-fg2); color: var(--n-card); }
    .seg.sm button { font-size: var(--ha-font-size-s, 13px); padding: 4px 10px; min-height: 28px; }
    ha-control-select, ha-button-toggle-group { --control-select-thickness: 36px; --control-select-border-radius: 16px; width: auto; max-width: 100%; }
    ha-control-select.sm { --control-select-thickness: 32px; --control-select-border-radius: 16px; }
    .rows { display: flex; flex-direction: column; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 0; border-top: 1px solid var(--n-line); min-width: 0; }
    .row:first-child { border-top: 0; }
    .row[role="button"] { cursor: pointer; }
    .row ha-icon { color: var(--state-icon-color, var(--n-fg2)); }
    .row .k { display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1 1 40%; }
    .row .k .t { min-width: 0; overflow-wrap: break-word; }
    .row .k .tx { min-width: 0; flex: 1; }
    .row.ell .k .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .row .v { text-align: right; font-weight: var(--ha-font-weight-medium, 500); flex: 0 1 auto; max-width: 62%; min-width: 0; }
    .row { position: relative; }
    .row .btn, .row .seg, .row ha-control-select, .row ha-button-toggle-group, .row ha-button, .row ha-switch, .row .sw, .row .lnk, .row .val { position: relative; z-index: 1; }
    .row.set { min-height: 48px; }
    /* (#1321) a setting's name wraps like HA's own settings rows; "…" hid
       which entity a row sets on a phone */
    .row.set .k .t { overflow-wrap: anywhere; white-space: normal; }
    .row.set .k { align-items: flex-start; }
    .tx { display: flex; flex-direction: column; min-width: 0; }
    .row .hlp { color: var(--n-fg2); font-weight: var(--ha-font-weight-normal, 400); font-size: var(--ha-font-size-s, 12px); text-wrap: pretty; }
    .row.set .v { color: var(--n-fg2); font-weight: var(--ha-font-weight-normal, 400); }
    .row.set.dirty .v { color: var(--n-accent); font-weight: var(--ha-font-weight-medium, 500); }
    .row.set[aria-disabled="true"] { cursor: default; }
    .row[role="button"]:focus-visible { outline: 2px solid var(--n-accent); outline-offset: -2px; border-radius: 4px; }
    .vbtn { background: none; border: 0; padding: 0; font: inherit; color: inherit; font-weight: inherit; text-align: right; cursor: pointer; }
    .vbtn::before { content: ""; position: absolute; inset: 0; }
    .vbtn:focus-visible { outline: none; }
    .vbtn:focus-visible::before { outline: 2px solid var(--n-accent); outline-offset: -2px; border-radius: 4px; }
    .vbtn[disabled] { cursor: default; }
    .vbtn[disabled]::before { display: none; }
    .ed-body { display: flex; flex-direction: column; gap: 12px; min-width: min(320px, 80vw); padding-top: 4px; }
    .ed-body .ed-help { color: var(--n-fg2); font-size: var(--ha-font-size-s, 12px); }
    .ed-body .ed-pair { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .ed-body input, .ed-body select { max-width: none; width: 100%; box-sizing: border-box; }
    .ed-body ha-textfield, .ed-body ha-selector, .ed-body ha-entity-picker { max-width: none; width: 100%; display: block; }
    /* (#1321) a narrow screen: the value sits under its label, in full width */
    @media (max-width: 600px) {
        /* (#1321) a greyed-out mode row (watch only) wraps instead of hiding
           its last modes behind a scroll */
        .seg { flex-wrap: wrap; overflow-x: visible; }
        .row.stack { flex-wrap: wrap; }
        .row.stack .v { flex: 1 1 100%; max-width: 100%; text-align: left; padding-left: 36px; }
    }
    .row .v small { display: block; color: var(--n-fg2); font-weight: var(--ha-font-weight-normal, 400); font-size: var(--ha-font-size-s, 12px); text-wrap: pretty; }
    .row:has(.btns) { flex-wrap: wrap; }
    .row:has(.btns) .btns { margin-left: auto; }
    .val { background: none; border: 0; padding: 0; font: inherit; color: var(--n-fg); text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 3px; text-decoration-color: var(--n-fg2); text-decoration-thickness: 1.5px; cursor: pointer; font-weight: var(--ha-font-weight-medium, 500); }
    .val[disabled] { cursor: default; opacity: .6; }
    .val { position: relative; }
    .val:not([disabled])::after { content: '✎'; position: absolute; left: 100%; bottom: 0; margin-left: 2px; font-size: .8em; color: var(--n-fg2); opacity: 0; transition: opacity .15s; text-decoration: none; }
    .big .val, .stats .val { font-size: inherit; font-weight: inherit; color: inherit; }
    .big .val[disabled], .stats .val[disabled] { opacity: 1; text-decoration: none; cursor: default; }
    .val:not([disabled]):hover::after, .val:not([disabled]):focus-visible::after { opacity: 1; }
    @media (hover: none) { .val:not([disabled])::after { opacity: .7; } }
    .sent { line-height: 1.6; margin: 0; color: var(--n-fg2); }
    .sent .val { color: var(--n-fg); }
    .btn { border: 1px solid var(--n-line); background: transparent; color: var(--n-accent); border-radius: 20px; padding: 0 16px; font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500); min-height: 40px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; text-decoration: none; }
    .btn.primary { background: var(--n-accent); color: var(--n-accent-fg); border-color: transparent; }
    .btn.ghost { border-color: transparent; }
    .btn.sm { min-height: 32px; padding: 0 12px; font-size: var(--ha-font-size-s, 13px); }
    .btn[disabled] { color: var(--n-fg2); border-color: var(--n-line); background: color-mix(in srgb, var(--n-fg2) 8%, transparent); cursor: default; }
    .btn ha-icon { --mdc-icon-size: 18px; vertical-align: -4px; }
    ha-button ha-icon { --mdc-icon-size: 18px; }
    .btns { display: flex; flex-wrap: wrap; gap: 8px; }
    .track { height: 8px; border-radius: 4px; background: var(--n-card2); position: relative; overflow: visible; }
    .fill { height: 100%; border-radius: 4px; position: absolute; left: 0; top: 0; }
    .pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 16px; font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-medium, 500); background: var(--n-card2); color: var(--n-fg2); white-space: nowrap; max-width: 100%; }
    /* (#1321) a long pill (who gets how much) wraps inside the card instead of running past it */
    .pill { white-space: normal; overflow-wrap: anywhere; }
    .pill.ok { color: var(--n-ok); } .pill.warn { background: color-mix(in srgb, var(--n-warn) 24%, var(--n-card)); color: var(--n-fg); } .pill.warn .dot { background: var(--n-warn); } .pill.bad { color: var(--n-bad); }
    .pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .app:not(.all) [data-more] { display: none !important; }
    .app.all .app-not-all { display: none; }
    .help { font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); margin: 6px 0 0; }
    .hr { border-top: 1px solid var(--n-line); margin: 10px 0; }
    .hint { font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); }
    select, input[type="time"], input[type="number"], input[type="text"], input.txt { font: inherit; color: var(--n-fg); background: var(--n-card2); border: 0; border-bottom: 1px solid var(--n-fg2); border-radius: 4px 4px 0 0; padding: 4px 8px; max-width: 160px; min-height: 32px; }
    select:focus, input:focus { outline: 0; border-bottom: 2px solid var(--n-accent); }
    ha-textfield, ha-selector { max-width: 200px; }
    .sent ha-textfield, .sent ha-selector, .help ha-textfield, .help ha-selector { display: inline-block; vertical-align: middle; max-width: 160px; }

    /* energy bar */
    .ebar { margin: 4px 0 2px; cursor: pointer; }
    .ebar .lane { display: flex; gap: 3px; height: 28px; }
    .ebar .mk { display: flex; align-items: center; justify-content: center; gap: 4px; font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-medium, 500); white-space: nowrap; color: var(--n-fg2); position: relative; min-width: 0; }
    .ebar .mk ha-icon { --mdc-icon-size: 18px; vertical-align: -4px; color: var(--c); }
    .ebar .top .mk::after { content: ""; position: absolute; left: 2px; right: 2px; bottom: -1px; height: 7px; border: 1.5px solid color-mix(in srgb, var(--c) 70%, transparent); border-bottom: 0; border-radius: 6px 6px 0 0; }
    .ebar .bot .mk::before { content: ""; position: absolute; left: 2px; right: 2px; top: -1px; height: 7px; border: 1.5px solid color-mix(in srgb, var(--c) 70%, transparent); border-top: 0; border-radius: 0 0 6px 6px; }
    .ebar .bar { display: flex; height: 38px; border-radius: 19px; overflow: hidden; gap: 2px; background: var(--n-card2); }
    .ebar .sg { display: flex; align-items: center; justify-content: center; font-weight: var(--ha-font-weight-medium, 500); font-size: var(--ha-font-size-m, 14px); color: var(--n-ink); min-width: 0; overflow: hidden; white-space: nowrap; }
    .ebar .sg.dark { color: var(--n-ink-dark); }
    .io { display: grid; grid-template-columns: 1fr; gap: 0 18px; margin-top: 12px; }
    @container (min-width: 720px) { .io { grid-template-columns: 1fr 1fr; } }
    .io .row .k ha-icon { color: var(--c); }

    /* plan strip */
    .strip svg { display: block; width: 100%; }
    .strip .blk { cursor: pointer; }
    .strip .blk:hover rect { stroke-width: 2; }
    .reason { display: flex; gap: 10px; align-items: flex-start; background: var(--n-card2); border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
    .reason ha-icon { color: var(--c); }
    .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); margin-top: 6px; }
    .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
    .lanes { margin-top: 8px; }
    .lanes svg { display: block; width: 100%; max-width: 100%; }

    /* devices */
    .dev { position: relative; }
    .dev .head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
    .dev .rank { width: 26px; height: 26px; border-radius: 8px; background: var(--n-card2); display: flex; align-items: center; justify-content: center; font-size: var(--ha-font-size-s, 12px); font-weight: var(--ha-font-weight-bold, 700); color: var(--n-fg2); flex: 0 0 auto; }
    .dev .name { font-weight: var(--ha-font-weight-medium, 500); font-size: var(--ha-font-size-l, 16px); flex: 1 1 11em; min-width: 8em; display: flex; align-items: center; gap: 6px; }
    .dev .name { flex-wrap: wrap; }
    .dev .name > span:not(.pill) { flex: 1 1 auto; min-width: 7em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dev .name ha-icon, .dev .name .pill { flex: none; }
    .dev .head > .live, .dev .head > .pill { flex: none; }
    .dev .name ha-icon { color: var(--c); }
    .dev .gear { border: 0; background: none; color: var(--n-fg2); cursor: pointer; padding: 4px; border-radius: 8px; }
    .stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 12px 0 10px; }
    .stats .lbl { display: block; }
    .stats .big { font-size: 20px; margin-top: 2px; }
    .stats .sub2 { font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ph { display: inline-flex; gap: 3px; margin-left: 6px; vertical-align: middle; }
    .ph i { width: 10px; height: 3px; border-radius: 2px; background: var(--n-fg3); }
    .ph i.on { background: var(--n-ev); }
    .target { position: relative; height: 14px; border-radius: 7px; background: var(--n-card2); margin: 34px 0 6px; }
    .target .soc { position: absolute; left: 0; top: 0; height: 100%; border-radius: 7px; background: repeating-linear-gradient(135deg, var(--c) 0 6px, color-mix(in srgb, var(--c) 70%, transparent) 6px 12px); }
    .target .band { position: absolute; top: -3px; height: 20px; border: 2px solid var(--n-fg3); border-radius: 6px; opacity: .6; }
    .target .flag { position: absolute; top: -22px; transform: translateX(-50%); font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); white-space: nowrap; }
    .target .flag::after { content: ""; position: absolute; left: 50%; top: 14px; height: 30px; border-left: 1.5px dashed var(--n-fg3); }
    .target .flag.start { transform: none; }
    .target .flag.start::after { left: 0; }
    .target .flag.end { transform: translateX(-100%); }
    .target .flag.end::after { left: 100%; }
    .zones { position: relative; height: 10px; border-radius: 5px; background: linear-gradient(90deg, var(--n-bad) 0 var(--z1, 20%), var(--n-warn) var(--z1, 20%) var(--z2, 50%), var(--n-card2) var(--z2, 50%) 100%); opacity: .9; margin: 26px 0 8px; }
    .zones .z { position: absolute; top: -16px; transform: translateX(-50%); font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); white-space: nowrap; }
    .zones .z.lo { top: 14px; }
    .zones .z.r { transform: translateX(-100%); }
    .zones .z.l { transform: none; }
    .zones.two { margin-bottom: 26px; }
    .zones .cur { position: absolute; top: -4px; width: 4px; height: 18px; border-radius: 2px; background: var(--n-fg); transform: translateX(-50%); }
    .reorder .dev .body { display: none; }
    .reorder .dev { padding: 8px 12px; }
    .reorder .dev .head { margin: 0; }
    .reorder .dev .gear { display: none; }
    .arrows { display: none; gap: 4px; }
    .reorder .arrows { display: inline-flex; }
    .arrows button { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--n-line); background: transparent; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
    .handle { display: none; color: var(--n-fg2); cursor: grab; touch-action: none; }
    .reorder .handle { display: inline-block; }
    .modehelp { font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); margin-top: 6px; }
    .sheet { border-top: 1px dashed var(--n-line); margin-top: 10px; padding-top: 10px; }

    /* charts */
    svg text { font-family: inherit; }
    .chart { display: block; width: 100%; height: auto; }
    .ring { display: flex; align-items: center; gap: 10px; }
    .ring svg { flex: 0 0 auto; margin: 0; }
    .sumrow { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: var(--ha-font-size-s, 12px); color: var(--n-fg2); margin-top: 6px; }
    .sumrow b { color: var(--n-fg); font-weight: var(--ha-font-weight-medium, 500); }
    .sumrow i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
    .flows .row { align-items: stretch; flex-direction: column; gap: 5px; }
    .flows .fh { display: flex; justify-content: space-between; align-items: center; }
    .flows .fb { display: flex; height: 8px; gap: 2px; }
    .flows .fb i { height: 100%; border-radius: 4px; }
    .period { display: flex; gap: 8px; align-items: center; margin: 0 0 12px; flex-wrap: wrap; }

    /* alert fallback (ha-alert is used when HA has it) */
    .alert { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: 4px; border: 1px solid var(--n-accent); background: color-mix(in srgb, var(--n-accent) 12%, var(--n-card)); }
    .alert.warning { border-color: var(--n-warn); background: color-mix(in srgb, var(--n-warn) 12%, var(--n-card)); }
    .alert.error { border-color: var(--n-bad); background: color-mix(in srgb, var(--n-bad) 12%, var(--n-card)); }
    .alert.success { border-color: var(--n-ok); background: color-mix(in srgb, var(--n-ok) 12%, var(--n-card)); }
    .alert .atxt { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .alert .atxt span { color: var(--n-fg2); font-size: var(--ha-font-size-s, 13px); }
    ha-alert { display: block; }
    .aact { display: flex; gap: 8px; flex: none; white-space: nowrap; }
    ha-alert ha-button { white-space: nowrap; min-width: max-content; }

    /* system */
    .group .row { align-items: flex-start; }
    .apply { position: sticky; bottom: 12px; display: flex; align-items: center; gap: 10px; background: var(--n-card); border-radius: var(--n-r); padding: 10px 16px; box-shadow: var(--ha-card-box-shadow, none); margin-top: 16px; border: 1px solid var(--n-line); z-index: 2; }
    .apply span { flex: 1; font-weight: var(--ha-font-weight-medium, 500); }
    .fresh { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
    .fresh .tile { display: flex; align-items: center; gap: 8px; }
    .fresh .tile ha-icon { color: var(--c); }
    :host(.observe) .card { opacity: .92; }
    .more { margin-top: 8px; border-top: 1px solid var(--n-line); }
    .more summary { cursor: pointer; color: var(--n-accent); font-weight: var(--ha-font-weight-medium, 500); padding: 10px 0; list-style: none; display: flex; align-items: center; gap: 4px; min-height: 40px; }
    .more summary::-webkit-details-marker { display: none; }
    .more summary::before { content: '\\25B8'; display: inline-block; transition: transform .15s; }
    .more[open] summary::before { transform: rotate(90deg); }
    /* dialog fallback when ha-dialog is not there */
    .dlg-overlay { position: fixed; inset: 0; background: var(--mdc-dialog-scrim-color, color-mix(in srgb, black 60%, transparent)); z-index: 999; display: flex; align-items: center; justify-content: center; }
    .dlg-box { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px); border: 1px solid var(--divider-color); padding: 24px; min-width: 320px; max-width: 90vw; max-height: 90vh; overflow: auto; color: var(--primary-text-color); }
    .dlg-title { font-weight: var(--ha-font-weight-medium, 500); font-size: var(--ha-font-size-l, 16px); margin-bottom: 16px; }
    /* (#1321) the footer stays in view in a tall dialog: the body scrolls, the buttons do not */
    .dlg-actions { display: flex; gap: 8px; align-items: center; position: sticky; bottom: 0; z-index: 1; padding: 12px 0 0;
        background: var(--ha-dialog-surface-background, var(--mdc-theme-surface, var(--card-background-color, #fff))); }
    .dlg-actions .grow { flex: 1; }
    .toast { position: fixed; left: 16px; right: 16px; margin: 0 auto; width: fit-content; bottom: calc(16px + env(safe-area-inset-bottom, 0px)); z-index: 10;
        max-width: 560px; box-sizing: border-box; display: flex; align-items: flex-start; gap: 8px; padding: 12px 16px; border-radius: 4px;
        background: var(--n-card); color: var(--n-fg); border: 1px solid var(--n-line); border-left: 4px solid var(--n-ok);
        box-shadow: var(--ha-card-box-shadow, none); font-size: var(--ha-font-size-m, 14px); line-height: 1.35; }
    .toast.bad { border-left-color: var(--n-bad); }
    .toast ha-icon { --mdc-icon-size: 18px; flex: none; color: var(--n-ok); }
    .toast.bad ha-icon { color: var(--n-bad); }
`;

export class SEMNextBase extends SEMLitBase {
    static get properties() { return { _all: { state: true }, _toastText: { state: true }, _toastBad: { state: true } }; }

    constructor() {
        super();
        this._prefix = 'sensor.sem_';
        this._key = '';
        this._chargers = [];
        this._all = getAllSettings();
        this._toastText = '';
        this._toastBad = false;
        this._onViewMode = (e) => { this._all = !!(e?.detail?.all ?? getAllSettings()); };
    }

    connectedCallback() {
        super.connectedCallback();
        window.addEventListener(VIEW_MODE_EVENT, this._onViewMode);
        this._wantHaElements();
        this._themeCards();
    }

    /** A panel view sets HA's card radius and border to 0; the cards here take the theme's own values. */
    _themeCards() {
        try {
            const root = getComputedStyle(document.documentElement);
            for (const [from, to] of [['--ha-card-border-radius', '--sem-card-radius'], ['--ha-card-border-width', '--sem-card-border-width'],
                                      ['--ha-card-border-color', '--sem-card-border-color']]) {
                const v = String(root.getPropertyValue(from) || '').trim();
                if (v && this.style && this.style.setProperty) this.style.setProperty(to, v);
            }
        } catch (e) { /* the fallbacks in the CSS stay */ }
    }

    /** (#1321) HA's lazy form elements: draw them once they exist (native ones until then). */
    async _wantHaElements() {
        const before = HA_DRAWN.filter(haDefined).length;
        try { await ensureHaElements(HA_DRAWN); } catch (e) { /* native fallbacks stay */ }
        if (HA_DRAWN.filter(haDefined).length !== before) this.requestUpdate();
    }

    disconnectedCallback() {
        window.removeEventListener(VIEW_MODE_EVENT, this._onViewMode);
        clearTimeout(this._toastTimer);
        super.disconnectedCallback();
    }

    setConfig(config) {
        super.setConfig(config || {});
    }

    /** Entity ids whose state or attributes drive a re-render. Screens extend it. */
    _watchIds() {
        return ['switch.sem_observer_mode', 'sensor.sem_night_start_time', 'sensor.sem_night_end_time',
                'sensor.sem_battery_soc', 'sensor.sem_tariff_current_import_rate', 'sensor.sem_tariff_price_level'];
    }

    set hass(hass) {
        this._hass = hass;
        if (!hass) return;
        setNumberLocale(hass);
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

    /** Chargers from the per-charger power sensors (skip the flow sensors). */
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

    // ── readers ──
    _has(id) { return !!this._hass?.states?.[id]; }
    _num(id) { return readNumber(this._hass?.states[id]); }
    _str(id) {
        const e = this._hass?.states[id];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }
    _attrs(id) { return this._hass?.states[id]?.attributes || {}; }
    _name(id) {
        const n = this._hass?.states[id]?.attributes?.friendly_name;
        return displayName(this._hass, { name: n ? String(n).replace(/^SEM\s+/i, '') : '', entity: id });
    }
    /** (#1321) a load's name for every screen: SEM name, HA device name, cleaned friendly name. */
    _loadName(id, d) { return displayName(this._hass, { name: d?.name, entity: d?.power_entity, id: String(id) }); }
    _observer() { return this._str('switch.sem_observer_mode') === 'on'; }
    _obs() { return this._observer(); }

    /**
     * (#1321) Watch-only mode: SEM's own settings stay editable (the classic
     * Configuration card never locked them); a write that moves a device is
     * refused. Checked where the write leaves, so no screen can skip it.
     * Device writes: SEM's one-off actions, the battery's mode, and any
     * entity that is not SEM's own.
     */
    _writeBlocked(domain, service, data) {
        if (!this._observer()) return false;
        const d = String(domain || '');
        if (d === 'solar_energy_management') return WATCH_BLOCKED_SERVICES.has(String(service));
        const ids = [].concat((data && data.entity_id) || []);
        if (!ids.length) return true;
        return !ids.every((id) => String(id).startsWith(d + '.sem_') && !WATCH_BLOCKED_ENTITY.test(String(id)));
    }
    /** A control for a device write is disabled while watching; `entity` is what it writes. */
    _devOff(entity, domain = 'select') {
        return this._writeBlocked(domain, 'x', { entity_id: entity });
    }
    /** Every write of the SEM Next screens goes through here (hass.callService, guarded). */
    _call(domain, service, data, ...rest) {
        if (this._writeBlocked(domain, service, data)) return Promise.reject(new Error(this._t('next_disabled_watching')));
        return this._hass.callService(domain, service, data, ...rest);
    }
    /** All settings on? Read `this._all` (a reactive property); flip it with `_toggleAll()`. */
    _toggleAll() { setAllSettings(!this._all); }
    _clock() { return hhmmIn(new Date(), this._hass?.config?.time_zone); }
    _night() {
        const s = this._str('sensor.sem_night_start_time'), e = this._str('sensor.sem_night_end_time');
        if (!s || !e) return false;
        const now = this._clock();
        return s > e ? (now >= s || now < e) : (now >= s && now < e);
    }
    _chargerName(cid) {
        const n = this._chargers.indexOf(cid);
        return chargerNameOf(this._hass?.states, cid, 'sensor.sem_', n >= 0 ? `${this._t('config_detect_charger')} ${n + 1}` : '');
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
    _currency() {
        const c = this._hass?.config?.currency;
        return c || 'CHF';
    }
    _tf(key, params) { return fill(this._t(key), params, (k) => this._t(k)); }
    /** (#1321) A temperature in the user's unit (payloads are °C). */
    _temp(c) {
        const unit = this._hass?.config?.unit_system?.temperature || '°C';
        const v = unit === '°F' ? Number(c) * 9 / 5 + 32 : Number(c);
        return fmtNum(Math.round(v * 10) / 10, 1) + '\u00a0' + unit;
    }
    _moreInfo(entityId) { this._fireMoreInfo(entityId); }
    /** The path of another screen of this dashboard, from the page we are on (#1321). */
    _screen(view) { return sibling(window.location.pathname, view); }
    /** Navigate inside HA without a reload. */
    _go(path) {
        window.history.pushState(null, '', path);
        window.dispatchEvent(new CustomEvent('location-changed', { bubbles: true, composed: true }));
    }

    // ── formatting ──
    // (#1321) every number goes through fmtNum: the user's locale, units kept
    _fmtKw(w, d = 1) { return w === null || !Number.isFinite(w) ? '—' : fmtNum(w / 1000, d); }
    _fmt(v, d = 1) { return fmtNum(v, d); }
    /**
     * (#1321) A reason in words for a decision that stands NOW: it never says the battery
     * level is unknown while the chip reads it. A past record keeps what it said then.
     */
    _plainNow(rec, t = (k) => this._t(k)) {
        const soc = this._num('sensor.sem_battery_soc');
        return plainReason(rec, t, { soc: soc === null ? NaN : soc, battery: batterySentence(this._hass?.states, t) });
    }
    _int(v) { return fmtNum(Math.round(Number(v)), 0); }
    _kw(w, d = 1) { return w === null || !Number.isFinite(w) ? '—' : `${fmtNum(w / 1000, d)} kW`; }
    /** A power as the screens say it: kW from 1 kW up, else W (#1321). */
    _power(w) { return w === null || !Number.isFinite(w) ? '—' : (Math.abs(w) >= 1000 ? this._kw(w) : `${fmtNum(Math.round(w), 0)} W`); }
    _kwh(v, d = 1) { return v === null || !Number.isFinite(Number(v)) ? '—' : `${Number(v) >= 100 ? fmtNum(Math.round(v), 0) : fmtNum(v, d)} kWh`; }
    _price(v) { return fmtPrice(v); }
    _money(v, d = 2) { return v === null || !Number.isFinite(Number(v)) ? '—' : `${fmtNum(v, d)} ${this._currency()}`; }
    _pct(v) { return v === null || !Number.isFinite(Number(v)) ? '—' : `${fmtNum(Math.round(v), 0)} %`; }
    /** 'HH:MM' from a Date, an ISO stamp, or an 'HH:MM[:SS]' string. */
    _hhmm(x) {
        if (x === null || x === undefined || x === '') return '';
        if (typeof x === 'string' && /^\d{1,2}:\d{2}/.test(x)) return x.slice(0, 5);
        const d = x instanceof Date ? x : new Date(Date.parse(x));
        if (!Number.isFinite(d.getTime())) return String(x);
        return hhmmIn(d, this._hass?.config?.time_zone);
    }
    /** (#1321) A clock time with its day when it is not today: never a future hour that reads as a past one. */
    _clockDay(x, nowMs = Date.now()) {
        const ms = typeof x === 'number' ? x : Date.parse(x instanceof Date ? x.toISOString() : x);
        if (!Number.isFinite(ms)) return this._hhmm(x);
        return clockWithDay(ms, nowMs, this._hass?.config?.time_zone, { tomorrow: this._t('next_when_tomorrow') }, this._weekdayOf());
    }
    /** (#1321) A CO2 total in ONE format on every screen: whole kg, tonnes from 1000 kg. */
    _co2Text(kg, unit) { return unit === 'kg' && kg >= 1000 ? `${this._fmt(kg / 1000, 1)} t` : `${this._fmt(Math.round(kg), 0)} ${unit}`; }
    /** (#1321) "at 07:30" today, "tomorrow at 07:30" or "Fri at 07:30" another day: never "at tomorrow 07:30". */
    _atWhen(ms, nowMs = Date.now()) {
        const tz = this._hass?.config?.time_zone;
        const off = dayOffset(ms, nowMs, tz);
        const time = hhmmIn(new Date(ms), tz);
        if (off === 0 || off < 0) return this._tf('next_batt_end_sub', { time });
        return this._tf('next_at_day_time', { day: off === 1 ? this._t('next_when_tomorrow') : this._weekdayOf()(ms), time });
    }
    _winText(s, e, nowMs = Date.now()) {
        return windowText(s, e, nowMs, this._hass?.config?.time_zone, { tomorrow: this._t('next_when_tomorrow') }, this._weekdayOf());
    }
    _weekdayOf() {
        const lang = this._hass?.language || 'en', tz = this._hass?.config?.time_zone;
        return (ms) => { try { return new Date(ms).toLocaleDateString(lang, { weekday: 'short', timeZone: tz || undefined }); } catch (e) { return ''; } };
    }
    /** 12 s · 4 min · 2 h */
    _ago(iso, nowMs = Date.now()) {
        const t = Date.parse(iso || '');
        if (!Number.isFinite(t)) return '';
        const s = Math.max(0, (nowMs - t) / 1000);
        if (s < 90) return `${Math.round(s)} s`;
        if (s < 5400) return `${Math.round(s / 60)} min`;
        return `${Math.round(s / 3600)} h`;
    }

    // ── render helpers ──
    _icon(mdi, cls = '') { return html`<ha-icon class="${cls}" icon="${mdi}"></ha-icon>`; }

    _renderHead() {
        const obs = this._observer();
        const soc = this._num('sensor.sem_battery_soc');
        const rate = this._num('sensor.sem_tariff_current_import_rate');
        const level = this._str('sensor.sem_tariff_price_level');
        const flat = !level || isAbsence(level);
        const all = haDefined('ha-switch')
            ? html`<label class="allsw"><ha-switch .checked=${this._all} @change=${(e) => { if (!!e.target.checked !== this._all) this._toggleAll(); }}></ha-switch>${this._t('next_all_settings')}</label>`
            : html`<button type="button" class="sw" role="switch" aria-checked="${this._all}" @click=${() => this._toggleAll()}><i></i>${this._t('next_all_settings')}</button>`;
        return html`
            <header class="hdr">
                ${soc === null ? nothing : html`<button type="button" class="chip" @click=${() => this._moreInfo('sensor.sem_battery_soc')}>${this._icon('mdi:battery-medium')}${this._int(soc)} %</button>`}
                ${rate === null || flat ? nothing : html`<button type="button" class="chip" @click=${() => this._moreInfo('sensor.sem_tariff_current_import_rate')}>${this._icon('mdi:cash')}${this._price(rate)} ${this._currency()}/kWh <span class="dim">· ${this._t(priceLevelKey(level))}</span></button>`}
                <span class="chip ${obs ? 'obs' : ''}"><span class="dot"></span>${obs ? this._t('next_pill_observing') : this._t('next_pill_live')}</span>
                <span class="sp"></span>
                ${all}
            </header>`;
    }

    _renderLead(main, sub) {
        return html`<h1 class="lead">${main}</h1>${sub ? html`<p class="sub">${sub}</p>` : html`<p class="sub"></p>`}`;
    }

    /** The outer frame every screen renders into: header, lead, then the body of ha-cards. */
    _frame(lead, body) {
        return html`<div class="app ${this._all ? 'all' : ''}">
            ${this._renderHead()}
            ${lead ? this._renderLead(lead.main, lead.sub) : nothing}
            ${body}
        </div>
        ${this._toastText ? html`<div class="toast ${this._toastBad ? 'bad' : ''}" role=${this._toastBad ? 'alert' : 'status'}>
            ${this._icon(this._toastBad ? 'mdi:alert-circle-outline' : 'mdi:check-circle-outline')}<span>${this._toastText}</span></div>` : nothing}`;
    }

    /**
     * One message near the button the user pressed. HA's own snackbar when
     * its notification manager exists (event `hass-notification`); the small
     * message in the card otherwise.
     */
    _toast(text, bad = false, ms = bad ? 8000 : 2500) {
        const message = String(text || '');
        if (message && haDefined('notification-manager') && typeof this.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
            this.dispatchEvent(new CustomEvent('hass-notification', { detail: { message, duration: ms }, bubbles: true, composed: true }));
            this._toastText = '';
            this._toastBad = !!bad;
            return;
        }
        this._toastText = message;
        this._toastBad = !!bad;
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => { this._toastText = ''; }, ms);
    }

    _failed(err) {
        const msg = (err && err.message) ? String(err.message) : String(err || '');
        this._toast(msg || this._t('next_apply_failed'), true);
    }

    /** true when Home Assistant accepted the call; a refusal is shown, never swallowed. */
    async _callService(domain, service, data) {
        if (!this._hass) return false;
        try {
            await this._call(domain, service, data, undefined, false);
            return true;
        } catch (err) {
            console.error(`[SEM ${this.tagName}]`, domain + '.' + service, err);
            this._failed(err);
            return false;
        }
    }

    _sec(title, body, o = {}) {
        return html`<ha-card class="card ${o.cls || ''}">
            ${title || o.extra ? html`<div class="ct"><h3>${title || ''}</h3>${o.extra || nothing}</div>` : nothing}
            ${body}</ha-card>`;
    }

    _link(label, onClick) { return html`<button type="button" class="lnk" @click=${onClick}>${label}</button>`; }

    /** One row. o = { color, onClick, more, cls, help } — more hides it unless All settings is on; help puts the sub line under the label. */
    _row(icon, text, value, sub, o = {}) {
        const click = o.onClick || null;
        const help = o.help && sub ? html`<small class="hlp">${sub}</small>` : nothing;
        return html`<div class="row ${o.cls || ''}" style="${o.color ? `--c:${o.color}` : ''}" ?data-more=${!!o.more}
                role="${click ? 'button' : nothing}" tabindex="${click ? 0 : nothing}"
                @click=${click || nothing} @keydown=${click ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); click(e); } } : nothing}>
            <div class="k">${icon ? this._icon(icon) : nothing}<div class="tx"><span class="t">${text}</span>${help}</div></div>
            <div class="v">${value ?? ''}${sub && !o.help ? html`<small>${sub}</small>` : nothing}</div></div>`;
    }

    /**
     * items = [{key, label, icon?, disabled?}]. HA's ha-control-select (or
     * ha-button-toggle-group) when defined, native buttons otherwise.
     */
    _seg(items, current, onPick, o = {}) {
        const cur = current === null || current === undefined ? '' : String(current);
        const pick = (v) => {
            const it = items.find((x) => String(x.key) === String(v));
            if (it && !it.disabled && String(v) !== cur) onPick(it.key);
        };
        // (#1321) many modes on a phone: a row of buttons cuts each label to
        // "Solar +…", so a dropdown names every mode in full instead
        if (items.length > 4 && !o.disabled && segNarrow()) {
            return this._pickChip(items.filter((it) => !it.disabled).map((it) => ({ value: String(it.key), label: it.label })),
                cur, (v) => pick(v), { ariaLabel: o.label || '' });
        }
        // HA's disabled look fades the labels to nothing, so a disabled control is the native one in readable colours
        if (haDefined('ha-control-select') && !o.disabled) {
            const options = items.map((it) => ({ value: String(it.key), label: it.label, disabled: !!it.disabled }));
            // each option gets room for one line of label (the control's own width is only its parent's)
            return html`<ha-control-select class="${o.small ? 'sm' : ''}" style="min-width:min(100%, ${items.length * (o.small ? 6.5 : 5.5)}em)" .options=${options} .value=${cur} ?disabled=${!!o.disabled}
                @value-changed=${(e) => pick(e.detail?.value)}></ha-control-select>`;
        }
        if (haDefined('ha-button-toggle-group') && !o.disabled) {
            const buttons = items.map((it) => ({ label: it.label, value: String(it.key) }));
            return html`<ha-button-toggle-group size="${o.small ? 'small' : 'medium'}" .buttons=${buttons} .active=${cur} ?disabled=${!!o.disabled}
                @value-changed=${(e) => pick(e.detail?.value)}></ha-button-toggle-group>`;
        }
        return html`<div class="seg ${o.small ? 'sm' : ''} ${o.disabled ? 'off' : ''}" role="group" title="${this._whyOff(o.disabled) || nothing}">
            ${items.map((it) => html`<button type="button" class="${String(it.key) === cur ? 'on' : ''}" ?disabled=${!!it.disabled || !!o.disabled}
                aria-pressed="${String(it.key) === cur}" @click=${() => onPick(it.key)}>${it.icon ? this._icon(it.icon, 's') : nothing}${it.label}</button>`)}
        </div>`;
    }

    /** A switch: ha-switch when defined, else a native switch button. */
    _switch(on, onChange, o = {}) {
        if (haDefined('ha-switch')) {
            return html`<ha-switch class="${o.cls || ''}" .checked=${!!on} ?disabled=${!!o.disabled} aria-label="${o.label || nothing}"
                @change=${(e) => onChange(!!e.target.checked)}></ha-switch>`;
        }
        return html`<button type="button" class="sw ${o.cls || ''}" role="switch" aria-checked="${!!on}" aria-label="${o.label || nothing}"
            ?disabled=${!!o.disabled} @click=${() => onChange(!on)}><i></i></button>`;
    }

    /**
     * A one-line field (text, number, time): ha-textfield when defined, else a
     * native input. o = { type, value, placeholder, min, max, step, cls, label,
     * disabled, onInput, onChange, onKeydown, onBlur }.
     */
    _input(o = {}) {
        const type = o.type || 'text';
        const v = o.value === null || o.value === undefined ? '' : String(o.value);
        const tag = haDefined('ha-textfield') ? 'ha-textfield' : 'input';
        if (tag === 'ha-textfield') {
            return html`<ha-textfield class="${o.cls || ''}" type="${type}" .value=${v} placeholder="${o.placeholder ?? nothing}" aria-label="${o.label || nothing}"
                min="${o.min ?? nothing}" max="${o.max ?? nothing}" step="${o.step ?? nothing}" ?disabled=${!!o.disabled}
                @input=${o.onInput || nothing} @change=${o.onChange || nothing} @keydown=${o.onKeydown || nothing} @blur=${o.onBlur || nothing}></ha-textfield>`;
        }
        return html`<input class="${o.cls || ''}" type="${type}" .value=${v} placeholder="${o.placeholder ?? nothing}" aria-label="${o.label || nothing}"
            min="${o.min ?? nothing}" max="${o.max ?? nothing}" step="${o.step ?? nothing}" ?disabled=${!!o.disabled}
            @input=${o.onInput || nothing} @change=${o.onChange || nothing} @keydown=${o.onKeydown || nothing} @blur=${o.onBlur || nothing}>`;
    }

    /**
     * A choice list: ha-selector (select) when defined, else a native select.
     * options = [{ value, label }]. o = { onKeydown, onBlur, label, disabled }.
     * A selector opens a menu that takes focus, so it gets no blur handler.
     */
    _select(options, value, onChange, o = {}) {
        const cur = value === null || value === undefined ? '' : String(value);
        // (#1321) every choice list on a screen is the rounded chip; HA's grey
        // form field with its clear "×" looked out of place among the cards
        if (!o.disabled && !o.onKeydown && !o.onBlur) return this._pickChip(options, value, onChange, o);
        if (haDefined('ha-selector') && this._hass) {
            const selector = { select: { mode: 'dropdown', options: options.map((x) => ({ value: String(x.value), label: x.label })) } };
            // (#1321) a required field draws an asterisk after its label; the topic switch names itself for readers instead
            return html`<ha-selector .hass=${this._hass} .selector=${selector} .value=${cur} .label=${o.label || ''} .required=${!!o.required} aria-label=${o.ariaLabel || nothing} ?disabled=${!!o.disabled}
                @value-changed=${(e) => { const v = e.detail?.value; if (v !== undefined && String(v) !== cur) onChange(String(v)); }}
                @keydown=${o.onKeydown || nothing}></ha-selector>`;
        }
        return html`<select aria-label="${o.label || o.ariaLabel || nothing}" ?disabled=${!!o.disabled} @change=${(e) => onChange(e.target.value)}
            @keydown=${o.onKeydown || nothing} @blur=${o.onBlur || nothing}>
            ${options.map((x) => html`<option value=${x.value} ?selected=${String(x.value) === cur}>${x.label}</option>`)}</select>`;
    }

    /**
     * (#1321) A switcher on a phone: a rounded chip "Today ▾" in the look of
     * the header chips. Tapping it opens the phone's own picker. HA's form
     * field (grey box, clear ×) stays for settings dialogs only.
     */
    _pickChip(options, value, onChange, o = {}) {
        const cur = value === null || value === undefined ? '' : String(value);
        return html`<label class="pickchip">
            <select aria-label="${o.ariaLabel || o.label || nothing}" @change=${(e) => { if (e.target.value !== cur) onChange(e.target.value); }}>
                ${options.map((x) => html`<option value=${x.value} ?selected=${String(x.value) === cur}>${x.label}</option>`)}
            </select>${this._icon('mdi:chevron-down', 's')}</label>`;
    }

    _pill(text, cls = '', o = {}) {
        return html`<span class="pill ${cls}">${o.icon ? this._icon(o.icon, 's') : html`<span class="dot"></span>`}${text}</span>`;
    }

    _ring(pct, color, size = 56, label = '') {
        const p = Math.max(0, Math.min(100, Number(pct) || 0));
        const r = (size - 8) / 2, c = 2 * Math.PI * r;
        return svg`<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${label || p + ' %'}">
            <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--n-card2)" stroke-width="6"></circle>
            <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
                stroke-dasharray="${c * p / 100} ${c}" transform="rotate(-90 ${size / 2} ${size / 2})"></circle>
            <text x="50%" y="50%" dy="5" text-anchor="middle" font-size="14" font-weight="500" fill="var(--n-fg)">${Math.round(p)} %</text></svg>`;
    }

    _spark(vals, color, w = 80, h = 24) {
        const v = (vals || []).map((x) => (Number.isFinite(Number(x)) ? Number(x) : 0));
        if (v.length < 2) return nothing;
        const mx = Math.max(...v) || 1, n = v.length;
        const pts = v.map((y, i) => [i / (n - 1) * w, h - 2 - (y / mx) * (h - 4)]);
        const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
        return svg`<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
            <path d="${d} L${w} ${h} L0 ${h} Z" fill="${color}" opacity=".18"></path>
            <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"></path>
            <circle cx="${pts[n - 1][0]}" cy="${pts[n - 1][1]}" r="2.5" fill="${color}"></circle></svg>`;
    }

    /** items = [[label, value, sub]] */
    _stats(items) {
        return html`<div class="stats">${items.map((s) => html`<div><span class="lbl">${s[0]}</span><div class="big num">${s[1]}</div><div class="sub2">${s[2] || ''}</div></div>`)}</div>`;
    }

    /** items = [{label, value, unit, sub, color, valueColor, extra}] */
    _tiles(items, o = {}) {
        return html`<div class="tiles ${o.stack ? 'stack' : o.three ? 't3' : ''}">${items.map((t) => html`<div class="tile ${t.cls || ''}">
            <span class="lbl">${t.color ? html`<i class="mark" style="background:${t.color}"></i>` : nothing}${t.label}</span>
            <div class="big" style="${t.valueColor ? `color:${t.valueColor}` : ''}">${t.value}${t.unit ? html`<small>${t.unit}</small>` : nothing}</div>
            ${t.sub ? html`<div class="xs dim">${typeof t.sub === 'string' ? t.sub.replace(/(\d) (kW|kWh|W|A|%)/g, '$1\u00a0$2') : t.sub}</div>` : nothing}${t.extra || nothing}</div>`)}</div>`;
    }

    _track(pct, color) {
        const p = Math.max(0, Math.min(100, Number(pct) || 0));
        return html`<div class="track"><div class="fill" style="width:${p}%;background:${color}"></div></div>`;
    }

    _val(text, onTap, o = {}) {
        return html`<button type="button" class="val" ?disabled=${!!o.disabled} @click=${onTap}>${text}</button>`;
    }


    /**
     * (#1321) A settings row, as Home Assistant draws them: the label left, the
     * value right, one line of help under the label. A tap (or Enter, Space)
     * opens the editor; a boolean is a switch on the row, no dialog.
     * o = { label, value, help, onTap, toggle: { on, onChange }, disabled, ro, dirty, more }.
     */
    _setRow(o0) {
        // (#1321) blocked = a device write while SEM only watches: disabled, with the reason under the label
        const o = o0.blocked ? { ...o0, disabled: true, help: this._t('next_disabled_watching') } : o0;
        const tog = o.toggle || null;
        const tap = !tog && !o.ro && !o.disabled && typeof o.onTap === 'function' ? o.onTap : null;
        const body = tog ? this._switch(tog.on, tog.onChange, { label: o.label, disabled: o.disabled }) : (o.value ?? '');
        return html`<div class="row set ${o.dirty ? 'dirty' : ''}" ?data-more=${!!o.more}
                role="${tap ? 'button' : nothing}" tabindex="${tap ? 0 : nothing}" aria-label="${tap ? `${o.label}: ${typeof o.value === 'string' ? o.value : ''}` : nothing}"
                aria-disabled="${o.disabled && !tog ? 'true' : nothing}"
                @click=${tap || nothing} @keydown=${tap ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tap(e); } } : nothing}>
            <div class="k"><div class="tx"><span class="t" title="${o.label}">${o.label}</span>${o.help ? html`<small class="hlp">${o.help}</small>` : nothing}</div></div>
            <div class="v">${body}</div></div>`;
    }

    /** (#1321) A row label from a translation key: sentence case, no unit in brackets. */
    _lbl(key) { return rowText(this._t(key)); }

    /** (#1321) A value that opens its editor; its hit area is the whole row (see .vbtn). */
    _vbtn(text, onTap, o = {}) {
        return html`<button type="button" class="vbtn" ?disabled=${!!o.disabled} @click=${onTap}>${text}</button>`;
    }

    /**
     * (#1321) The one editing dialog of every settings row. spec = { title, help, kind
     * (number | text | time | select | entity | pair), value, min, max, step, unit, placeholder,
     * options [{ value, label }], domains, deviceClasses, filter, allowClear, a, b (pair), onCommit }.
     * Draws HA's ha-textfield / ha-selector / ha-entity-picker when defined, the styled
     * native field otherwise. OK commits (a blank number commits nothing); Escape and Cancel
     * close. Returns { el, close }.
     */
    async _editDialog(spec) {
        const t = (k) => this._t(k);
        if (spec.kind === 'entity') await ensureHaElements(['ha-entity-picker'], 3000);
        const esc = (x) => String(x ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        const btn = (id, label, slot, kind, dlg) => (dlg
            ? `<ha-button id="${id}" appearance="${kind}">${esc(label)}</ha-button>`
            : `<button type="button" id="${id}" class="btn ${kind === 'filled' ? 'primary' : 'ghost'}">${esc(label)}</button>`);
        const none = spec.allowClear && spec.value ? (d) => btn('ed-none', t('action_none'), 'secondaryAction', 'plain', d) : () => '';
        const { el, close } = this._dialog({
            id: 'sem-edit-dlg', title: spec.title || '',
            build: (d) => (d
                ? `<div class="ed-body"></div><div class="dlg-actions" style="display:flex;gap:8px;justify-content:flex-end;align-items:center;margin-top:16px">${none(true)}<div class="grow" style="flex:1"></div>${btn('ed-cancel', t('next_cancel'), '', 'plain', true)}${btn('ed-ok', t('next_ok'), '', 'filled', true)}</div>`
                : `<div class="dlg-box"><div class="dlg-title">${esc(spec.title)}</div><div class="ed-body"></div>
                    <div class="dlg-actions">${none(false)}<div class="grow"></div>${btn('ed-cancel', t('next_cancel'), '', 'plain', false)}${btn('ed-ok', t('next_ok'), '', 'filled', false)}</div></div>`),
        });
        const body = el.querySelector('.ed-body');
        const fields = (spec.kind === 'pair' ? [{ ...spec.a, kind: 'number', unit: '' }, { ...spec.b, kind: 'number', unit: spec.unit }] : [spec])
            .map((f) => this._editField(f, () => this._editOk(spec, fields, close)));
        if (spec.help && body) {
            const h = document.createElement('div');
            h.className = 'ed-help'; h.textContent = spec.help;
            body.appendChild(h);
        }
        for (const f of fields) if (body && f.el) body.appendChild(f.el);
        el.querySelector('#ed-ok')?.addEventListener('click', () => this._editOk(spec, fields, close));
        el.querySelector('#ed-cancel')?.addEventListener('click', () => close());
        el.querySelector('#ed-none')?.addEventListener('click', () => { close(); spec.onCommit(''); });
        const first = fields[0];
        if (first && typeof first.focus === 'function') first.focus();
        else if (first && first.el && typeof first.el.focus === 'function') first.el.focus();
        return { el, close };
    }

    /**
     * (#1321) Every action that changes what SEM does asks first. A tap opens
     * this dialog; only the confirm button runs `run`. Cancel, Escape and a
     * click outside call nothing. spec = { title, body, okLabel, run }.
     */
    _confirmDo(spec) {
        const t = (k) => this._t(k);
        const esc = (x) => String(x ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        const ok = spec.okLabel || t('next_yes');
        const { el, close } = this._dialog({
            id: 'sem-confirm-dlg', title: spec.title || '',
            build: (d) => (d
                ? `<div class="ed-help">${esc(spec.body)}</div><div class="dlg-actions" style="display:flex;gap:8px;justify-content:flex-end;align-items:center;margin-top:16px"><ha-button id="cf-cancel" appearance="plain">${esc(t('next_cancel'))}</ha-button><ha-button id="cf-ok" appearance="filled">${esc(ok)}</ha-button></div>`
                : `<div class="dlg-box"><div class="dlg-title">${esc(spec.title)}</div><div class="ed-help">${esc(spec.body)}</div>
                    <div class="dlg-actions"><div class="grow"></div><button type="button" id="cf-cancel" class="btn ghost">${esc(t('next_cancel'))}</button><button type="button" id="cf-ok" class="btn primary">${esc(ok)}</button></div></div>`),
        });
        el.querySelector('#cf-cancel')?.addEventListener('click', () => close());
        el.querySelector('#cf-ok')?.addEventListener('click', () => { close(); spec.run(); });
        return { el, close };
    }

    /** The words of a confirm for an action named `label`: "Replan?" and what a yes does. */
    _askFirst(label, run, o = {}) {
        this._confirmDo({ title: o.title || this._tf('next_confirm_title', { action: label }), body: o.body || this._t('next_confirm_body'),
            okLabel: o.okLabel || label, run });
    }

    /** Commit what the dialog holds, once; a blank number or an unchanged value commits nothing. */
    _editOk(spec, fields, close) {
        const vals = fields.map((f) => f.get());
        close();
        if (spec.kind === 'pair') {
            const [a, b] = vals.map((v) => (Number.isFinite(v) ? v : null));
            if (a !== null || b !== null) spec.onCommit(a, b);
        } else if (spec.kind === 'number') {
            // (#1321) inside the setting's own range, as the staged settings are; blank = no change
            const lo = Number(spec.min), hi = Number(spec.max);
            let v = vals[0];
            if (Number.isFinite(v)) {
                if (spec.min !== undefined && spec.min !== null && spec.min !== '' && Number.isFinite(lo)) v = Math.max(lo, v);
                if (spec.max !== undefined && spec.max !== null && spec.max !== '' && Number.isFinite(hi)) v = Math.min(hi, v);
                if (v !== Number(spec.value)) spec.onCommit(v);
            }
        } else if (spec.kind === 'text' || spec.kind === 'time') {
            if (spec.kind === 'text' || vals[0]) if (String(vals[0]) !== String(spec.value ?? '')) spec.onCommit(vals[0]);
        } else if (String(vals[0] ?? '') !== String(spec.value ?? '')) spec.onCommit(vals[0]);
    }

    /** One field of the edit dialog: { el, get() }. */
    _editField(f, submit) {
        const cur = f.value === null || f.value === undefined ? '' : f.value;
        const keys = (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } };
        if (f.kind === 'select') {
            let v = String(cur);
            const opts = f.options || [];
            if (opts.length <= 8) {
                // (#1321) a few choices: one row each, the chosen one ticked, as HA's
                // own choice dialogs do; a tap picks it (OK still commits)
                const list = document.createElement('div');
                list.className = 'choices';
                list.setAttribute('role', 'radiogroup');
                const rows = opts.map((o) => {
                    const b = document.createElement('button');
                    b.type = 'button';
                    b.className = 'choice';
                    b.setAttribute('role', 'radio');
                    b.dataset.value = String(o.value);
                    b.textContent = o.label;
                    b.addEventListener('click', () => { v = String(o.value); mark(); });
                    b.addEventListener('dblclick', () => { v = String(o.value); mark(); submit(); });
                    list.appendChild(b);
                    return b;
                });
                const mark = () => rows.forEach((b) => {
                    const on = b.dataset.value === v;
                    b.classList.toggle('on', on);
                    b.setAttribute('aria-checked', String(on));
                });
                mark();
                return { el: list, get: () => v };
            }
            const el = document.createElement('select');
            el.className = 'chip-select';
            for (const o of f.options || []) {
                const op = document.createElement('option');
                op.value = String(o.value); op.textContent = o.label;
                if (String(o.value) === v) op.selected = true;
                el.appendChild(op);
            }
            el.addEventListener('keydown', keys);
            return { el, get: () => el.value };
        }
        if (f.kind === 'entity') return this._entityField2(f, String(cur), keys);
        const type = f.kind === 'number' ? 'number' : f.kind === 'time' ? 'time' : 'text';
        const tf = haDefined('ha-textfield');
        const el = document.createElement(tf ? 'ha-textfield' : 'input');
        el.setAttribute('type', type);
        for (const k of ['min', 'max', 'step', 'placeholder']) if (f[k] !== undefined && f[k] !== null && f[k] !== '') el.setAttribute(k, String(f[k]));
        if (f.label) el.setAttribute('aria-label', f.label);
        if (tf && f.unit) el.setAttribute('suffix', f.unit);
        el.value = String(cur);
        el.addEventListener('keydown', keys);
        const wrap = tf || !f.unit ? null : document.createElement('div');
        if (wrap) { wrap.className = 'ed-pair'; wrap.appendChild(el); const u = document.createElement('span'); u.textContent = f.unit; wrap.appendChild(u); }
        return { el: wrap || el, get: () => (type === 'number' ? (el.value === '' ? NaN : parseFloat(el.value)) : String(el.value).trim()), focus: () => el.focus() };
    }

    /** An entity field: HA's picker when defined, a text box with the matching ids otherwise. */
    _entityField2(f, cur, keys) {
        let v = cur;
        if (haDefined('ha-entity-picker')) {
            const el = document.createElement('ha-entity-picker');
            el.hass = this._hass; el.value = v; el.allowCustomEntity = false;
            if (f.domains) el.includeDomains = f.domains;
            if (f.deviceClasses) el.includeDeviceClasses = f.deviceClasses;
            if (f.filter) el.entityFilter = f.filter;
            el.addEventListener('value-changed', (e) => { e.stopPropagation(); v = String(e.detail?.value || ''); });
            return { el, get: () => v };
        }
        const el = document.createElement('input');
        el.setAttribute('type', 'text'); el.setAttribute('placeholder', f.placeholder || 'sensor.…');
        el.value = v; el.addEventListener('keydown', keys);
        return { el, get: () => String(el.value).trim() };
    }

    /** A button: ha-button when defined, else a native one in HA's look. */
    _btn(label, onClick, o = {}) {
        // (#1321) one filled main action per card; every other button is a text button
        return renderButton(label, onClick, { ...o, ghost: o.ghost ?? !o.primary, title: o.title ?? this._whyOff(o.disabled) }, (mdi) => this._icon(mdi));
    }

    /** A disabled control says why on hover while SEM only watches. */
    _whyOff(disabled) { return disabled && this._obs() ? this._t('next_disabled_watching') : undefined; }

    /**
     * (#1321) The one dialog every screen uses. o = { id, title, build(native) -> html string,
     * onClose }. HA's ha-dialog when defined, a plain overlay otherwise; both get
     * role=dialog, aria-modal, Escape to close, focus on the first field and back to the
     * control that opened it. Returns { el, close }; the caller wires its buttons on el.
     */
    _dialog(o) {
        const root = this.renderRoot;
        const old = root?.getElementById?.(o.id);
        if (old) old.remove();
        const opener = (root && root.activeElement) || (typeof document !== 'undefined' ? document.activeElement : null);
        const native = haDefined('ha-dialog');
        const el = document.createElement(native ? 'ha-dialog' : 'div');
        el.id = o.id;
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-modal', 'true');
        el.setAttribute('aria-label', o.title || '');
        let done = false;
        const close = () => {
            if (done) return;
            done = true;
            el.remove();
            if (typeof o.onClose === 'function') o.onClose();
            if (opener && typeof opener.focus === 'function') opener.focus();
        };
        if (native) {
            el.open = true; el.heading = o.title || ''; el.setAttribute('header-title', o.title || '');
            el.addEventListener('closed', (e) => { if (e.target === el) close(); });
        } else {
            el.className = 'dlg-overlay';
            el.addEventListener('click', (e) => { if (e.target === el) close(); });
        }
        el.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
        el.innerHTML = o.build(native);
        root.appendChild(el);
        const first = el.querySelector('input, select, ha-textfield, button');
        if (first && typeof first.focus === 'function') first.focus();
        return { el, close };
    }

    /** (#1321) Settings that rarely change sit under one fold named More, closed until asked. */
    _more(body, label) {
        return html`<details class="more"><summary>${label || this._t('next_more')}</summary>${body}</details>`;
    }

    /** An alert in HA's style (ha-alert when defined). */
    _alert(type, title, body, actions) { return renderAlert(type, title, body, actions); }

    getCardSize() { return 8; }
    static getStubConfig() { return {}; }
}
