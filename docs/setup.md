# Installation guide

Commands are run from a Linux operator host with SSH access to the VMs and
access to the image registries. Set `REPO` to the checkout root. These procedures
describe a fresh installation; they must not be used to reinitialize an existing
Vault cluster or replace an existing certificate authority.

## 1. Prepare the VMs and operator host

The recorded network is:

| Host | Address | Role |
| --- | --- | --- |
| cp-01 | 172.16.90.129 | control plane, etcd, workload scheduling |
| cp-02 | 172.16.90.130 | control plane, etcd, workload scheduling |
| cp-03 | 172.16.90.131 | control plane, etcd, workload scheduling |
| worker-01 | 172.16.90.132 | dedicated worker |
| lb-01 | 172.16.90.133 | HAProxy, Keepalived, priority 150 |
| lb-02 | 172.16.90.134 | HAProxy, Keepalived, priority 100 |
| api.utravs.test | 172.16.90.135 | API virtual IP, TCP 6443 |

The inventory explicitly defines control-plane, etcd and workload roles.
HAProxy and Keepalived use independent hosts outside the Kubernetes cluster.

Use a Kubespray-supported Linux distribution. Configure unique hostnames,
non-overlapping VM/pod/service networks, working DNS, synchronized clocks, SSH
public-key access and sudo before provisioning. Install Python on every host;
the current inventory points to Python 3.13.16 at `/opt/cpython-3.13.16-linux-x86_64-gnu/bin/python3.13`
for Kubernetes hosts and a user-managed Python path for the load balancers.
Either provide those paths or adapt `ansible_python_interpreter` to the prepared
hosts. Adapt the `devops`/`kube` SSH users and `ansible_become_exe` as necessary.
The inventory disables NTP management, so time synchronization is a host
prerequisite. Reserve sufficient CPU, memory and disk for three Kafka and three
Vault replicas, observability and the Argo CD HA components. Hard anti-affinity
requires at least three schedulable nodes.

Permit the Kubernetes and Calico networking required by the pinned Kubespray
source, plus TCP 6443 between the API load balancers and control planes and
IP protocol 112 between the two Keepalived peers. The template uses interface
`ens33` and a `/24` subnet; adapt both the VIP and HAProxy backends if addresses
change. Resolve `api.utravs.test` to the VIP on nodes and the operator host.

Install Python 3.13.16, Helm 3.19.0, kubectl 1.36.4, Git, OpenSSL and curl on the
operator host. Install jq for the client Secret transfer below. Vault commands
for initialization/unseal run inside the Vault pods, so the operator host does
not need a local Vault CLI for the core setup.
The chart sources are vendored; container images and Python packages still
require registry/mirror access. `k8s-mirror.liara.ir` is configured for Kubernetes
images; select an accessible trusted mirror when reproducing elsewhere.

```sh
export REPO="$PWD"
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r cluster/kubespray/source/requirements.txt
# Match the ansible-core version observed with the pinned source.
python -m pip install ansible-core==2.19.14
ansible --version
export UTRAVS_PRIVATE_DIR="$HOME/.local/share/utravs"
umask 077
mkdir -p "$UTRAVS_PRIVATE_DIR/kubespray-credentials" "$UTRAVS_PRIVATE_DIR/kube"
# On a fresh checkout only; preserve an existing credentials link/directory.
test -e cluster/kubespray/inventory-utravs/credentials || \
  ln -s "$UTRAVS_PRIVATE_DIR/kubespray-credentials" cluster/kubespray/inventory-utravs/credentials
```

Keep all private inputs and generated files in the protected directory. Back up
the Vault unseal shares independently; do not place them in the repository.

## 2. Provision the API load balancers and Kubernetes

```sh
ansible -i cluster/loadbalancers/inventory.ini loadbalancers -m ping
ansible-playbook -i cluster/loadbalancers/inventory.ini cluster/loadbalancers/haproxy.yml -b -K
ansible-playbook -i cluster/loadbalancers/inventory.ini cluster/loadbalancers/keepalived.yml -b -K
cd "$REPO/cluster/kubespray/source"
ansible-inventory -i ../inventory-utravs/inventory.ini --graph
ansible-playbook -i ../inventory-utravs/inventory.ini cluster.yml --syntax-check
ansible-playbook -i ../inventory-utravs/inventory.ini cluster.yml -b -K \
  -e kube_version=1.36.4 -e kubeconfig_localhost=true \
  -e "artifacts_dir=$UTRAVS_PRIVATE_DIR/kube"
cd "$REPO"
```

Kubespray runs with its own `ansible.cfg`. The project inventory consists of the
three override files; remaining settings come from this pinned source. Keep the
same credentials directory when rerunning against an existing cluster. The
playbook installs containerd, Kubernetes and Calico. Never use `reset.yml` as a
validation command.

The `kubeconfig_localhost` option above generates an administrator kubeconfig
on the operator host in the external artifacts directory, with mode `0600`.

```sh
chmod 600 "$UTRAVS_PRIVATE_DIR/kube/admin.conf"
export KUBECONFIG="$UTRAVS_PRIVATE_DIR/kube/admin.conf"
kubectl config set-cluster cluster.local --server=https://api.utravs.test:6443
kubectl get nodes -o wide
kubectl get --raw=/readyz
```

The Ansible `-K` prompt supplies the sudo password without storing it in Git.
Use the actual cluster name shown by `kubectl config get-clusters` if it differs.

## 3. Install bootstrap components and prepare Git access

```sh
kubectl apply -f platform/storage/manifests/local-path-storage.yaml
helm upgrade --install argocd platform/argocd/chart -n argocd --create-namespace \
  -f platform/argocd/values.yaml --wait --timeout 15m
kubectl create namespace kafka --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install strimzi-kafka-operator platform/strimzi/chart -n strimzi --create-namespace \
  -f platform/strimzi/values.yaml --wait --timeout 15m
kubectl create namespace vault --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace istio-system --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/gitops/argocd/applications/messaging-namespace.yaml
```

Argo CD needs read access to the repository branch containing these files.
For a private SSH repository, create its repository Secret using a read-only
deploy key stored outside the checkout:

```sh
kubectl -n argocd create secret generic utravs-repository \
  --from-literal=type=git \
  --from-literal=url=git@github.com:AlirezaHossaini79/UTRAVS-DevOps-Assignment.git \
  --from-file=sshPrivateKey="$UTRAVS_PRIVATE_DIR/git/deploy-key" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n argocd label secret utravs-repository argocd.argoproj.io/secret-type=repository --overwrite
```

Register the matching public deploy key in the Git repository and verify the
Git host key in Argo CD's SSH known-hosts configuration. For a different remote
or branch, update all Application `repoURL`/`targetRevision` fields consistently.
The referenced files must be committed to that remote before Argo CD can read
them; applying an Application does not upload local changes.

## 4. Generate Vault TLS inputs outside Git

For a fresh lab, create a CA and server key with mode `0600`. Stop if either
already exists. Existing clusters keep their current CA and initialization
material. Example for the supplied service names:

```sh
mkdir -p "$UTRAVS_PRIVATE_DIR/vault-pki" "$UTRAVS_PRIVATE_DIR/vault-bootstrap"
PKI="$UTRAVS_PRIVATE_DIR/vault-pki"
test ! -e "$PKI/ca.key" && test ! -e "$PKI/tls.key" || exit 1
openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 365 \
  -keyout "$PKI/ca.key" -out "$PKI/ca.crt" -subj '/CN=UTRAVS Vault Lab CA' \
  -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign'
openssl req -new -newkey rsa:3072 -nodes -keyout "$PKI/tls.key" \
  -out "$PKI/vault.csr" -subj '/CN=vault.vault.svc.cluster.local'
cat > "$PKI/server.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:vault,DNS:vault.vault.svc,DNS:vault.vault.svc.cluster.local,DNS:vault-active.vault.svc.cluster.local,DNS:vault-internal.vault.svc.cluster.local,DNS:*.vault-internal.vault.svc.cluster.local,IP:127.0.0.1
EOF
openssl x509 -req -in "$PKI/vault.csr" -CA "$PKI/ca.crt" -CAkey "$PKI/ca.key" \
  -CAcreateserial -out "$PKI/tls.crt" -days 365 -sha256 -extfile "$PKI/server.ext"
kubectl -n vault create secret generic vault-ha-tls \
  --from-file=ca.crt="$PKI/ca.crt" --from-file=tls.crt="$PKI/tls.crt" --from-file=tls.key="$PKI/tls.key" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Only the public CA goes into `platform/messaging/chart/files/vault/ca.crt` and
the `vault-ca.crt` field of `platform/vault-blackbox/manifests/configmap.yaml`.
Do not copy either private key into Git. Section 7 updates these public inputs
and repackages the local messaging chart before application deployment.

## 5. Bootstrap Argo CD applications in dependency order

Apply the following child definitions in
stages and wait for each prerequisite before continuing:

```sh
kubectl apply -f infra/gitops/argocd/applications/istio-base.yaml
kubectl -n argocd wait application/istio-base --for=jsonpath='{.status.sync.status}'=Synced --timeout=10m
kubectl wait crd/peerauthentications.security.istio.io --for=condition=Established --timeout=3m
kubectl apply -f infra/gitops/argocd/applications/istiod.yaml
kubectl -n argocd wait application/istiod --for=jsonpath='{.status.sync.status}'=Synced --timeout=10m
kubectl -n istio-system rollout status deployment/istiod --timeout=10m
kubectl apply -f infra/gitops/argocd/applications/monitoring.yaml
kubectl apply -f infra/gitops/argocd/applications/metrics-server.yaml
kubectl apply -f infra/gitops/argocd/applications/jaeger.yaml
kubectl -n argocd wait application/monitoring --for=jsonpath='{.status.sync.status}'=Synced --timeout=15m
kubectl wait crd/podmonitors.monitoring.coreos.com crd/prometheusrules.monitoring.coreos.com \
  --for=condition=Established --timeout=3m
kubectl apply -f infra/gitops/argocd/applications/kafka.yaml
kubectl apply -f infra/gitops/argocd/applications/vault.yaml
kubectl -n argocd wait application/kafka application/vault --for=jsonpath='{.status.sync.status}'=Synced --timeout=15m
kubectl -n argocd get applications
kubectl -n kafka wait kafka/utravs-kafka --for=condition=Ready --timeout=15m
```

Argo CD performs the actual chart/manifest deployment. Vault remains unready
until initialized and unsealed. Monitor pod events, PVC binding and Argo CD
conditions if a stage does not converge. Monitoring must exist before the Kafka
PodMonitor and Vault blackbox PrometheusRule are applied.

## 6. Initialize Vault once, unseal and configure authentication

Check `vault status` on `vault-0` first; an exit status of 2 means sealed, not
uninitialized. Initialize **only when `initialized` is false**. A lost init
file is not a reason to initialize a cluster again.

```sh
kubectl -n vault exec vault-0 -- vault status -format=json
# Fresh cluster only. Keep stdout private and do not overwrite a previous file.
test ! -e "$UTRAVS_PRIVATE_DIR/vault-bootstrap/vault-init.json" || exit 1
kubectl -n vault exec vault-0 -- vault operator init -key-shares=5 -key-threshold=3 -format=json \
  > "$UTRAVS_PRIVATE_DIR/vault-bootstrap/vault-init.json"
chmod 600 "$UTRAVS_PRIVATE_DIR/vault-bootstrap/vault-init.json"
# Run three times per pod, entering a different share at each hidden prompt:
kubectl -n vault exec -it vault-0 -- vault operator unseal
kubectl -n vault exec -it vault-1 -- vault operator unseal
kubectl -n vault exec -it vault-2 -- vault operator unseal
```

Unseal `vault-0` first. Its initialized Raft cluster is discovered through
`retry_join`; allow followers to join before entering their shares. If joining
does not occur, inspect TLS/DNS and retry-join logs before changing state.
Check all three pods are unsealed and one is active.

```sh
python platform/vault/bootstrap/configure-kubernetes-auth.py
python platform/vault/bootstrap/configure-runtime-approle.py
kubectl -n vault get pods -L vault-active,vault-sealed
```

These scripts select the current active pod, verify TLS using the private
directory's public CA and use the protected initialization token only for
bootstrap. They configure Kubernetes Auth, AppRole, policies, KV v2 and the
non-exportable Ed25519 Transit key. Never print the token or put it in values.

Normal event processing uses Transit sign/verify and short-lived AppRole
credentials. The bootstrap scripts prepare the authentication roles, policies
and Transit key used by that path. After administrative setup, use a dedicated
bootstrap identity, split unseal custody and revoke the initialization root
token according to the operator access procedure.

## 7. Prepare application trust, client certificates and images

Strimzi generates the Kafka CA and client credentials. Copy only the public CA
into the chart. Transfer each KafkaUser client certificate/key directly into
its destination Kubernetes Secret; do not save the decoded key in the checkout.

```sh
kubectl -n kafka get secret utravs-kafka-cluster-ca-cert -o jsonpath='{.data.ca\.crt}' | \
  base64 -d > platform/messaging/chart/files/kafka/ca.crt
cp "$UTRAVS_PRIVATE_DIR/vault-pki/ca.crt" platform/messaging/chart/files/vault/ca.crt
for app in producer consumer; do
  kubectl -n kafka get secret "utravs-$app" -o json | \
    jq --arg name "utravs-$app-kafka-client" \
    '{apiVersion:"v1",kind:"Secret",metadata:{name:$name,namespace:"messaging"},type:"Opaque",data:{"user.crt":.data["user.crt"],"user.key":.data["user.key"]}}' | \
    kubectl apply -f -
done
```

Open `platform/vault-blackbox/manifests/configmap.yaml`. Replace only the
`data.vault-ca.crt` certificate block with the contents of
`$UTRAVS_PRIVATE_DIR/vault-pki/ca.crt`, preserving YAML indentation and the
blackbox module configuration. This certificate is public; do not paste
`ca.key` or `tls.key`. Check each KafkaUser Secret exists with both required
keys before the transfer; do not continue after an error.

The client Secret copy is bootstrap/credential lifecycle work. Schedule renewal
and recopy when Strimzi rotates client certificates.

CI in `.github/workflows/build-images.yml` builds the producer/consumer and
publishes `ghcr.io/alirezahossaini79/utravs-{producer,consumer}:sha-<commit>`.
Use successful image tags in `platform/messaging/values.yaml`; change repository
names and CI destinations for a fork. The checked-in image tags reproduce the
recorded lab. After the CI build, commit the selected image tags to Helm values. If images are private, create `messaging/ghcr-pull` from a
protected Docker config file, never a literal password in Git:

```sh
kubectl -n messaging create secret generic ghcr-pull --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="$UTRAVS_PRIVATE_DIR/registry/config.json" \
  --dry-run=client -o yaml | kubectl apply -f -
```

`platform/messaging/values-prod.yaml` selects three replicas for the production
environment profile. Set its image tags and resources for the target environment.

After changing public CA files, repackage the local messaging chart and update
its package SHA-256 in `platform/messaging/VERSION.yaml`:

```sh
helm package platform/messaging/chart --destination platform/messaging/packages
sha256sum platform/messaging/packages/utravs-messaging-0.1.0.tgz
```

Set `package_sha256` in `platform/messaging/VERSION.yaml` to the printed hash.
When intentionally changing the chart version, also update `chart/Chart.yaml`
and the VERSION `version`/`package` fields to match the new package filename.

Commit the updated public trust inputs, package, version metadata and image tags
to the configured Git remote before the final application stage.

## 8. Deploy the application and root Application

```sh
kubectl apply -f infra/gitops/argocd/applications/vault-blackbox.yaml
kubectl apply -f infra/gitops/argocd/applications/messaging.yaml
kubectl -n messaging rollout status deployment/utravs-producer --timeout=10m
kubectl -n messaging rollout status deployment/utravs-consumer --timeout=10m
kubectl apply -f infra/gitops/argocd/bootstrap/root.yaml
kubectl -n argocd get applications
```

All ten Applications, including the root, should converge to Synced/Healthy.
Producer and consumer pods should have the application and Istio sidecar ready.
Continue with [verification](verification.md). Normal configuration and image
changes are Git commits reconciled by Argo CD. Ansible host reruns and the two
bootstrap Helm releases remain operator workflows.

## 9. Rebuild and recovery notes

Chart `.tgz` files can be installed with the adjacent environment values instead
of chart directories. Dependencies are already bundled. The packages do not
contain VM disks, container images, Kafka records, Vault Raft data or private
runtime inputs. Rebuilding configuration is different from restoring data.

Retain secure Vault Raft snapshots, its TLS key material and unseal shares,
Kubernetes/etcd backups, and the intended Kafka retention/backup strategy outside
Git. Local-path PVCs are node-bound and are not replicated storage. A fresh CA
or Vault initialization requires the explicit trust/secret bootstrap described
above; do not reuse old public CA files with newly generated private keys.
