// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
// NatSpec recreation of the pinned official eip712-uniswap-permit2.json.
// ABI-only interface: no implementation or on-chain behavior is claimed.
/// @custom:clearsig-owner Uniswap Labs
interface UniswapEip712UniswapPermit2 {
    struct PermitDetails { address token; uint160 amount; uint48 expiration; uint48 nonce; }
    struct TokenPermissions { address token; uint256 amount; }

    /// @notice Authorize spending of token
    /// @param spender Spender
    /// @custom:clearsig-format spender=raw details.amount=tokenAmount details.expiration=date
    /// @custom:clearsig-label details.amount=Amount allowance details.expiration=Approval expires
    /// @custom:clearsig-token-path details.amount=#.details.token
    /// @custom:clearsig-threshold details.amount=0xffffffffffffffffffffffffffffffffffffffff
    /// @custom:clearsig-message details.amount=Unlimited
    /// @custom:clearsig-date-encoding details.expiration=timestamp
    /// @custom:clearsig-exclude sigDeadline,details.token,details.nonce
    /// @custom:clearsig-typed-data PermitSingle
    function sign0(PermitDetails calldata details, address spender, uint256 sigDeadline) external;

    /// @notice Authorize spending of tokens
    /// @param spender Spender
    /// @custom:clearsig-format spender=raw details.amount=tokenAmount details.expiration=date
    /// @custom:clearsig-label details.amount=Amount allowance details.expiration=Approval expires
    /// @custom:clearsig-token-path details.amount=#.details.[].token
    /// @custom:clearsig-threshold details.amount=0xffffffffffffffffffffffffffffffffffffffff
    /// @custom:clearsig-message details.amount=Unlimited
    /// @custom:clearsig-date-encoding details.expiration=timestamp
    /// @custom:clearsig-exclude sigDeadline,details.token,details.nonce
    /// @custom:clearsig-group allowances fields=(details.amount,details.expiration) iteration=sequential
    /// @custom:clearsig-typed-data PermitBatch
    function sign1(PermitDetails[] calldata details, address spender, uint256 sigDeadline) external;

    /// @notice Transfer `permitted.amount`
    /// @custom:clearsig-intent Authorize token transfer
    /// @param spender Spender
    /// @param deadline Deadline
    /// @custom:clearsig-format spender=addressName permitted.amount=tokenAmount deadline=date
    /// @custom:clearsig-types spender=["contract"]
    /// @custom:clearsig-label permitted.amount=Amount
    /// @custom:clearsig-token-path permitted.amount=#.permitted.token
    /// @custom:clearsig-threshold permitted.amount=0x8000000000000000000000000000000000000000000000000000000000000000
    /// @custom:clearsig-message permitted.amount=Any amount
    /// @custom:clearsig-date-encoding deadline=timestamp
    /// @custom:clearsig-exclude permitted.token,nonce
    /// @custom:clearsig-typed-data PermitTransferFrom
    function sign2(TokenPermissions calldata permitted, address spender, uint256 nonce, uint256 deadline) external;
}
