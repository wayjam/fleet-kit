{
  config,
  lib,
  ...
}: let
  cfg = config.my.secrets.sopsAgeKey;
in {
  options.my.secrets.sopsAgeKey = {
    enable = lib.mkEnableOption "a shared age key for sops-nix host secret decryption";

    keyFile = lib.mkOption {
      type = lib.types.str;
      default = "/etc/sops/age/key.txt";
      description = "Runtime path to the age identity used by sops-nix.";
    };
  };

  config = lib.mkIf cfg.enable {
    sops = {
      age = {
        keyFile = cfg.keyFile;
        sshKeyPaths = lib.mkForce [];
      };
      gnupg.sshKeyPaths = lib.mkForce [];
    };
  };
}
