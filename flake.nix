{
  description = "fleet-kit: reusable Nix modules, fleet CLI, and inventory helpers";

  nixConfig = {
    extra-substituters = [
      "https://mirrors.ustc.edu.cn/nix-channels/store"
      "https://cache.nixos.org"
      "https://nix-community.cachix.org"
    ];
    extra-trusted-public-keys = [
      "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
    ];
  };

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";

    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    darwin-nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";

    darwin = {
      url = "github:LnL7/nix-darwin";
      inputs.nixpkgs.follows = "darwin-nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    darwin-home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "darwin-nixpkgs";
    };

    sops-nix = {
      # Last commit before sops-nix switched to Go 1.25 and dropped 25.05-or-older compatibility.
      url = "github:Mic92/sops-nix/17eea6f3816ba6568b8c81db8a4e6ca438b30b7c";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    rime-config = {
      url = "github:Mintimate/oh-my-rime/main";
      flake = false;
    };

    impermanence.url = "github:nix-community/impermanence";

    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs @ {
    self,
    flake-utils,
    nixpkgs,
    ...
  }: let
    lib = nixpkgs.lib;
    hostInventoryLib = import ./lib/host-inventory.nix {inherit lib;};
  in
    (flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
      fleet = pkgs.writeShellApplication {
        name = "fleet";
        runtimeInputs = with pkgs;
          [
            age
            gnutar
            nix
            openssh
            openssl
            sops
            ssh-to-age
            xray
          ]
          ++ lib.optionals (!isDarwin) [
            wireguard-tools
          ];
        text = ''
          export FLEET_KIT_TEMPLATE_DIR='${./templates/fleet-inventory}'
          export FLEET_KIT_SKILLS_DIR='${./skills}'
          exec ${pkgs.python3}/bin/python3 ${./tools/fleet} "$@"
        '';
      };
    in {
      formatter = pkgs.alejandra;
      packages.fleet = fleet;
      apps.fleet = {
        type = "app";
        program = "${fleet}/bin/fleet";
      };
    }))
    // {
      lib = {
        hostInventory = hostInventoryLib;
      };

      nixosModules = {
        default = ./modules/nixos;
        profiles-server = ./modules/nixos/profiles/server.nix;
        profiles-kvm-server = ./modules/nixos/profiles/kvm-server.nix;
        profiles-builder = ./modules/nixos/profiles/builder.nix;
        container = ./modules/nixos/container;
        server-ssh = ./modules/nixos/server/ssh.nix;
        server-journald = ./modules/nixos/server/journald.nix;
        server-firewall = ./modules/nixos/server/firewall.nix;
        server-fail2ban = ./modules/nixos/server/fail2ban.nix;
        server-disk-expansion = ./modules/nixos/server/disk-expansion.nix;
        server-tuning = ./modules/nixos/server/tuning.nix;
        sops-age-key = ./modules/nixos/secrets/sops-age-key.nix;
        vpn-wireguard = ./modules/nixos/vpn/wireguard.nix;
        proxy-xray = ./modules/shared/proxy/xray.nix;
        proxy-hy2 = ./modules/shared/proxy/hy2.nix;
        proxy-sing-box = ./modules/shared/proxy/sing-box.nix;
        proxy-realm = ./modules/shared/proxy/realm.nix;
        monitoring-komari-agent = ./modules/shared/monitoring/komari-agent.nix;
        web-caddy = ./modules/shared/web/caddy.nix;
        nix-remote-builder = ./modules/shared/nix-remote-builder.nix;
      };

      systemManagerModules = {
        lxc-host = ./modules/shared/profiles/lxc-host.nix;
        server-base = ./modules/shared/server/base.nix;
        server-firewall-options = ./modules/shared/server/firewall-options.nix;
        proxy-xray = ./modules/shared/proxy/xray.nix;
        proxy-hy2 = ./modules/shared/proxy/hy2.nix;
        proxy-sing-box = ./modules/shared/proxy/sing-box.nix;
        proxy-realm = ./modules/shared/proxy/realm.nix;
        monitoring-komari-agent = ./modules/shared/monitoring/komari-agent.nix;
        nix-remote-builder = ./modules/shared/nix-remote-builder.nix;
      };

      darwinModules = {
        default = ./modules/darwin;
      };

      templates.fleet-inventory = {
        path = ./templates/fleet-inventory;
        description = "Private fleet inventory skeleton using fleet-kit";
      };

      devShells =
        nixpkgs.lib.genAttrs [
          "x86_64-linux"
          "aarch64-linux"
          "x86_64-darwin"
          "aarch64-darwin"
        ] (system: {
          default = nixpkgs.legacyPackages.${system}.mkShell {
            buildInputs = with nixpkgs.legacyPackages.${system}; [
              age
              colmena
              just
              nixos-anywhere
              sops
              ssh-to-age
            ];
          };
        });
    };
}
