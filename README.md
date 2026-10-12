# UTRAVS DevOps Assignment

A Kubernetes-based DevOps infrastructure project featuring
high availability, GitOps, messaging, security, and observability.

## Project Structure

- `provisioning/kubespray/` - Kubernetes inventory, configuration, and pinned Kubespray commit
- `loadbalancers/` - HAProxy and Keepalived Ansible playbooks
- `infra/storage/` - Kubernetes storage provisioning
- `infra/operators/` - Kubernetes operator configurations
- `infra/messaging/kafka/` - Kafka cluster, node pool, and topic manifests
- `infra/gitops/argocd/` - Argo CD Helm values and GitOps applications
- `apps/` - Application deployment manifests
- `docs/` - Architecture and technical documentation
- `evidence/` - Local test evidence (excluded from Git until reviewed)

## Implemented Components

- Kubernetes v1.36.4 provisioned using Kubespray v2.32.0
- HAProxy and Keepalived for Kubernetes API high availability
- Calico CNI and containerd
- Rancher Local Path Provisioner
- Strimzi Operator v1.2.0
- Apache Kafka v4.3.1 with three KRaft broker/controller nodes
- Argo CD v3.5.4 with Redis HA

## High Availability Validation

- Kubernetes API VIP failover tested
- Kubespray playbook rerun tested
- Kafka broker failure and partition leader election tested
- Kafka producer and consumer verified during broker failure
- Kafka replication recovered successfully

## Configuration Management

Kubespray is pinned to the commit stored in:

`provisioning/kubespray/KUBESPRAY_COMMIT`

Only project-specific Kubespray inventory and configuration
overrides are tracked. Upstream Kubespray and third-party Helm
charts are excluded from the repository.

## Status

Work in progress. GitOps integration, service mesh, secrets
management, observability, and final reliability documentation
are being implemented.
