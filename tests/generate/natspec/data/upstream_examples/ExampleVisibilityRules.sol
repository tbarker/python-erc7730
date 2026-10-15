// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-visibility-rules.json; bindings and presentation-only edits live in recipe.json.
/// @author Example
interface ExampleVisibilityRules {

    /// @notice Send `value` to `to`
    /// @custom:clearsig-intent Send
    /// @param to To
    /// @param value Amount
    /// @param referrer Referrer
    /// @param legacy Legacy Amount
    /// @param fee Fee Amount
    /// @custom:clearsig-format to=addressName value=tokenAmount referrer=addressName rfu=raw legacy=raw fee=amount
    /// @custom:clearsig-token-path value=@.to
    /// @custom:clearsig-exclude rfu
    /// @custom:clearsig-visible to="always" value="always" referrer="optional"
    /// @custom:clearsig-must-match legacy=[0]
    /// @custom:clearsig-if-not-in fee=[0]
    function transfer(address to, uint256 value, address referrer, address rfu, uint256 legacy, uint256 fee) external;
}
