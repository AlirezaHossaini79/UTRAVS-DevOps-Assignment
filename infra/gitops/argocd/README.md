# Argo CD applications

`bootstrap/root.yaml` defines `platform-root`, whose directory source is
`infra/gitops/argocd/applications` on `main`. Child Applications refer to vendored
charts under `platform/` and load environment overrides using `../values.yaml`.
`messaging-namespace.yaml` enables Istio injection before application creation.

Bootstrap Argo CD with `platform/argocd/chart` and its adjacent values. Configure
Git access using an Argo CD repository Secret created from a protected deploy
key outside Git. Change `repoURL` and `targetRevision` consistently for a fork.

Complete the prerequisite stages in
[the setup guide](../../../docs/setup.md), then apply the root Application.
After bootstrap, commit desired-state changes for Argo CD to reconcile.
