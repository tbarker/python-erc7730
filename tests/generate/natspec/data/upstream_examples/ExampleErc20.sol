// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-erc20.json; bindings and presentation-only edits live in recipe.json.
/// @author Fixture
interface ExampleErc20 {

    /// @notice Approve `spender` to spend `value`
    /// @custom:clearsig-intent Approve
    /// @param spender Spender
    /// @param value Amount
    /// @custom:clearsig-format spender=addressName value=tokenAmount
    /// @custom:clearsig-token-path value=@.to
    function approve(address spender, uint256 value) external;
}
