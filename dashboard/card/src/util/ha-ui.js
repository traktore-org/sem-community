/**
 * (#1321) Two Home Assistant pieces both card families draw: a button and an
 * alert. HA's own element when it is defined, a native one in HA's look when
 * it is not (the styles for the fallbacks live in `base/sem-next-base.js`).
 */
import { html, nothing } from 'lit';
import { haDefined } from './ha-elements.js';

/** o = { primary, ghost, small, disabled, icon (mdi), title, onIcon: (mdi) => template }. */
export function renderButton(label, onClick, o = {}, icon = (mdi) => html`<ha-icon icon="${mdi}"></ha-icon>`) {
    // HA fades a disabled ha-button to nothing on a light theme: a disabled one is the native button in readable colours
    if (haDefined('ha-button') && !o.disabled) {
        return html`<ha-button appearance="${o.primary ? 'filled' : o.ghost ? 'plain' : 'outlined'}" size="${o.small ? 'small' : 'medium'}"
            title="${o.title || nothing}" ?raised=${!!o.primary} ?outlined=${!o.primary && !o.ghost} ?disabled=${!!o.disabled}
            @click=${onClick}>${o.icon ? html`<ha-icon slot="start" icon="${o.icon}"></ha-icon>` : nothing}${label}</ha-button>`;
    }
    return html`<button type="button" class="btn ${o.primary ? 'primary' : ''} ${o.small ? 'sm' : ''} ${o.ghost ? 'ghost' : ''}"
        title="${o.title || nothing}" ?disabled=${!!o.disabled} @click=${onClick}>${o.icon ? icon(o.icon) : nothing}${label}</button>`;
}

/**
 * An alert: ha-alert when defined, a styled box otherwise.
 * type = info | warning | error | success. `actions` goes to the right.
 */
export function renderAlert(type, title, body, actions = nothing) {
    if (haDefined('ha-alert')) {
        return html`<ha-alert alert-type="${type}" .title=${title || ''}>${body || nothing}${actions === nothing ? nothing : html`<span slot="action">${actions}</span>`}</ha-alert>`;
    }
    return html`<div class="alert ${type}" role="${type === 'error' ? 'alert' : 'status'}">
        <div class="atxt">${title ? html`<strong>${title}</strong>` : nothing}${body ? html`<span>${body}</span>` : nothing}</div>
        ${actions === nothing ? nothing : html`<div class="aact">${actions}</div>`}</div>`;
}
