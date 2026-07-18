{lib}: let
  supportedSystems = [
    "x86_64-linux"
    "aarch64-linux"
    "x86_64-darwin"
    "aarch64-darwin"
  ];

  mkHostDefaults = hostName: {lib, ...}: {
    nixpkgs.overlays = [
      (final: prev:
        lib.optionalAttrs (!(prev ? buildGo125Module) && (prev ? buildGo124Module)) {
          buildGo125Module = prev.buildGo124Module;
        })
    ];
    networking.hostName = lib.mkDefault hostName;
  };

  mkNixosModuleList = hostName: host: [
    (mkHostDefaults hostName)
    host.path
  ];
in rec {
  inherit supportedSystems mkHostDefaults mkNixosModuleList;

  mkColmena = {
    inputs,
    pkgs,
    system,
    inventory,
  }:
    {
      meta = {
        nixpkgs = pkgs;
        specialArgs = {inherit inputs;};
      };
    }
    // (builtins.mapAttrs (hostName: host: {
        imports = mkNixosModuleList hostName host;
        inherit (host) deployment;
      })
      inventory.nixos);

  mkPrivateRepoOutputs = {
    self,
    inputs,
    nixpkgs,
    system-manager,
    inventory,
    system ? "x86_64-linux",
  }: let
    pkgs = import nixpkgs {inherit system;};
  in {
    formatter = lib.genAttrs supportedSystems (
      formatterSystem: nixpkgs.legacyPackages.${formatterSystem}.alejandra
    );

    apps = lib.genAttrs supportedSystems (appSystem: let
      appPkgs = nixpkgs.legacyPackages.${appSystem};
    in {
      colmena = {
        type = "app";
        program = "${appPkgs.colmena}/bin/colmena";
      };

      nixos-anywhere = {
        type = "app";
        program = "${appPkgs.nixos-anywhere}/bin/nixos-anywhere";
      };

      fleet = inputs.fleetkit.apps.${appSystem}.fleet;
    });

    devShells = lib.genAttrs supportedSystems (shellSystem: let
      shellPkgs = nixpkgs.legacyPackages.${shellSystem};
      isDarwin = shellPkgs.stdenv.hostPlatform.isDarwin;
    in {
      default = shellPkgs.mkShell {
        packages = with shellPkgs;
          [
            age
            just
            nixos-anywhere
            openssl
            sops
            ssh-to-age
            xray
          ]
          ++ lib.optionals (!isDarwin) [
            wireguard-tools
          ];
      };
    });

    colmena = mkColmena {inherit inputs pkgs system inventory;};

    nixosConfigurations = lib.mapAttrs (hostName: host:
      nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = {inherit inputs hostName;};
        modules = mkNixosModuleList hostName host;
      })
    inventory.nixos;

    packages.${system} = lib.mapAttrs (name: _:
      self.nixosConfigurations.${name}.config.system.build.diskoImages)
    (lib.filterAttrs (_: host: host.image or false) inventory.nixos);

    systemConfigs = lib.mapAttrs (_: host:
      system-manager.lib.makeSystemConfig {
        specialArgs = {inherit inputs;};
        modules = [
          {
            nixpkgs.hostPlatform = system;
          }
          host.path
        ];
      })
    inventory.system;
  };
}
