
path "auth/approle/role/utravs-consumer-runtime/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/utravs-consumer-runtime/secret-id" {
  capabilities = ["update"]
}
