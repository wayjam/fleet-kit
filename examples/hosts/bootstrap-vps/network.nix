{
  config,
  pkgs,
  lib,
  ...
}: {
  # 使用 systemd-networkd 管理网络，这是一个现代且强大的网络管理工具
  networking.useNetworkd = true;
  # DHCP 功能应由 systemd-networkd 内部处理。设为 false。
  networking.useDHCP = false;
  # 显式启用 systemd-networkd 服务
  systemd.network.enable = true;

  # 示例：为 eth0 (因为设置了 net.ifnames=0) 配置 DHCP
  # 如果你的 host 主要使用 DHCP，这个配置会让它开箱即用
  systemd.network.networks."10-dhcp" = {
    matchConfig.Name = "eth0"; # 匹配名为 eth0 的网卡
    networkConfig.DHCP = "ipv4"; # 仅启用 IPv4 DHCP (可选 "ipv6" 或 "yes" 代表两者都启用)
  };

  # 禁用 systemd-resolved (DNS 解析服务)
  # 假设 DNS 由 DHCP 提供，或者你打算手动配置 /etc/resolv.conf 或使用其他 DNS 服务
  services.resolved.enable = false;

  # Firewall ports are managed by my.server.firewall and service modules.
}
