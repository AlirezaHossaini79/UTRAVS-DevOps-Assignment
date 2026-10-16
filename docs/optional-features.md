# Optional assignment features

## Message-path SLI and SLO

The latency SLO is **at least 99% of timestamp-valid, successfully processed
message attempts complete within 5 seconds, over a rolling 24-hour window**.
The producer sets an aware UTC timestamp before Vault signing. The consumer
records `utravs_message_end_to_end_seconds` only after signature verification,
business processing and synchronous Kafka offset commit succeed. The histogram
includes a 5-second bucket. No event IDs or booking IDs become metric labels.

`utravs:message_latency_sli:ratio24h` divides the increase of that bucket by the
increase of the histogram count. `utravs:message_latency_slo:target` is 0.99.
With no measured traffic the SLI is absent/No data, never an invented 100%.
Invalid, missing, naive or future timestamps increment
`utravs_consumer_latency_timestamp_errors_total` without changing message
processing or offset behavior. Keep producer and consumer clocks synchronized.

This latency SLI measures successful attempts; it is not a delivery-completeness
ratio. At-least-once redelivery can create another observation. Producer publish
success, consumer errors, DLQ and unique-partition lag are displayed alongside it.

The `UTRAVS Message Path SLO` Grafana dashboard is provisioned from
`platform/monitoring/dashboards/message-slo.yaml`. Its data source is the existing
Prometheus. Recording rules and Grafana settings are in
`platform/monitoring/values.yaml`. Both are reconciled through Argo CD.

Create the external Grafana admin Secret as described in `setup.md`, then:

```sh
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

Open `http://127.0.0.1:3000/d/utravs-message-slo` and log in using the operator's
private credentials. No fixed password is stored in Git. The dashboard is also
available under the UTRAVS folder. Submit events using the verification guide,
wait for at least two 30-second scrapes, and compare the observed SLI with 99%.
The configured window is 24 hours; the displayed sample count shows how much
traffic actually supports the current value.

When using the jump server, first open an SSH tunnel from your laptop:

```sh
ssh -L 3000:127.0.0.1:3000 interview@192.168.149.20
```

Run the Kubernetes port-forward above in that SSH session and keep it open.
The URL then opens on your laptop. For this installation the username is
`utravs-admin`; retrieve the password from the operator's private
`~/.local/share/utravs/grafana/admin-password` file on the jump server.

Grafana requests 250m CPU and 512Mi memory, with limits of 1 CPU and 1Gi.
The earlier 500m/384Mi limits allowed API smoke tests but saturated during
interactive login, causing internal API timeouts and a failing readiness probe.
Verify both `/api/health` and an authenticated dashboard page after changes;
an API-only dashboard check does not verify the interactive login path.

## Policy as Code

The native Kubernetes `ValidatingAdmissionPolicy` and binding are in
`platform/policy/manifests/messaging-policy.yaml`. Argo CD's `messaging-policy`
Application manages them. The policy applies to CREATE/UPDATE of Deployments
in namespace `messaging`, including producer and consumer. It requires:

- Pod `runAsNonRoot: true`.
- Application containers with `allowPrivilegeEscalation: false`.
- CPU and memory requests and limits on every declared application container.

The final binding uses Deny. During rollout it is first observed with Warn/Audit,
then switched to Deny through Git after positive and negative dry-runs. The scope
is Deployment admission, not every Pod, Job or StatefulSet in the cluster.
Istio-injected containers are added later during Pod admission. No separate
policy engine or Istio CNI change is needed for these application-template checks.

```sh
kubectl get validatingadmissionpolicy utravs-messaging-deployments -o yaml
kubectl get validatingadmissionpolicybinding utravs-messaging-deployments -o yaml
# Accepted: the existing non-root setting.
kubectl -n messaging patch deployment utravs-consumer --type=json --dry-run=server \
  -p='[{"op":"replace","path":"/spec/template/spec/securityContext/runAsNonRoot","value":true}]'
# Rejected: a conflicting pod security setting.
kubectl -n messaging patch deployment utravs-consumer --type=json --dry-run=server \
  -p='[{"op":"replace","path":"/spec/template/spec/securityContext/runAsNonRoot","value":false}]'
# Rejected: missing resource limits.
kubectl -n messaging patch deployment utravs-consumer --type=json --dry-run=server \
  -p='[{"op":"remove","path":"/spec/template/spec/containers/0/resources/limits"}]'
# Rejected: privilege escalation.
kubectl -n messaging patch deployment utravs-consumer --type=json --dry-run=server \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/securityContext/allowPrivilegeEscalation","value":true}]'
```

The three negative commands must exit nonzero with the policy's denial message.
All are server-side dry-runs: the live Deployment is not changed.

## Controlled GitOps application upgrade and rollback

Use two known-good, commit-tagged application images. Before the change, record
the running tag, Deployment readiness and messaging Application revision.

1. Build and publish the new image through the existing GitHub Actions workflow.
2. Set the relevant image tag in `platform/messaging/values.yaml`; commit and push.
3. Wait for Argo CD Synced/Healthy, rollout completion and an HTTP 201 event with
   matching consumer progress. Record image IDs and Git revision.
4. `git revert <image-tag-change-commit>` and push; wait for the previous image
   and repeat the checks. This is a new Git commit, not a force push/reset.
5. Revert that revert when the intended final state is the newer image, then
   repeat readiness and event checks.

Do not use `kubectl set image` or `kubectl rollout undo` to perform this demo.
Read-only `kubectl rollout status` is a verification command. Self-Heal demonstrates
drift correction; this demo additionally demonstrates a version change and return.
Kafka/Vault data upgrades have their own compatibility requirements and are not
part of this application-image demonstration.

The short incident procedures are in `runbook.md`. Sanitized live results are
stored under `evidence/optional/`.

## Observed verification

The [verification records](../evidence/optional/README.md) include 80 accepted and
processed synthetic events, all eight dashboard queries, zero final lag, native
policy denials and a validated A-to-B-to-A-to-B Consumer image sequence.
