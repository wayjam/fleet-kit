{
  config,
  pkgs,
  lib,
  hostName,
  ...
}: {
  # 内核、引导、Initrd 相关设置

  # 一些内核参数
  boot.kernelParams = [
    # 关闭内核的操作审计功能，可以减少日志量和轻微提升性能
    "audit=0"
    # 不要根据 PCIe 地址生成复杂的网卡名（例如 enpXsY），而是使用传统的顺序命名（例如 eth0）
    # 这对于通用镜像很有用，因为硬件位置不确定，eth0 更易于预测和配置
    "net.ifnames=0"
  ];

  # Initrd (初始 RAM 磁盘) 配置
  boot.initrd = {
    # 使用 ZSTD 压缩，压缩率高，启动时解压速度快
    compressor = "zstd";
    # ZSTD 压缩参数：级别 19（高压缩率），T0（使用所有可用 CPU 线程）
    compressorArgs = ["-19" "-T0"];
    # 在 Initrd 阶段（第一阶段启动）使用 systemd
    systemd.enable = true;

    # 早期启动（Initrd 阶段）可能需要的内核模块，特别是针对虚拟化环境
    availableKernelModules = [
      "virtio_net" # VirtIO 网络驱动
      "virtio_pci" # VirtIO PCI 总线驱动
      "virtio_mmio" # VirtIO MMIO 总线驱动 (一些较新或 ARM 平台可能使用)
      "virtio_blk" # VirtIO 块设备驱动 (虚拟磁盘)
      "virtio_scsi" # VirtIO SCSI 驱动 (另一种虚拟磁盘)
      "nvme" # NVMe 固态硬盘驱动 (现代 host 常用)
      "ahci" # SATA/AHCI 控制器
      "ata_piix" # 常见 legacy IDE/SATA 控制器
      "sd_mod" # SCSI 磁盘驱动 (SATA/SAS/USB 磁盘通常也用这个)
      "sr_mod" # SCSI CD-ROM 驱动 (不太常用，但包含成本低)
      "xhci_pci" # USB/XHCI 控制器
    ];
    # 明确要在 Initrd 中加载的内核模块
    kernelModules = [
      "virtio_balloon" # VirtIO 内存气球驱动 (动态调整 VM 内存)
      "virtio_console" # VirtIO 串口驱动 (用于访问 VM 控制台)
      "virtio_rng" # VirtIO 随机数生成器驱动
    ];

    # QEMU 时钟问题修复，仅在未使用 systemd initrd 时需要，此处 systemd.enable = true，故不再需要
    # postDeviceCommands = lib.mkIf (!config.boot.initrd.systemd.enable) ''
    #   hwclock -s
    # '';
  };

  # 引导加载程序 (GRUB) 配置
  boot.loader.grub = {
    # 仅在非容器环境下启用 GRUB
    enable = !config.boot.isContainer;
    # 默认启动上次选中的条目，方便在多代配置间切换后保持选择
    default = "saved";
    # 【重要修改】使用 "nodev" 而不是硬编码 "/dev/vda"。
    # 这让 NixOS 在安装/更新 GRUB 时，自动检测应该安装到哪个磁盘（基于 '/' 和 '/boot' 的挂载点）。
    # 这是解决 sda/vda 等设备名变化的关键，提高了通用性。
    devices = ["nodev"];
    # 启用 EFI 引导支持，兼容 UEFI 启动的机器
    efiSupport = true;
    # 推荐与 efiSupport 一起使用，将 GRUB EFI 文件安装到可移动介质路径。
    # 这提高了在不同 UEFI 实现中的兼容性，特别是在首次安装或系统迁移时。
    efiInstallAsRemovable = true;
    # 不扫描其他操作系统，服务器通常是单系统
    useOSProber = false;
  };

  # 如果需要 NixOS 直接管理 EFI 启动项（通常不需要，efiInstallAsRemovable 更通用）
  # boot.loader.efi.canTouchEfiVariables = true;
}
