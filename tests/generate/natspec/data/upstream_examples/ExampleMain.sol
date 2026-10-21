// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-main.json; bindings and presentation-only edits live in recipe.json.
/// @title MyToken
/// @author Example
interface ExampleMain {

    /// @notice Send `value` to `to`
    /// @custom:clearsig-intent Send
    /// @param to To
    /// @param value Amount
    /// @custom:clearsig-format to=addressName value=tokenAmount
    /// @custom:clearsig-token-path value=@.to
    function transfer(address to, uint256 value) external;
}
