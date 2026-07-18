{pkgs, ...}: {
  fonts = {
    # use fonts specified by user rather than default ones
    # enableDefaultPackages = false;

    packages = with pkgs; [
      font-awesome
      cardo

      maple-mono.NF

      # https://github.com/NixOS/nixpkgs/blob/nixos-unstable-small/pkgs/data/fonts/nerd-fonts/manifests/fonts.json
      nerd-fonts.dejavu-sans-mono
      nerd-fonts.caskaydia-cove
      nerd-fonts.lilex
      nerd-fonts._0xproto
      nerd-fonts.recursive-mono
      nerd-fonts.symbols-only # anything need nerd icon(editor, system bar, etc...)
    ];
  };
}
