# Architecture

```mermaid
flowchart TB
  Operator[Operator / kubectl] --> VIP[API VIP 172.16.90.135:6443]
  VIP --> LB1[lb-01 HAProxy + Keepalived]
  VIP --> LB2[lb-02 HAProxy + Keepalived]
  LB1 --> CP[cp-01 / cp-02 / cp-03\nAPI servers + stacked etcd]
  LB2 --> CP
  Git[Git repository] --> Argo[Argo CD\nroot + child Applications]
  Argo --> K8s[Kubernetes desired state]
  CP --- K8s
  Argo --> Policy[Native admission policy / messaging Deployments]
  Policy -.-> K8s
  subgraph Workloads[3 shared control-plane workers + worker-01]
    Producer[Producer + Envoy] -->|TLS client certificate / Kafka| Kafka[3 Kafka KRaft broker/controllers\nStrimzi]
    Kafka -->|TLS client certificate / Kafka| Consumer[Consumer + Envoy]
    Producer -->|HTTPS / Kubernetes Auth → AppRole / Transit sign| Vault[3 Vault Raft nodes\nmanual Shamir unseal]
    Consumer -->|HTTPS / short-lived token / Transit verify| Vault
    Mesh[Istiod / namespace STRICT mTLS] -.-> Producer
    Mesh -.-> Consumer
    Producer -->|OTLP / trace context in Kafka headers| Jaeger[Jaeger]
    Consumer -->|OTLP / propagated parent context| Jaeger
    Metrics[Kubernetes / Istio / apps / Kafka JMX] --> Prom[Prometheus]
    Vault -->|TLS health probes| Blackbox[2 Vault blackbox probes]
    Blackbox --> Prom
    Prom --> AM[Alertmanager]
    Prom --> Grafana[Grafana / message-path SLO dashboard]
    Kafka --- Disk[Node-local PVCs / local-path]
    Vault --- Disk
  end
  K8s --- Workloads
```

The VIP moves between two independent load balancers. HAProxy forwards TCP to
three API servers; three etcd members tolerate one member loss. The current lab
also uses the control-plane hosts for application scheduling. VM addresses,
network interface and API endpoint are explicit in the Ansible inventory and
templates.

The producer exposes `POST /events`, signs the event with Vault Transit and
publishes with `acks=all`. Kafka uses three combined KRaft nodes, replication
factor 3 and minimum ISR 2. The consumer verifies the signature and commits an
offset after processing or acknowledged dead-letter publication. OpenTelemetry
context is propagated in Kafka headers so producer and consumer spans share a
trace. See [delivery semantics](decisions.md#kafka-and-message-delivery).

Istio injects sidecars into the messaging namespace; its PeerAuthentication is
STRICT. Kafka additionally requires TLS client certificates at port 9094, and
Vault verifies its HTTPS server certificate. The public CA files in the messaging chart are
trust anchors; their corresponding private keys are kept outside Git.

The application uses a projected service-account JWT for Vault Kubernetes Auth,
then obtains one-use AppRole SecretIDs and 60-second runtime tokens. Separate
producer and consumer Vault policies limit KV and Transit operations. Normal producer/consumer processing calls Transit sign/verify with short-lived
runtime tokens.

Prometheus collects Kubernetes, Istio, application and Kafka exporter metrics.
Vault is monitored using certificate-validated health probes for all three pods;
this collects availability and seal-state signals. Jaeger receives spans over OTLP. Alertmanager receives consumer-lag,
mesh-degradation and Vault-availability alerts. Persistent lab data uses
node-local volumes.

The consumer records producer-to-commit latency as a Prometheus histogram.
Grafana displays the rolling 24-hour 99%-within-5s SLO together with lag and
errors. Dashboard provisioning and the messaging Deployment admission policy
are reconciled by two additional Argo CD Applications. See
[optional controls](optional-features.md) and the [incident runbook](runbook.md).
