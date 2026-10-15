// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-include.json; bindings and presentation-only edits live in recipe.json.
/// @title MyToken
/// @author Example
interface ExampleInclude {

    /// @notice Approve `spender` to spend `value`
    /// @custom:clearsig-intent Approve
    /// @param spender Spender
    /// @param value Amount
    /// @custom:clearsig-format spender=addressName value=tokenAmount
    /// @custom:clearsig-token-path value=@.to
    /// @custom:clearsig-threshold value="0xFFFFFFFFFFFFFFFFFF"
    function approve(address spender, uint256 value) external;
}
