#!/usr/bin/env bash
# Disposable offline PKI test: never contacts AWS or uses existing keys.
set -euo pipefail
umask 077
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cert_config="$repo_root/config/environments/aws/staging/homelab-recovery/openssl.cnf"
cert_test_dir=$(mktemp -d "${TMPDIR:-/tmp}/homelab-backup-cert-test.XXXXXXXX")
trap 'rm -rf "$cert_test_dir"' EXIT
cd "$cert_test_dir"
# Random disposable passphrase, passed by file; never printed or committed.
openssl rand -hex 32 > passphrase
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -aes-256-cbc \
  -pass file:passphrase -out ca.key 2>/dev/null
openssl req -new -x509 -sha256 -days 3650 -key ca.key -passin file:passphrase \
  -out ca.crt -subj '/CN=homelab-backup-ca' -config "$cert_config" -extensions ca_extensions
openssl x509 -in ca.crt -noout -checkend 7776000 >/dev/null
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out client.key 2>/dev/null
# A malicious CSR asks to be a CA. The issuer must ignore that extension.
openssl req -new -sha256 -key client.key -subj '/CN=homelab-backup-uploader-01' \
  -addext 'basicConstraints=critical,CA:TRUE' -out client.csr
openssl req -in client.csr -noout -verify 2>/dev/null
openssl x509 -req -sha256 -days 90 -in client.csr -CA ca.crt -CAkey ca.key \
  -passin file:passphrase -set_serial "0x$(openssl rand -hex 16)" \
  -extfile "$cert_config" -extensions client_extensions -out client.crt 2>/dev/null
openssl verify -purpose sslclient -CAfile ca.crt client.crt >/dev/null
openssl x509 -in client.crt -noout -subject -nameopt RFC2253 | grep -qx 'subject=CN=homelab-backup-uploader-01'
openssl x509 -in client.crt -noout -ext basicConstraints | grep -q 'CA:FALSE'
openssl x509 -in ca.crt -noout -ext basicConstraints | grep -q 'CA:TRUE, pathlen:0'
openssl x509 -in client.crt -noout -ext keyUsage | grep -q 'Digital Signature'
openssl x509 -in client.crt -noout -checkend 2592000 >/dev/null
if openssl x509 -in client.crt -noout -checkend 7862400 >/dev/null; then
  echo 'FAIL: leaf must expire within 91 days' >&2; exit 1
fi
openssl x509 -in client.crt -pubkey -noout > cert.pub
openssl pkey -in client.key -pubout > key.pub
cmp cert.pub key.pub
openssl req -new -x509 -newkey rsa:2048 -noenc -sha256 -days 1 \
  -subj '/CN=unrelated-ca' -keyout unrelated.key -out unrelated.crt \
  -config "$cert_config" -extensions ca_extensions 2>/dev/null
if openssl verify -CAfile unrelated.crt client.crt >/dev/null 2>&1; then
  echo 'FAIL: unrelated CA accepted' >&2; exit 1
fi
if openssl pkey -in ca.key -passin pass:incorrect -noout >/dev/null 2>&1; then
  echo 'FAIL: encrypted CA opened with wrong passphrase' >&2; exit 1
fi
echo 'PASS: encrypted CA, direct chain, exact CN, client-only extensions, key match, expiry and wrong-CA rejection'
