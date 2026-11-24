/**
 * (#1419) Security devices are never loads. The server's rule lives in
 * features/load_device_discovery.py (is_security_entity); this is its card
 * twin, so the Add a device picker never offers them. A device is a security
 * device when it carries any entity in one of these Home Assistant domains.
 */
export const SECURITY_DOMAINS = ['camera', 'alarm_control_panel', 'lock', 'siren'];

const domainOf = (id) => String(id || '').split('.')[0];

/** Is this entity, or its Home Assistant device, a security device? */
export function isSecurityEntity(hass, entityId) {
    if (!entityId) return false;
    if (SECURITY_DOMAINS.includes(domainOf(entityId))) return true;
    const ents = hass?.entities || {};
    const dev = ents[entityId]?.device_id;
    if (!dev) return false;
    return Object.values(ents).some((e) => e?.device_id === dev && SECURITY_DOMAINS.includes(domainOf(e.entity_id)));
}

/** An entity-picker filter that drops security devices, then applies `filter`. */
export function withoutSecurity(hass, filter = null) {
    return (st) => !isSecurityEntity(hass, st?.entity_id) && (!filter || filter(st));
}
