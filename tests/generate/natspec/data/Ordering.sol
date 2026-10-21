// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
interface Ordering {
    /// @notice Send tokens
    /// @param to Recipient
    /// @param amount Amount
    /// @custom:clearsig-format amount=raw to=addressName
    function send(address to, uint256 amount, uint256 extra) external;
}
