# Short incident runbook

Run commands from the configured operator host. Check the affected dependency
before scaling or restarting applications. Preserve Kafka/Vault PVCs.

## High consumer lag

```sh
kubectl -n messaging get deployments,pods
kubectl -n messaging logs deployment/utravs-consumer -c consumer --tail=100
kubectl -n kafka get kafka,kafkanodepool,kafkatopic
kubectl -n vault get pods
```

Inspect `KafkaConsumerLagHigh` and unique-partition lag in Prometheus/Grafana.
Look for processing, Vault, TLS, broker/ISR or offset-commit errors. Restore the
failed dependency first. If capacity is the cause, increase consumer replicas in
`platform/messaging/values.yaml`, commit and push. Extra consumers beyond the
topic's partition count cannot increase parallel partition consumption. Confirm
replicas Ready, sustained processing and falling lag before closing the incident.

## Vault sealed or unavailable

```sh
kubectl -n vault get pods -o wide
kubectl -n vault exec vault-0 -- vault status -tls-skip-verify=false
kubectl -n vault get pvc
```

Check the Vault health probes, TLS trust, node/PVC health and Raft quorum. A sealed
Vault status can return a nonzero exit code. Use the configured HTTPS/CA settings
and three distinct protected unseal shares to unseal a restarted initialized
member. Follow the setup guide's interactive unseal procedure; never put shares
in a command log. **Never initialize an already initialized cluster.** Confirm
all expected members healthy and a signed/verified event processed afterward.

## Kafka broker lost

```sh
kubectl -n kafka get pods -o wide
kubectl -n kafka get kafka utravs-kafka -o yaml
kubectl -n kafka get pvc
kubectl -n messaging logs deployment/utravs-producer -c producer --tail=100
```

Check node/PVC health, Kafka Ready conditions and partition leader/ISR. Restore
the failed node or broker through its normal operator-managed lifecycle. Do not
delete data volumes or lower minimum ISR to force unsafe writes. Wait for broker
readiness and ISR recovery before another disruption; confirm publish success,
consumer progress and lag recovery.

## Application upgrade regresses

Revert the application image-tag commit in Git and push. Observe Argo CD
Synced/Healthy and `kubectl -n messaging rollout status deployment/utravs-consumer`.
Submit a test event and inspect consumer progress. See `optional-features.md` for
the controlled upgrade/rollback procedure and version evidence.
