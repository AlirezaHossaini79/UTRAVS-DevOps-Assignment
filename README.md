# UTRAVS Senior DevOps Assignment

An event platform on Kubernetes with an HA API endpoint, GitOps delivery,
three Kafka brokers, Vault HA, Istio, Prometheus/Alertmanager and Jaeger.

## Deliverables

| Deliverable | Location |
| --- | --- |
| Installation from prepared VMs to application deployment | [Setup guide](docs/setup.md) |
| Topology, traffic and trust boundaries | [Architecture](docs/architecture.md) |
| Design choices, delivery semantics and production differences | [Decisions and trade-offs](docs/decisions.md) |
| Failure scenarios, observations and measured recovery | [Reliability report](docs/reliability.md) |
| Technical evidence and validation procedures | [Evidence index](evidence/README.md), [verification guide](docs/verification.md) |

## Repository

```text
cluster/
  kubespray/source/             # pinned upstream source, including sample inventory
  kubespray/inventory-utravs/   # lab inventory and explicit configuration overrides
  loadbalancers/               # HAProxy and Keepalived Ansible playbooks
platform/<service>/
  chart/                       # complete Helm chart source, with dependencies
  packages/                    # versioned chart package (.tgz)
  values.yaml                  # environment overrides
  VERSION.yaml                 # version, source and package SHA-256
platform/kafka/manifests/      # Strimzi resources
platform/storage/manifests/    # local-path provisioner
platform/vault-blackbox/       # Vault availability probes and alert
infra/gitops/argocd/           # root and child Applications
apps/producer/, apps/consumer/ # application source and container build definitions
scripts/reliability/           # explicitly enabled failure test
evidence/                    # selected historical test outputs
docs/                        # technical delivery documentation
```

## Version baseline

| Component | Version |
| --- | --- |
| Kubernetes / kubectl | 1.36.4 |
| Kubespray | 2.32.0; commit in `cluster/kubespray/KUBESPRAY_COMMIT` |
| Controller Python / Helm | 3.13.16 / 3.19.0 |
| Ansible | 12.3.0 distribution; observed ansible-core 2.19.14 |
| Argo CD chart / application | 10.10.2 / 3.5.4 |
| Strimzi chart / Kafka | 1.2.0 / 4.3.1 |
| Istio base and istiod charts | 1.31.1 |
| Vault chart / application | 0.34.1 / 2.0.4 |
| kube-prometheus-stack chart | 91.5.0 |
| metrics-server chart / image | 3.14.0 / 0.9.0 |
| Jaeger chart / image | 4.16.0 / 2.22.0 |
| Messaging chart | 0.1.0; image tags in environment values |

Argo CD and the Strimzi operator are bootstrap Helm releases. The child Argo CD
Applications manage the remaining platform and application resources. All nine
chart sources and exact packages are included. A `.tgz` is a compressed Helm
chart containing templates, default values, metadata and bundled dependencies;
the environment overrides are kept alongside it in `values.yaml`.

Credentials, private keys, Vault initialization output and kubeconfig belong in
protected operator storage outside Git. Public CA certificates and Kubernetes
Secret references are included so TLS trust and mounts can be reproduced.
Fresh installations generate their own certificates and runtime secrets.

## Architecture baseline

The inventory schedules workloads on cp-01, cp-02, cp-03 and worker-01.
HAProxy and Keepalived run on dedicated lb-01 and lb-02 hosts, keeping the API
entry point independent of Kubernetes workload scheduling. The setup guide
describes the dependency order and the environment-specific inputs.
