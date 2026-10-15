// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
// NatSpec recreation of the pinned official eip712-UniswapX-ExclusiveDutchOrder.json.
// ABI-only interface: no implementation or on-chain behavior is claimed.
/// @custom:clearsig-owner Uniswap Labs
interface UniswapEip712UniswapxExclusivedutchorder {
    struct DutchOutput { address token; uint256 startAmount; uint256 endAmount; address recipient; }
    struct ExclusiveDutchOrder { OrderInfo info; uint256 decayStartTime; uint256 decayEndTime; address exclusiveFiller; uint256 exclusivityOverrideBps; address inputToken; uint256 inputStartAmount; uint256 inputEndAmount; DutchOutput[] outputs; }
    struct OrderInfo { address reactor; address swapper; uint256 nonce; uint256 deadline; address additionalValidationContract; bytes additionalValidationData; }
    struct TokenPermissions { address token; uint256 amount; }

    /// @notice UniswapX Exclusive Dutch Order
    /// @param spender Approve to spender
    /// @param deadline Approval expire
    /// @custom:clearsig-format spender=raw permitted.amount=tokenAmount witness.inputStartAmount=tokenAmount witness.outputs.endAmount=tokenAmount witness.outputs.recipient=raw deadline=date
    /// @custom:clearsig-label permitted.amount=Approve amount witness.inputStartAmount=Spend max witness.outputs.endAmount=Minimum amounts to receive witness.outputs.recipient=On Addresses
    /// @custom:clearsig-token-path permitted.amount=#.permitted.token witness.inputStartAmount=#.witness.inputToken witness.outputs.endAmount=token
    /// @custom:clearsig-date-encoding deadline=timestamp
    /// @custom:clearsig-exclude nonce,witness.info,witness.decayStartTime,witness.decayEndTime,witness.exclusiveFiller,witness.exclusivityOverrideBps,witness.inputEndAmount,witness.outputs.startAmount,permitted.token,witness.inputToken,witness.outputs.token
    /// @custom:clearsig-typed-data PermitWitnessTransferFrom
    function sign0(TokenPermissions calldata permitted, address spender, uint256 nonce, uint256 deadline, ExclusiveDutchOrder calldata witness) external;
}
