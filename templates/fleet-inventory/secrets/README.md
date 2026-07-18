# Secrets

Secrets in this directory should be encrypted with `sops`.

Expected keys for `proxy-example.yaml`:

```yaml
xray_uuid: replace-me
xray_reality_private_key: replace-me
xray_xhttp_path: /replace-me
wg_private_key: replace-me
```

Create or edit with:

```shell
sops secrets/proxy-example.yaml
git add secrets/proxy-example.yaml
```

Because flakes only include tracked files, a host that sets
`sops.defaultSopsFile = ../../secrets/<host>.yaml;` will not evaluate until the
encrypted file exists and has been added to git.

## Generate values

Use the private repo's `just secret` commands:

```shell
just secret age-file admin
just secret uuid
just secret xray-reality
just secret xray-shortid
just secret password --length 16 --mode ss2022
just secret randstr --prefix /
just secret wireguard
just secret proxy
```

Use `just secret age-file admin` for the initial `.sops.yaml` setup. It writes
the private age identity to `local/keys/admin.agekey` and prints a `public_key`.
Replace the placeholder recipient in `.sops.yaml` with that public key.
