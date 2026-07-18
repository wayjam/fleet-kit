{
  config,
  pkgs,
  lib,
  hostName,
  ...
}: {
  # Disko 配置 (用于构建镜像时的磁盘布局)
  disko = {
    # 让 Disko 自动生成 NixOS 的 fileSystems 配置。
    # 这样可以避免在主配置文件中硬编码设备名（如 /dev/sda2），生成的配置会使用 UUID 或 Label。
    enableConfig = true;

    devices = {
      disk.main = {
        # 这个 device 指的是 Disko 构建镜像时内部 QEMU 虚拟机的设备名。
        # 通常是 /dev/vda，无论你的目标 host 磁盘是 sda 还是 vda 都写 vda。
        device = "/dev/vda";
        type = "disk";
        # 生成的磁盘镜像文件的大小，根据需要调整
        imageSize = "4G";
        # 定义磁盘分区表和分区
        content = {
          type = "gpt"; # 使用 GPT 分区表
          partitions = {
            # 分区 1: BIOS Boot Partition (1MB)
            # 在 GPT 磁盘上供 GRUB 在 BIOS 模式下安装引导代码使用。
            # 类型 EF02 代表 "BIOS boot partition"。
            bios_boot = {
              # 名称可以自定，如 'boot' 或 'grub'
              size = "1M";
              type = "EF02";
              priority = 0; # 优先级最高，确保是第一个分区
            };

            # 分区 2: EFI System Partition (ESP) / Boot Partition (512MB)
            # 用于存放 UEFI 引导加载器和内核/initrd。
            # 类型 EF00 代表 "EFI System Partition"。
            ESP = {
              name = "ESP"; # 分区名/标签 (可选，但推荐)
              size = "512M";
              type = "EF00";
              priority = 1; # 第二个分区
              # 格式化为 FAT32 (VFAT)，这是 UEFI 规范要求的
              content = {
                type = "filesystem";
                format = "vfat";
                # 在最终 NixOS 系统中的挂载点
                mountpoint = "/boot";
                # 挂载选项，限制权限，提高安全性
                mountOptions = ["fmask=0077" "dmask=0077"];
              };
            };

            # 分区 3: 根文件系统 (使用剩余全部空间)
            root = {
              name = "NIXROOT"; # 分区名/标签 (可选，但推荐)
              size = "100%"; # 使用所有剩余空间
              priority = 2; # 最后一个分区
              content = {
                type = "filesystem";
                format = "ext4";
                mountpoint = "/";
              };
            };
          };
        };
      };
    };
  };
}
