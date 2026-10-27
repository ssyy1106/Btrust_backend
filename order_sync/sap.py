import re

import requests

from .config import get_config


class SapClient:
    def _request(self, operation, method, path, **kwargs):
        url = f"{self.base_url}/{path}"
        response = None
        try:
            response = getattr(self.session, method.lower())(
                url, timeout=self.timeout, **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            # Preserve the exception type and response for the worker's retry policy.
            details = [f"SAP {operation} failed", f"method={method}", f"url={url}"]
            if kwargs.get("params"):
                details.append(f"params={kwargs['params']!r}")
            if response is not None:
                details.append(f"status={response.status_code} {response.reason}")
                body = response.text.strip()
                if len(body) > 6000:
                    body = body[:6000] + "... [truncated]"
                details.append(f"response_body={body or '<empty>'}")
            details.append(f"cause={exc}")
            # Do not include request bodies/headers: Login contains credentials.
            exc.args = ("; ".join(details),)
            raise

    def __init__(self):
        self.settings = get_config()["sap_order_sync"]
        self.base_url = self.settings["base_url"].rstrip("/")
        self.timeout = self.settings.getfloat("timeout_seconds")
        self.session = requests.Session()
        self.session.verify = self.settings.getboolean("verify_ssl")
        self.logged_in = False

    def login(self):
        self._request(
            "login", "POST", "Login",
            json={"CompanyDB": self.settings["company_db"],
                  "UserName": self.settings["username"], "Password": self.settings["password"]},
        )
        self.logged_in = True

    def close(self):
        try:
            if self.logged_in:
                self.session.post(f"{self.base_url}/Logout", timeout=self.timeout)
        except requests.RequestException:
            pass
        finally:
            self.session.close()

    def find_order(self, external_key):
        field = self.settings["external_key_field"].strip()
        if field != "NumAtCard" and not re.fullmatch(r"U_[A-Za-z0-9_]+", field):
            raise ValueError("external_key_field must be NumAtCard or an existing SAP order UDF (U_...)")
        escaped = external_key.replace("'", "''")
        response = self._request(
            "find_order", "GET", "Orders",
            params={"$select": "DocEntry,DocNum", "$filter": f"{field} eq '{escaped}'", "$top": 2},
        )
        matches = response.json()["value"]
        if len(matches) > 1:
            raise ValueError(f"Multiple SAP orders found for {external_key}")
        return matches[0] if matches else None

    def create_order(self, payload):
        response = self._request(
            "create_order", "POST", "Orders", json=payload,
            headers={"Prefer": "return-no-content"},
        )
        if response.status_code == 204:
            # No JSON body is returned with this preference. Resolve the order
            # by its external key so only an actual Sales Order is marked done.
            field = self.settings["external_key_field"].strip()
            external_key = payload.get(field)
            result = self.find_order(external_key) if external_key else None
            if result is None:
                raise ValueError(
                    "SAP create_order returned HTTP 204 (no content), but no Sales Order "
                    f"was found for {field}={external_key!r}. Approval procedures may have "
                    "created a draft; verify SAP drafts/approval status manually before resending."
                )
        else:
            result = response.json()
        if not isinstance(result.get("DocEntry"), int) or not isinstance(result.get("DocNum"), int):
            raise ValueError("SAP creation response has no valid DocEntry/DocNum; verify manually")
        return result
