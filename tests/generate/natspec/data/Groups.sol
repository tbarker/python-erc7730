// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
interface Groups {
    /// @notice Send tokens
    /// @param maker Sender
    /// @param recipient Recipient
    /// @param amount Amount
    /// @custom:clearsig-format amount=raw maker=addressName recipient=addressName
    /// @custom:clearsig-group parties="Parties" fields=(recipient,maker)
    function send(address maker, address recipient, uint256 amount) external;

    /// @notice Distribute fees
    /// @param recipients Recipient
    /// @param percentages Fee
    /// @custom:clearsig-format recipients=raw percentages=raw
    /// @custom:clearsig-group fees="Recipients and Fees" fields=(recipients,percentages) iteration=bundled
    function distribute(uint256[] calldata recipients, uint256[] calldata percentages) external;
}
