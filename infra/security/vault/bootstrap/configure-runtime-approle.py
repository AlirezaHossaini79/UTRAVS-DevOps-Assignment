import json
import socket
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

base = Path.home() / ".local/share/utravs"
vault_dir = Path(__file__).resolve().parents[1]
policy_dir = vault_dir / "policies"
policy_dir.mkdir(parents=True, exist_ok=True)

root_token = json.loads(
    (base / "vault-bootstrap/vault-init.json").read_text()
)["root_token"]

ctx = ssl.create_default_context(
    cafile=str(base / "vault-pki/ca.crt")
)

pf = subprocess.Popen(
    [
        "kubectl", "-n", "vault", "port-forward",
        "pod/vault-0", "18300:8200",
        "--address=127.0.0.1"
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

def api(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://127.0.0.1:18300/v1/{path}",
        data=data,
        headers={
            "X-Vault-Token": root_token,
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        body = r.read()
        return json.loads(body) if body else {}

try:
    for _ in range(30):
        if pf.poll() is not None:
            raise RuntimeError("Vault port-forward stopped")
        try:
            with socket.create_connection(("127.0.0.1", 18300), 1):
                break
        except OSError:
            time.sleep(1)
    else:
        raise TimeoutError("Vault connection timeout")

    methods = api("sys/auth")["data"]

    if "approle/" not in methods:
        api("sys/auth/approle", {"type": "approle"})
        print("PASS: AppRole enabled")
    elif methods["approle/"]["type"] != "approle":
        raise RuntimeError("Unexpected approle auth type")

    for app in ("producer", "consumer"):
        name = f"utravs-{app}"
        runtime = f"{name}-runtime"
        bootstrap = f"{name}-bootstrap"

        policy = f'''
path "auth/approle/role/{runtime}/role-id" {{
  capabilities = ["read"]
}}

path "auth/approle/role/{runtime}/secret-id" {{
  capabilities = ["update"]
}}
'''
        (policy_dir / f"{app}-bootstrap.hcl").write_text(policy)

        api(
            f"sys/policies/acl/{bootstrap}",
            {"policy": policy},
        )

        api(
            f"auth/approle/role/{runtime}",
            {
                "bind_secret_id": True,
                "secret_id_ttl": "60s",
                "secret_id_num_uses": 1,
                "token_ttl": "60s",
                "token_max_ttl": "60s",
                "token_explicit_max_ttl": "60s",
                "token_policies": [name],
                "token_no_default_policy": True,
            },
        )

        # Keep the existing application policy during rollout.
        api(
            f"auth/kubernetes/role/{name}",
            {
                "bound_service_account_names": [name],
                "bound_service_account_namespaces": ["messaging"],
                "token_policies": [name, bootstrap],
                "token_ttl": "5m",
                "token_max_ttl": "15m",
            },
        )

        info = api(f"auth/approle/role/{runtime}")["data"]

        assert int(info["secret_id_ttl"]) == 60
        assert int(info["secret_id_num_uses"]) == 1
        assert int(info["token_ttl"]) == 60

        print(f"PASS: {runtime} — SecretID 60s, one use")

    print("PASS: Vault runtime authentication configured")

finally:
    pf.terminate()
    try:
        pf.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pf.kill()
        pf.wait()
