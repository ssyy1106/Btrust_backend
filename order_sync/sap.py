import re

import requests

from .config import get_config


class SapClient:
    def __init__(self):
        self.settings = get_config()["sap_order_sync"]
        self.base_url = self.settings["base_url"].rstrip("/")
        self.timeout = self.settings.getfloat("timeout_seconds")
        self.session = requests.Session()
        self.session.verify = self.settings.getboolean("verify_ssl")
        self.logged_in = False

    def login(self):
        response = self.session.post(
            f"{self.base_url}/Login",
            json={"CompanyDB": self.settings["company_db"],
                  "UserName": self.settings["username"], "Password": self.settings["password"]},
            timeout=self.timeout,
        )
        response.raise_for_status()
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
        response = self.session.get(
            f"{self.base_url}/Orders",
            params={"$select": "DocEntry,DocNum", "$filter": f"{field} eq '{escaped}'", "$top": 2},
            timeout=self.timeout,
        )
        response.raise_for_status()
        matches = response.json()["value"]
        if len(matches) > 1:
            raise ValueError(f"Multiple SAP orders found for {external_key}")
        return matches[0] if matches else None

    def create_order(self, payload):
        response = self.session.post(f"{self.base_url}/Orders", json=payload, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result.get("DocEntry"), int) or not isinstance(result.get("DocNum"), int):
            raise ValueError("SAP creation response has no valid DocEntry/DocNum; verify manually")
        return result
