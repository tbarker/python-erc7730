// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-eip712.json; bindings and presentation-only edits live in recipe.json.
/// @author MyContract
interface ExampleEip712 {
    struct PermitDetails { address token; uint160 amount; uint48 expiration; uint48 nonce; }

    /// @notice Authorize spending of token
    /// @param spender Spender
    /// @custom:clearsig-label details.amount=Amount allowance details.expiration=Approval expires
    /// @custom:clearsig-format spender=raw details.amount=tokenAmount details.expiration=date
    /// @custom:clearsig-token-path details.amount=#.details.token
    /// @custom:clearsig-date-encoding details.expiration=timestamp
    /// @custom:clearsig-exclude details.token,details.nonce,sigDeadline
    /// @custom:clearsig-typed-data PermitSingle
    function PermitSingle(PermitDetails calldata details, address spender, uint256 sigDeadline) external;

    /// @notice Authorize spending of tokens
    /// @param spender Spender
    /// @custom:clearsig-label details.amount=Amount allowance details.expiration=Approval expires
    /// @custom:clearsig-format spender=raw details.amount=tokenAmount details.expiration=date
    /// @custom:clearsig-token-path details.amount=#.details.[].token
    /// @custom:clearsig-date-encoding details.expiration=timestamp
    /// @custom:clearsig-exclude details.token,details.nonce,sigDeadline
    /// @custom:clearsig-typed-data PermitBatch
    function PermitBatch(PermitDetails[] calldata details, address spender, uint256 sigDeadline) external;
}
