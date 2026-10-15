// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-userops-eip712.json; bindings and presentation-only edits live in recipe.json.
/// @author Account Abstraction
interface ExampleUseropsEip712 {

    /// @notice Authorize user operation from `sender`
    /// @custom:clearsig-intent Sign Packed User Operation
    /// @param sender Sender Account
    /// @param initCode Init Code
    /// @param callData Embedded Call Data
    /// @param paymasterAndData Paymaster Data
    /// @custom:clearsig-format sender=addressName nonce=raw initCode=raw callData=calldata accountGasLimits=raw preVerificationGas=raw gasFees=raw paymasterAndData=raw
    /// @custom:clearsig-exclude nonce,accountGasLimits,preVerificationGas,gasFees
    /// @custom:clearsig-types sender=["contract"]
    /// @custom:clearsig-if-not-in initCode=[0] paymasterAndData=[0]
    /// @custom:clearsig-callee-path callData="#.sender"
    /// @custom:clearsig-typed-data PackedUserOperation
    function PackedUserOperation(address sender, uint256 nonce, bytes calldata initCode, bytes calldata callData, bytes32 accountGasLimits, uint256 preVerificationGas, bytes32 gasFees, bytes calldata paymasterAndData) external;
}
