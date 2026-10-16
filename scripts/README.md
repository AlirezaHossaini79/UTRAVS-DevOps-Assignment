# Reliability tools

`reliability/vault-failover.sh` evicts the current Vault active pod and records
producer HTTP responses, the observed leader change and consumer processing.
It requires an initialized, unsealed three-node Vault cluster, kubectl, curl,
Python 3 and permission to create an Eviction. Read
[the reliability report](../docs/reliability.md) before use.

```sh
UTRAVS_RUN_FAILOVER=yes bash scripts/reliability/vault-failover.sh
```

The test deliberately disrupts Vault. The replacement pod requires manual
Shamir unseal. Runtime output is written with restrictive permissions beneath
`$HOME/.local/state/utravs`, or `UTRAVS_STATE_DIR` when explicitly configured.
Wall-clock timestamps are recorded in milliseconds using Python.
Running the script without the explicit enable variable exits before cluster
access. A new test does not replace the historical evidence in this repository.
