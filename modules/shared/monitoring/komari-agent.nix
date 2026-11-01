{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.monitoring.komariAgent;
  komariAgentVersion = "1.5.11";
  komariAgentPackage = pkgs.stdenvNoCC.mkDerivation {
    pname = "komari-agent";
    version = komariAgentVersion;

    src =
      if pkgs.stdenv.hostPlatform.system == "x86_64-linux"
      then
        pkgs.fetchurl {
          url = "https://github.com/komari-monitor/komari-agent/releases/download/${komariAgentVersion}/komari-agent-linux-amd64";
          hash = "sha256-eMKNieUjgWuuoBDA7QcU8kX1CP/aygVA9cnyMPcFPIw=";
        }
      else if pkgs.stdenv.hostPlatform.system == "aarch64-linux"
      then
        pkgs.fetchurl {
          url = "https://github.com/komari-monitor/komari-agent/releases/download/${komariAgentVersion}/komari-agent-linux-arm64";
          hash = "sha256-/44z3BLvK1c4+ikaWEmL0V3L+O9Rlmq2X9Z2eaCryH0=";
        }
      else throw "komari-agent supports only x86_64-linux and aarch64-linux.";

    dontUnpack = true;

    installPhase = ''
      runHook preInstall
      install -Dm755 "$src" "$out/bin/komari-agent"
      runHook postInstall
    '';

    meta = {
      description = "Lightweight monitoring agent for Komari";
      homepage = "https://github.com/komari-monitor/komari-agent";
      license = lib.licenses.mit;
      mainProgram = "komari-agent";
      platforms = ["x86_64-linux" "aarch64-linux"];
    };
  };

  boolEnv = value:
    if value
    then "true"
    else "false";

  optionalEnv = name: value:
    lib.optional (value != null && value != "") "${name}=${toString value}";

  optionalListEnv = name: values:
    lib.optional (values != []) "${name}=${lib.concatStringsSep "," values}";

  optionalMountpointsEnv = name: values:
    lib.optional (values != []) "${name}=${lib.concatStringsSep ";" values}";

  runner = pkgs.writeShellScript "run-komari-agent" ''
    set -euo pipefail

    ${lib.optionalString (cfg.endpointFile != null) ''
      AGENT_ENDPOINT="$(${pkgs.coreutils}/bin/tr -d '\r\n' < ${lib.escapeShellArg cfg.endpointFile})"
      export AGENT_ENDPOINT
    ''}

    AGENT_TOKEN="$(${pkgs.coreutils}/bin/tr -d '\r\n' < ${lib.escapeShellArg cfg.tokenFile})"
    export AGENT_TOKEN

    exec ${lib.escapeShellArg (lib.getExe cfg.package)} "$@"
  '';
in {
  options.my.monitoring.komariAgent = {
    enable = lib.mkEnableOption "Komari monitoring agent";

    package = lib.mkOption {
      type = lib.types.package;
      default = komariAgentPackage;
      description = "Komari agent package to run.";
    };

    endpoint = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Komari server endpoint, for example https://komari.example.com.";
    };

    endpointFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Runtime file containing the Komari server endpoint.";
    };

    tokenFile = lib.mkOption {
      type = lib.types.str;
      description = "Runtime file containing the Komari agent token.";
    };

    interval = lib.mkOption {
      type = lib.types.float;
      default = 1.0;
      description = "Monitoring data report interval in seconds.";
    };

    infoReportInterval = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "Basic system information report interval in minutes.";
    };

    reconnectInterval = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "WebSocket reconnect interval in seconds.";
    };

    maxRetries = lib.mkOption {
      type = lib.types.int;
      default = 3;
      description = "Maximum retry count for failed reports.";
    };

    disableAutoUpdate = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Disable the agent auto-updater because Nix manages the package.";
    };

    disableWebSsh = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Disable remote Web SSH and remote command execution.";
    };

    ignoreUnsafeCert = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Allow connecting to a Komari server with an unsafe TLS certificate.";
    };

    includeNics = lib.mkOption {
      type = with lib.types; listOf str;
      default = [];
      description = "Network interfaces to include in traffic statistics.";
    };

    excludeNics = lib.mkOption {
      type = with lib.types; listOf str;
      default = [];
      description = "Network interfaces to exclude from traffic statistics.";
    };

    includeMountpoints = lib.mkOption {
      type = with lib.types; listOf str;
      default = [];
      description = "Mountpoints to include in disk statistics.";
    };

    monthRotate = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "Traffic statistics monthly reset day. Null leaves the agent default.";
    };

    customDns = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional custom DNS server used by the agent.";
    };

    enableGpu = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable detailed GPU monitoring.";
    };

    memoryIncludeCache = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Include cache and buffers in memory usage reporting.";
    };

    memoryReportRawUsed = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Report raw used memory.";
    };

    customIpv4 = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional custom IPv4 address reported by the agent.";
    };

    customIpv6 = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional custom IPv6 address reported by the agent.";
    };

    getIpAddrFromNic = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Get the reported IP address from a network interface.";
    };

    hostProc = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional host /proc mountpoint for container deployments.";
    };

    extraEnvironment = lib.mkOption {
      type = with lib.types; attrsOf str;
      default = {};
      description = "Additional environment variables passed to komari-agent.";
    };

    extraArgs = lib.mkOption {
      type = with lib.types; listOf str;
      default = [];
      description = "Additional command-line arguments passed to komari-agent.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.endpoint != "" || cfg.endpointFile != null;
        message = "my.monitoring.komariAgent.endpoint or endpointFile must be set.";
      }
      {
        assertion = cfg.tokenFile != "";
        message = "my.monitoring.komariAgent.tokenFile must point to a runtime secret file.";
      }
    ];

    environment.systemPackages = [cfg.package];

    systemd.services.komari-agent = {
      description = "Komari monitoring agent";
      wantedBy = ["multi-user.target"];
      after = ["network-online.target"];
      wants = ["network-online.target"];
      environment =
        lib.optionalAttrs (cfg.endpointFile == null) {
          AGENT_ENDPOINT = cfg.endpoint;
        }
        // {
          AGENT_INTERVAL = toString cfg.interval;
          AGENT_INFO_REPORT_INTERVAL = toString cfg.infoReportInterval;
          AGENT_RECONNECT_INTERVAL = toString cfg.reconnectInterval;
          AGENT_MAX_RETRIES = toString cfg.maxRetries;
          AGENT_DISABLE_AUTO_UPDATE = boolEnv cfg.disableAutoUpdate;
          AGENT_DISABLE_WEB_SSH = boolEnv cfg.disableWebSsh;
          AGENT_IGNORE_UNSAFE_CERT = boolEnv cfg.ignoreUnsafeCert;
          AGENT_ENABLE_GPU = boolEnv cfg.enableGpu;
          AGENT_MEMORY_INCLUDE_CACHE = boolEnv cfg.memoryIncludeCache;
          AGENT_MEMORY_REPORT_RAW_USED = boolEnv cfg.memoryReportRawUsed;
          AGENT_GET_IP_ADDR_FROM_NIC = boolEnv cfg.getIpAddrFromNic;
        }
        // cfg.extraEnvironment;
      serviceConfig = {
        ExecStart = lib.escapeShellArgs ([runner] ++ cfg.extraArgs);
        Restart = "on-failure";
        RestartSec = "5s";
        Environment =
          optionalListEnv "AGENT_INCLUDE_NICS" cfg.includeNics
          ++ optionalListEnv "AGENT_EXCLUDE_NICS" cfg.excludeNics
          ++ optionalMountpointsEnv "AGENT_INCLUDE_MOUNTPOINTS" cfg.includeMountpoints
          ++ optionalEnv "AGENT_MONTH_ROTATE" cfg.monthRotate
          ++ optionalEnv "AGENT_CUSTOM_DNS" cfg.customDns
          ++ optionalEnv "AGENT_CUSTOM_IPV4" cfg.customIpv4
          ++ optionalEnv "AGENT_CUSTOM_IPV6" cfg.customIpv6
          ++ optionalEnv "HOST_PROC" cfg.hostProc;
      };
    };
  };
}
