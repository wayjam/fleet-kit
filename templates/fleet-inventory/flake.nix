{
  description = "Example private host inventory for fleet-kit modules";

  inputs = {
    fleetkit.url = "path:../fleet-kit";

    nixpkgs.follows = "fleetkit/nixpkgs";
    sops-nix.follows = "fleetkit/sops-nix";
    disko.follows = "fleetkit/disko";

    colmena = {
      url = "github:zhaofengli/colmena";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    system-manager = {
      url = "github:numtide/system-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs @ {
    self,
    fleetkit,
    nixpkgs,
    system-manager,
    ...
  }: let
    system = "x86_64-linux";
    pkgs = import nixpkgs {inherit system;};
    inventory = import ./hosts {inherit inputs pkgs system;};
  in
    fleetkit.lib.hostInventory.mkPrivateRepoOutputs {
      inherit self inputs nixpkgs system-manager inventory system;
    };
}
