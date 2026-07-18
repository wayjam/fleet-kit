# fleet-kit library Justfile
#
# This public flake is a library: no personal darwinConfigurations or
# nixosConfigurations live here. Host build/deploy recipes belong in a
# private inventory (see templates/fleet-inventory/Justfile and docs/).

set positional-arguments := true

# List all the just commands
default:
  @just --list


############################################################################
#
#  flake / nix maintenance
#
############################################################################

# Update all the flake inputs
[group('common')]
up:
  nix flake update

# Update specific input
# Usage: just upp nixpkgs
[group('common')]
upp input:
  nix flake update {{input}}

# Open a nix shell with nixpkgs
[group('common')]
repl:
  nix repl -f flake:nixpkgs

# Format the nix files in this repo
[group('common')]
fmt:
  nix fmt

# Evaluate the flake (smoke-check public outputs)
[group('common')]
check:
  nix flake check

# List all generations of the system profile
[group('common')]
history:
  nix profile history --profile /nix/var/nix/profiles/system

# remove all generations older than 7 days
# on darwin, you may need to switch to root user to run this command
[group('common')]
clean:
  sudo nix profile wipe-history --profile /nix/var/nix/profiles/system --older-than 7d

# Garbage collect all unused nix store entries
[group('common')]
gc:
  # garbage collect all unused nix store entries(system-wide)
  sudo nix-collect-garbage --delete-older-than 7d
  # garbage collect all unused nix store entries(for the user - home-manager)
  # https://github.com/NixOS/nix/issues/8508
  nix-collect-garbage --delete-older-than 7d

# Show all the auto gc roots in the nix store
[group('common')]
gcroot:
  ls -al /nix/var/nix/gcroots/auto/


############################################################################
#
#  fleet CLI (library package)
#
############################################################################

# Run fleet CLI help
[group('fleet')]
fleet *args:
  nix run .#fleet -- {{args}}


############################################################################
#
#  git related commands
#
############################################################################

# Stash & Pull & Pop
[group('git')]
git-temp:
  @git stash save 'temp'
  @git pull --rebase
  @git stash pop

# Calc Github Sha256
[group('git')]
prefetch-gh owner repo rev="HEAD":
    #!/usr/bin/env bash
    json=$(nix-prefetch-github --no-deep-clone --quiet --rev {{ rev }} {{ owner }} {{ repo }})
    owner=$(echo "$json" | jq -r '.owner')
    repo=$(echo "$json" | jq -r '.repo')
    rev=$(echo "$json" | jq -r '.rev' | cut -c 1-8)
    hash=$(echo "$json" | jq -r '.hash')
    cat <<EOF
    pkgs.fetchFromGitHub {
      owner = "$owner";
      repo  = "$repo";
      rev   = "$rev";
      hash  = "$hash";
    };
    EOF
