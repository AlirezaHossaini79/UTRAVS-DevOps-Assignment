# Optional feature verification — 2026-10-16

## Dashboard and SLO

[observability.json](observability.json) records Grafana 13.2.2, its provisioned
eight-panel dashboard, healthy Prometheus datasource and successful queries for
every panel, including the Grafana datasource proxy path. Eighty synthetic events
returned HTTP 201 and all 80 event IDs appeared in successful consumer processing.
The observed latency SLI was 100% against a 99% target, with an observed histogram
p95 of approximately 0.313 seconds. End-state lag was zero; the active consumer
histogram contained 81 observations, including the preceding final-version smoke.

The configured SLO window is rolling 24 hours. These results describe the traffic
and timestamps in this test record, not a claim of a complete day's observations.
Prometheus `increase` extrapolates between scrapes and may return fractional counts.

## Native admission enforcement

[policy-warn.json](policy-warn.json) contains the initial positive/negative
warning-mode checks. [policy-deny.json](policy-deny.json) confirms the final
binding is Deny, type checking has no warnings, the valid request is accepted,
and requests for a false non-root flag, missing limits or privilege escalation
are rejected. Every request uses server dry-run; the live Deployment is unchanged.

## GitOps upgrade and rollback

| Stage | Desired Git commit | Consumer image tag | Health and event |
| --- | --- | --- | --- |
| [Baseline](gitops-baseline.json) | a91a431 | sha-697c83017f3bd044857cbeaf6ee9212699056c2e | 2 Ready, Synced/Healthy, HTTP 201 and matching consumer log |
| [Upgrade](gitops-upgrade.json) | d77f701 | sha-a91a431b36f5c588e79470d4877a9b559671cff2 | 2 Ready, Synced/Healthy, HTTP 201 and matching consumer log |
| [Rollback](gitops-rollback.json) | f1a37a7 | sha-697c83017f3bd044857cbeaf6ee9212699056c2e | 2 Ready, Synced/Healthy, HTTP 201 and matching consumer log |
| [Reapply / final](gitops-final.json) | 343e366 | sha-a91a431b36f5c588e79470d4877a9b559671cff2 | 2 Ready, Synced/Healthy, HTTP 201 and matching consumer log |

The upgrade commit changes image values only. Rollback reverts that commit;
reapply reverts the rollback. Argo CD reconciles each version from Git. No direct
workload image mutation or `kubectl rollout undo` is used. The snapshots include
running image digests, synthetic event IDs, partition/offset and namespace STRICT
mTLS configuration. Producer remains on its previously validated image.

[preflight.json](preflight.json) records syntax, unit, Helm, Prometheus and API
dry-run checks. Credentials and private keys are not included in these records.
