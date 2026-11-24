/**
 * (#1419) Security devices are never loads. The server's rule lives in
 * features/load_device_discovery.py (is_security_device_entries); this is its
 * card twin, so the Add a device picker never offers them. A device is a
 * security device when it carries a camera, alarm panel or siren, or its own
 * lock — not an appliance setting like a child lock, and not when the device
 * is a load (a main switch or climate with a measured power sensor).
 */
export const SECURITY_DOMAINS = ['camera', 'alarm_control_panel', 'siren'];
const SETTING_LOCK_WORDS = ['child', 'key_lock', 'keylock', 'button_lock', 'panel_lock', 'control_lock', 'kindersicherung'];
const LOAD_CONTROL_DOMAINS = ['switch', 'climate', 'water_heater'];

const domainOf = (id) => String(id || '').split('.')[0];
const isSetting = (e) => ['config', 'diagnostic'].includes(String(e?.entity_category || '').toLowerCase());

function isPrimaryLock(e) {
    if (isSetting(e)) return false;
    const words = [e?.translation_key, e?.entity_id, e?.name].map((x) => String(x || '').toLowerCase()).join(' ');
    return !SETTING_LOCK_WORDS.some((w) => words.includes(w));
}

function isLoadDevice(hass, entries) {
    const control = entries.some((e) => LOAD_CONTROL_DOMAINS.includes(domainOf(e.entity_id)) && !isSetting(e));
    const power = entries.some((e) => domainOf(e.entity_id) === 'sensor'
        && hass?.states?.[e.entity_id]?.attributes?.device_class === 'power');
    return control && power;
}

/** Is this entity part of a security device? */
export function isSecurityEntity(hass, entityId) {
    if (!entityId) return false;
    const ents = hass?.entities || {};
    const own = ents[entityId];
    const dev = own?.device_id;
    if (!dev) {
        if (SECURITY_DOMAINS.includes(domainOf(entityId))) return true;
        return domainOf(entityId) === 'lock' && isPrimaryLock(own || { entity_id: entityId });
    }
    const entries = Object.values(ents).filter((e) => e?.device_id === dev);
    if (entries.some((e) => SECURITY_DOMAINS.includes(domainOf(e.entity_id)))) return true;
    const locks = entries.filter((e) => domainOf(e.entity_id) === 'lock' && isPrimaryLock(e));
    return locks.length > 0 && !isLoadDevice(hass, entries);
}

/** An entity-picker filter that drops security devices, then applies `filter`. */
export function withoutSecurity(hass, filter = null) {
    return (st) => !isSecurityEntity(hass, st?.entity_id) && (!filter || filter(st));
}
