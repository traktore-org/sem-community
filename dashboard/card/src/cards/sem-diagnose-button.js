/**
 * SEM Diagnose Button (#432)
 *
 * Per-section diagnostic button + modal for the Configuration tab. Click
 * → calls the ``solar_energy_management.diagnose`` service with the
 * configured section name → opens a modal showing the focused payload
 * (config + state + recent SEM log lines) with a Copy-to-clipboard
 * button. The user pastes the result on GitHub Discussions; the
 * maintainer gets a signal-rich payload instead of a 5 MB diagnostics
 * dump.
 *
 * Usage:
 *   <sem-diagnose-button section="heat_pump" label="Diagnose"></sem-diagnose-button>
 *
 * Sections supported by the backend ``diagnose`` service:
 *   all (Overview), heat_pump, ev_chargers, battery_zones, tariff,
 *   battery_scheduler, load_management, forecast, notifications,
 *   advanced. Heat pump + overview have dedicated slicers; others use a
 *   generic prefix-match slice (Phase 1; per-section slicers land in a
 *   follow-up beta).
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard } from '../base/sem-shared.js';


class SEMDiagnoseButton extends SEMLitBase {
    static get properties() {
        return {
            ...super.properties,
            section: { type: String },
            label: { type: String },
            _open: { state: true },
            _busy: { state: true },
            _payload: { state: true },
            _error: { state: true },
            _copied: { state: true },
        };
    }

    constructor() {
        super();
        this.section = 'all';
        this.label = '';
        this._open = false;
        this._busy = false;
        this._payload = null;
        this._error = null;
        this._copied = false;
    }

    // No HA-state subscription needed — purely on-demand modal.
    static get watchedEntities() { return []; }

    async _click() {
        if (!this._hass) return;
        this._open = true;
        this._busy = true;
        this._error = null;
        this._payload = null;
        try {
            const resp = await this._hass.callService(
                'solar_energy_management', 'diagnose',
                { section: this.section || 'all' },
                undefined, undefined, true,  // returnResponse
            );
            this._payload = resp?.response || resp;
        } catch (err) {
            this._error = err?.message || String(err);
            console.error('[sem-diagnose-button] failed', err);
        } finally {
            this._busy = false;
        }
    }

    _close() {
        this._open = false;
        this._copied = false;
        this._payload = null;
        this._error = null;
    }

    async _copy() {
        if (!this._payload) return;
        const text = JSON.stringify(this._payload, null, 2);
        const succeed = () => {
            this._copied = true;
            this._error = null;
            setTimeout(() => { this._copied = false; }, 1500);
        };

        // Modern path — only works in secure contexts (HTTPS / localhost).
        // Most HA installs are accessed at http://<local-ip>:8123, which
        // is an insecure context per #460, so this falls through there.
        // Pattern mirrors sem-system-card._writeClipboard (#285).
        if (navigator?.clipboard?.writeText && window.isSecureContext !== false) {
            try {
                await navigator.clipboard.writeText(text);
                succeed();
                return;
            } catch (err) {
                console.warn('[sem-diagnose-button] modern clipboard refused, '
                    + 'falling back to execCommand', err);
            }
        }
        // Legacy execCommand path — works on plain HTTP. Textarea must be
        // in-DOM and visible-ish (1×1 zero-opacity) for iOS Safari to
        // honour the selection across the shadow boundary.
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.top = '0';
            ta.style.left = '0';
            ta.style.width = '1px';
            ta.style.height = '1px';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            if (ok) { succeed(); return; }
            console.error('[sem-diagnose-button] execCommand("copy") returned false');
        } catch (err) {
            console.error('[sem-diagnose-button] legacy clipboard fallback threw', err);
        }
        // Both paths exhausted — surface the manual-select hint.
        this._error = this._t('config_diagnose_clipboard_failed');
    }

    render() {
        const T = this._theme();
        const accent = T.accent || '#5BC8D8';
        const labelText = this.label || this._t('config_diagnose');

        return html`
            <style>
                :host { display: inline-flex; }
                .btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 5px 10px; border-radius: 8px; cursor: pointer;
                    background: ${T.surface}; color: var(--primary-text-color, ${T.text});
                    border: 1px solid ${T.surfaceBorder};
                    font-size: 12px; font-family: inherit;
                    transition: background 0.15s, border-color 0.15s;
                }
                .btn:hover { background: ${T.surfaceHover}; border-color: ${accent}; }
                .modal-backdrop {
                    position: fixed; inset: 0;
                    background: rgba(0,0,0,0.72);
                    backdrop-filter: blur(6px);
                    -webkit-backdrop-filter: blur(6px);
                    display: flex; align-items: center; justify-content: center;
                    z-index: 9999; padding: 20px;
                }
                .modal {
                    background: var(--ha-card-background, var(--card-background-color, #1a1d24));
                    border: 1px solid ${T.surfaceBorder};
                    border-radius: 14px; padding: 18px;
                    max-width: 800px; width: 100%;
                    max-height: 80vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 12px 40px rgba(0,0,0,0.65);
                    color: var(--primary-text-color, ${T.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .modal-header {
                    display: flex; align-items: center; gap: 10px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid ${T.surfaceBorder};
                }
                .modal-title { font-size: 16px; font-weight: 700; flex: 1; }
                .icon-btn {
                    background: transparent; border: none;
                    color: var(--secondary-text-color, ${T.textSec});
                    cursor: pointer; padding: 4px; border-radius: 50%;
                    transition: background 0.15s;
                }
                .icon-btn:hover { background: ${T.surfaceHover}; }
                .modal-body {
                    flex: 1; overflow: auto; padding: 12px 0;
                    font-family: ui-monospace, 'SF Mono', 'Roboto Mono', monospace;
                    font-size: 11px; line-height: 1.5;
                    white-space: pre-wrap; word-break: break-word;
                    color: var(--primary-text-color, ${T.text});
                }
                .modal-footer {
                    display: flex; gap: 8px; padding-top: 12px;
                    border-top: 1px solid ${T.surfaceBorder};
                    justify-content: flex-end;
                }
                .footer-btn {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                }
                .footer-btn.primary {
                    background: ${accent}; color: #1a1d24;
                    border-color: ${accent};
                }
                .footer-btn.primary:hover {
                    background: color-mix(in srgb, ${accent} 88%, white);
                }
                .footer-btn.secondary {
                    background: transparent;
                    color: var(--secondary-text-color, ${T.textSec});
                    border-color: ${T.surfaceBorder};
                }
                .footer-btn.secondary:hover { background: ${T.surfaceHover}; }
                .footer-btn.copied {
                    background: #8DC892; color: #1a1d24;
                    border-color: #8DC892;
                }
                .busy {
                    text-align: center; padding: 30px;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .error {
                    color: var(--error-color, #d33);
                    padding: 12px;
                    background: rgba(220, 50, 50, 0.1);
                    border-radius: 8px;
                    font-family: ui-monospace, monospace;
                    font-size: 11px;
                }
            </style>
            <button class="btn" @click=${this._click}>
                <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:14px"></ha-icon>
                ${labelText}
            </button>
            ${this._open ? html`
                <div class="modal-backdrop" @click=${(e) => e.target.classList.contains('modal-backdrop') && this._close()}>
                    <div class="modal">
                        <div class="modal-header">
                            <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:18px;color:${accent}"></ha-icon>
                            <span class="modal-title">${this._t('config_diagnose')} — ${this.section}</span>
                            <button class="icon-btn" @click=${this._close} title="${this._t('cancel') || 'Close'}">
                                <ha-icon icon="mdi:close" style="--mdc-icon-size:18px"></ha-icon>
                            </button>
                        </div>
                        <div class="modal-body">
                            ${this._busy ? html`<div class="busy">${this._t('config_diagnose_busy') || 'Collecting diagnostics…'}</div>` : nothing}
                            ${this._error ? html`<div class="error">${this._error}</div>` : nothing}
                            ${(!this._busy && !this._error && this._payload) ? html`${JSON.stringify(this._payload, null, 2)}` : nothing}
                        </div>
                        <div class="modal-footer">
                            <button class="footer-btn secondary" @click=${this._close}>
                                ${this._t('cancel') || 'Close'}
                            </button>
                            ${this._payload ? html`
                                <button class="footer-btn ${this._copied ? 'copied' : 'primary'}" @click=${this._copy}>
                                    ${this._copied ? this._t('copied') : this._t('config_diagnose_copy') || 'Copy to clipboard'}
                                </button>
                            ` : nothing}
                        </div>
                    </div>
                </div>
            ` : nothing}
        `;
    }
}


if (!customElements.get('sem-diagnose-button')) {
    customElements.define('sem-diagnose-button', SEMDiagnoseButton);
}

export { SEMDiagnoseButton };
