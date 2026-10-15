// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
/// @author Example
interface ContainerFields {
    /// @notice Send `@.value` to `recipient`
    /// @param recipient Recipient
    /// @custom:clearsig-intent Send native currency
    /// @custom:clearsig-format @.value=amount recipient=addressName
    /// @custom:clearsig-label @.value=Amount
    function send(address recipient) external payable;

    /// @notice Deposit
    /// @custom:clearsig-format @.value=amount
    /// @custom:clearsig-label @.value=Deposit
    function deposit() external payable;
}
