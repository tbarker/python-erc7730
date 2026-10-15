// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

/// @title Fee Controller
/// @author Contract Developer
/// @custom:clearsig-owner Protocol DAO
/// @custom:clearsig-url https://example.org/
/// @custom:clearsig-constant feeBase="%",
/// @custom:clearsig-constant feeDecimals=2,
interface MetadataAnnotations {
    /// @notice Set fee
    /// @param fee Fee
    /// @custom:clearsig-format fee=unit
    /// @custom:clearsig-base fee=$.metadata.constants.feeBase
    /// @custom:clearsig-decimals fee=$.metadata.constants.feeDecimals
    function setFee(uint256 fee) external;
}
