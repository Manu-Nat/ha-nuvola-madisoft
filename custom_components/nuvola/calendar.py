from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import NuvolaCoordinator


def _parse_date(value: Any) -> date | None:
    if not value:
        return None

    text = str(value)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue

    return None


class NuvolaCalendar(
    CoordinatorEntity[NuvolaCoordinator],
    CalendarEntity,
):
    _attr_has_entity_name = True
    _attr_name = "Scadenze e compiti"
    _attr_icon = "mdi:calendar-school"

    def __init__(self, coordinator: NuvolaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.student_id}_calendar"

        student = coordinator.data["student"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(coordinator.student_id))},
            "name": f"Nuvola - {student.get('nomeCompleto', 'Studente')}",
            "manufacturer": "Madisoft",
            "model": "Registro elettronico",
        }

    def _build_events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        local_timezone = dt_util.now().tzinfo

        for item in self.coordinator.data.get("homework", []):
            day = _parse_date(
                item.get("_date") or item.get("dataConsegna")
            )
            if day is None:
                continue

            start = datetime.combine(
                day,
                time(hour=8),
                tzinfo=local_timezone,
            )
            end = start + timedelta(minutes=30)

            description = item.get("descrizione", "")
            if isinstance(description, list):
                description = "\n".join(str(value) for value in description)

            subject = item.get("materia") or "Compito"
            teacher = item.get("docente")

            events.append(
                CalendarEvent(
                    summary=str(subject),
                    start=start,
                    end=end,
                    description=str(description),
                    location=str(teacher) if teacher else None,
                )
            )

        events.sort(key=lambda event: event.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming homework event."""
        now = dt_util.now()

        for event in self._build_events():
            if event.end > now:
                return event

        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return homework events within the requested time range."""
        events = []

        for event in self._build_events():
            # Calendar ranges use an exclusive end bound.
            if event.end <= start_date or event.start >= end_date:
                continue
            events.append(event)

        return events


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities,
) -> None:
    coordinators = entry.runtime_data.coordinators
    async_add_entities(
        [NuvolaCalendar(coordinator) for coordinator in coordinators.values()]
    )