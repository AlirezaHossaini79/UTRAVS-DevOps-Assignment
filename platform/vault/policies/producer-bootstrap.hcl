
path "auth/approle/role/utravs-producer-runtime/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/utravs-producer-runtime/secret-id" {
  capabilities = ["update"]
}
