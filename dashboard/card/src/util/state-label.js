/**
 * #1053 — sensors whose state is a word SEM chose for its own code.
 *
 * `diag_grid_mode` publishes `manual`, `split-lowconf`, …; `heat_pump_mode`
 * publishes `force_on`; `tariff_provider` publishes `custom`. A card that
 * puts that state on screen shows an English word made for a log line. The
 * System tab mapped two of the six grid modes and printed the other four
 * as-is ("Netmodus: manual" on a Dutch dashboard); the Control tab printed
 * the grid sign, the heat pump mode and the tariff source raw.
 *
 * One table per sensor, here, for every card. A card reads these sensors
 * with `_valLabel()` (sem-lit-base), never with `_val()`.
 * `tests/test_1053_machine_words.py` reads the backend's words from the code
 * that writes them and fails when one has no row here, or a row's key has
 * no translation.
 *
 * A row is a translation key. TARIFF_BRANDS holds names that are the same
 * in every language. A word with no row is shown as it is: a new backend
 * word must stay visible, not turn into a blank.
 */

export const GRID_MODE = {
    combined: 'grid_combined',
    split: 'grid_split',
    'split-declared': 'grid_split',
    'split-declared-unverified': 'grid_split_unverified',
    'split-lowconf': 'grid_split_unverified',
    manual: 'grid_manual',
};

// Grid and battery sign. The battery sign can list one entry per battery:
// "b1: negated, b2: normal (learning)" — each word is mapped in place.
export const SIGN = {
    normal: 'normal',
    negated: 'sign_negated',
    learning: 'learning',
};

// SGReadyState names, lower case (devices/heat_pump_controller.py).
export const HEAT_PUMP_MODE = {
    blocked: 'blocked',
    normal: 'normal',
    boost: 'boost',
    force_on: 'force_on',
};

// How SEM sets the charge current. `none` means no charger: the count says it.
export const CHARGER_CONTROL = {
    number: 'charger_control_number',
    service: 'charger_control_service',
    none: '',
};

export const TARIFF_PROVIDER = {
    custom: 'custom',
    static: 'tariff_static',
    calendar: 'tariff_calendar',
    unknown: 'unknown',
};

// LoadManagementState (consts/states.py); `idle` is the coordinator's
// value before the first load-management cycle.
export const LOAD_MANAGEMENT = {
    normal: 'normal',
    warning: 'warning',
    shedding: 'shedding',
    emergency: 'emergency',
    disabled: 'disabled',
    error: 'error',
    idle: 'idle',
};

export const TARIFF_BRANDS = {
    tibber: 'Tibber',
    amber: 'Amber',
    octopus: 'Octopus Energy',
    nordpool: 'Nord Pool',
    nordpool_official: 'Nord Pool',
    awattar: 'aWATTar',
    entsoe: 'ENTSO-e',
};

// Sensor key (without the sensor.sem_ prefix) → its table.
export const VOCAB = {
    diag_grid_mode: GRID_MODE,
    diag_grid_sign: SIGN,
    diag_battery_sign: SIGN,
    heat_pump_mode: HEAT_PUMP_MODE,
    diag_charger_control: CHARGER_CONTROL,
    tariff_provider: TARIFF_PROVIDER,
    load_management_status: LOAD_MANAGEMENT,
};

// Sensors whose state can hold several words in a sentence.
const WORDWISE = new Set(['diag_battery_sign']);

function one(table, word, t) {
    if (Object.prototype.hasOwnProperty.call(table, word)) {
        const key = table[word];
        return key ? t(key) : '';
    }
    return null;
}

/**
 * The label for a sensor's state. `t` is the card's translator.
 * Empty state → ''. A word with no row → the word.
 */
export function stateLabel(sensorKey, raw, t) {
    const word = String(raw ?? '').trim();
    if (!word) return '';
    const table = VOCAB[sensorKey];
    if (!table) return word;
    if (WORDWISE.has(sensorKey)) {
        return word.replace(/[a-z_]+/g, w => {
            const label = one(table, w, t);
            return label === null ? w : label;
        });
    }
    const label = one(table, word.toLowerCase(), t);
    if (label !== null) return label;
    if (sensorKey === 'tariff_provider') {
        const brand = TARIFF_BRANDS[word.toLowerCase()];
        if (brand) return brand;
    }
    return word;
}
