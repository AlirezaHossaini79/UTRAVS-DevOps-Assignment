import base64
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class VaultUnavailable(Exception):
    pass


@dataclass(frozen=True)
class RuntimeSecret:
    value: str
    version: int


class VaultClient:
    def __init__(self, role):
        self.role = role
        self.address = os.getenv(
            "VAULT_ADDR",
            "https://vault-active.vault.svc.cluster.local:8200"
        ).rstrip("/")
        self.jwt_path = Path(os.getenv(
            "VAULT_JWT_PATH",
            "/var/run/secrets/tokens/vault-jwt"
        ))
        self.context = ssl.create_default_context(
            cafile=os.getenv("VAULT_CACERT", "/etc/vault/ca.crt")
        )
        self.lock = threading.RLock()
        self.token = None
        self.token_expires = 0
        self.cached_secret = None
        self.cache_expires = 0

    def _request(self, path, payload=None, token=None):
        data = None if payload is None else json.dumps(payload).encode()

        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Vault-Token"] = token

        request = urllib.request.Request(
            f"{self.address}/v1/{path}",
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET"
        )

        with urllib.request.urlopen(
            request, context=self.context, timeout=5
        ) as response:
            return json.load(response)

    def _authenticate(self):
        jwt = self.jwt_path.read_text().strip()

        # First authenticate with Kubernetes ServiceAccount JWT.
        bootstrap = self._request(
            "auth/kubernetes/login",
            payload={"role": self.role, "jwt": jwt},
        )
        bootstrap_token = bootstrap["auth"]["client_token"]
        runtime_role = f"{self.role}-runtime"

        # Get the AppRole identifier.
        role_info = self._request(
            f"auth/approle/role/{runtime_role}/role-id",
            token=bootstrap_token,
        )
        role_id = role_info["data"]["role_id"]

        # Generate a short-lived, single-use SecretID.
        issued = self._request(
            f"auth/approle/role/{runtime_role}/secret-id",
            payload={},
            token=bootstrap_token,
        )
        secret = issued["data"]

        if (
            int(secret["secret_id_ttl"]) != 60
            or int(secret["secret_id_num_uses"]) != 1
        ):
            raise VaultUnavailable("Unexpected SecretID limits")

        # Consume SecretID to obtain the runtime token.
        login = self._request(
            "auth/approle/login",
            payload={
                "role_id": role_id,
                "secret_id": secret["secret_id"],
            },
        )

        auth = login["auth"]
        ttl = int(auth["lease_duration"])

        if ttl <= 0 or ttl > 60:
            raise VaultUnavailable("Invalid runtime token TTL")

        self.token = auth["client_token"]
        self.token_expires = time.monotonic() + max(1, ttl - 10)

        import logging
        logging.getLogger("utravs.vault").info(
            "vault_runtime_credential_rotated role=%s "
            "secret_id_ttl=60s secret_id_uses=1 "
            "runtime_token_ttl=%ss",
            self.role,
            ttl,
        )

    def _transit(self, action, message, signature=None):
        if action not in ("sign", "verify"):
            raise ValueError("Unsupported Transit operation")

        if not isinstance(message, bytes):
            raise TypeError("Message must be bytes")

        if action == "verify" and not isinstance(signature, str):
            raise ValueError("Signature must be a string")

        payload = {
            "input": base64.b64encode(message).decode("ascii")
        }

        if action == "verify":
            payload["signature"] = signature

        path = f"transit/{action}/utravs-events"

        with self.lock:
            try:
                if (
                    not self.token
                    or time.monotonic() >= self.token_expires
                ):
                    self._authenticate()

                try:
                    response = self._request(
                        path, payload=payload, token=self.token
                    )
                except urllib.error.HTTPError as error:
                    if error.code not in (401, 403):
                        raise

                    self._authenticate()
                    response = self._request(
                        path, payload=payload, token=self.token
                    )

                if action == "sign":
                    signed = response["data"]["signature"]

                    if not signed.startswith("vault:v"):
                        raise ValueError("Invalid Vault signature")

                    return signed

                valid = response["data"]["valid"]

                if not isinstance(valid, bool):
                    raise ValueError("Invalid verification response")

                return valid

            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                urllib.error.URLError,
            ):
                raise VaultUnavailable(
                    f"Vault Transit {action} failed"
                ) from None

    def sign_message(self, message: bytes) -> str:
        return self._transit("sign", message)

    def verify_message(
        self, message: bytes, signature: str
    ) -> bool:
        return self._transit("verify", message, signature)

    def get_runtime_secret(self):
        with self.lock:
            now = time.monotonic()

            if self.cached_secret and now < self.cache_expires:
                return self.cached_secret

            try:
                if not self.token or now >= self.token_expires:
                    self._authenticate()

                path = f"secret/data/utravs/{self.role.removeprefix('utravs-')}"

                try:
                    response = self._request(path, token=self.token)
                except urllib.error.HTTPError as error:
                    if error.code not in (401, 403):
                        raise

                    self._authenticate()
                    response = self._request(path, token=self.token)

                data = response["data"]
                value = data["data"]["runtime_key"]
                version = int(data["metadata"]["version"])

                if not isinstance(value, str) or not value:
                    raise VaultUnavailable("Invalid runtime secret")

                secret = RuntimeSecret(value=value, version=version)

                self.cached_secret = secret
                self.cache_expires = time.monotonic() + 10

                return secret

            except (
                OSError,
                ValueError,
                KeyError,
                urllib.error.URLError,
            ) as error:
                raise VaultUnavailable(
                    "Vault authentication or secret retrieval failed"
                ) from None
