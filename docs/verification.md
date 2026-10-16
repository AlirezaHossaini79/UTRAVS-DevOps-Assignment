# Verification and operations

These checks run after the [setup procedure](setup.md). Collect results outside
the checkout, review them for secret content and include only selected technical
evidence.

## Static configuration checks

```sh
git diff --check
cd cluster/kubespray/source
ansible-playbook -i ../inventory-utravs/inventory.ini cluster.yml --syntax-check
cd ../../..
helm lint platform/messaging/chart -f platform/messaging/values.yaml
helm template messaging platform/messaging/chart -n messaging -f platform/messaging/values.yaml >/dev/null
helm template messaging platform/messaging/chart -n messaging -f platform/messaging/values.yaml -f platform/messaging/values-prod.yaml >/dev/null
```

For each `platform/*/VERSION.yaml`, verify `package_sha256` against the adjacent
package and compare its chart version with `chart/Chart.yaml`. Helm rendering
requires no cluster access. Inspect Application source paths and the relative
Helm `valueFiles` whenever files move. Check CRD availability and admission
at the corresponding installation stage.

The [2026-10-16 rebuild review](../evidence/rebuild-review-20261016.json)
validated a clean export of the staged Git tree without local operator files.
It also compared all nine child Applications to their previous configuration
and checked SSH/Python on six hosts.

## Health and application traffic

```sh
kubectl get nodes
kubectl get --raw=/readyz
kubectl -n argocd get applications
kubectl -n kafka get kafka,kafkanodepool,kafkatopic,kafkauser
kubectl -n vault get pods -L vault-active,vault-sealed
kubectl -n messaging get pods
kubectl top nodes
kubectl -n messaging port-forward deployment/utravs-producer 18080:8080 --address=127.0.0.1
# In another terminal:
curl --fail-with-body http://127.0.0.1:18080/healthz
curl --fail-with-body http://127.0.0.1:18080/readyz
curl --fail-with-body -X POST http://127.0.0.1:18080/events \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"verification","booking_id":"VERIFY-001","payload":{"source":"assignment"}}'
kubectl -n messaging logs -l app=utravs-consumer -c consumer --since=5m --prefix=true
```

Expect HTTP 201 with an event ID and Kafka offset, followed by consumer
processing of that event. Match the event ID in consumer logs and stop each
port-forward after use.

## Metrics, alerts and traces

```sh
kubectl -n monitoring get prometheus,alertmanager,prometheusrule,podmonitor
kubectl -n monitoring get services
kubectl -n tracing port-forward service/jaeger 16686:16686 --address=127.0.0.1
```

Use Jaeger at `http://127.0.0.1:16686`, find `utravs-producer` and inspect a trace
that contains `kafka.produce` and `kafka.consume`. The consumer parent span must
match the producer span ID. The checked-in [trace](../evidence/tracing/jaeger-end-to-end.json)
contains both spans and their recorded timing, exported from an existing trace
without generating new traffic.

The deployed Jaeger exposes the v3 query API. Its
[official query schema](https://github.com/jaegertracing/jaeger-idl/blob/main/proto/api_v3/query_service.proto)
defines `GET /api/v3/traces` with `query.service_name`, RFC3339
`query.start_time_min`/`query.start_time_max` and `query.search_depth` parameters.
Keep exported span attributes limited to technical evidence; exclude credentials
and request headers.

In Prometheus, inspect targets for Kubernetes, istiod, messaging merged metrics,
Kafka JMX/exporter and `utravs-vault-health`. Check `up`, `probe_success` grouped
by `vault_node`, Kafka consumer lag and application publish/processing counters.
Check these configured critical alerts in Alertmanager:

| Alert | Trigger |
| --- | --- |
| KafkaConsumerLagHigh | consumer lag over 100 for 2 minutes |
| VaultUnavailable | fewer than 3 successful Vault probes or scrapes for 2 minutes |
| IstioMeshDegradation | missing/down messaging mesh target or failed TCP connections |

Blackbox probes use the public Vault CA and accept health HTTP 200, including
unsealed standbys through `standbyok=true`. A sealed node fails the probe.

## Security verification

Inspect the rendered messaging PeerAuthentication for `STRICT`, Kafka listener
9094 for `tls: true` plus TLS client authentication, and pod mounts for references
to generated client Secrets. Check `automountServiceAccountToken: false`, the
explicit short-lived projected JWT, non-root security contexts and TLS CA paths.
Never collect decoded Secret objects or Vault initialization output as evidence.

A full enforcement test should show authorized application traffic succeeds,
a disposable non-mesh client cannot reach a STRICT mesh workload, and Kafka
clients lacking the required certificate cannot authenticate. Use the actual
in-cluster workload path: a local port-forward can bypass the mesh boundary and
is not a valid negative mTLS test. Repeat enforcement checks before, during and
after each controlled failure.

For rotation, continuously submit test events for longer than the 60-second
runtime credential TTL and inspect rotation log entries without token values.
The existing rotation log records AppRole credential renewal while event
processing continued.

## Controlled failure tests

Run these only in the disposable lab, after health checks and with an operator
ready to restore the failed component. Record UTC timestamps with known units,
request results, consumer progress, security checks and recovery state.

For VIP failover, probe `/readyz` repeatedly through the VIP while stopping
Keepalived or HAProxy on the active load balancer. Record the failure action,
VIP ownership change and first sustained successful API response, then restore
the service. For Kafka, identify a test partition leader, deliberately delete
its broker pod and monitor producer results, consumer offsets, leader/ISR and
pod recovery. Broker eviction may be constrained by its disruption budget.

For Vault, the supplied script checks readiness and disruption allowance before
evicting the active pod:

```sh
UTRAVS_RUN_FAILOVER=yes bash scripts/reliability/vault-failover.sh
```

Unseal the recreated pod with three distinct shares and confirm all three Raft
members are healthy. The script records the leader-change observation interval
in milliseconds.

## Incident runbook

| Symptom | First checks and recovery |
| --- | --- |
| Consumer lag | Check consumer readiness, error logs, Vault/TLS access, partitions and ISR. Restore the failed dependency; scale consumers through Git only when partitions/capacity justify it. |
| Vault sealed/unavailable | Check active/standby labels, Raft quorum, TLS and PVC/node health. Unseal restarted pods; preserve data and never reinitialize a previously initialized cluster. |
| Kafka broker unavailable | Check pod/node/PVC state and leader/ISR. Restore the host or pod and wait for ISR recovery before another disruption. Avoid unsafe writes with insufficient ISR. |
| API VIP unavailable | Check VRRP reachability, VIP ownership, HAProxy state and control-plane TCP 6443 health. Restore the failed load balancer service and verify API readiness through the VIP. |

For application rollback, revert the relevant image tag/values commit and allow
Argo CD to reconcile. Database/Kafka/Vault upgrades require their own supported
upgrade and data-compatibility procedure; a chart rollback alone is insufficient.

## Optional features

See [optional features](optional-features.md) for the message-path SLI and provisioned
Grafana dashboard, native Deployment admission policy and controlled GitOps image
upgrade/rollback. The [runbook](runbook.md) contains incident commands and recovery
checks. Live results are stored under `evidence/optional/`.
