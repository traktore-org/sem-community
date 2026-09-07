#!/usr/bin/env node
// tests/live/gui/test_915_detected_hardware.js
//
// #915 — the Detected-hardware section, driven the way a person drives it.
//
// The cases here exist because each one was a real defect or a real question
// during the build:
//
//   A1  the card renders at all, with no console errors
//   A2  the section names what SEM found, with its evidence
//   A3  near-misses are hardware, not the MQTT bus (24 zigbee rows on .46)
//   A4  an installed integration's declared controls are proposed
//   A5  a proposal offers an ACTION, not just the word "unconfirmed"
//        ("Huawei Solar unconfirmed — how do I confirm?")
//   A6  clicking Use this WRITES the option SEM reads
//   A7  ...and the accepted row stops being a proposal — the loop closes
//
// Run:  HA_TOKEN=... node tests/live/gui/test_915_detected_hardware.js
// Never against PROD; lib.js refuses.

const L = require('./lib');
const OUT = process.env.SHOT_DIR || '/tmp';

(async () => {
    const { browser, page } = await L.openBrowser();
    let acceptedKey = null, acceptedEntity = null;
    try {
        await L.openConfigCard(page);
        const text = await L.cardText(page);

        L.check('A1 the config card renders with no console errors',
                page.__errors.length === 0, page.__errors.slice(0, 2).join(' | '));
        L.check('A1b the Detected hardware section is open',
                text.includes('Detected hardware'));

        // (#915) The report built at boot is unjudged and a slow modbus
        // integration's entities may not have states for a minute after a
        // restart; the coordinator re-heals it. Wait for that instead of
        // asserting on the boot-time copy — the README's settle trap, in
        // its A form.
        await L.until(async () => {
            const r = await L.api('states/sensor.sem_diag_charger_control');
            const dr = r?.attributes?.detection_report;
            return dr && dr.judged === true && !(dr.not_loaded > 0);
        }, { timeoutMs: 150000, everyMs: 10000 });
        const report = JSON.parse(await page.evaluate(`(() => {
            const st = document.querySelector('home-assistant')?.hass
                ?.states?.['sensor.sem_diag_charger_control'];
            return JSON.stringify(st?.attributes?.detection_report || {});
        })()`));

        // A2 — what SEM found, with evidence
        const chargers = report.chargers || [];
        L.check('A2 at least one charger is detected', chargers.length > 0,
                chargers.map(c => c.platform).join(', '));
        L.check('A2b every detected charger shows its control method',
                chargers.every(c => c.control));
        L.check('A2c the card prints each charger and a mapped entity',
                chargers.every(c => text.includes(c.platform))
                && chargers.every(c => Object.values(c.mapped || {})
                    .some(v => text.includes(v.entity))));

        // A3 — a near miss is about hardware
        const misses = report.near_misses || [];
        const mqttNoise = misses.filter(m => m.platform === 'mqtt');
        L.check('A3 no MQTT bus device is reported as a near miss',
                mqttNoise.length === 0, `${mqttNoise.length} mqtt rows`);
        const detectedPlatforms = new Set(chargers.map(c => String(c.platform).split('_')[0]));
        L.check('A3b no near miss for a brand whose charger is already detected',
                misses.every(m => !detectedPlatforms.has(String(m.platform).split('_')[0])),
                misses.map(m => m.platform).join(', '));

        // A4 — declared controls of an installed integration
        const proposals = report.roster_proposals || [];
        L.check('A4 an installed integration is named and proposed for',
                proposals.length > 0 && proposals[0].roster && proposals[0].roster.name,
                proposals.map(p => `${p.roster?.name}:${Object.keys(p.proposed_roles || {}).length}`).join(' '));
        const allRoles = proposals.flatMap(p => Object.entries(p.proposed_roles || {}));
        L.check('A4b every proposal cites the key the integration declares',
                allRoles.length > 0 && allRoles.every(([, v]) => v.matched_key && v.entity));
        L.check('A4c a role SEM resolves by itself is never listed as a chore',
                allRoles.every(([r]) => !['battery_capacity_spec', 'system_size_spec'].includes(r)));
        L.check('A4d the card shows the declared key beside the entity',
                allRoles.every(([, v]) => text.includes(v.matched_key)));

        // A5 — the action exists
        const settable = allRoles.filter(([, v]) => v.action === 'set_option');
        L.check('A5 at least one proposal can be accepted with one click',
                settable.length > 0, `${settable.length} settable`);
        L.check('A5b every settable proposal names the option key it writes',
                settable.every(([, v]) => v.config_key));
        L.check('A5c the Use this button is rendered', text.includes('Use this'));
        const perCharger = allRoles.filter(([, v]) => v.action === 'per_charger');
        L.check('A5d a charger-scoped role explains itself instead of offering a button',
                perCharger.every(() => text.includes('EV chargers')) || perCharger.length === 0);

        // A5e — (#915 gap close) a policy selector is named and NOT offered.
        // Huawei's working-mode select is the #845 boundary: SEM watches
        // it, the user sets it. The card has to say so, not just omit a
        // button.
        const observe = allRoles.filter(([, v]) => v.action === 'observe_only');
        // A policy selector SEM already watches (#845's
        // battery_operating_mode_entity) is filtered as "in use" and never
        // proposed — correct, and distinguishable from a lost reason.
        const cfg = await L.config();
        const policyBound = !!(cfg.battery_operating_mode_entity || '').startsWith?.('select.');
        L.check('A5e a policy selector is observe-only, with the reason on the card',
                observe.length > 0 ? text.includes('SEM reads it and never writes it') : policyBound,
                observe.length ? observe.map(([r, v]) => `${r}:${v.matched_key}`).join(' ')
                               : `none proposed; policy selector bound=${cfg.battery_operating_mode_entity || '—'}`);
        L.check('A5e2 every proposal on a running HA was judged against its live state',
                allRoles.every(([, v]) => v.judged === true),
                allRoles.filter(([, v]) => v.judged !== true).map(([r]) => r).join(' ') || 'all judged');
        L.check('A5f an observe-only role carries no config key',
                observe.every(([, v]) => !v.config_key));

        // A5g — every button-bearing proposal points at an entity whose
        // LIVE unit is what SEM will write. Read the states directly: the
        // backend judged them, this is the independent check.
        const WANT = { battery_charge_limit: ['W', 'kW'], battery_discharge_limit: ['W', 'kW'],
                       battery_target_soc: ['%'], battery_power: ['W', 'kW'],
                       battery_soc: ['%'], solar_power: ['W', 'kW'], grid_power: ['W', 'kW'],
                       ev_current_control: ['A'] };
        let unitOk = true; const unitNotes = [];
        for (const [role, v] of settable) {
            if (!WANT[role]) continue;
            const st = await L.api(`states/${v.entity}`);
            const u = st?.attributes?.unit_of_measurement;
            if (!WANT[role].includes(u)) { unitOk = false; unitNotes.push(`${role}=${v.entity}:${u}`); }
        }
        L.check('A5g every button-bearing proposal has the unit SEM will write',
                unitOk, unitNotes.join(' ') || `${settable.length} checked`);
        const refused = allRoles.filter(([, v]) => ['unit_mismatch', 'no_unit', 'not_loaded', 'options_unmapped'].includes(v.action));
        L.check('A5h every refusal carries a reason the card renders',
                refused.every(([, v]) => v.action !== 'unit_mismatch' || (v.unit_seen && v.unit_wanted)),
                refused.map(([r, v]) => `${r}:${v.action}`).join(' ') || 'none refused on this rig');

        await L.shot(page, `${OUT}/915_A_detected_hardware.png`);

        // A6 — the click writes the option
        if (settable.length) {
            const [role, body] = settable[0];
            acceptedKey = body.config_key; acceptedEntity = body.entity;
            const before = (await L.config())[acceptedKey];
            const clicked = await L.clickCardButton(page, 'Use this', 0);
            L.check('A6 the Use this button clicks', clicked === 'clicked', clicked);
            await page.waitForTimeout(6000);
            const after = (await L.config())[acceptedKey];
            L.check(`A6b clicking wrote ${acceptedKey}`,
                    after === acceptedEntity,
                    `role=${role} before=${before} after=${after} want=${acceptedEntity}`);

            // A7 — the loop closes: SEM stops proposing what it now uses
            await page.waitForTimeout(12000);
            await L.openConfigCard(page);
            const report2 = JSON.parse(await page.evaluate(`(() => {
                const st = document.querySelector('home-assistant')?.hass
                    ?.states?.['sensor.sem_diag_charger_control'];
                return JSON.stringify(st?.attributes?.detection_report || {});
            })()`));
            const stillProposed = (report2.roster_proposals || [])
                .flatMap(p => Object.values(p.proposed_roles || {}))
                .some(v => v.entity === acceptedEntity);
            L.check('A7 an accepted entity stops being proposed', !stillProposed,
                    acceptedEntity);
            await L.shot(page, `${OUT}/915_A7_after_accept.png`);
        }
    } catch (err) {
        L.check('suite ran to completion', false, err.message);
    } finally {
        await browser.close();
    }
    if (acceptedKey) {
        console.log(`\nnote: this run wrote ${acceptedKey}=${acceptedEntity} on the rig`);
    }
    process.exit(L.summary() ? 0 : 1);
})();
