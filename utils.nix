# Legacy host-builder helpers removed from the public kit surface.
# Host instances live in private inventory; this file is kept only so
# accidental imports fail clearly rather than pulling personal hosts.
{
  inputs,
  self,
  nixpkgs,
  flake-utils,
}: {
  hostInventory = {
    nixos = {};
    darwin = {};
    packages = {};
  };
  loadHostConfig = _: throw "fleet-kit: loadHostConfig removed; use private inventory + nixosModules";
  mkHost = _: _: throw "fleet-kit: mkHost removed; use private inventory + nixosModules/darwinModules";
  forAllSystems = flake-utils.lib.eachDefaultSystem;
}
