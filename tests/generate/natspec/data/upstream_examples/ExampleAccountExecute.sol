// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-account-execute.json; bindings and presentation-only edits live in recipe.json.
/// @author Smart Account
/// @custom:clearsig-url https://eips.ethereum.org/EIPS/eip-4337
/// @custom:clearsig-format data=calldata
interface ExampleAccountExecute {

    /// @notice Execute transaction to `to` with `value` ETH
    /// @custom:clearsig-intent Execute Transaction
    /// @param to To
    /// @param value Value
    /// @param data Call Data
    /// @custom:clearsig-format to=addressName
    /// @custom:clearsig-types to=["wallet","eoa","contract","token"]
    /// @custom:clearsig-callee-path data="#.to"
    /// @custom:clearsig-amount-path data="#.value"
    function execute(address to, uint256 value, bytes calldata data) external;
}
