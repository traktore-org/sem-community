/**
 * SEM Setup Checklist (#1379)
 *
 * Top of the Home screen of both dashboards. While SEM only watches it says
 * so, with one button to let SEM take control (an inline confirm first).
 * Below it, a short checklist: hardware found, charger, forecast, price,
 * things to check. Each row opens the place that fixes it. Once SEM is in
 * control and nothing must be done, only a small chip stays; the chip
 * reopens the list. "Hide" folds the list for this browser.
 *
 * Reads the setup_checklist attribute of sensor.sem_diag_charger_control,
 * the same facts the AI setup tool uses.
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { renderButton, renderAlert } from '../util/ha-ui.js';
import { ensureHaElements } from '../util/ha-elements.js';
import { semDefineCard } from '../base/sem-shared.js';
import {
    CHECKLIST_ENTITY, OBSERVER_SWITCH, readChecklist, isWatchOnly, viewModel,
    brandLabel, rowTarget, readHidden, writeHidden,
} from '../util/setup-checklist.js';

const ICON_OK = 'mdi:check-circle';
const ICON_TODO = 'mdi:circle-outline';

class SEMSetupChecklistCard extends SEMLitBase {
    static get watchedEntities() { return [CHECKLIST_ENTITY, OBSERVER_SWITCH]; }
    static get watchedAttributes() { return { [CHECKLIST_ENTITY]: ['setup_checklist'] }; }

    static get properties() {
        return {
            ...super.properties,
            _hidden: { state: true },
            _reopened: { state: true },
            _confirming: { state: true },
        };
    }

    constructor() {
        super();
        this._hidden = readHidden();
        this._reopened = false;
        this._confirming = false;
    }

    _hide() { this._reopened = false; this._hidden = true; writeHidden(true); }
    _reopen() { this._hidden = false; this._reopened = true; writeHidden(false); }

    // Only after the inline confirm: this is the one call that makes SEM move hardware.
    _takeControl() {
        this._confirming = false;
        this._callService('switch', 'turn_off', { entity_id: OBSERVER_SWITCH });
    }

    _go(key) {
        const target = rowTarget(key, window.location.pathname);
        try { if (target.store) window.sessionStorage.setItem(target.store[0], target.store[1]); } catch (e) { /* the page still opens */ }
        window.history.pushState(null, '', target.path);
        window.dispatchEvent(new CustomEvent('location-changed', { bubbles: true, composed: true }));
    }

    _fill(key, vars) {
        return Object.entries(vars).reduce((t, [k, v]) => t.split('{' + k + '}').join(v), this._t(key));
    }

    _btn(label, onClick, o = {}) { return renderButton(label, onClick, o, (mdi) => html`<ha-icon icon="${mdi}"></ha-icon>`); }

    connectedCallback() {
        super.connectedCallback();
        ensureHaElements(['ha-alert', 'ha-button'])
            .then(() => this.requestUpdate()).catch(() => { /* the native look stays */ });
    }

    _banner() {
        if (this._confirming) {
            return html`<div class="gap">${renderAlert('warning', this._t('setup_confirm_text'), '', html`
                ${this._btn(this._t('setup_confirm_yes'), () => this._takeControl(), { primary: true, small: true })}
                ${this._btn(this._t('setup_confirm_no'), () => { this._confirming = false; }, { ghost: true, small: true })}`)}</div>`;
        }
        return html`<div class="gap">${renderAlert('info', this._t('setup_watch_title'), this._t('setup_watch_body'),
            this._btn(this._t('setup_take_control'), () => { this._confirming = true; }, { primary: true, small: true }))}</div>`;
    }

    _row(done, title, sub, action) {
        return html`<div class="row">
            <ha-icon class=${done ? 'ok' : 'todo'} icon=${done ? ICON_OK : ICON_TODO}></ha-icon>
            <div class="txt"><span class="t">${title}</span>${sub ? html`<span class="s">${sub}</span>` : nothing}</div>
            ${action ? this._btn(action.label, action.fn, { small: true }) : nothing}
        </div>`;
    }

    _itemRow(item) {
        const opt = html` <span class="s">· ${this._t('setup_optional')}</span>`;
        switch (item.key) {
            case 'hardware': return this._row(item.done,
                this._t(item.done ? 'setup_hw_found' : 'setup_hw_missing'),
                (item.brands || []).map(brandLabel).join(' · '));
            case 'dashboard': return this._row(true, this._t('setup_dashboard_ready'), this._t('setup_dashboard_sub'));
            case 'charger': return this._chargerRow(item);
            case 'forecast': return this._row(item.done,
                html`${this._t('setup_forecast_title')}${opt}`,
                this._t(item.done ? 'setup_forecast_set' : 'setup_forecast_sub'),
                item.done ? null : { label: this._t('setup_btn_how'), fn: () => this._go('forecast') });
            default: return this._row(item.done,
                html`${this._t('setup_price_title')}${opt}`,
                this._t(item.done ? 'setup_price_done' : 'setup_price_sub'),
                item.done ? null : { label: this._t('setup_btn_add'), fn: () => this._go('price') });
        }
    }

    _chargerRow(item) {
        if (item.done) return this._row(true, this._t('setup_charger_done'), '');
        const found = !!item.detected;
        return this._row(false, this._t('setup_charger_title'),
            found ? this._fill('setup_charger_found', { name: item.detected }) : this._t('setup_charger_none'),
            { label: this._t(found ? 'setup_btn_use' : 'setup_btn_add'), fn: () => this._go('charger') });
    }

    _repairsRow(repairs) {
        if (!repairs.count) return nothing;
        const title = repairs.count === 1 ? this._t('setup_check_one')
            : this._fill('setup_check_n', { n: repairs.count });
        return this._row(false, title, repairs.first || '',
            { label: this._t('setup_btn_open'), fn: () => this._go('repairs') });
    }

    /** (#1321) All steps done: one line, tap to open the list; the check-up row only when it needs action. */
    _complete(vm) {
        return html`<ha-card class="list done" aria-label=${this._t('setup_list_title')}>
            <button type="button" class="one" aria-expanded="false" @click=${() => this._reopen()}>
                <ha-icon class="ok" icon=${ICON_OK}></ha-icon><span class="t">${this._t('setup_complete')}</span><ha-icon icon="mdi:chevron-down"></ha-icon></button>
            ${this._repairsRow(vm.repairs)}
        </ha-card>`;
    }

    _list(c, vm) {
        return html`<ha-card class="list" aria-label=${this._t('setup_list_title')}>
            <div class="lhead">
                <span class="cap">${this._t('setup_list_title')} · ${this._fill('setup_of', { done: vm.done, total: vm.total })}</span>
                ${this._btn(this._t('setup_hide'), () => this._hide(), { ghost: true, small: true })}
            </div>
            <div class="bar" role="progressbar" aria-valuenow=${vm.pct} aria-valuemin="0" aria-valuemax="100"
                aria-label=${this._t('setup_list_title')}><div class="fill" style="width:${vm.pct}%"></div></div>
            ${c.items.map((i) => this._itemRow(i))}
            ${this._repairsRow(vm.repairs)}
            <div class="hint">${this._t('setup_ai_hint')}</div>
        </ha-card>`;
    }

    _chip(vm, watchOnly) {
        return html`<div class="chip-row">
            ${watchOnly ? nothing : html`<span class="chip ok"><ha-icon icon=${ICON_OK}></ha-icon>${this._t('setup_chip_control')}</span>`}
            ${vm.done >= vm.total ? nothing : html`<button type="button" class="chip link" @click=${() => this._reopen()}>
                ${this._fill('setup_chip_setup', { done: vm.done, total: vm.total })}</button>`}
        </div>`;
    }

    render() {
        const c = readChecklist(this._hass?.states);
        if (!c) return nothing;
        const watchOnly = isWatchOnly(this._hass.states, c);
        const vm = viewModel(c, watchOnly, this._hidden, this._reopened);
        return html`${vm.banner ? this._banner() : nothing}
            ${vm.list ? (vm.complete && !this._reopened ? this._complete(vm) : this._list(c, vm)) : this._chip(vm, watchOnly)}`;
    }

    getCardSize() { return 3; }
    static getStubConfig() { return {}; }

    static get styles() {
        return css`
            :host { display: block; color: var(--primary-text-color); font-size: var(--ha-font-size-m, 14px); }
            .gap { margin-bottom: 16px; }
            .aact { display: flex; gap: 8px; flex: none; white-space: nowrap; }
            ha-alert ha-button { white-space: nowrap; min-width: max-content; }
            .alert { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: 4px; border: 1px solid var(--primary-color);
                background: color-mix(in srgb, var(--primary-color) 12%, var(--card-background-color, #fff)); }
            .alert.warning { border-color: var(--warning-color, #ffa600); background: color-mix(in srgb, var(--warning-color, #ffa600) 12%, var(--card-background-color, #fff)); }
            .atxt { flex: 1; display: flex; flex-direction: column; min-width: 0; }
            .atxt span { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 13px); }
            .aact { display: flex; gap: 8px; flex-wrap: wrap; }
            .btn { min-height: 36px; border-radius: 20px; padding: 0 16px; font: inherit; font-weight: var(--ha-font-weight-medium, 500); cursor: pointer;
                border: 1px solid var(--divider-color); background: transparent; color: var(--primary-color); display: inline-flex; align-items: center; gap: 6px; }
            .btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
            .btn.ghost { border-color: transparent; }
            .btn.sm { min-height: 32px; padding: 0 12px; font-size: var(--ha-font-size-s, 13px); }
            ha-card.list { display: block; padding: 16px; margin-bottom: 16px; color: var(--primary-text-color);
                background: var(--ha-card-background, var(--card-background-color, #fff)); border-radius: var(--sem-card-radius, 12px);
                border: var(--sem-card-border-width, 1px) solid var(--sem-card-border-color, var(--divider-color, #e0e0e0)); box-shadow: var(--ha-card-box-shadow, none); }
            .one { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 44px; padding: 0; border: 0; background: none; color: inherit; font: inherit; cursor: pointer; text-align: left; }
            .one .t { flex: 1; font-size: var(--ha-font-size-l, 16px); font-weight: var(--ha-font-weight-medium, 500); }
            ha-card.list.done { padding-top: 4px; padding-bottom: 4px; }
            .lhead { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; }
            .cap { font-size: var(--ha-font-size-l, 16px); font-weight: var(--ha-font-weight-medium, 500); }
            .bar { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-bottom: 6px; }
            .fill { height: 6px; background: var(--success-color, #43a047); }
            .row { display: flex; gap: 12px; align-items: center; min-height: 52px; border-top: 1px solid var(--divider-color); }
            .row ha-icon { --mdc-icon-size: 20px; flex: none; }
            .row .ok { color: var(--success-color, #43a047); }
            .row .todo { color: var(--secondary-text-color); }
            .txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
            .row .t { font-size: var(--ha-font-size-m, 14px); color: var(--primary-text-color); }
            .row .s { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); }
            .hint { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); padding-top: 10px; border-top: 1px solid var(--divider-color); }
            .chip-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
            .chip { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 12px; border-radius: 16px;
                font-size: var(--ha-font-size-s, 13px); font-weight: var(--ha-font-weight-medium, 500); font-family: inherit; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); }
            .chip.ok { color: var(--success-color, #43a047); }
            .chip.link { color: var(--secondary-text-color); cursor: pointer; }
            .chip ha-icon { --mdc-icon-size: 18px; }
        `;
    }
}

semDefineCard('sem-setup-checklist-card', SEMSetupChecklistCard, {
    type: 'sem-setup-checklist-card',
    name: 'SEM Setup Checklist',
    description: 'First-run banner and checklist: says when SEM only watches, lets you take control, and links each open step',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-setup-checklist-card',
    preview: false,
});
