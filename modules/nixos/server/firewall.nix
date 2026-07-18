{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.server.firewall;
  redirectRule = range:
    "-p udp --dport ${toString range.from}:${toString range.to} -j REDIRECT --to-ports ${toString range.target}";
  redirectRules = lib.unique (map redirectRule cfg.redirectUDPPortRanges);
  renderDelete = rule: "${pkgs.iptables}/bin/iptables -t nat -D PREROUTING ${rule} 2>/dev/null || true";
  renderAppend = rule: "${pkgs.iptables}/bin/iptables -t nat -A PREROUTING ${rule}";
in {
  imports = [
    ../../shared/server/firewall-options.nix
  ];

  config = {
    networking.firewall = {
      inherit (cfg) enable allowPing;
      allowedTCPPorts = lib.unique cfg.allowedTCPPorts;
      allowedUDPPorts = lib.unique cfg.allowedUDPPorts;
      allowedUDPPortRanges = lib.unique cfg.allowedUDPPortRanges;
      extraCommands = lib.mkIf (redirectRules != []) ''
        ${lib.concatMapStringsSep "\n" renderDelete redirectRules}
        ${lib.concatMapStringsSep "\n" renderAppend redirectRules}
      '';
      extraStopCommands = lib.mkIf (redirectRules != []) ''
        ${lib.concatMapStringsSep "\n" renderDelete redirectRules}
      '';
    };
  };
}
