"""Dashboard generator for Solar Energy Management integration."""
import json
import logging
import os
import yaml
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.components import lovelace

_LOGGER = logging.getLogger(__name__)


class DashboardGenerator:
    """Generate Lovelace dashboard configuration for SEM."""

    def __init__(self, hass: HomeAssistant):
        """Initialize dashboard generator."""
        self.hass = hass
        self._config_dir = hass.config.config_dir
        dashboard_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
        premium_path = os.path.join(dashboard_dir, "sem_dashboard_template.yaml")
        basic_path = os.path.join(dashboard_dir, "basic_template.yaml")

        # Use premium template if available, otherwise basic
        if os.path.exists(premium_path):
            self._dashboard_template_path = premium_path
            self._is_premium = True
        else:
            self._dashboard_template_path = basic_path
            self._is_premium = False

    def _load_dashboard_translations(self) -> dict:
        """Load translations from dashboard/translations.json (single source of truth)."""
        import json as _json
        translations_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard", "translations.json",
        )
        try:
            with open(translations_path, "r", encoding="utf-8") as f:
                return _json.load(f)
        except (OSError, ValueError) as e:
            _LOGGER.warning("Could not load dashboard translations: %s", e)
            return {}

    def _translate_dashboard(self, config: dict) -> dict:
        """Translate dashboard strings to user's HA language (#60).

        Reads from dashboard/translations.json — the single source of truth
        shared with sem-localize.js (browser cards).
        """
        lang = self.hass.config.language
        if lang == "en":
            return config  # English template, no translation needed

        all_translations = self._load_dashboard_translations()
        lang_translations = all_translations.get(lang)
        if not lang_translations:
            return config

        # Build reverse lookup: English text → translated text
        en = all_translations.get("en", {})
        reverse_map = {}
        for key, en_text in en.items():
            translated = lang_translations.get(key)
            if translated and translated != en_text:
                reverse_map[en_text] = translated

        if not reverse_map:
            return config

        # Walk the config and replace English strings with translations
        def _walk(obj):
            if isinstance(obj, dict):
                for field in ("title", "subtitle", "primary", "name", "label"):
                    if field in obj and isinstance(obj[field], str):
                        text = obj[field]
                        if text in reverse_map:
                            obj[field] = reverse_map[text]
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(config)
        _LOGGER.info(
            "Dashboard translated to '%s' (%d strings available)",
            lang, len(reverse_map),
        )
        return config

    async def _load_comprehensive_dashboard_template(self) -> Optional[Dict[str, Any]]:
        """Load the comprehensive dashboard template from YAML file."""
        try:
            if os.path.exists(self._dashboard_template_path):
                def _read():
                    with open(self._dashboard_template_path, "r", encoding="utf-8") as f:
                        return yaml.safe_load(f)
                template = await self.hass.async_add_executor_job(_read)
                _LOGGER.info("Loaded comprehensive dashboard template from %s", self._dashboard_template_path)
                return template
            else:
                _LOGGER.warning("Dashboard template not found at %s", self._dashboard_template_path)
                return None
        except Exception as e:
            _LOGGER.error("Failed to load dashboard template: %s", e, exc_info=True)
            return None

    async def generate_dashboard(
        self,
        dashboard_title: str = "Solar Energy Management",
        dashboard_path: str = "sem-dashboard",
    ) -> Dict[str, Any]:
        """Generate complete SEM v6.0 dashboard configuration.

        Args:
            dashboard_title: Title for the dashboard
            dashboard_path: URL path for accessing the dashboard

        Returns:
            Dashboard configuration dictionary
        """
        _LOGGER.info(
            "Generating SEM dashboard: %s (path: %s)",
            dashboard_title,
            dashboard_path,
        )

        # Store dashboard path for use in sync button
        self._dashboard_path = dashboard_path

        # Try to load comprehensive template first
        template = await self._load_comprehensive_dashboard_template()

        if template and "views" in template:
            # Translate section titles to user's language (#60)
            template = self._translate_dashboard(template)
            _LOGGER.info("Using comprehensive dashboard template with %d views", len(template["views"]))

            # Find and update views with dynamic content
            for view in template["views"]:
                if view.get("path") == "peak-load-management":
                    _LOGGER.info("Updating Peak Load Management view with dynamic device cards")
                    await self._update_peak_load_management_view(view)

            # Update power-flow-card-plus with individual devices from load management
            await self._update_power_flow_individual_devices(template)

            # Inject individual devices into sem-flow-card
            await self._update_flow_card_devices(template)

            # Inject individual devices into picture-elements system diagram
            await self._update_system_diagram_devices(template)

            # Substitute weather entity (template uses weather.home as placeholder)
            self._substitute_weather_entity(template)

            # Override template title/path with user preferences
            template["title"] = dashboard_title
            template["path"] = dashboard_path
            template["icon"] = "mdi:solar-power"
            template["show_in_sidebar"] = True
            template["require_admin"] = False

            _LOGGER.info("Dashboard generation complete using comprehensive template")
            return template

        else:
            _LOGGER.error("Dashboard template not found at %s", self._dashboard_template_path)
            raise FileNotFoundError(f"Dashboard template not found: {self._dashboard_template_path}")

    async def _update_peak_load_management_view(self, view: Dict[str, Any]) -> None:
        """Update peak load management view with dynamic device cards.

        Args:
            view: The peak load management view dict to update (modified in-place)
        """
        from ..const import DOMAIN

        # Get coordinator to access load manager
        coordinator = None
        if DOMAIN in self.hass.data:
            # Get first coordinator instance
            for entry_id, coord in self.hass.data[DOMAIN].items():
                if hasattr(coord, "_load_manager"):
                    coordinator = coord
                    break

        if not coordinator or not coordinator._load_manager:
            _LOGGER.warning("Load manager not available for device card generation")
            return

        # Find the device management section
        sections = view.get("sections", [])
        if not sections:
            _LOGGER.warning("No sections found in peak load management view")
            return

        # Find the section with "Device Priority Management" title or vertical-stack with device cards
        device_section_index = None
        for idx, section in enumerate(sections):
            cards = section.get("cards", [])
            for card in cards:
                if not isinstance(card, dict):
                    continue
                # Check for mushroom title card with "Device Priority" in title
                if card.get("type") == "custom:mushroom-title-card":
                    title = card.get("title", "")
                    if "Device Priority" in title or "Controllable Devices" in title:
                        device_section_index = idx
                        break
                # Also check for vertical-stack containing device management
                if card.get("type") == "vertical-stack":
                    for inner_card in card.get("cards", []):
                        if isinstance(inner_card, dict) and inner_card.get("type") == "custom:mushroom-title-card":
                            title = inner_card.get("title", "")
                            if "Device Priority" in title or "Controllable Devices" in title:
                                device_section_index = idx
                                break
            if device_section_index is not None:
                break

        if device_section_index is None:
            _LOGGER.warning("Could not find device management section (looking for 'Device Priority' title)")
            return

        # Generate new device cards
        devices = coordinator._load_manager._devices
        if not devices:
            _LOGGER.warning("No devices found in load manager")
            return

        sorted_devices = sorted(devices.items(), key=lambda x: x[1].get("priority", 5))
        _LOGGER.info("Generating cards for %d devices: %s", len(devices), list(devices.keys()))

        new_device_cards = []

        # Title card
        new_device_cards.append({
            "type": "custom:mushroom-title-card",
            "title": "Device Priority Management",
            "subtitle": f"{len(devices)} devices | Drag to reorder, then Sync"
        })

        # Add dynamic device cards for each device
        for device_id, device_info in sorted_devices:
            friendly_name = device_info.get("friendly_name", device_id)
            device_type = device_info.get("device_type", "unknown")
            icon = self._get_device_icon(device_type)

            new_device_cards.append({
                "type": "custom:mushroom-template-card",
                "primary": friendly_name,
                "secondary": (
                    "{% set devices = state_attr('sensor.sem_load_management', 'device_list') | default([]) %}\n"
                    f"{{% set device = devices | selectattr('id', 'eq', '{device_id}') | list | first | default(none) %}}\n"
                    "{% if device %}\n"
                    "  Priority: {{ device.priority }} | Power: {{ device.power }}W | "
                    "{% if device.critical %}🔒{% else %}⚡{% endif %} | "
                    "{% if device.controllable %}✅{% else %}🚫{% endif %}\n"
                    "{% else %}\n"
                    f"  '{device_id}'\n"
                    "{% endif %}"
                ),
                "icon": icon,
                "icon_color": (
                    "{% set devices = state_attr('sensor.sem_load_management', 'device_list') | default([]) %}\n"
                    f"{{% set device = devices | selectattr('id', 'eq', '{device_id}') | list | first | default(none) %}}\n"
                    "{% if device and device.available %}green{% else %}grey{% endif %}"
                ),
                "badge_icon": (
                    "{% set devices = state_attr('sensor.sem_load_management', 'device_list') | default([]) %}\n"
                    f"{{% set device = devices | selectattr('id', 'eq', '{device_id}') | list | first | default(none) %}}\n"
                    "{% if device and device.critical %}mdi:lock{% endif %}"
                ),
                "badge_color": "red",
            })

        # Add control buttons
        dashboard_storage_key = f"lovelace.{getattr(self, '_dashboard_path', 'sem-dashboard')}"
        new_device_cards.append({
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button",
                    "name": "Refresh Cards",
                    "icon": "mdi:refresh",
                    "tap_action": {
                        "action": "call-service",
                        "service": "solar_energy_management.generate_dashboard",
                        "data": {
                            "dashboard_path": getattr(self, '_dashboard_path', 'sem-dashboard'),
                        },
                    },
                },
                {
                    "type": "button",
                    "name": "Sync Priorities",
                    "icon": "mdi:sort-numeric-ascending",
                    "tap_action": {
                        "action": "call-service",
                        "service": "solar_energy_management.sync_priorities_from_dashboard",
                        "data": {
                            "dashboard_storage_key": dashboard_storage_key,
                            "view_path": "peak-load-management",
                        },
                    },
                },
            ]
        })

        # Find and replace the vertical-stack containing device cards, or create new section
        section = sections[device_section_index]
        section_cards = section.get("cards", [])

        # Look for vertical-stack to replace
        replaced = False
        for i, card in enumerate(section_cards):
            if isinstance(card, dict) and card.get("type") == "vertical-stack":
                # Check if this vertical-stack has the device management title
                inner_cards = card.get("cards", [])
                for inner in inner_cards:
                    if isinstance(inner, dict) and inner.get("type") == "custom:mushroom-title-card":
                        title = inner.get("title", "")
                        if "Device Priority" in title or "Controllable Devices" in title:
                            # Replace this vertical-stack's cards
                            section_cards[i] = {
                                "type": "vertical-stack",
                                "cards": new_device_cards
                            }
                            replaced = True
                            break
                if replaced:
                    break

        if not replaced:
            # No vertical-stack found, replace entire section cards
            section["cards"] = [{
                "type": "vertical-stack",
                "cards": new_device_cards
            }]

        _LOGGER.info("Updated peak load management view with %d device cards", len(sorted_devices))

    def _substitute_weather_entity(self, template: Dict[str, Any]) -> None:
        """Replace placeholder weather.home with a real weather entity, or
        drop weather card entirely if the user has none."""
        states = self.hass.states.async_all("weather")
        # Prefer real weather entities over the auto-generated weather.forecast_*
        # subentity (which lacks the forecast attributes the card expects).
        non_forecast = [s for s in states if not s.entity_id.startswith("weather.forecast_")]
        chosen = non_forecast or states
        weather_id = chosen[0].entity_id if chosen else None

        weather_card_types = ("custom:clock-weather-card", "custom:sem-weather-card")

        def walk(node):
            if isinstance(node, list):
                # Filter out weather cards if no weather entity available
                if weather_id is None:
                    node[:] = [
                        c for c in node
                        if not (isinstance(c, dict) and c.get("type") in weather_card_types)
                    ]
                for c in node:
                    walk(c)
            elif isinstance(node, dict):
                if node.get("type") in weather_card_types and weather_id:
                    node["entity"] = weather_id
                for v in node.values():
                    walk(v)

        walk(template.get("views", []))
        if weather_id:
            _LOGGER.info("Weather card: using %s", weather_id)
        else:
            _LOGGER.info("Weather card: no weather entity, card removed")

    async def _update_power_flow_individual_devices(self, template: Dict[str, Any]) -> None:
        """Update power-flow-card-plus individual devices from load management.

        Finds the power-flow-card-plus card in the template and populates
        the individual section with up to 4 devices from load management,
        sorted by priority.
        """
        from ..const import DOMAIN

        # Get coordinator to access load manager
        coordinator = None
        if DOMAIN in self.hass.data:
            for entry_id, coord in self.hass.data[DOMAIN].items():
                if hasattr(coord, "_load_manager"):
                    coordinator = coord
                    break

        if not coordinator or not coordinator._load_manager:
            _LOGGER.debug("Load manager not available for power flow card device injection")
            return

        devices = coordinator._load_manager._devices
        if not devices:
            _LOGGER.debug("No load management devices found for power flow card")
            return

        # Sort by priority, take first 3 non-EV devices (EV is already in the card)
        sorted_devices = sorted(devices.items(), key=lambda x: x[1].get("priority", 5))
        # Exclude EV charger — both by is_ev flag and by matching EV power entity
        ev_power_entity = coordinator.config.get("ev_charging_power_sensor", "")
        non_ev_devices = [
            (did, info) for did, info in sorted_devices
            if not info.get("is_ev", False)
            and info.get("power_entity")
            and info.get("power_entity") != ev_power_entity
        ][:3]  # Max 3 non-EV (EV charger is already individual #1, total max = 4)

        if not non_ev_devices:
            _LOGGER.debug("No non-EV devices with power sensors found for power flow card")
            return

        # Color palette for individual devices (after EV's #4DD0E1)
        colors = ["#FF8A65", "#AED581", "#CE93D8"]

        # Build individual device entries
        new_individuals = []
        for idx, (device_id, device_info) in enumerate(non_ev_devices):
            power_entity = device_info["power_entity"]
            friendly_name = device_info.get("friendly_name", device_id)
            device_type = device_info.get("device_type", "unknown")
            icon = self._get_device_icon(device_type)
            color = colors[idx] if idx < len(colors) else "#90A4AE"

            entry = {
                "entity": power_entity,
                "name": friendly_name,
                "icon": icon,
                "color": color,
                "color_icon": True,
                "color_value": True,
                "display_zero": False,
                "display_zero_tolerance": 50,
                "decimals": 0,
            }
            new_individuals.append(entry)

        # Find the power-flow-card-plus card in the template and update its individual list
        self._inject_individual_devices(template.get("views", []), new_individuals)

    async def _update_flow_card_devices(self, template: Dict[str, Any]) -> None:
        """Inject individual devices into sem-flow-card from load management.

        Finds the sem-flow-card in the template and populates the entities.individual
        section with up to 6 devices from load management, sorted by priority.
        """
        from ..const import DOMAIN

        coordinator = None
        if DOMAIN in self.hass.data:
            for entry_id, coord in self.hass.data[DOMAIN].items():
                if hasattr(coord, "_load_manager"):
                    coordinator = coord
                    break

        if not coordinator or not coordinator._load_manager:
            _LOGGER.debug("Load manager not available for flow card device injection")
            return

        devices = coordinator._load_manager._devices
        if not devices:
            return

        # Sort by priority, exclude EV (already a core node), max 6
        ev_power_entity = coordinator.config.get("ev_charging_power_sensor", "")
        sorted_devices = sorted(devices.items(), key=lambda x: x[1].get("priority", 5))
        non_ev_devices = [
            (did, info) for did, info in sorted_devices
            if not info.get("is_ev", False)
            and info.get("power_entity")
            and info.get("power_entity") != ev_power_entity
        ][:6]

        if not non_ev_devices:
            return

        colors = ["#FF8A65", "#AED581", "#CE93D8", "#64B5F6", "#ff9800", "#96CAEE"]

        individual = []
        for idx, (device_id, device_info) in enumerate(non_ev_devices):
            entry = {
                "entity": device_info["power_entity"],
                "name": device_info.get("friendly_name", device_id),
                "icon": self._get_device_icon(device_info.get("device_type", "unknown")),
                "color": colors[idx % len(colors)],
            }
            # Add daily energy sensor if available
            daily_entity = device_info.get("daily_energy_entity")
            if daily_entity:
                entry["daily_energy"] = daily_entity
            individual.append(entry)

        # Find sem-flow-card and inject devices
        # Skip injection if card uses entity_prefix — prefix mode reads devices
        # from sensor.sem_controllable_devices_count attributes at runtime.
        # Only inject for explicit entities mode (no entity_prefix).
        for view in template.get("views", []):
            for card in self._iter_cards(view):
                if isinstance(card, dict) and card.get("type") == "custom:sem-flow-card":
                    if card.get("entity_prefix"):
                        _LOGGER.debug(
                            "sem-flow-card uses entity_prefix, skipping individual device injection"
                        )
                        return
                    if "entities" not in card:
                        card["entities"] = {}
                    existing = card.get("entities", {}).get("individual", [])
                    existing_entities = {d.get("entity") for d in existing}
                    for device in individual:
                        if device["entity"] not in existing_entities:
                            existing.append(device)
                    card["entities"]["individual"] = existing[:6]
                    _LOGGER.info(
                        "Injected %d individual devices into sem-flow-card",
                        len(card["entities"]["individual"]),
                    )
                    return

    async def _update_system_diagram_devices(self, template: Dict[str, Any]) -> None:
        """Inject individual device labels into the picture-elements system diagram.

        Adds up to 6 devices as state-label elements positioned below the house,
        reusing the same device list from load management.
        """
        from ..const import DOMAIN

        coordinator = None
        if DOMAIN in self.hass.data:
            for entry_id, coord in self.hass.data[DOMAIN].items():
                if hasattr(coord, "_load_manager"):
                    coordinator = coord
                    break

        if not coordinator or not coordinator._load_manager:
            _LOGGER.debug("Load manager not available for system diagram device injection")
            return

        devices = coordinator._load_manager._devices
        if not devices:
            return

        # Get all devices with power sensors, sorted by priority, max 6
        sorted_devices = sorted(devices.items(), key=lambda x: x[1].get("priority", 5))
        display_devices = [
            (did, info) for did, info in sorted_devices
            if info.get("power_entity")
        ][:6]

        if not display_devices:
            return

        # Colors for device labels
        colors = ["#FF8A65", "#AED581", "#CE93D8", "#4DD0E1", "#FFD54F", "#90CAF9"]

        # Position devices in a row below the house (top: 88-96%, spread across left 20-80%)
        device_count = len(display_devices)
        spacing = 60 / max(device_count, 1)  # spread across 60% width (20% to 80%)

        new_elements = []
        for idx, (device_id, device_info) in enumerate(display_devices):
            power_entity = device_info["power_entity"]
            friendly_name = device_info.get("friendly_name", device_id)
            # Shorten name for display
            short_name = friendly_name[:12] if len(friendly_name) > 12 else friendly_name
            color = colors[idx % len(colors)]
            left_pct = 20 + (idx * spacing) + (spacing / 2)

            # Device name label
            new_elements.append({
                "type": "state-label",
                "entity": power_entity,
                "prefix": f"{short_name} ",
                "style": {
                    "top": "96%",
                    "left": f"{left_pct:.0f}%",
                    "color": color,
                    "font-size": "11px",
                    "font-weight": "bold",
                    "text-shadow": f"0 0 6px {color}40",
                    "transform": "translate(-50%, -50%)",
                    "white-space": "nowrap",
                },
            })

        # Find the picture-elements card and append device elements
        # Note: sem-system-diagram-card reads devices from sensor attributes directly,
        # so this only applies if the legacy picture-elements card is still in use.
        for view in template.get("views", []):
            for card in self._iter_cards(view):
                if isinstance(card, dict) and card.get("type") == "picture-elements":
                    elements = card.get("elements", [])
                    elements.extend(new_elements)
                    _LOGGER.info(
                        "Injected %d device labels into system diagram",
                        len(new_elements),
                    )
                    return

    def _inject_individual_devices(self, views: List, new_individuals: List[Dict]) -> None:
        """Recursively find power-flow-card-plus and append individual devices."""
        for view in views:
            for card in self._iter_cards(view):
                if isinstance(card, dict) and card.get("type") == "custom:power-flow-card-plus":
                    entities = card.get("entities", {})
                    existing = entities.get("individual", [])
                    # Append new devices, avoiding duplicates by entity ID
                    existing_entities = {d.get("entity") for d in existing}
                    for device in new_individuals:
                        if device["entity"] not in existing_entities:
                            existing.append(device)
                    entities["individual"] = existing[:4]  # power-flow-card-plus max 4
                    _LOGGER.info(
                        "Updated power-flow-card-plus with %d individual devices",
                        len(entities["individual"]),
                    )
                    return

    def _iter_cards(self, container: Any):
        """Yield all card dicts from a view/section/stack recursively."""
        if not isinstance(container, dict):
            return
        # Direct cards list
        for card in container.get("cards", []):
            yield card
            yield from self._iter_cards(card)
        # Sections (HA sections layout)
        for section in container.get("sections", []):
            yield from self._iter_cards(section)

    def _get_device_icon(self, device_type: str) -> str:
        """Get appropriate icon for device type."""
        icon_map = {
            "heater": "mdi:radiator",
            "ev_charger": "mdi:car-electric",
            "water_heater": "mdi:water-boiler",
            "appliance": "mdi:washing-machine",
            "hvac": "mdi:air-conditioner",
            "pool_pump": "mdi:pool",
            "manual": "mdi:power-plug",
        }
        return icon_map.get(device_type, "mdi:power-socket-eu")

    async def save_dashboard(
        self,
        config: Dict[str, Any],
        storage_key: str = "lovelace.sem-dashboard",
    ) -> bool:
        """Save dashboard configuration to storage and register it.

        Args:
            config: Dashboard configuration dictionary
            storage_key: Storage key for the dashboard

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            storage_path = os.path.join(
                self._config_dir,
                ".storage",
                storage_key,
            )

            # Create .storage directory if it doesn't exist
            os.makedirs(os.path.dirname(storage_path), exist_ok=True)

            # Wrap config in storage format
            storage_data = {
                "version": 1,
                "minor_version": 1,
                "key": storage_key,
                "data": {"config": config},
            }

            with open(storage_path, "w", encoding="utf-8") as f:
                json.dump(storage_data, f, indent=2, ensure_ascii=False)

            _LOGGER.info("Dashboard saved to %s", storage_path)

            # Register dashboard in lovelace_dashboards
            await self._register_dashboard(config, storage_key)

            return True

        except Exception as e:
            _LOGGER.error("Failed to save dashboard: %s", e, exc_info=True)
            return False

    async def _register_dashboard(
        self,
        config: Dict[str, Any],
        storage_key: str,
    ) -> bool:
        """Register dashboard in lovelace_dashboards storage.

        Args:
            config: Dashboard configuration
            storage_key: Storage key for the dashboard

        Returns:
            True if registered successfully, False otherwise
        """
        try:
            dashboards_path = os.path.join(
                self._config_dir,
                ".storage",
                "lovelace_dashboards",
            )

            # Read current dashboard registry
            if os.path.exists(dashboards_path):
                with open(dashboards_path, "r", encoding="utf-8") as f:
                    dashboards_data = json.load(f)
            else:
                dashboards_data = {
                    "version": 1,
                    "minor_version": 1,
                    "key": "lovelace_dashboards",
                    "data": {"items": []},
                }

            # Extract URL key from storage key (e.g., "lovelace.sem-dashboard" -> "sem-dashboard")
            url_key = storage_key.replace("lovelace.", "")

            # Check if dashboard already registered
            items = dashboards_data["data"]["items"]
            existing_item = next(
                (item for item in items if item.get("url_path") == url_key),
                None
            )

            if existing_item:
                # Update existing registration
                existing_item.update({
                    "require_admin": config.get("require_admin", False),
                    "show_in_sidebar": config.get("show_in_sidebar", True),
                    "icon": config.get("icon", "mdi:solar-power"),
                    "title": config.get("title", "Solar Energy Management"),
                })
                _LOGGER.info("Updated existing dashboard registration: %s", url_key)
            else:
                # Add new registration
                new_item = {
                    "id": url_key,
                    "url_path": url_key,
                    "require_admin": config.get("require_admin", False),
                    "show_in_sidebar": config.get("show_in_sidebar", True),
                    "icon": config.get("icon", "mdi:solar-power"),
                    "title": config.get("title", "Solar Energy Management"),
                    "mode": "storage",
                }
                items.append(new_item)
                _LOGGER.info("Added new dashboard registration: %s", url_key)

            # Save updated registry
            with open(dashboards_path, "w", encoding="utf-8") as f:
                json.dump(dashboards_data, f, indent=2, ensure_ascii=False)

            _LOGGER.info("Dashboard registered in lovelace_dashboards")
            return True

        except Exception as e:
            _LOGGER.error("Failed to register dashboard: %s", e, exc_info=True)
            return False

    async def create_dashboard(
        self,
        dashboard_title: str = "Solar Energy Management",
        dashboard_path: str = "sem-dashboard",
    ) -> Optional[str]:
        """Generate and save dashboard in one step.

        Returns:
            Dashboard path if successful, None otherwise
        """
        try:
            # Generate configuration
            config = await self.generate_dashboard(
                dashboard_title=dashboard_title,
                dashboard_path=dashboard_path,
            )

            # Save to storage
            storage_key = f"lovelace.{dashboard_path}"
            success = await self.save_dashboard(config, storage_key)

            if success:
                _LOGGER.info(
                    "Dashboard created successfully: %s",
                    dashboard_path,
                )
                return dashboard_path

            return None

        except Exception as e:
            _LOGGER.error(
                "Failed to create dashboard: %s",
                e,
                exc_info=True,
            )
            return None
