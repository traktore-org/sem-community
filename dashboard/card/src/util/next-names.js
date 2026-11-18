/**
 * (#1321) ONE way to turn a load, device or entity into the name a person
 * reads: the name SEM holds for it (when a person or SEM chose one), else
 * the HA device's name, else the friendly name cleaned up. Never an entity
 * id, never a snake_case slug. Pure; `hass` is only read.
 */

const CLASS_WORD = /\s+(power|energy|leistung|verbrauch|vermogen|vermogen)$/i;
const ENTITY_ID = /^[a-z_]+\.[a-z0-9_]+$/;

/** True for text that was cut from an entity: an id, a slug, a list with no spaces, or a sensor-class tail. */
export function looksRaw(name) {
    const s = String(name || '').trim();
    if (!s) return true;
    return ENTITY_ID.test(s) || /_/.test(s) || /,\S/.test(s) || CLASS_WORD.test(s);
}

/** Words for a raw name: "garage_carport_licht Power" → "Garage carport licht". */
export function cleanName(name) {
    let s = String(name || '').trim();
    if (ENTITY_ID.test(s)) s = s.split('.')[1];
    s = s.replace(/_+/g, ' ').replace(/,\s*/g, ', ').replace(CLASS_WORD, '').replace(/\s+/g, ' ').trim();
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}

/** The HA device name an entity belongs to (the user's own name first), or ''. */
export function haDeviceName(hass, entityId) {
    const did = hass?.entities?.[entityId]?.device_id;
    const d = did ? hass?.devices?.[did] : null;
    const n = d ? (d.name_by_user || d.name) : '';
    return typeof n === 'string' ? n.trim() : '';
}

/**
 * name: what SEM calls it (may be ''), entity: the entity it reads,
 * id: the load's own key (the last-resort words).
 */
export function displayName(hass, { name = '', entity = '', id = '' } = {}) {
    if (name && !looksRaw(name)) return String(name).trim();
    const dev = entity ? haDeviceName(hass, entity) : '';
    if (dev && !looksRaw(dev)) return dev;
    const friendly = entity ? String(hass?.states?.[entity]?.attributes?.friendly_name || '') : '';
    return cleanName(name || friendly || entity || id);
}

/** A source entity's name for a "reads from" line: device name, else the cleaned friendly name. */
export function entityName(hass, entityId) {
    return displayName(hass, { entity: entityId });
}
