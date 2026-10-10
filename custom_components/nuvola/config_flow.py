from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import (
    NuvolaApi,
    NuvolaApiError,
    NuvolaAuthError,
    NuvolaInvalidCredentials,
)
from .const import (
    CONF_PASSWORD,
    CONF_STUDENT_IDS,
    CONF_USERNAME,
    DOMAIN,
    MAX_STUDENTS,
)


class NuvolaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._username = ""
        self._password = ""
        self._students: list[dict[str, Any]] = []

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"detail": ""}
        if user_input:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()

            api = NuvolaApi(self.hass, self._username, self._password)
            try:
                await api.login()
                self._students = await api.get_students()
                if not self._students:
                    errors["base"] = "no_students"
                elif len(self._students) == 1:
                    await api.close()
                    return self.async_create_entry(
                        title=f"Nuvola - {self._student_name(self._students[0])}",
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_STUDENT_IDS: [int(self._students[0]["id"])],
                        },
                    )
                else:
                    await api.close()
                    return await self.async_step_students()
            except NuvolaInvalidCredentials:
                errors["base"] = "invalid_auth"
            except NuvolaAuthError as err:
                errors["base"] = "login_failed"
                placeholders["detail"] = str(err)
            except NuvolaApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            finally:
                await api.close()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=1)),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_students(self, user_input=None):
        errors: dict[str, str] = {}
        options = self._student_options()
        if user_input:
            student_ids = [int(value) for value in user_input[CONF_STUDENT_IDS]]
            if not 1 <= len(student_ids) <= MAX_STUDENTS:
                errors["base"] = "too_many_students"
            else:
                return self.async_create_entry(
                    title=self._entry_title(student_ids),
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_STUDENT_IDS: student_ids,
                    },
                )

        return self.async_show_form(
            step_id="students",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STUDENT_IDS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={"max_students": str(MAX_STUDENTS)},
        )

    def _student_options(self) -> list[dict[str, str]]:
        return [
            {"value": str(student["id"]), "label": self._student_name(student)}
            for student in self._students
        ]

    def _student_name(self, student: dict[str, Any]) -> str:
        return str(
            student.get("nomeCompleto")
            or f"{student.get('nome', '')} {student.get('cognome', '')}".strip()
            or f"Studente {student.get('id', '')}"
        )

    def _entry_title(self, student_ids: list[int]) -> str:
        names = [
            self._student_name(student)
            for student in self._students
            if int(student.get("id", -1)) in student_ids
        ]
        if len(names) == 1:
            return f"Nuvola - {names[0]}"
        return f"Nuvola - {len(names)} studenti"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NuvolaOptionsFlow(config_entry)


class NuvolaOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry
        self._students: list[dict[str, Any]] = []

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}
        api = NuvolaApi(
            self.hass,
            self.config_entry.data[CONF_USERNAME],
            self.config_entry.data[CONF_PASSWORD],
        )
        try:
            await api.login()
            self._students = await api.get_students()
        except NuvolaAuthError:
            errors["base"] = "invalid_auth"
        except NuvolaApiError:
            errors["base"] = "cannot_connect"
        except Exception:
            errors["base"] = "unknown"
        finally:
            await api.close()

        if errors:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if user_input:
            student_ids = [int(value) for value in user_input[CONF_STUDENT_IDS]]
            if not 1 <= len(student_ids) <= MAX_STUDENTS:
                errors["base"] = "too_many_students"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_STUDENT_IDS: student_ids,
                    },
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="")

        options = [
            {
                "value": str(student["id"]),
                "label": str(
                    student.get("nomeCompleto")
                    or f"{student.get('nome', '')} {student.get('cognome', '')}".strip()
                    or f"Studente {student.get('id', '')}"
                ),
            }
            for student in self._students
        ]
        current = [str(x) for x in self.config_entry.data.get(CONF_STUDENT_IDS, [])]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STUDENT_IDS, default=current): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={"max_students": str(MAX_STUDENTS)},
        )
