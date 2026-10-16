# Kubernetes provisioning

`source/` is Kubespray v2.32.0 at the commit recorded in `KUBESPRAY_COMMIT`.
`inventory-utravs/` holds the lab inventory and the original project overrides.
Unspecified settings use defaults from the pinned source. The upstream sample
inventory remains available under `source/inventory/sample/`; it is not merged
into the project inventory.

Run from `source/` to load its Ansible configuration:

```sh
ansible-playbook -i ../inventory-utravs/inventory.ini cluster.yml --syntax-check
ansible-playbook -i ../inventory-utravs/inventory.ini cluster.yml -b -K
```

The second command provisions the hosts. Generated credentials are referenced
through the ignored `inventory-utravs/credentials` link to protected operator
storage outside the checkout. Prepare this link as described in
[the setup guide](../../docs/setup.md). Select this inventory explicitly.
