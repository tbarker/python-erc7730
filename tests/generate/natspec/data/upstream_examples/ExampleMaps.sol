// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-maps.json; bindings and presentation-only edits live in recipe.json.
/// @author Example
/// @custom:clearsig-map underlyingToken[1]=0x00000000000000000000000000000000deadbeef,
/// @custom:clearsig-map underlyingToken[137]=0x00000000000000000000000000000000feedface,
/// @custom:clearsig-map underlyingToken[42161]=0x00000000000000000000000000000000cafebabe,
/// @custom:clearsig-map shareToken[1]=0x00000000000000000000000000000000abcdef01,
/// @custom:clearsig-map shareToken[137]=0x00000000000000000000000000000000abcdef02,
/// @custom:clearsig-map shareToken[42161]=0x00000000000000000000000000000000abcdef03,
interface ExampleMaps {

    /// @notice Deposit `amount` to get at least `minShares`
    /// @custom:clearsig-intent Deposit
    /// @param amount Deposit Amount
    /// @param minShares Min Received Shares
    /// @custom:clearsig-format amount=tokenAmount minShares=tokenAmount
    /// @custom:clearsig-token amount=map(underlyingToken,@.chainId) minShares=map(shareToken,@.chainId)
    function deposit(uint256 amount, uint256 minShares) external;
}
