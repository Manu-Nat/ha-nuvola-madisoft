from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NuvolaCoordinator


def _device_info(coordinator):
    student = coordinator.data["student"]
    return {
        "identifiers": {(DOMAIN, str(coordinator.student_id))},
        "name": f"Nuvola - {student.get('nomeCompleto', 'Studente')}",
        "manufacturer": "Madisoft",
        "model": "Registro elettronico",
    }


_SCHOOL_KEY_HINTS = ("scuola", "plesso", "istituto")
_NAME_KEYS = ("nome", "descrizione", "denominazione", "nomeCompleto", "label")


def _text_of(value: Any, depth: int = 0) -> str | None:
    """Return a readable name from a string / dict / list value."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if depth > 2:
        return None
    if isinstance(value, dict):
        for key in _NAME_KEYS:
            text = _text_of(value.get(key), depth + 1)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = _text_of(item, depth + 1)
            if text:
                return text
    return None


def _school_name(student: dict[str, Any]) -> str | None:
    """Find the school name, wherever the API puts it."""
    # exact key first, then any key that looks like school/plesso/istituto
    text = _text_of(student.get("scuola"))
    if text:
        return text
    for key, value in student.items():
        if any(hint in str(key).lower() for hint in _SCHOOL_KEY_HINTS):
            text = _text_of(value)
            if text:
                return text
    # one level deeper (e.g. classe: {"scuola": {...}})
    for value in student.values():
        if isinstance(value, dict):
            for key, inner in value.items():
                if any(hint in str(key).lower() for hint in _SCHOOL_KEY_HINTS):
                    text = _text_of(inner)
                    if text:
                        return text
    return None


def _attrs(coordinator):
    data = coordinator.data
    student = data["student"]
    return {
        "studente": student.get("nomeCompleto")
        or f"{student.get('nome', '')} {student.get('cognome', '')}".strip(),
        "classe": student.get("classe"),
        "scuola": _school_name(student),
        "periodo_corrente": (data.get("current_period") or {}).get("nome"),
        "ultimo_aggiornamento": data.get("last_update"),
    }


class NuvolaSensor(CoordinatorEntity[NuvolaCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name, icon, value_fn, attrs_fn=None):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._value_fn = value_fn
        self._attrs_fn = attrs_fn
        self._attr_unique_id = f"{coordinator.student_id}_{key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self):
        return self._value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        attrs = _attrs(self.coordinator)
        if self._attrs_fn:
            attrs.update(self._attrs_fn(self.coordinator.data))
        return attrs


def _latest_vote(data):
    vote = data.get("last_vote")
    if not vote:
        return None
    return vote.get("valutazione", vote.get("valore"))


def _latest_vote_attrs(data):
    vote = data.get("last_vote") or {}
    return {
        "data": vote.get("data"),
        "materia": vote.get("materia"),
        "docente": vote.get("docente"),
        "descrizione": vote.get("descrizione"),
        "tipo": vote.get("tipo"),
    }


def _homework_today(data):
    from datetime import date
    return sum(1 for x in data.get("homework", []) if x.get("_date") == date.today().isoformat())


def _homework_attrs(data):
    items = data.get("homework", [])
    return {
        "elenco": [
            {
                "data": x.get("_date"),
                "materia": x.get("materia"),
                "descrizione": x.get("descrizione"),
                "docente": x.get("docente"),
            }
            for x in items
        ]
    }


def _subject_attrs(data):
    return {
        "materie": [
            {
                "materia": x.get("materia"),
                "media": x.get("media"),
                "voti": x.get("voti", []),
            }
            for x in data.get("subjects", [])
        ]
    }


# --- Pagamenti ---------------------------------------------------------------

# Stati che NON sono "da pagare". Qualsiasi altro stato (es. "DA PAGARE",
# "NON PAGATO", "SCADUTO", "IN ATTESA") viene considerato ancora dovuto.
_NOT_DUE_STATES = {"PAGATO", "ANNULLATO", "RIMBORSATO", "ELIMINATO"}


def _is_due(payment: dict[str, Any]) -> bool:
    state = str(payment.get("statoPagamento") or "").strip().upper()
    return state not in _NOT_DUE_STATES


def _amount(payment: dict[str, Any]) -> float | None:
    """Parse amounts like '8,00 €' or '1.250,50 €'."""
    raw = re.sub(r"[^\d,.]", "", str(payment.get("importo") or ""))
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _compact_payment(payment: dict[str, Any]) -> dict[str, Any]:
    # Solo i campi utili: gli attributi molto grandi non vengono salvati
    # nella cronologia di Home Assistant (limite 16 KB).
    return {
        "tassa": payment.get("tassa"),
        "rata": payment.get("rata"),
        "scadenza": payment.get("dataScadenzaRata"),
        "importo": payment.get("importo"),
        "stato": payment.get("statoPagamento"),
        "data_pagamento": payment.get("dataPagamento"),
        "pagabile_online": payment.get("pagabileOnline"),
    }


def _payments_due(data) -> int:
    return sum(1 for x in data.get("payments", []) if _is_due(x))


def _payments_attrs(data):
    payments = data.get("payments", [])
    due = [x for x in payments if _is_due(x)]
    amounts = [a for a in (_amount(x) for x in due) if a is not None]
    deadlines = [x.get("dataScadenzaRata") for x in due if x.get("dataScadenzaRata")]
    return {
        "totale_pagamenti": len(payments),
        "totale_da_pagare": round(sum(amounts), 2),
        "prossima_scadenza": min(deadlines) if deadlines else None,
        "da_pagare": [_compact_payment(x) for x in due],
        "elenco": [_compact_payment(x) for x in payments],
    }


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data
    entities = []

    for coordinator in runtime.coordinators.values():
        entities.extend(
            [
            NuvolaSensor(
                coordinator,
                "average",
                "Media",
                "mdi:school",
                lambda d: d["stats"].get("average_subjects")
                if d["stats"].get("average_subjects") is not None
                else d["stats"].get("average_votes"),
                lambda d: _subject_attrs(d),
            ),
            NuvolaSensor(
                coordinator,
                "last_vote",
                "Ultimo voto",
                "mdi:clipboard-text",
                _latest_vote,
                _latest_vote_attrs,
            ),
            NuvolaSensor(
                coordinator,
                "vote_count",
                "Numero voti",
                "mdi:format-list-numbered",
                lambda d: len(d.get("votes", [])),
            ),
            NuvolaSensor(
                coordinator,
                "absence_count",
                "Assenze",
                "mdi:calendar-remove",
                lambda d: d["stats"]["absence_count"],
            ),
            NuvolaSensor(
                coordinator,
                "late_count",
                "Ritardi",
                "mdi:clock-alert-outline",
                lambda d: d["stats"]["late_count"],
            ),
            NuvolaSensor(
                coordinator,
                "exit_count",
                "Uscite anticipate",
                "mdi:exit-run",
                lambda d: d["stats"]["exit_count"],
            ),
            NuvolaSensor(
                coordinator,
                "unjustified_count",
                "Assenze non giustificate",
                "mdi:alert-circle-outline",
                lambda d: d["stats"]["unjustified_count"],
            ),
            NuvolaSensor(
                coordinator,
                "notes_count",
                "Note",
                "mdi:alert",
                lambda d: len(d.get("notes", [])),
            ),
            NuvolaSensor(
                coordinator,
                "notifications",
                "Notifiche non lette",
                "mdi:bell",
                lambda d: d.get("notifications", 0),
            ),
            NuvolaSensor(
                coordinator,
                "homework_today",
                "Compiti oggi",
                "mdi:book-open-page-variant",
                _homework_today,
                _homework_attrs,
            ),
            NuvolaSensor(
                coordinator,
                "homework_next_days",
                "Compiti prossimi giorni",
                "mdi:book-clock",
                lambda d: len(d.get("homework", [])),
                _homework_attrs,
            ),
            NuvolaSensor(
                coordinator,
                "events",
                "Eventi",
                "mdi:calendar-star",
                lambda d: len(d.get("events", [])),
                lambda d: {"elenco": d.get("events", [])},
            ),
            NuvolaSensor(
                coordinator,
                "payments",
                "Pagamenti da pagare",
                "mdi:cash-clock",
                _payments_due,
                _payments_attrs,
            ),
            ]
        )

    async_add_entities(entities)