/**
 * Resolve the SOC a single charger's tile should display (#683).
 *
 * Three candidate readings exist per charger tile:
 *
 *   perChargerSoc — ``sensor.sem_charger_<id>_vehicle_soc``, the real SOC of
 *                   the car on THIS charger. ``null`` unless that charger has
 *                   its own ``vehicle_soc_entity`` configured.
 *   globalSoc     — ``sensor.sem_vehicle_soc``, a FLEET-level sensor. On an
 *                   install where no global ``vehicle_soc_entity`` is set, the
 *                   coordinator promotes the first per-charger reading it finds
 *                   into it (coordinator.py, #245 review #3) — so on a
 *                   multi-charger fleet this value belongs to *some* charger,
 *                   not to this one.
 *   estimatedSoc  — ``sensor.sem_charger_<id>_estimated_soc``, the taper
 *                   detector's virtual SOC for THIS charger.
 *
 * The global fallback exists for legacy single-charger installs that never
 * configured a per-charger ``vehicle_soc_entity``. It must not apply once
 * there is more than one charger: with two boxes and one instrumented car,
 * the uninstrumented tile fell back to the promoted global and displayed the
 * other charger's car — the multi-charger bug class (docs/MULTI_CHARGER.md),
 * a per-charger surface reading a fleet value. Reported as #683: "Under EV I
 * have two Smart EVSE listed. Only one of them has a vehicle's battery sensor
 * connected, but I'm seeing that SOC applied to both."
 *
 * @param {number|null} perChargerSoc
 * @param {number|null} globalSoc
 * @param {number|null} estimatedSoc
 * @param {number} chargerCount how many chargers the card is rendering
 * @returns {{soc: number|null, isEstimate: boolean}}
 */
export function resolveChargerSoc(perChargerSoc, globalSoc, estimatedSoc, chargerCount) {
    const vehicleSoc = perChargerSoc != null
        ? perChargerSoc
        : (chargerCount <= 1 ? (globalSoc ?? null) : null);
    if (vehicleSoc != null) return { soc: vehicleSoc, isEstimate: false };
    if (estimatedSoc != null) return { soc: estimatedSoc, isEstimate: true };
    return { soc: null, isEstimate: false };
}
