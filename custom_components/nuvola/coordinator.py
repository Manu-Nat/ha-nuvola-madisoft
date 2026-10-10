from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import unicodedata
from statistics import mean
from typing import Any

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import NuvolaApi, NuvolaApiError
from .const import COMPITI_DAYS, UPDATE_INTERVAL_MINUTES


_LOGGER = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip().replace(",", ".")
    text = text.replace("½", ".5")

    try:
        return float(text)
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    if not value:
        return None

    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None


def _normalise_name(value: Any) -> str:
    """Normalise a name for comparison, ignoring case, accents and spaces."""
    if not value:
        return ""

    text = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(character for character in text if character.isalnum())


def _student_full_name(student: dict[str, Any]) -> str:
    full_name = student.get("nomeCompleto")
    if full_name:
        return _normalise_name(full_name)

    first_name = student.get("nome") or student.get("nomeAlunno") or ""
    last_name = student.get("cognome") or student.get("cognomeAlunno") or ""
    return _normalise_name(f"{first_name} {last_name}")


def _payment_belongs_to_student(
    payment: dict[str, Any],
    student: dict[str, Any],
) -> bool:
    """Return whether a payment explicitly belongs to this student."""
    student_name = _student_full_name(student)
    if not student_name:
        return False

    payment_first_name = payment.get("nomeAlunno") or payment.get("nome")
    payment_last_name = payment.get("cognomeAlunno") or payment.get("cognome")

    if payment_first_name or payment_last_name:
        payment_name = _normalise_name(
            f"{payment_first_name or ''} {payment_last_name or ''}"
        )
    else:
        payment_name = _normalise_name(
            payment.get("nomeCompleto")
            or payment.get("alunno")
            or payment.get("destinatario")
        )

    # Exclude payments without a recognisable student name. Assigning them
    # could mix one student's payments into another student's sensor.
    return bool(payment_name and payment_name == student_name)


class NuvolaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass, api: NuvolaApi, student_id: int) -> None:
        self.api = api
        self.student_id = student_id

        super().__init__(
            hass,
            _LOGGER,
            name="Nuvola Madisoft",
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            students = await self.api.get_students()
            student = next(
                (
                    item
                    for item in students
                    if int(item.get("id", -1)) == self.student_id
                ),
                None,
            )
            if not student:
                raise UpdateFailed(
                    "Studente non trovato nell'account Nuvola."
                )

            periods = await self.api.get_periods(self.student_id)
            current_period = next(
                (item for item in periods if item.get("corrente") is True),
                periods[-1] if periods else None,
            )

            votes = await self.api.get_votes(self.student_id)
            absences = await self.api.get_absences(self.student_id)
            notes = await self.api.get_notes(self.student_id)
            notifications = await self.api.get_notification_count(
                self.student_id
            )

            subjects: list[dict[str, Any]] = []
            if current_period and current_period.get("id") is not None:
                try:
                    subjects = await self.api.get_subject_votes(
                        self.student_id,
                        int(current_period["id"]),
                    )
                except NuvolaApiError as err:
                    _LOGGER.warning(
                        "Medie per materia non disponibili: %s",
                        err,
                    )

            homework: list[dict[str, Any]] = []
            today = dt_util.now().date()

            for offset in range(COMPITI_DAYS):
                day = today + timedelta(days=offset)
                try:
                    items = await self.api.get_homework(
                        self.student_id,
                        day.strftime("%d-%m-%Y"),
                    )
                except NuvolaApiError as err:
                    _LOGGER.warning(
                        "Compiti non disponibili per %s: %s",
                        day,
                        err,
                    )
                    continue

                for item in items:
                    item = dict(item)
                    item["_date"] = day.isoformat()
                    homework.append(item)

            events: list[dict[str, Any]] = []
            for endpoint in (
                "eventi-classe",
                "eventi-classe-materia",
                "eventi-alunno",
            ):
                try:
                    events.extend(
                        await self.api.get_events(
                            self.student_id,
                            endpoint,
                        )
                    )
                except NuvolaApiError:
                    pass

            payments: list[dict[str, Any]] = []
            try:
                all_payments = await self.api.get_payments(self.student_id)
                payments = [
                    payment
                    for payment in all_payments
                    if _payment_belongs_to_student(payment, student)
                ]
            except NuvolaApiError:
                pass

            visible_votes = [
                vote
                for vote in votes
                if vote.get("visibile", True) is not False
            ]

            numeric_votes = [
                number
                for number in (
                    _num(vote.get("valore", vote.get("valutazione")))
                    for vote in visible_votes
                )
                if number is not None and 0 <= number <= 10
            ]

            averages = []
            for subject in subjects:
                number = _num(subject.get("media"))
                if number is not None:
                    averages.append(number)

            last_vote = None
            dated_votes = []
            for vote in visible_votes:
                vote_date = _date(vote.get("data"))
                if vote_date:
                    dated_votes.append((vote_date, vote))

            if dated_votes:
                dated_votes.sort(key=lambda item: item[0], reverse=True)
                last_vote = dated_votes[0][1]

            absence_count = sum(
                1
                for item in absences
                if str(item.get("tipo", "")).lower() == "assenza"
            )
            late_count = sum(
                1
                for item in absences
                if str(item.get("tipo", "")).lower() == "ritardo"
            )
            exit_count = sum(
                1
                for item in absences
                if str(item.get("tipo", "")).lower() == "uscita"
            )
            unjustified_count = sum(
                1
                for item in absences
                if item.get("giustificata") is False
            )

            return {
                "student": student,
                "periods": periods,
                "current_period": current_period,
                "votes": visible_votes,
                "subjects": subjects,
                "absences": absences,
                "notes": notes,
                "notifications": notifications,
                "homework": homework,
                "events": events,
                "payments": payments,
                "stats": {
                    "average_votes": (
                        round(mean(numeric_votes), 2)
                        if numeric_votes
                        else None
                    ),
                    "average_subjects": (
                        round(mean(averages), 2)
                        if averages
                        else None
                    ),
                    "absence_count": absence_count,
                    "late_count": late_count,
                    "exit_count": exit_count,
                    "unjustified_count": unjustified_count,
                },
                "last_vote": last_vote,
                "last_update": dt_util.now().isoformat(),
            }

        except NuvolaApiError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            _LOGGER.exception("Errore inatteso aggiornando Nuvola")
            raise UpdateFailed(f"Errore inatteso: {err}") from err