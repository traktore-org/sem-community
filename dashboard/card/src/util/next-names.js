/**
 * (#1321) ONE way to turn a load, device or entity into the name a person
 * reads: the name SEM holds for it (when a person or SEM chose one), else
 * the HA device's name, else the friendly name cleaned up. Never an entity
 * id, never a snake_case slug. Pure; `hass` is only read.
 */

const CLASS_WORD = /\s+(power|energy|input|leistung|verbrauch|vermogen)$/i;
// the English sensor-class tails SEM's own naming leaves; a person's "Wärmepumpe Verbrauch" is not one
const RAW_TAIL = /\s+(power|energy)$/i;
const ENTITY_ID = /^[a-z_]+\.[a-z0-9_]+$/;

/**
 * True for text that was cut from an entity: an id, a slug, or a list with no
 * spaces ("a,b"). A name a person typed is never raw: "Heizstab 1,5 kW" (a
 * decimal comma) and "Wärmepumpe Verbrauch" stay as they are.
 */
export function looksRaw(name) {
    const s = String(name || '').trim();
    if (!s) return true;
    return ENTITY_ID.test(s) || /_/.test(s) || /(?<!\d),\S|,(?!\d)\S/.test(s) || RAW_TAIL.test(s);
}

/** Words for a raw name: "garage_carport_licht Power" → "Garage carport licht". */
export function cleanName(name) {
    let s = String(name || '').trim();
    if (ENTITY_ID.test(s)) s = s.split('.')[1];
    // a raw entity name: no slug dashes, no "(HA Convention)" notes, no register or id number tail
    s = s.replace(/_+/g, ' ').replace(/\s*\([^)]*\)/g, '').replace(/,\s*/g, ', ').replace(/\s+\d{4,}$/, '').replace(CLASS_WORD, '').replace(/\s+/g, ' ').trim();
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
    // (#1321) a friendly name a person chose is kept as it is ("Wärmepumpe Verbrauch", "Heizstab 1,5 kW")
    if (friendly && !looksRaw(friendly)) return friendly.trim();
    return cleanName(name || friendly || entity || id);
}

/** A source entity's name for a "reads from" line: device name, else the cleaned friendly name. */
export function entityName(hass, entityId) {
    return displayName(hass, { entity: entityId });
}
