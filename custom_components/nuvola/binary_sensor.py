from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class NuvolaHomeworkBinarySensor(
    CoordinatorEntity, BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_name = "Compiti presenti oggi"
    _attr_icon = "mdi:book-open-page-variant"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.student_id}_homework_today"
        student = coordinator.data["student"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(coordinator.student_id))},
            "name": f"Nuvola - {student.get('nomeCompleto', 'Studente')}",
            "manufacturer": "Madisoft",
            "model": "Registro elettronico",
        }

    @property
    def is_on(self):
        from datetime import date
        return any(
            x.get("_date") == date.today().isoformat()
            for x in self.coordinator.data.get("homework", [])
        )

    @property
    def extra_state_attributes(self):
        return {
            "compiti": [
                {
                    "materia": x.get("materia"),
                    "descrizione": x.get("descrizione"),
                    "docente": x.get("docente"),
                }
                for x in self.coordinator.data.get("homework", [])
                if x.get("_date") == __import__("datetime").date.today().isoformat()
            ]
        }


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [NuvolaHomeworkBinarySensor(coordinator) for coordinator in entry.runtime_data.coordinators.values()]
    )
