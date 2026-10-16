# Technical evidence

Files below are selected outputs from the recorded lab. They contain no
private keys, initialization tokens or decoded Kubernetes Secret data.

| Requirement / observation | Evidence |
| --- | --- |
| Kubernetes API availability during VIP failover | [vip-failover-rto.log](vip-failover-rto.log) |
| Nodes/pods before and after Ansible rerun | [nodes-before-rerun.txt](nodes-before-rerun.txt), [nodes-after-rerun.txt](nodes-after-rerun.txt), [pods-before-rerun.txt](pods-before-rerun.txt), [pods-after-rerun.txt](pods-after-rerun.txt) |
| Argo CD self-heal / sync history | [argocd-self-heal.txt](argocd-self-heal.txt), [argocd-sync-history.txt](argocd-sync-history.txt) |
| Kafka leader and ISR before/during/after failure | [before](kafka-topic-before-failure.txt), [during](kafka-topic-during-failure.txt), [after](kafka-topic-after-recovery.txt) |
| Kafka traffic around failure | [producer](kafka-producer-during-failure.txt), [consumer](kafka-consumer-during-failure.txt), [baseline messages](kafka-messages-before-failure.txt) |
| Vault active-pod eviction, traffic and recovery | [Vault test directory](reliability/vault-failover-20261015T091552Z/) |
| AppRole credential renewal beyond 60-second TTL | [vault-approle-rotation.log](vault-approle-rotation.log) |
| Monitoring / Alertmanager / metrics-server checks | [monitoring-base-success.log](monitoring-base-success.log), [monitoring-alertmanager-smoke.log](monitoring-alertmanager-smoke.log), [metrics-server-success.log](metrics-server-success.log) |
| Producer-to-consumer trace parentage | [jaeger-end-to-end.json](tracing/jaeger-end-to-end.json) |
| Chart/package equivalence, syntax, paths and read-only cluster state | [submission-checks-20261016.json](submission-checks-20261016.json) |
| Fresh Git export and migration resource equivalence | [rebuild-review-20261016.json](rebuild-review-20261016.json) |

The trace was exported read-only from Jaeger on 2026-10-16. Trace ID
`b05f49b3b8a7b2e61e356817edeb1c11` contains producer span
`78a58749695fd616` and consumer span `214033d23c6b0a92`, whose parent is the
producer span. Kafka partition 2, offset 14 and technical timing are retained.
Span events, request headers and resource attributes other than service name
are omitted. The retained Unix nanosecond timestamps are original observations.

See [the reliability report](../docs/reliability.md) for results and measurement
interpretation, and [the TLS authentication checks](security/kafka-tls-auth-20261013.txt)
for certificate rejection/acceptance results.

The initial c5c4901 organization checks on 2026-10-16 passed for nine chart packages (206 rendered
resources), the alternative messaging values, Ansible syntax/inventory, the
disabled failover guard and trace parentage. Four nodes were Ready and all ten
live Argo CD Applications were Synced/Healthy.

The rebuild review additionally exported the staged Git tree to a clean
directory without operator files, rendered all nine charts and their packages,
checked syntax and paths, and tested SSH/Python access to the four Kubernetes
hosts and two load balancers. Each of the nine child Applications rendered the
same resources as its previous configuration.

## Optional feature verification

See [optional feature evidence](optional/README.md) for the provisioned SLO
dashboard, 80 successful synthetic events, native policy acceptance/rejection
and the GitOps image upgrade, rollback and reapply. Two added child Applications
manage the dashboard and policy; the platform now has 12 Applications.
