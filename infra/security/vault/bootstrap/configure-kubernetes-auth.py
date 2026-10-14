import json
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

base = Path.home() / ".local/share/utravs"

token = json.loads(
    (base / "vault-bootstrap/vault-init.json").read_text()
)["root_token"]

ctx = ssl.create_default_context(
    cafile=str(base / "vault-pki/ca.crt")
)

pf = subprocess.Popen(
    [
        "kubectl", "-n", "vault", "port-forward",
        "pod/vault-0", "18200:8200",
        "--address=127.0.0.1"
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

def vault_api(path, payload=None):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()

    req = urllib.request.Request(
        f"https://127.0.0.1:18200/v1/{path}",
        data=data,
        headers={
            "X-Vault-Token": token,
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(
        req, context=ctx, timeout=15
    ) as response:
        body = response.read()
        return json.loads(body) if body else {}

try:
    for _ in range(30):
        if pf.poll() is not None:
            raise RuntimeError("Vault port-forward failed")
        try:
            with socket.create_connection(
                ("127.0.0.1", 18200), 1
            ):
                break
        except OSError:
            time.sleep(1)
    else:
        raise TimeoutError("Vault connection timeout")

    auth_methods = vault_api("sys/auth")["data"]

    if "kubernetes/" not in auth_methods:
        vault_api(
            "sys/auth/kubernetes",
            {"type": "kubernetes"}
        )
        print("Kubernetes Auth enabled")
    else:
        assert auth_methods["kubernetes/"]["type"] == "kubernetes"
        print("Kubernetes Auth already enabled")

    vault_api(
        "auth/kubernetes/config",
        {
            "kubernetes_host":
                "https://kubernetes.default.svc:443"
        }
    )


    policy_dir = Path(__file__).resolve().parents[1] / "policies"

    for app in ("producer", "consumer"):
        name = f"utravs-{app}"

        policy = (policy_dir / f"{app}.hcl").read_text()

        vault_api(
            f"sys/policies/acl/{name}",
            {"policy": policy}
        )

        vault_api(
            f"auth/kubernetes/role/{name}",
            {
                "bound_service_account_names": [name],
                "bound_service_account_namespaces": ["messaging"],
                "token_policies": [name, f"{name}-bootstrap"],
                "token_ttl": "5m",
                "token_max_ttl": "15m"
            }
        )

        print(f"Policy and Kubernetes Role configured: {name}")


    # Configure KV v2 secrets engine idempotently
    mounts = vault_api("sys/mounts")["data"]

    if "secret/" not in mounts:
        vault_api(
            "sys/mounts/secret",
            {
                "type": "kv",
                "description": "UTRAVS application secrets",
                "options": {"version": "2"}
            }
        )
        print("KV v2 engine enabled at secret/")
    else:
        mount = mounts["secret/"]

        if (
            mount["type"] != "kv"
            or mount.get("options", {}).get("version") != "2"
        ):
            raise RuntimeError(
                "Existing secret/ mount is not KV v2"
            )

        print("KV v2 engine already enabled")


    # Configure Vault Transit engine and signing key
    mounts = vault_api("sys/mounts")["data"]

    if "transit/" not in mounts:
        vault_api(
            "sys/mounts/transit",
            {"type": "transit"}
        )
        print("Transit engine enabled")
    elif mounts["transit/"]["type"] != "transit":
        raise RuntimeError("Invalid transit mount")
    else:
        print("Transit engine already enabled")

    try:
        key_info = vault_api(
            "transit/keys/utravs-events"
        )["data"]

    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise

        vault_api(
            "transit/keys/utravs-events",
            {
                "type": "ed25519",
                "exportable": False
            }
        )

        key_info = vault_api(
            "transit/keys/utravs-events"
        )["data"]

        print("Transit signing key created")

    if (
        key_info["type"] != "ed25519"
        or key_info.get("exportable", False)
    ):
        raise RuntimeError("Unexpected Transit key configuration")

    print("Transit signing key verified: ed25519")

    print("Kubernetes Auth configured successfully")

finally:
    pf.terminate()
    pf.wait(timeout=10)
