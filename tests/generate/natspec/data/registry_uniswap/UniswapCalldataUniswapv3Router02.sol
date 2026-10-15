// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;
// NatSpec recreation of the pinned official calldata-UniswapV3Router02.json.
// ABI-only interface: no implementation or on-chain behavior is claimed.
/// @custom:clearsig-owner Uniswap Labs
interface UniswapCalldataUniswapv3Router02 {
    struct ExactInputParams { bytes path; address recipient; uint256 amountIn; uint256 amountOutMinimum; }
    struct ExactInputSingleParams { address tokenIn; address tokenOut; uint24 fee; address recipient; uint256 amountIn; uint256 amountOutMinimum; uint160 sqrtPriceLimitX96; }
    struct ExactOutputParams { bytes path; address recipient; uint256 amountOut; uint256 amountInMaximum; }
    struct ExactOutputSingleParams { address tokenIn; address tokenOut; uint24 fee; address recipient; uint256 amountOut; uint256 amountInMaximum; uint160 sqrtPriceLimitX96; }

    /// @notice Swap
    /// @custom:clearsig-label params.amountIn=Amount to Send params.amountOutMinimum=Minimum to Receive params.recipient=Beneficiary
    /// @custom:clearsig-format params.amountIn=tokenAmount params.amountOutMinimum=tokenAmount params.recipient=addressName
    /// @custom:clearsig-token-path params.amountIn=#.params.path.[0:20] params.amountOutMinimum=#.params.path.[-20:]
    /// @custom:clearsig-types params.recipient=["eoa","contract"]
    /// @custom:clearsig-exclude params.path
    function exactInput(ExactInputParams calldata params) external;

    /// @notice swap
    /// @custom:clearsig-label params.amountIn=Send params.amountOutMinimum=Minimum to Receive params.fee=Uniswap fee params.recipient=Beneficiary
    /// @custom:clearsig-format params.amountIn=tokenAmount params.amountOutMinimum=tokenAmount params.fee=unit params.recipient=addressName
    /// @custom:clearsig-token-path params.amountIn=#.params.tokenIn params.amountOutMinimum=#.params.tokenOut
    /// @custom:clearsig-decimals params.fee=4
    /// @custom:clearsig-base params.fee=%
    /// @custom:clearsig-prefix params.fee=false
    /// @custom:clearsig-types params.recipient=["eoa","contract"]
    /// @custom:clearsig-exclude params.tokenIn,params.tokenOut,params.sqrtPriceLimitX96
    function exactInputSingle(ExactInputSingleParams calldata params) external;

    /// @notice Swap
    /// @custom:clearsig-label params.amountInMaximum=Maximum Amount In params.amountOut=Amount to Receive params.recipient=Beneficiary
    /// @custom:clearsig-format params.amountInMaximum=tokenAmount params.amountOut=tokenAmount params.recipient=addressName
    /// @custom:clearsig-token-path params.amountInMaximum=#.params.path.[-20:] params.amountOut=#.params.path.[0:20]
    /// @custom:clearsig-types params.recipient=["eoa","contract"]
    /// @custom:clearsig-exclude params.path
    function exactOutput(ExactOutputParams calldata params) external;

    /// @notice Swap
    /// @custom:clearsig-label params.amountInMaximum=Maximum Amount In params.amountOut=Amount to Receive params.fee=Uniswap fee params.recipient=Beneficiary
    /// @custom:clearsig-format params.amountInMaximum=tokenAmount params.amountOut=tokenAmount params.fee=unit params.recipient=addressName
    /// @custom:clearsig-token-path params.amountInMaximum=#.params.tokenIn params.amountOut=#.params.tokenOut
    /// @custom:clearsig-decimals params.fee=4
    /// @custom:clearsig-base params.fee=%
    /// @custom:clearsig-prefix params.fee=false
    /// @custom:clearsig-types params.recipient=["eoa","contract"]
    /// @custom:clearsig-exclude params.tokenIn,params.tokenOut,params.sqrtPriceLimitX96
    function exactOutputSingle(ExactOutputSingleParams calldata params) external;

    /// @notice Swap
    /// @param amountIn Amount to Send
    /// @param amountOutMin Minimum to Receive
    /// @param to Recipient
    /// @custom:clearsig-format amountIn=tokenAmount amountOutMin=tokenAmount to=addressName
    /// @custom:clearsig-token-path amountIn=#.path.[0] amountOutMin=#.path.[-1]
    /// @custom:clearsig-types to=["eoa","contract"]
    /// @custom:clearsig-exclude path
    function swapExactTokensForTokens(uint256 amountIn, uint256 amountOutMin, address[] calldata path, address to) external;

    /// @notice Swap
    /// @param amountOut Amount to Receive
    /// @param amountInMax Maximum to Send
    /// @param to Recipient
    /// @custom:clearsig-format amountOut=tokenAmount amountInMax=tokenAmount to=addressName
    /// @custom:clearsig-token-path amountOut=#.path.[-1] amountInMax=#.path.[0]
    /// @custom:clearsig-types to=["eoa","contract"]
    /// @custom:clearsig-sender-address to=["0x0000000000000000000000000000000000000001"]
    /// @custom:clearsig-exclude path
    function swapTokensForExactTokens(uint256 amountOut, uint256 amountInMax, address[] calldata path, address to) external;
}
