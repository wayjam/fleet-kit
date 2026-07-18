"""`fleet secret <sub>` — pure-Python secret generation.

Replaces the former bash `secret-gen` script.  Uses stdlib (`os.urandom`,
`uuid`) for random material and subprocess for external tools (`openssl`,
`age-keygen`, `xray`, `wg`, `ssh-keygen`).
"""

import os
import re
import subprocess
import uuid as _uuid
from pathlib import Path
from shutil import which

from common import die


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rand_hex(nbytes):
    return os.urandom(nbytes).hex()


def _needs(name):
    if not which(name):
        die(
            f"required command not found: {name}\n"
            f"hint: run through 'nix run .#fleet -- secret ...' or a just secret-* command"
        )


def _positive_int(value, name="value"):
    try:
        n = int(value)
    except (TypeError, ValueError):
        die(f"{name} must be a positive integer, got {value!r}")
    if n < 1:
        die(f"{name} must be a positive integer, got {n}")
    return n


# ---------------------------------------------------------------------------
# generators
# ---------------------------------------------------------------------------

def gen_uuid():
    if which("uuidgen"):
        return subprocess.check_output(["uuidgen"], text=True).strip().lower()
    h = _rand_hex(16)
    return f"{h:0>8}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def gen_password(length=32, mode="plain"):
    length = _positive_int(length, "password length")
    if length < 8:
        die(f"password length must be >= 8, got {length}")
    if mode == "ss2022":
        if length not in (16, 32):
            die(
                "Shadowsocks 2022 password byte count must be 16 or 32\n"
                "hint: 16 bytes for 2022-blake3-aes-128-gcm, 32 bytes for 2022-blake3-aes-256-gcm"
            )
        _needs("openssl")
        return subprocess.check_output(["openssl", "rand", "-base64", str(length)], text=True).strip()
    # plain
    _needs("openssl")
    chars = ""
    while len(chars) < length:
        raw = subprocess.check_output(["openssl", "rand", "-base64", str(length * 2)], text=True)
        chars += re.sub(r"[^A-Za-z0-9@#%+=:,._-]", "", raw)
    return chars[:length]


def gen_hex(nbytes=32):
    nbytes = _positive_int(nbytes, "byte count")
    _needs("openssl")
    return subprocess.check_output(["openssl", "rand", "-hex", str(nbytes)], text=True).strip()


def gen_randstr(nbytes=16, prefix=""):
    nbytes = _positive_int(nbytes, "byte count")
    return f"{prefix}{_rand_hex(nbytes)}"


def gen_xray_shortid(nbytes=8):
    nbytes = _positive_int(nbytes, "shortId byte count")
    if nbytes > 8:
        die(f"xray Reality shortId byte count must be between 1 and 8, got {nbytes}")
    return gen_hex(nbytes)


def gen_xray_reality():
    """Generate an Xray Reality keypair *and* a shortId (merged output)."""
    _needs("xray")
    result = subprocess.check_output(["xray", "x25519"], text=True)
    shortid = gen_xray_shortid(8)
    return f"{result.strip()}\nshortId: {shortid}"


def gen_age_keypair():
    _needs("age-keygen")
    return subprocess.check_output(["age-keygen"], text=True).strip()


def gen_age_file(output):
    if not output:
        die("missing output file")
    path = Path(output)
    if path.exists():
        die(f"refusing to overwrite existing age key: {output}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _needs("age-keygen")
    subprocess.check_call(["age-keygen", "-o", str(path)], stdout=subprocess.DEVNULL)
    os.chmod(path, 0o600)
    public = subprocess.check_output(["age-keygen", "-y", str(path)], text=True).strip()
    print(f"age_key_file: {output}")
    print(f"public_key:   {public}")


def gen_wireguard_keypair():
    _needs("wg")
    private = subprocess.check_output(["wg", "genkey"], text=True).strip()
    public = subprocess.check_output(["wg", "pubkey"], input=private, text=True).strip()
    print(f"private: {private}")
    print(f"public:  {public}")


def gen_ssh_ed25519(output, comment="operator@example.invalid"):
    if not output:
        die("missing output file")
    path = Path(output)
    pub_path = path.with_suffix(path.suffix + ".pub")
    if path.exists() or pub_path.exists():
        die(f"refusing to overwrite existing key: {output}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _needs("ssh-keygen")
    subprocess.check_call(
        ["ssh-keygen", "-q", "-t", "ed25519", "-a", "100", "-N", "", "-C", comment, "-f", str(path)]
    )
    os.chmod(path, 0o600)
    public = pub_path.read_text().strip()
    print(f"private_key_file: {output}")
    print(f"public_key_file:  {output}.pub")
    print(f"public_key:       {public}")


def gen_proxy_bundle():
    """Print a bundle of proxy-related secrets."""
    print(f"xray_uuid: {gen_uuid()}")
    print(f"xray_ss2022_password: {gen_password(16, 'ss2022')}")
    print(f"xray_xhttp_path: {gen_randstr(16, '/')}")
    print(f"hy2_password: {gen_password(32)}")
    print(f"xray_short_id: {gen_xray_shortid(8)}")
    if which("xray"):
        print(gen_xray_reality())
    else:
        print("xray binary not found; run just secret-xray-reality inside nix develop when needed.")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_SECRET_COMMANDS = {
    "uuid": lambda args, config: print(gen_uuid()),
    "password": lambda args, config: print(gen_password(args.length, args.mode)),
    "hex": lambda args, config: print(gen_hex(args.bytes)),
    "randstr": lambda args, config: print(gen_randstr(args.bytes, args.prefix)),
    "xray-shortid": lambda args, config: print(gen_xray_shortid(args.bytes)),
    "xray-reality": lambda args, config: print(gen_xray_reality()),
    "age": lambda args, config: print(gen_age_keypair()),
    "age-file": lambda args, config: gen_age_file(
        _resolve_age_file(args, config)
    ),
    "wireguard": lambda args, config: gen_wireguard_keypair(),
    "ssh": lambda args, config: gen_ssh_ed25519(
        _resolve_ssh_path(args, config), args.comment
    ),
    "proxy": lambda args, config: gen_proxy_bundle(),
}


def _resolve_age_file(args, config):
    """If name looks like a bare filename, place it under secret_key_dir."""
    output = args.name
    if "/" not in output:
        key_dir = config.get("paths", {}).get("secret_key_dir", "local/keys")
        output = str(Path(key_dir) / f"{args.name}.agekey")
    return output


def _resolve_ssh_path(args, config):
    """If name looks like a bare filename, place it under secret_key_dir."""
    output = args.name
    if "/" not in output:
        key_dir = config.get("paths", {}).get("secret_key_dir", "local/keys")
        output = str(Path(key_dir) / args.name)
    return output


def cmd_secret(args, config):
    handler = _SECRET_COMMANDS.get(args.secret_command)
    if not handler:
        die(f"missing secret command: {args.secret_command}")
    handler(args, config)
