// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.30;

/// @title Test Token
/// @author Example
/// @custom:clearsig-format amount=tokenAmount
/// @custom:clearsig-token-path amount=@.to
/// @custom:clearsig-exclude nonce
interface ClearsigToken {
    struct Order { address maker; uint256 amount; uint256 deadline; }

    /// @notice Send `amount` to `to`
    /// @param to Recipient
    /// @param amount Amount to send
    /// @custom:clearsig-intent Send
    /// @custom:clearsig-example params=(Alice,1500000) intent="Send 1.5 USDC to Alice"
    function transfer(address to, uint256 amount) external returns (bool);

    /// @notice Approve a spender
    /// @param spender Spender
    /// @param amount Allowance
    /// @custom:clearsig-intent Approve
    /// @custom:clearsig-exclude amount
    /// @custom:clearsig-example params=(amount=1500000,spender=Alice) intent="Approve"
    function approve(address spender, uint256 amount) external returns (bool);

    /// @notice Settle an order
    /// @param order The order to settle
    /// @param nonce Replay protection
    /// @custom:clearsig-intent Settle order
    /// @custom:clearsig-format order.amount=tokenAmount
    /// @custom:clearsig-token-path order.amount=@.to
    /// @custom:clearsig-date-encoding order.deadline=timestamp
    /// @custom:clearsig-label order.maker=Maker order.amount=Amount order.deadline=Deadline
    /// @custom:clearsig-example params=((Alice,1500000,1700000000),42) intent="Settle order"
    function settle(Order calldata order, uint256 nonce) external;
}
