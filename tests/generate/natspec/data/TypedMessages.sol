// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

/// @author Example
interface TypedMessages {
    struct Order { address maker; uint256 quantity; }

    /// @custom:clearsig-typed-data Permit
    /// @notice Permit `quantity`
    /// @param quantity Quantity
    /// @custom:clearsig-intent Permit
    /// @custom:clearsig-format quantity=raw
    /// @custom:clearsig-example params=(9007199254740993) intent="Permit 9007199254740993" fields={"Quantity":"9007199254740993"}
    function describePermit(uint256 quantity) external;

    /// @custom:clearsig-typed-data Batch
    /// @notice Sign orders
    /// @param orders Orders
    /// @custom:clearsig-format orders.maker=raw orders.quantity=raw
    /// @custom:clearsig-example params=([(0x1111111111111111111111111111111111111111,2),(0x2222222222222222222222222222222222222222,3)]) intent="Sign orders"
    function describeBatch(Order[] calldata orders) external;

    /// @custom:clearsig-typed-data Signed
    /// @notice Sign
    /// @custom:clearsig-format quantity=raw @.from=raw
    /// @custom:clearsig-label @.from=Signer
    /// @custom:clearsig-example params=(1) intent="Sign" fields={"Signer":"0x1111111111111111111111111111111111111111"}
    function describeSigner(uint256 quantity) external;

    function unrelated(address recipient) external;
}
