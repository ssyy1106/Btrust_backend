import time
import json
import httpx
import jwt
from dotenv import load_dotenv
import os
import certifi

load_dotenv()

ACCOUNT_ID = os.getenv("NETSUITE_ACCOUNT_ID", "").strip()
CLIENT_ID = os.getenv("NETSUITE_CLIENT_ID", "").strip()
CERTIFICATE_ID = os.getenv("NETSUITE_CERTIFICATE_ID", "").strip()
PRIVATE_KEY_FILE = os.getenv("NETSUITE_PRIVATE_KEY_FILE", "private.pem").strip()

TOKEN_URL = (
    f"https://{ACCOUNT_ID}.suitetalk.api.netsuite.com"
    "/services/rest/auth/oauth2/v1/token"
)

def get_access_token() -> dict:
    now = int(time.time())

    with open(PRIVATE_KEY_FILE, "r", encoding="utf-8") as f:
        private_key = f.read()

    payload = {
        "iss": CLIENT_ID,
        "scope": ["rest_webservices"],
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 300,
    }

    headers = {
        "kid": CERTIFICATE_ID,
        "typ": "JWT",
        "alg": "PS256",
    }

    client_assertion = jwt.encode(
        payload,
        private_key,
        algorithm="PS256",
        headers=headers,
    )

    data = {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": client_assertion,
    }

    with httpx.Client(timeout=30, verify=certifi.where()) as client:
        resp = client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    print("Status:", resp.status_code)
    print(resp.text)

    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    token_result = get_access_token()
    print("\nAccess Token:")
    print(token_result["access_token"])