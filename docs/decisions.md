# Architecture decisions

## Provisioning and API entry point

Kubespray provides versioned Ansible automation for containerd, Kubernetes and
Calico. The pinned upstream source and explicit inventory make the selected
defaults and project overrides reproducible.

HAProxy and Keepalived run on dedicated load-balancer VMs outside Kubernetes.
This separates API ingress administration and service dependencies from the
workload hosts and keeps the entry point available independently of pod
scheduling. HAProxy checks all three API backends; Keepalived moves the VIP
between the two load balancers. Three stacked etcd members provide quorum.
The inventory explicitly enables workload scheduling on the three control-plane
hosts and worker-01.

This separation is also appropriate for production security boundaries:
restrict API traffic between load balancers and control planes to TCP 6443,
restrict VRRP to the two peers, and apply separate administrative access rules.
Network ACLs and segmentation are configured at the infrastructure boundary.

## GitOps and chart provenance

Argo CD reconciles the desired state from Git. Argo CD and Strimzi are bootstrap
Helm releases; child Applications manage platform and application resources.
Chart source, package, environment values and version/checksum metadata are kept
together. The Vault chart is packaged from its official v0.34.1 source tag and
recorded source commit. The installation guide stages CRDs, operators, TLS and
Vault initialization before the root and messaging Applications.

## Kafka and message delivery

Strimzi manages the Kafka cluster, KRaft node pool, topics and TLS users.
Three combined broker/controller replicas, RF=3, minimum ISR=2 and producer
`acks=all` provide quorum-based message persistence. Required pod anti-affinity
spreads Kafka replicas across hosts. TLS client certificates authenticate
producer and consumer on listener 9094.

The delivery model is **at-least-once**. Consumer auto commit and auto offset
store are disabled. The offset advances after processing, or after acknowledged
dead-letter delivery. A restart between processing and offset commit can
redeliver an event. Business handlers should use `event_id` as an idempotency
key. Producer idempotence handles retried sends within its Kafka session.

## Vault, identity and trust

Vault uses three Raft members, HTTPS and Shamir 3-of-5 unseal. Kubernetes Auth
binds the application service accounts and messaging namespace. The application
obtains a one-use AppRole SecretID with a 60-second TTL, then a runtime token
with a 60-second maximum lifetime. Producer and consumer have separate policies
for Transit signing and verification. The Ed25519 signing key is non-exportable.

Istio injects messaging sidecars and enforces namespace STRICT mTLS. Kafka TLS
client authentication and Vault HTTPS provide explicit trust boundaries for
those services. Public CA certificates are versioned as trust inputs; private
keys, unseal shares and administrative credentials remain outside Git.

## Observability and production design

Prometheus collects Kubernetes, Istio, application, Kafka and Vault health
signals. Alertmanager receives consumer-lag, mesh-health and Vault-availability
alerts. OpenTelemetry propagates context through Kafka headers and sends spans
to Jaeger. Node-local PVCs provide the selected storage class.

Production design decisions include isolated administrative access, failure-domain
placement, storage/backup policy, KMS/HSM auto-unseal, immutable image digests,
certificate lifecycle management and retention/capacity planning. These decisions
can be evolved through the same versioned configuration and GitOps workflow.
