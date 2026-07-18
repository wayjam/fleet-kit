{inputs, ...}: {
  imports = [
    inputs.fleetkit.systemManagerModules.lxc-host
    inputs.fleetkit.systemManagerModules.proxy-xray
    inputs.fleetkit.systemManagerModules.proxy-hy2
    inputs.fleetkit.systemManagerModules.proxy-realm
    inputs.fleetkit.systemManagerModules.monitoring-komari-agent
  ];

  my.proxy.xray = {
    enable = false;
    inbounds.vless-reality = {
      type = "vless";
      listenPort = 443;
      uuidFile = "/run/secrets/xray_uuid";
    };
  };

  my.proxy.hy2 = {
    enable = false;
    listenPort = 8443;
    passwordFile = "/run/secrets/hy2_password";
    tls = {
      certFile = "/etc/ssl/example/fullchain.pem";
      keyFile = "/etc/ssl/example/key.pem";
    };
  };

  my.proxy.realm = {
    enable = false;
    forwards.web = {
      listenPort = 8080;
      remote = "127.0.0.1:3000";
      protocol = "tcp";
    };
  };

  my.monitoring.komariAgent = {
    enable = false;
    endpoint = "https://komari.example.invalid";
    tokenFile = "/run/secrets/komari_agent_token";
    hostProc = "/host/proc";
  };
}
