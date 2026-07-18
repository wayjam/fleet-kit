{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.nixCore;

  officialCache = "https://cache.nixos.org";
  chinaMirrors = [
    # cache mirror located in China
    # status: https://mirror.sjtu.edu.cn/
    # "https://mirror.sjtu.edu.cn/nix-channels/store"
    # status: https://mirrors.ustc.edu.cn/status/
    # "https://mirrors.ustc.edu.cn/nix-channels/store"

    # "https://mirror.nju.edu.cn/nix-channels/store/"
    "https://mirrors.tuna.tsinghua.edu.cn/nix-channels/store"
  ];

  profileSubstituters = {
    global = [officialCache];
    china = chinaMirrors ++ [officialCache];
  };
in {
  options.my.nixCore = {
    cacheProfile = lib.mkOption {
      type = lib.types.enum (builtins.attrNames profileSubstituters);
      default = "global";
      description = ''
        Nix binary cache profile for this host (optional China mirrors).

        - `global` (default): cache.nixos.org only.
        - `china`: TUNA mirror first, then cache.nixos.org.

        Set per host, e.g. `my.nixCore.cacheProfile = "china";`.
      '';
    };
  };

  config = {
    nix.settings = {
      # enable flakes globally
      experimental-features = ["nix-command" "flakes"];

      substituters = lib.mkForce profileSubstituters.${cfg.cacheProfile};
      trusted-public-keys = [
        # the default public key of cache.nixos.org, it's built-in, no need to add it here
        "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      ];
      builders-use-substitutes = true;
    };

    nixpkgs.config.allowUnfree = true;
    # Needed to build the flake.
    environment.systemPackages = [pkgs.git];

    # Auto upgrade nix package and the daemon service.
    nix.enable = true;
    nix.optimise.automatic = true;
    nix.package = pkgs.nix;
  };
}
