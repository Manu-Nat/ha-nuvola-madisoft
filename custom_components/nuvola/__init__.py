from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .api import NuvolaApi
from .const import (
    CONF_PASSWORD,
    CONF_STUDENT_ID,
    CONF_STUDENT_IDS,
    CONF_USERNAME,
    DOMAIN,
    MAX_STUDENTS,
    PLATFORMS,
)
from .coordinator import NuvolaCoordinator


@dataclass
class NuvolaRuntime:
    api: NuvolaApi
    coordinators: dict[int, NuvolaCoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if not hass.services.has_service(DOMAIN, "refresh"):
        async def _refresh(call: ServiceCall) -> None:
            for configured_entry in hass.config_entries.async_entries(DOMAIN):
                runtime = getattr(configured_entry, "runtime_data", None)
                if runtime is None:
                    continue
                for coordinator in runtime.coordinators.values():
                    await coordinator.async_request_refresh()

        hass.services.async_register(DOMAIN, "refresh", _refresh)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = NuvolaApi(
        hass,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    students = await api.get_students()

    configured_ids = entry.data.get(CONF_STUDENT_IDS)
    if not configured_ids:
        legacy_id = entry.data.get(CONF_STUDENT_ID)
        configured_ids = [legacy_id] if legacy_id is not None else []

    available_ids = {int(student["id"]) for student in students if student.get("id") is not None}
    student_ids = [int(student_id) for student_id in configured_ids if int(student_id) in available_ids]
    if len(student_ids) > MAX_STUDENTS:
        await api.close()
        raise ConfigEntryNotReady(
            f"Sono stati configurati più di {MAX_STUDENTS} studenti; riduci la selezione dalle opzioni dell'integrazione."
        )
    if not student_ids:
        await api.close()
        raise ConfigEntryNotReady(
            "Nessuno degli studenti configurati è disponibile nell'account Nuvola."
        )

    # Keep the entry synchronized with the current selected students and remove legacy keys.
    new_data = dict(entry.data)
    new_data[CONF_STUDENT_IDS] = student_ids
    new_data.pop(CONF_STUDENT_ID, None)
    new_data.pop("student_name", None)
    if new_data != entry.data:
        hass.config_entries.async_update_entry(entry, data=new_data)

    coordinators: dict[int, NuvolaCoordinator] = {}
    try:
        for student_id in student_ids:
            coordinator = NuvolaCoordinator(hass, api, student_id)
            await coordinator.async_config_entry_first_refresh()
            coordinators[student_id] = coordinator
    except Exception:
        await api.close()
        raise

    entry.runtime_data = NuvolaRuntime(api=api, coordinators=coordinators)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime = getattr(entry, "runtime_data", None)
    if runtime:
        await runtime.api.close()
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version < 2:
        data = dict(entry.data)
        legacy_id = data.get(CONF_STUDENT_ID)
        if legacy_id is not None:
            data[CONF_STUDENT_IDS] = [int(legacy_id)]
        data.pop(CONF_STUDENT_ID, None)
        data.pop("student_name", None)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=2,
            unique_id=(entry.unique_id.split(":", 1)[0] if entry.unique_id else None),
        )
    return True
