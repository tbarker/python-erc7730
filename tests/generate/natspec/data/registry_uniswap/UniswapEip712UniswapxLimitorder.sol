// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
// NatSpec recreation of the pinned official eip712-UniswapX-LimitOrder.json.
// ABI-only interface: no implementation or on-chain behavior is claimed.
/// @custom:clearsig-owner Uniswap Labs
interface UniswapEip712UniswapxLimitorder {
    struct LimitOrder { OrderInfo info; address inputToken; uint256 inputAmount; OutputToken[] outputs; }
    struct OrderInfo { address reactor; address swapper; uint256 nonce; uint256 deadline; address additionalValidationContract; bytes additionalValidationData; }
    struct OutputToken { address token; uint256 amount; address recipient; }
    struct TokenPermissions { address token; uint256 amount; }

    /// @notice UniswapX Limit Order
    /// @param spender Approve to spender
    /// @param deadline Approval expire
    /// @custom:clearsig-format spender=raw permitted.amount=tokenAmount witness.inputAmount=tokenAmount witness.outputs.amount=tokenAmount witness.outputs.recipient=raw deadline=date
    /// @custom:clearsig-label permitted.amount=Amount allowance witness.inputAmount=Send witness.outputs.amount=Min amount to receive witness.outputs.recipient=On Address
    /// @custom:clearsig-token-path permitted.amount=#.permitted.token witness.inputAmount=#.witness.inputToken witness.outputs.amount=token
    /// @custom:clearsig-date-encoding deadline=timestamp
    /// @custom:clearsig-exclude nonce,witness.info,permitted.token,witness.inputToken,witness.outputs.token
    /// @custom:clearsig-typed-data PermitWitnessTransferFrom
    function sign0(TokenPermissions calldata permitted, address spender, uint256 nonce, uint256 deadline, LimitOrder calldata witness) external;
}
