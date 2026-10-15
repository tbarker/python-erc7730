// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
// NatSpec recreation of the pinned official eip712-uniswap-V2DutchOrder.json.
// ABI-only interface: no implementation or on-chain behavior is claimed.
/// @custom:clearsig-owner Uniswap Labs
interface UniswapEip712UniswapV2Dutchorder {
    struct DutchOutput { address token; uint256 startAmount; uint256 endAmount; address recipient; }
    struct OrderInfo { address reactor; address swapper; uint256 nonce; uint256 deadline; address additionalValidationContract; bytes additionalValidationData; }
    struct TokenPermissions { address token; uint256 amount; }
    struct V2DutchOrder { OrderInfo info; address cosigner; address baseInputToken; uint256 baseInputStartAmount; uint256 baseInputEndAmount; DutchOutput[] baseOutputs; }

    /// @notice UniswapX V2 Dutch Order
    /// @param spender Approve to spender
    /// @param deadline Approval expire
    /// @custom:clearsig-format spender=raw permitted.amount=tokenAmount witness.baseInputStartAmount=tokenAmount witness.baseOutputs.endAmount=tokenAmount witness.baseOutputs.recipient=raw deadline=date
    /// @custom:clearsig-label permitted.amount=Approve amount witness.baseInputStartAmount=Spend max witness.baseOutputs.endAmount=Min amount to receive witness.baseOutputs.recipient=On Address
    /// @custom:clearsig-token-path permitted.amount=#.permitted.token witness.baseInputStartAmount=#.witness.baseInputToken witness.baseOutputs.endAmount=token
    /// @custom:clearsig-date-encoding deadline=timestamp
    /// @custom:clearsig-exclude nonce,witness.info,witness.cosigner,witness.baseInputEndAmount,witness.baseOutputs.startAmount,permitted.token,witness.baseInputToken,witness.baseOutputs.token
    /// @custom:clearsig-typed-data PermitWitnessTransferFrom
    function sign0(TokenPermissions calldata permitted, address spender, uint256 nonce, uint256 deadline, V2DutchOrder calldata witness) external;
}
