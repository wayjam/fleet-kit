"""`fleet profile` and `fleet xray-uri`.

Builds client connection profiles by combining nix-eval'd module config with
sops-decrypted host secrets, for xray (vless/shadowsocks/reality), sing-box
(shadowsocks), hysteria2, and wireguard backends.
"""

import base64
import json
from shutil import which
from subprocess import run as _run
from urllib.parse import quote, urlencode, urlparse

from common import die
from nix import (
    host_target,
    load_host_secrets,
    maybe_nix_eval_json,
    secret_key_from_runtime_path,
    secret_value,
)


def reality_public_key(secrets, private_key_path):
    private_key_name = secret_key_from_runtime_path(private_key_path)
    candidates = []
    if private_key_name:
        candidates.append(private_key_name.replace("_private_key", "_public_key"))
    candidates.extend(["xray_reality_public_key", "reality_public_key"])
    for key in candidates:
        value = secrets.get(key)
        if value:
            return str(value).strip()
    die("missing Reality public key in decrypted secrets")


def xray_inbounds(host):
    return maybe_nix_eval_json(f".#nixosConfigurations.{host}.config.my.proxy.xray.inbounds") or {}


def hy2_config(host):
    cfg = maybe_nix_eval_json(f".#nixosConfigurations.{host}.config.my.proxy.hy2") or {}
    if not cfg.get("enable"):
        return {}
    return cfg


def sing_box_shadowsocks_inbounds(host):
    cfg = maybe_nix_eval_json(f".#nixosConfigurations.{host}.config.my.proxy.singBox") or {}
    if not cfg.get("enable"):
        return {}
    return cfg.get("shadowsocksInbounds") or {}


def wireguard_interfaces(host):
    return maybe_nix_eval_json(f".#nixosConfigurations.{host}.config.my.vpn.wireguard.interfaces") or {}


def xhttp_profile_settings(host, inbound_name, inbound, secrets):
    xhttp = inbound.get("xhttp") or {}
    settings = dict(xhttp.get("settings") or {})

    path = xhttp.get("path") or settings.get("path") or ""
    path_file = xhttp.get("pathFile")
    if path_file:
        path = secret_value(secrets, path_file, f"{host}.{inbound_name}.xhttp")
    if path:
        settings["path"] = path

    host_name = xhttp.get("host") or settings.get("host") or ""
    if host_name:
        settings["host"] = host_name

    mode = xhttp.get("mode") or settings.get("mode") or "auto"
    settings["mode"] = mode

    return {
        "path": path,
        "host": host_name,
        "mode": mode,
        "settings": settings,
    }


def vless_uri(host, host_address, inbound_name, inbound, secrets, fingerprint, profile_name=None):
    uuid = secret_value(secrets, inbound.get("uuidFile"), f"{host}.{inbound_name}")
    label = profile_name or f"{host}-{inbound_name}"
    query = {
        "type": inbound.get("transport", "tcp"),
        "encryption": "none",
    }

    flow = inbound.get("flow")
    if flow:
        query["flow"] = flow

    if inbound.get("transport") == "xhttp":
        xhttp = xhttp_profile_settings(host, inbound_name, inbound, secrets)
        if xhttp["path"]:
            query["path"] = xhttp["path"]
        query["mode"] = xhttp["mode"]
        if xhttp["host"]:
            query["host"] = xhttp["host"]

    reality = inbound.get("reality") or {}
    if reality.get("enable"):
        server_names = reality.get("serverNames") or []
        short_ids = reality.get("shortIds") or []
        query.update(
            {
                "security": "reality",
                "pbk": reality_public_key(secrets, reality.get("privateKeyFile")),
                "fp": fingerprint,
            }
        )
        if server_names:
            query["sni"] = server_names[0]
        if short_ids and short_ids[0]:
            query["sid"] = short_ids[0]
    else:
        query["security"] = "none"

    query_string = urlencode(query, doseq=True)
    return f"vless://{quote(uuid, safe='')}@{host_address}:{inbound['listenPort']}?{query_string}#{quote(label)}"


def ss_uri(host, host_address, inbound_name, inbound, secrets, profile_name=None):
    password = secret_value(secrets, inbound.get("passwordFile"), f"{host}.{inbound_name}")
    label = profile_name or f"{host}-{inbound_name}"
    userinfo = base64.urlsafe_b64encode(f"{inbound['method']}:{password}".encode()).decode().rstrip("=")
    return f"ss://{userinfo}@{host_address}:{inbound['listenPort']}#{quote(label)}"


def xray_profile_entries(host, host_address, secrets, args):
    inbounds = xray_inbounds(args.host)
    entries = []

    for name, inbound in inbounds.items():
        if args.inbound is not None and args.inbound != name:
            continue

        inbound_type = inbound.get("type")
        base = {
            "kind": "xray",
            "name": name,
            "tag": inbound.get("tag"),
            "protocol": inbound_type,
            "address": host_address,
            "port": inbound.get("listenPort"),
        }

        if inbound_type == "vless":
            uuid = secret_value(secrets, inbound.get("uuidFile"), f"{host}.{name}")
            reality = inbound.get("reality") or {}
            entry = {
                **base,
                "uuid": uuid,
                "flow": inbound.get("flow") or "",
                "transport": inbound.get("transport", "tcp"),
                "security": "reality" if reality.get("enable") else "none",
                "uri": vless_uri(host, host_address, name, inbound, secrets, args.fingerprint, args.name),
            }
            if inbound.get("transport") == "xhttp":
                entry["xhttp"] = xhttp_profile_settings(host, name, inbound, secrets)
            if reality.get("enable"):
                server_names = reality.get("serverNames") or []
                short_ids = reality.get("shortIds") or []
                entry["reality"] = {
                    "dest": reality.get("dest"),
                    "sni": server_names[0] if server_names else "",
                    "serverNames": server_names,
                    "publicKey": reality_public_key(secrets, reality.get("privateKeyFile")),
                    "shortId": short_ids[0] if short_ids else "",
                    "shortIds": short_ids,
                    "fingerprint": args.fingerprint,
                }
            entries.append(entry)
        elif inbound_type == "shadowsocks":
            entry = {
                **base,
                "method": inbound.get("method"),
                "network": inbound.get("network"),
                "uri": ss_uri(host, host_address, name, inbound, secrets, args.name),
            }
            entries.append(entry)

    if args.inbound and not entries:
        die(f"missing Xray inbound {args.inbound!r} on host {args.host}")
    return entries


def sing_box_profile_entries(host, host_address, secrets, args):
    inbounds = sing_box_shadowsocks_inbounds(args.host)
    entries = []

    for name, inbound in inbounds.items():
        if args.inbound is not None and args.inbound != name:
            continue

        entries.append(
            {
                "kind": "sing-box",
                "name": name,
                "tag": inbound.get("tag"),
                "protocol": "shadowsocks",
                "address": host_address,
                "port": inbound.get("listenPort"),
                "method": inbound.get("method"),
                "network": inbound.get("network"),
                "uri": ss_uri(host, host_address, name, inbound, secrets, args.name),
            }
        )

    if args.inbound and not entries:
        die(f"missing sing-box Shadowsocks inbound {args.inbound!r} on host {args.host}")
    return entries


def derive_wireguard_public_key(private_key):
    if not which("wg"):
        return None
    result = _run(
        ["wg", "pubkey"],
        input=private_key,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def wireguard_profile_entries(host, host_address, secrets, args):
    interfaces = wireguard_interfaces(host)
    entries = []
    for name, interface in interfaces.items():
        if args.interface is not None and args.interface != name:
            continue

        private_key_name = secret_key_from_runtime_path(interface.get("privateKeyFile"))
        private_key = secrets.get(private_key_name, "") if private_key_name else ""
        public_key = derive_wireguard_public_key(str(private_key).strip()) if private_key else None
        entries.append(
            {
                "kind": "wireguard",
                "name": name,
                "address": host_address,
                "ips": interface.get("ips") or [],
                "listenPort": interface.get("listenPort"),
                "mtu": interface.get("mtu"),
                "privateKeySecret": private_key_name,
                "publicKey": public_key,
                "peers": interface.get("peers") or [],
            }
        )

    if args.interface and not entries:
        die(f"missing WireGuard interface {args.interface!r} on host {args.host}")
    return entries


def hy2_sni(cfg):
    masquerade_url = ((cfg.get("masquerade") or {}).get("proxy") or {}).get("url") or ""
    if not masquerade_url:
        return ""
    parsed = urlparse(masquerade_url)
    return parsed.hostname or ""


def hy2_uri(host, host_address, cfg, secrets, profile_name=None):
    password = secret_value(secrets, cfg.get("passwordFile"), f"{host}.hy2")
    label = profile_name or f"{host}-hy2"
    query = {}
    port_hopping = cfg.get("portHopping") or {}
    port = cfg["listenPort"]
    if port_hopping.get("enable"):
        port = f"{port_hopping['from']}-{port_hopping['to']}"
        if port_hopping.get("hopInterval"):
            query["hopInterval"] = port_hopping["hopInterval"]

    sni = hy2_sni(cfg)
    if sni:
        query["sni"] = sni
    if (cfg.get("client") or {}).get("insecure"):
        query["insecure"] = "1"

    obfs_password_file = cfg.get("obfsPasswordFile")
    if obfs_password_file:
        query["obfs"] = "salamander"
        query["obfs-password"] = secret_value(secrets, obfs_password_file, f"{host}.hy2.obfs")

    query_string = urlencode(query)
    suffix = f"?{query_string}" if query_string else ""
    return f"hysteria2://{quote(password, safe='')}@{host_address}:{port}/{suffix}#{quote(label)}"


def hy2_profile_entries(host, host_address, secrets, args):
    cfg = hy2_config(host)
    if not cfg:
        return []

    port_hopping = cfg.get("portHopping") or {}
    listen = str(cfg.get("listenPort"))
    if port_hopping.get("enable"):
        listen = f"{port_hopping['from']}-{port_hopping['to']}"

    masquerade = ((cfg.get("masquerade") or {}).get("proxy") or {})
    obfs_password_file = cfg.get("obfsPasswordFile")
    entry = {
        "kind": "hy2",
        "name": "hy2",
        "protocol": "hysteria2",
        "address": host_address,
        "port": cfg.get("listenPort"),
        "listen": listen,
        "portHopping": cfg.get("portHopping") or {},
        "passwordSecret": secret_key_from_runtime_path(cfg.get("passwordFile")),
        "tls": {
            "certFile": cfg.get("tls", {}).get("certFile"),
            "keyFile": cfg.get("tls", {}).get("keyFile"),
            "sni": hy2_sni(cfg),
            "insecure": (cfg.get("client") or {}).get("insecure", False),
        },
        "masquerade": {
            "url": masquerade.get("url") or "",
            "rewriteHost": masquerade.get("rewriteHost"),
        },
        "uri": hy2_uri(host, host_address, cfg, secrets, args.name),
    }
    if obfs_password_file:
        entry["obfs"] = {
            "type": "salamander",
            "passwordSecret": secret_key_from_runtime_path(obfs_password_file),
        }
    return [entry]


def print_profile_text(host, address, entries, *, uri_only=False):
    if uri_only:
        for entry in entries:
            if entry.get("uri"):
                print(entry["uri"])
        return

    print(f"Host: {host}")
    print(f"Address: {address}")
    for entry in entries:
        print()
        if entry["kind"] == "xray":
            print(f"[Xray: {entry['name']}]")
            print(f"Protocol: {entry['protocol']}")
            print(f"Address: {entry['address']}")
            print(f"Port: {entry['port']}")
            if entry["protocol"] == "vless":
                print(f"Transport: {entry['transport']}")
                print(f"Security: {entry['security']}")
                print(f"UUID: {entry['uuid']}")
                if entry.get("flow"):
                    print(f"Flow: {entry['flow']}")
                xhttp = entry.get("xhttp")
                if xhttp:
                    print(f"xHTTP path: {xhttp.get('path') or '-'}")
                    print(f"xHTTP mode: {xhttp.get('mode') or '-'}")
                    if xhttp.get("host"):
                        print(f"xHTTP host: {xhttp.get('host')}")
                reality = entry.get("reality")
                if reality:
                    print(f"Reality dest: {reality.get('dest')}")
                    print(f"SNI: {reality.get('sni')}")
                    print(f"Reality public key: {reality.get('publicKey')}")
                    print(f"Short ID: {reality.get('shortId')}")
                    print(f"Fingerprint: {reality.get('fingerprint')}")
            elif entry["protocol"] == "shadowsocks":
                print(f"Method: {entry.get('method')}")
                print(f"Network: {entry.get('network')}")
            if entry.get("uri"):
                print(f"URI: {entry['uri']}")
        elif entry["kind"] == "sing-box":
            print(f"[sing-box: {entry['name']}]")
            print(f"Protocol: {entry['protocol']}")
            print(f"Address: {entry['address']}")
            print(f"Port: {entry['port']}")
            print(f"Method: {entry.get('method')}")
            print(f"Network: {entry.get('network')}")
            if entry.get("uri"):
                print(f"URI: {entry['uri']}")
        elif entry["kind"] == "wireguard":
            print(f"[WireGuard: {entry['name']}]")
            print(f"Address: {entry['address']}")
            print(f"Interface IPs: {', '.join(entry['ips']) if entry['ips'] else '-'}")
            print(f"Listen port: {entry.get('listenPort') or '-'}")
            if entry.get("mtu"):
                print(f"MTU: {entry['mtu']}")
            print(f"Private key secret: {entry.get('privateKeySecret') or '-'}")
            print(f"Public key: {entry.get('publicKey') or 'unavailable locally'}")
            peers = entry.get("peers") or []
            if peers:
                print("Peers:")
                for peer in peers:
                    print(f"  - Public key: {peer.get('publicKey')}")
                    if peer.get("endpoint"):
                        print(f"    Endpoint: {peer.get('endpoint')}")
                    allowed = peer.get("allowedIPs") or []
                    if allowed:
                        print(f"    Allowed IPs: {', '.join(allowed)}")
                    if peer.get("persistentKeepalive") is not None:
                        print(f"    Persistent keepalive: {peer.get('persistentKeepalive')}")
            else:
                print("Peers: -")
        elif entry["kind"] == "hy2":
            print(f"[HY2: {entry['name']}]")
            print(f"Protocol: {entry['protocol']}")
            print(f"Address: {entry['address']}")
            print(f"Listen: {entry.get('listen') or entry['port']}")
            port_hopping = entry.get("portHopping") or {}
            if port_hopping.get("enable"):
                print(f"Port hopping: {port_hopping.get('from')}-{port_hopping.get('to')}")
                print(f"Hop interval: {port_hopping.get('hopInterval')}")
            print(f"Password secret: {entry.get('passwordSecret') or '-'}")
            tls = entry.get("tls") or {}
            print(f"SNI: {tls.get('sni') or '-'}")
            print(f"TLS insecure: {tls.get('insecure')}")
            print(f"TLS cert file: {tls.get('certFile') or '-'}")
            masquerade = entry.get("masquerade") or {}
            if masquerade.get("url"):
                print(f"Masquerade URL: {masquerade.get('url')}")
                print(f"Masquerade rewrite host: {masquerade.get('rewriteHost')}")
            obfs = entry.get("obfs")
            if obfs:
                print(f"Obfs: {obfs.get('type')}")
                print(f"Obfs password secret: {obfs.get('passwordSecret')}")
            if entry.get("uri"):
                print(f"URI: {entry['uri']}")


def cmd_profile(args, config):
    address = args.host_address or host_target(args.host)
    secrets = load_host_secrets(args.host, config)
    entries = []
    if args.kind in ("all", "xray"):
        entries.extend(xray_profile_entries(args.host, address, secrets, args))
    if args.kind in ("all", "sing-box"):
        entries.extend(sing_box_profile_entries(args.host, address, secrets, args))
    if args.kind in ("all", "hy2"):
        entries.extend(hy2_profile_entries(args.host, address, secrets, args))
    if args.kind in ("all", "wireguard"):
        entries.extend(wireguard_profile_entries(args.host, address, secrets, args))

    if not entries:
        die(f"host {args.host} has no matching client profiles")

    if args.format == "json":
        print(json.dumps({"host": args.host, "address": address, "profiles": entries}, indent=2) + "\n")
    else:
        print_profile_text(args.host, address, entries, uri_only=getattr(args, "uri_only", False))
