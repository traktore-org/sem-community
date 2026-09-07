#!/usr/bin/env node
// tests/live/gui/test_915_near_miss_offer.js
//
// #915 — "Add this charger", the one path that had no live proof.
//
// A near miss with an offer is unreachable on a healthy rig by construction:
// every brand present is detected, and a near miss for a detected brand is
// filtered as noise. So the simulator grows a fixture — `unmapped_charger` —
// that publishes the installation device alone: a power reading and the
// site's grid-guard current, with no cable state, no charging state and no
// charger-level throttle. SEM can describe it and cannot map it.
//
//   C1  turning the fixture on produces a near miss, named from the roster
//   C2  ...carrying the role the integration declares (available_current)
//   C3  ...and an offer, because the device has a power sensor
//   C4  the card shows "Add this charger" rather than "please report"
//   C5  clicking it creates a charger wired to the proposed entities
//   C6  turning the fixture off puts the rig back and the offer disappears
//
// Mutates the rig: flips a sim option and adds a charger. Both undone in the
// `finally` block.

const L = require('./lib');
const OUT = process.env.SHOT_DIR || '/tmp';

const ws = (page, msg) => page.evaluate(
    m => document.querySelector('home-assistant').hass.callWS(m), msg);

async function simEntry(page) {
    const entries = await ws(page, { type: 'config_entries/get' });
    return (entries || []).find(e => e.domain === 'zaptec_sim') || null;
}

/** Flip the fixture by rewriting the sim entry's data through its own flow. */
async function setFixture(page, on) {
    const entry = await simEntry(page);
    if (!entry) throw new Error('zaptec_sim is not installed on this rig');
    await L.api(`config/config_entries/entry/${entry.entry_id}`, { method: 'DELETE' });
    await page.waitForTimeout(4000);
    const flow = await L.api('config/config_entries/flow', {
        method: 'POST',
        body: JSON.stringify({ handler: 'zaptec_sim', show_advanced_options: false }),
    });
    const res = await L.api(`config/config_entries/flow/${flow.flow_id}`, {
        method: 'POST',
        body: JSON.stringify({
            device_prefix: 'Guido Coppes',
            expose_charger_current: true,
            unmapped_charger: !!on,
        }),
    });
    if (res.type !== 'create_entry') throw new Error(`sim reinstall: ${JSON.stringify(res).slice(0, 200)}`);
    await page.waitForTimeout(12000);
}

async function report(page) {
    await L.openConfigCard(page);
    return JSON.parse(await page.evaluate(`(() => {
        const st = document.querySelector('home-assistant')?.hass
            ?.states?.['sensor.sem_diag_charger_control'];
        return JSON.stringify(st?.attributes?.detection_report || {});
    })()`));
}

(async () => {
    const { browser, page } = await L.openBrowser();
    let addedId = null;   // kept for the assertion; cleanup sweeps by prefix
    try {
        await page.goto(`${L.HOST}/config/integrations`, { waitUntil: 'networkidle' });
        await page.waitForTimeout(3000);

        await setFixture(page, true);
        // SEM rebuilds the detection report on setup; give the reload a cycle
        await L.api('services/homeassistant/reload_config_entry', {
            method: 'POST',
            body: JSON.stringify({ entry_id: await L.entryId() }),
        });
        await page.waitForTimeout(20000);

        const r = await report(page);
        const miss = (r.near_misses || []).find(m => String(m.platform).startsWith('zaptec'));
        L.check('C1 the fixture produces a near miss', !!miss,
                (r.near_misses || []).map(m => m.platform).join(',') || 'none');
        L.check('C1b it is named from the roster',
                miss?.roster?.name === 'Zaptec EV charger', miss?.roster?.name);
        L.check('C2 it carries the role the integration declares',
                miss?.proposed_roles?.ev_current_control?.matched_key === 'available_current',
                JSON.stringify(miss?.proposed_roles || {}));
        const offer = miss?.suggested_charger;
        L.check('C3 it comes with a ready charger', !!offer?.id, JSON.stringify(offer || {}));
        L.check('C3b the offer wires the proposed control and a power sensor',
                offer?.ev_current_control_entity?.includes('beschikbare_stroom')
                && !!offer?.ev_charging_power_sensor,
                `${offer?.ev_current_control_entity} / ${offer?.ev_charging_power_sensor}`);

        const text = await L.cardText(page);
        L.check('C4 the card offers the action, not a bug report',
                text.includes('Add this charger'));
        await L.shot(page, `${OUT}/915_C_near_miss_offer.png`);

        const before = ((await L.config()).ev_chargers || []).length;
        const clicked = await L.clickCardButton(page, 'Add this charger', 0);
        L.check('C5 the offer clicks', clicked === 'clicked', clicked);
        await page.waitForTimeout(15000);
        const chargers = (await L.config()).ev_chargers || [];
        const added = chargers.find(c => c && String(c.id).startsWith('zaptec'));
        addedId = added?.id || null;
        L.check('C5b a charger was created', chargers.length === before + 1 && !!added,
                `${before} -> ${chargers.length}`);
        // `ev_charging_power_sensor` is in SEM's REDACT_CONFIG_KEYS, so the
        // diagnostics view returns **REDACTED** for it — assert it is SET
        // rather than comparing a value the reader is never shown.
        L.check('C5c it is wired to the control SEM proposed',
                added?.ev_current_control_entity === offer?.ev_current_control_entity,
                `${added?.ev_current_control_entity}`);
        L.check('C5d and to a power sensor',
                !!added?.ev_charging_power_sensor,
                String(added?.ev_charging_power_sensor));
    } catch (err) {
        L.check('suite ran to completion', false, err.message);
    } finally {
        try {
            // Removal is a SERVICE, not a shorter list: `set_option` merges
            // ev_chargers BY ID and preserves siblings (#464, so a partial
            // submit can never drop a charger) — so the obvious cleanup
            // silently did nothing and left the rig with the test's chargers.
            for (const c of ((await L.config()).ev_chargers || [])) {
                if (c && String(c.id).startsWith('zaptec')) {
                    await L.api('services/solar_energy_management/remove_charger', {
                        method: 'POST',
                        body: JSON.stringify({ charger_id: c.id }),
                    });
                    await page.waitForTimeout(4000);
                }
            }
            await setFixture(page, false);
            // SEM builds the detection report at SETUP, so a rig that has
            // changed underneath it still shows the old one until it reloads.
            // Without this the restore check read a fixture-era report and
            // reported a failure against a rig that was already fine.
            await L.api('services/homeassistant/reload_config_entry', {
                method: 'POST',
                body: JSON.stringify({ entry_id: await L.entryId() }),
            });
            await page.waitForTimeout(20000);
            const r2 = await report(page);
            const stillOffered = (r2.near_misses || [])
                .some(m => m.suggested_charger && m.suggested_charger.id);
            L.check('C6 the rig is back and the offer is gone', !stillOffered,
                    `chargers=${(r2.chargers || []).map(c => c.platform).join(',')}`);
        } catch (e) {
            L.check('C6 the rig is back and the offer is gone', false, e.message);
        }
        await browser.close();
    }
    process.exit(L.summary() ? 0 : 1);
})();
