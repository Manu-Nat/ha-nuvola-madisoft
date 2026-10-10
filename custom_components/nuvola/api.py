from __future__ import annotations

import asyncio
import json
import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from aiohttp import ClientResponseError, ClientSession, ClientTimeout

from .const import API_BASE, BASE_URL, REQUEST_TIMEOUT


_LOGGER = logging.getLogger(__name__)


class NuvolaAuthError(Exception):
    """Authentication flow failure (not necessarily wrong credentials)."""


class NuvolaInvalidCredentials(NuvolaAuthError):
    """Nuvola explicitly rejected username/password."""


class NuvolaApiError(Exception):
    """Nuvola API error."""


class NuvolaApi:
    def __init__(self, hass, username: str, password: str) -> None:
        self.hass = hass
        self.username = username
        self.password = password
        self.session: ClientSession | None = None
        self.jwt: str | None = None
        self._login_lock = asyncio.Lock()

    async def _ensure_session(self) -> ClientSession:
        if self.session is None or self.session.closed:
            self.session = ClientSession(
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    ),
                    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
                },
            )
        return self.session

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    @staticmethod
    def _csrf(html: str) -> str:
        class _CsrfParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.value = None

            def handle_starttag(self, tag, attrs):
                if tag.lower() != "input":
                    return
                attrs = dict(attrs)
                if attrs.get("name") == "_csrf_token" and attrs.get("value"):
                    self.value = attrs["value"]

        parser = _CsrfParser()
        parser.feed(html)
        if parser.value:
            return str(parser.value)

        match = re.search(
            r"""name=["']_csrf_token["'][^>]*value=["']([^"']+)["']""",
            html,
            re.I,
        )
        if match:
            return match.group(1)

        match = re.search(
            r"""value=["']([^"']+)["'][^>]*name=["']_csrf_token["']""",
            html,
            re.I,
        )
        if match:
            return match.group(1)

        raise NuvolaAuthError("Token CSRF non trovato nella pagina di login.")

    @staticmethod
    def _token(value: Any) -> str:
        if isinstance(value, str) and value.startswith("ey"):
            return value
        if isinstance(value, dict):
            for key in ("token", "access_token", "jwt"):
                if isinstance(value.get(key), str):
                    return value[key]
        raise NuvolaAuthError("JWT Nuvola non trovato nella risposta.")

    @staticmethod
    def _parse_forms(
        page: str, base_url: str
    ) -> list[tuple[str, dict[str, str], str | None, str | None]]:
        """Return (action_url, inputs, username_key, password_key) for forms."""

        class _FormParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.forms: list[dict[str, Any]] = []
                self._current: dict[str, Any] | None = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                tag = tag.lower()

                if tag == "form":
                    self._current = {
                        "action": attrs.get("action") or "",
                        "inputs": {},
                        "user": None,
                        "pass": None,
                    }
                    self.forms.append(self._current)

                elif (
                    tag == "input"
                    and self._current is not None
                    and attrs.get("name")
                ):
                    name = attrs["name"]
                    input_type = (attrs.get("type") or "text").lower()
                    self._current["inputs"][name] = attrs.get("value") or ""

                    if (
                        input_type == "password" or name == "password"
                    ) and not self._current["pass"]:
                        self._current["pass"] = name
                    elif (
                        input_type in ("text", "email") or name == "username"
                    ) and not self._current["user"]:
                        self._current["user"] = name

            def handle_endtag(self, tag):
                if tag.lower() == "form":
                    self._current = None

        parser = _FormParser()
        parser.feed(page)

        return [
            (
                urljoin(base_url, form["action"]),
                form["inputs"],
                form["user"],
                form["pass"],
            )
            for form in parser.forms
        ]

    @staticmethod
    def _js_unescape(value: str) -> str:
        """Decode a JS/JSON string literal body."""

        def replace(match: re.Match) -> str:
            token = match.group(1)
            if len(token) == 3 and token[0] == "x":
                return chr(int(token[1:], 16))
            if len(token) == 5 and token[0] == "u":
                return chr(int(token[1:], 16))
            return {"n": "\n", "t": "\t", "r": "\r"}.get(token, token)

        return unescape(
            re.sub(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", replace, value)
        )

    @classmethod
    def _kc_value(cls, page: str, key: str) -> str | None:
        """Read a string value from the embedded Keycloak theme context."""

        match = re.search(
            r"""["']?"""
            + re.escape(key)
            + r"""["']?\]?\s*[:=]\s*"""
            + r"""(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)')""",
            page,
        )
        if not match:
            return None

        value = match.group(1) if match.group(1) is not None else match.group(2)
        return cls._js_unescape(value)

    @classmethod
    def _kc_form(
        cls, page: str, base_url: str
    ) -> tuple[str, dict[str, str], str | None, str | None] | None:
        """Describe a login form rendered by a JavaScript Keycloak theme."""

        action = cls._kc_value(page, "loginAction")
        if not action:
            return None

        page_id = cls._kc_value(page, "pageId") or "login.ftl"
        action = urljoin(base_url, action)

        # The current Nuvola theme reports "login"; older Keycloak themes
        # may report "login.ftl".
        if page_id in ("login.ftl", "login"):
            return action, {"credentialId": ""}, "username", "password"
        if page_id == "login-username.ftl":
            return action, {}, "username", None
        if page_id == "login-password.ftl":
            return action, {"credentialId": ""}, None, "password"

        return None

    @classmethod
    def _login_form(
        cls,
        page: str,
        base_url: str,
        allow_username_only: bool = False,
    ) -> tuple[str, dict[str, str], str | None, str | None] | None:
        """Find a login form in HTML or in Keycloak's embedded theme context."""

        forms = cls._parse_forms(page, base_url)

        for form in forms:
            if form[3]:
                return form

        if allow_username_only:
            for form in forms:
                if form[2]:
                    return form

        keycloak_form = cls._kc_form(page, base_url)
        if keycloak_form and (
            keycloak_form[3]
            or (allow_username_only and keycloak_form[2])
        ):
            return keycloak_form

        return None

    @classmethod
    def _describe_page(cls, page: str, base_url: str) -> str:
        forms = cls._parse_forms(page, base_url)

        if not forms:
            title = re.search(
                r"<title[^>]*>(.*?)</title>", page, re.I | re.S
            )
            scripts = re.findall(
                r"""<script[^>]*\ssrc=["']([^"']+)["']""",
                page,
                re.I,
            )
            return (
                "nessun form nella pagina "
                f"(titolo={title.group(1).strip()[:80] if title else None!r}, "
                f"pageId={cls._kc_value(page, 'pageId')!r}, "
                f"loginAction="
                f"{'sì' if cls._kc_value(page, 'loginAction') else 'no'}, "
                f"messaggio={cls._kc_value(page, 'summary')!r}, "
                f"script={[script[-50:] for script in scripts[:2]]}, "
                f"{len(page)} caratteri)"
            )

        return "form: " + " | ".join(
            f"{urlparse(action).path} campi={sorted(inputs)} "
            f"utente={username} password={password}"
            for action, inputs, username, password in forms
        )

    async def login(self) -> None:
        """Login via Nuvola's Keycloak flow, then retrieve the API JWT."""
        async with self._login_lock:
            # OIDC state is bound to the session cookies.
            await self.close()
            session = await self._ensure_session()
            html_headers = {
                "Accept": "text/html,application/xhtml+xml",
            }

            try:
                candidates = [
                    BASE_URL + "/login",
                    BASE_URL + "/connect/authentication-service",
                ]
                form = None
                diagnostics = ""
                tried: list[str] = []
                index = 0

                while index < len(candidates) and index < 6:
                    url = candidates[index]
                    index += 1

                    async with session.get(
                        url,
                        headers=html_headers,
                    ) as resp:
                        page = await resp.text()
                        login_url = str(resp.url)

                        # Log only the host and path: OIDC URLs may contain
                        # temporary state or session parameters.
                        _LOGGER.debug(
                            "login step %s: HTTP %s, URL finale=%s%s",
                            urlparse(url).path,
                            resp.status,
                            urlparse(login_url).netloc,
                            urlparse(login_url).path,
                        )
                        tried.append(
                            f"{resp.status} "
                            f"{urlparse(login_url).netloc}"
                            f"{urlparse(login_url).path}"
                        )

                        if resp.status >= 400:
                            continue

                    form = self._login_form(
                        page,
                        login_url,
                        allow_username_only=True,
                    )
                    if form is not None:
                        break

                    diagnostics = self._describe_page(page, login_url)

                    # Find a link that starts the OIDC flow.
                    for href in re.findall(
                        r"""href=["']([^"']*(?:/connect/|openid-connect/auth)[^"']*)["']""",
                        page,
                    ):
                        link = urljoin(login_url, unescape(href))
                        if link not in candidates:
                            candidates.insert(index, link)

                if form is None:
                    raise NuvolaAuthError(
                        "Form di login non trovato (provato: "
                        + "; ".join(tried)
                        + f"). Ultima pagina, {diagnostics}."
                    )

                action, fields, user_key, pass_key = form

                # Submit the Keycloak form, allowing username-first flows.
                submitted_password = False
                reached_nuvola = False

                for _step in range(4):
                    payload = dict(fields)

                    if user_key:
                        payload[user_key] = self.username

                    if pass_key:
                        payload[pass_key] = self.password
                        submitted_password = True

                    async with session.post(
                        action,
                        data=payload,
                        headers=html_headers,
                    ) as resp:
                        body = await resp.text()
                        final_url = str(resp.url)

                        _LOGGER.debug(
                            "invio form (campi=%s): HTTP %s, URL finale=%s%s",
                            sorted(payload),
                            resp.status,
                            urlparse(final_url).netloc,
                            urlparse(final_url).path,
                        )

                        if (
                            urlparse(final_url).netloc
                            == urlparse(BASE_URL).netloc
                        ):
                            if resp.status >= 400:
                                raise NuvolaAuthError(
                                    "Ritorno da Keycloak fallito "
                                    f"(HTTP {resp.status})."
                                )
                            reached_nuvola = True
                            break

                    if 'name="otp"' in body:
                        raise NuvolaAuthError(
                            "Nuvola richiede un codice OTP "
                            "(non supportato)."
                        )

                    next_form = self._login_form(
                        body,
                        final_url,
                        allow_username_only=True,
                    )
                    if next_form is None:
                        raise NuvolaAuthError(
                            "Keycloak richiede un passaggio aggiuntivo: "
                            + self._describe_page(body, final_url)
                            + "."
                        )

                    action, fields, user_key, pass_key = next_form

                    if pass_key and submitted_password:
                        raise NuvolaInvalidCredentials(
                            "Username o password non validi."
                        )

                    if not pass_key and user_key:
                        raise NuvolaInvalidCredentials(
                            "Username non riconosciuto o non valido."
                        )

                if not reached_nuvola:
                    raise NuvolaAuthError(
                        "Troppi passaggi di login su Keycloak."
                    )

                # Exchange the authenticated web session for the API JWT.
                async with session.get(
                    API_BASE + "/login-from-web",
                    headers={"Accept": "application/json"},
                ) as resp:
                    _LOGGER.debug(
                        "login-from-web: HTTP %s, Content-Type=%s",
                        resp.status,
                        resp.headers.get("Content-Type"),
                    )

                    if resp.status in (401, 403):
                        raise NuvolaAuthError(
                            "login-from-web: sessione non autorizzata "
                            f"(HTTP {resp.status})."
                        )

                    if resp.status >= 400:
                        raise NuvolaAuthError(
                            f"login-from-web: HTTP {resp.status}."
                        )

                    raw = (await resp.text()).strip()
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        data = raw

                self.jwt = self._token(data)

            except NuvolaAuthError as err:
                _LOGGER.warning("Login Nuvola fallito: %s", err)
                self.jwt = None
                raise
            except Exception as err:
                self.jwt = None
                raise NuvolaApiError(
                    "Errore di rete durante l'autenticazione "
                    f"({type(err).__name__})."
                ) from err

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        if not self.jwt:
            await self.login()

        session = await self._ensure_session()
        headers = {"Authorization": f"Bearer {self.jwt}"}

        try:
            async with session.request(
                method,
                API_BASE + path,
                params=params,
                headers=headers,
            ) as resp:
                if resp.status == 401 and retry_auth:
                    self.jwt = None
                    await self.login()
                    return await self._request(
                        method,
                        path,
                        params=params,
                        retry_auth=False,
                    )

                if resp.status == 403:
                    raise NuvolaApiError(
                        "Nuvola ha negato l'accesso alla risorsa."
                    )

                if resp.status == 404:
                    raise NuvolaApiError(
                        f"Risorsa Nuvola non trovata: {path}"
                    )

                if resp.status >= 400:
                    # Avoid logging or displaying the response body: it may
                    # contain personal or session information.
                    raise NuvolaApiError(
                        f"Nuvola HTTP {resp.status} su {path}."
                    )

                return await resp.json(content_type=None)

        except (NuvolaAuthError, NuvolaApiError):
            raise
        except ClientResponseError as err:
            raise NuvolaApiError(
                f"Errore HTTP durante la richiesta ({err.status})."
            ) from err
        except Exception as err:
            raise NuvolaApiError(
                f"Errore di rete su {path} ({type(err).__name__})."
            ) from err

    @staticmethod
    def values(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if isinstance(payload, dict):
            value = payload.get("valori")
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]

        return []

    async def get_students(self) -> list[dict[str, Any]]:
        return self.values(await self._request("GET", "/alunni"))

    async def get_periods(self, student_id: int) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/frazioni-temporali",
                params={"contextAlunno": student_id},
            )
        )

    async def get_votes(self, student_id: int) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/voti",
                params={"contextAlunno": student_id},
            )
        )

    async def get_subject_votes(
        self,
        student_id: int,
        period_id: int,
    ) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/frazione-temporale/"
                f"{period_id}/voti/materie",
                params={"contextAlunno": student_id},
            )
        )

    async def get_absences(self, student_id: int) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/assenze",
                params={"contextAlunno": student_id, "limit": 500},
            )
        )

    async def get_notes(self, student_id: int) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/note",
                params={"contextAlunno": student_id, "limit": 200},
            )
        )

    async def get_notification_count(self, student_id: int) -> int:
        payload = await self._request(
            "GET",
            f"/alunno/{student_id}/notifiche/conteggio",
            params={"contextAlunno": student_id},
        )

        if isinstance(payload, dict):
            for key in ("count", "conteggio", "numero"):
                try:
                    return int(payload[key])
                except (KeyError, TypeError, ValueError):
                    pass

        return 0

    async def get_homework(
        self,
        student_id: int,
        date_ddmmyyyy: str,
    ) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/compito/elenco/{date_ddmmyyyy}",
                params={"contextAlunno": student_id},
            )
        )

    async def get_events(
        self,
        student_id: int,
        endpoint: str,
    ) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/{endpoint}",
                params={"contextAlunno": student_id},
            )
        )

    async def get_lessons(
        self,
        student_id: int,
        date_ddmmyyyy: str,
    ) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/argomento-lezione/elenco/"
                f"{date_ddmmyyyy}",
                params={"contextAlunno": student_id},
            )
        )

    async def get_payments(self, student_id: int) -> list[dict[str, Any]]:
        return self.values(
            await self._request(
                "GET",
                f"/alunno/{student_id}/pagamenti",
                params={"contextAlunno": student_id},
            )
        )