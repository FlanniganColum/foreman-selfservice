# TLS / HTTPS configuration

The portal terminates HTTPS in the Nginx container and listens on ports 80 and 443. HTTP is redirected to HTTPS.

## Automatic development certificate

If `secrets/tls/fullchain.pem` or `secrets/tls/privkey.pem` is missing when the Nginx container starts, its entrypoint automatically creates a 3072-bit RSA self-signed certificate valid for 365 days.

The certificate uses `PORTAL_HOSTNAME` from `.env` as its primary DNS Subject Alternative Name and also contains `localhost` and `127.0.0.1`. Because `./secrets/tls` is bind-mounted into the Nginx container, the generated files persist on the Docker host.

This fallback is intended for development/test only. Browsers will warn until the self-signed certificate is explicitly trusted.

If you change `PORTAL_HOSTNAME` after a self-signed certificate has already been generated, remove the old `secrets/tls/fullchain.pem` and `secrets/tls/privkey.pem` while the stack is stopped, then start Nginx again so a certificate containing the new hostname is generated.

## Install an organisation/public CA certificate

Nginx expects these exact PEM files:

- `secrets/tls/fullchain.pem` — leaf/server certificate followed by any intermediate CA certificates.
- `secrets/tls/privkey.pem` — matching unencrypted PEM private key.

Example:

```bash
mkdir -p secrets/tls
cp /secure/path/portal-fullchain.pem secrets/tls/fullchain.pem
cp /secure/path/portal-private-key.pem secrets/tls/privkey.pem
chmod 644 secrets/tls/fullchain.pem
chmod 600 secrets/tls/privkey.pem
```

If the CA provides a leaf certificate and intermediate chain separately, build the full chain with the leaf first:

```bash
cat portal.crt intermediate-ca.crt > secrets/tls/fullchain.pem
```

Validate the certificate and key before restarting:

```bash
openssl x509 -in secrets/tls/fullchain.pem -noout -subject -issuer -dates -ext subjectAltName
openssl x509 -in secrets/tls/fullchain.pem -pubkey -noout | openssl sha256
openssl pkey -in secrets/tls/privkey.pem -pubout | openssl sha256
```

The final two hashes must match.

Then restart Nginx:

```bash
docker compose up -d nginx
# or, if already running:
docker compose restart nginx
```

Check what Nginx is serving:

```bash
openssl s_client -connect "${PORTAL_HOSTNAME}:443" -servername "${PORTAL_HOSTNAME}" -showcerts </dev/null
```

## PKCS#12 / PFX certificates

If your certificate is supplied as `.pfx`/`.p12`, extract the key and certificates into PEM format. Keep the source PFX protected and remove temporary unencrypted key material after installation.

```bash
openssl pkcs12 -in portal.pfx -nocerts -nodes -out secrets/tls/privkey.pem
openssl pkcs12 -in portal.pfx -clcerts -nokeys -out /tmp/portal-leaf.pem
openssl pkcs12 -in portal.pfx -cacerts -nokeys -chain -out /tmp/portal-chain.pem
cat /tmp/portal-leaf.pem /tmp/portal-chain.pem > secrets/tls/fullchain.pem
chmod 600 secrets/tls/privkey.pem
chmod 644 secrets/tls/fullchain.pem
rm -f /tmp/portal-leaf.pem /tmp/portal-chain.pem
```

## Trusting the generated self-signed certificate (development/test only)

Copy `secrets/tls/fullchain.pem` to the client machine and add it to that machine's trusted root store.

### Debian / Ubuntu

```bash
sudo cp fullchain.pem /usr/local/share/ca-certificates/foreman-selfservice.crt
sudo update-ca-certificates
```

### RHEL / Rocky / Alma / Fedora

```bash
sudo cp fullchain.pem /etc/pki/ca-trust/source/anchors/foreman-selfservice.crt
sudo update-ca-trust
```

### Windows

Run an elevated command prompt:

```text
certutil -addstore -f Root fullchain.pem
```

For enterprise deployment, prefer issuing the portal certificate from your corporate PKI and distribute/trust the corporate root CA through normal endpoint policy instead of trusting an individual self-signed server certificate.

## Entra redirect URI

The Entra application registration must use the same externally visible HTTPS hostname, for example:

```text
https://portal.example.com/auth/entra/callback
```

Set both `PORTAL_HOSTNAME=portal.example.com` and `ENTRA_REDIRECT_URI=https://portal.example.com/auth/entra/callback` in `.env`.
