# NOTE: OpenBao logs "the file physical backend is deprecated; use bao
# operator migrate ... by v2.7.0" (confirmed live against openbao/openbao
# :latest — currently v2.6.1, so this still works). Migrate to "raft"
# storage before that version lands, since :latest is a floating tag.
storage "file" {
  path = "/openbao/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

# Internal-only listener (never reaches the host or public internet — same
# trust boundary as postgres/redis in this stack), so plain HTTP is an
# accepted tradeoff here rather than managing internal TLS certs.
api_addr = "http://openbao:8200"

# Long-lived on purpose: the fixed application token bootstrap.sh creates
# is meant to last indefinitely, and an explicit large cap here stops
# OpenBao's default (much shorter) system max TTL from silently capping it.
max_lease_ttl      = "87600h"
default_lease_ttl  = "87600h"

ui = false
