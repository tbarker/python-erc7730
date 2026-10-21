// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.30;

// Recreates example-array-iteration.json; bindings and presentation-only edits live in recipe.json.
// Preserve the published example's raw native-value display instead of inferring amount.
/// @title Example Array Iteration Contract
/// @author Example
/// @custom:clearsig-format values=raw
interface ExampleArrayIteration {

    /// @notice Distribute fees `percentages` among recipients `recipients`
    /// @custom:clearsig-intent Distribute fees among recipients
    /// @param recipients Recipients
    /// @param percentages Percentages
    /// @custom:clearsig-format @.value=amount recipients=addressName percentages=unit
    /// @custom:clearsig-label @.value=Total Distributed Amount
    /// @custom:clearsig-separator recipients="Recipient {index}"
    /// @custom:clearsig-group fees="Recipients and Fees" fields=(recipients,percentages) iteration=bundled
    /// @custom:clearsig-base percentages="%"
    /// @custom:clearsig-decimals percentages=2
    function distribute(address[] calldata recipients, uint256[] calldata percentages) external;

    /// @notice Execute batch calls to targets
    /// @custom:clearsig-interpolated-intent Execute batch calls to targets {targets} with values {values}
    /// @param datas Nested Calls
    /// @custom:clearsig-format datas=calldata
    /// @custom:clearsig-separator datas="Transaction {index}"
    /// @custom:clearsig-callee-path datas="targets.[]"
    /// @custom:clearsig-amount-path datas="values.[]"
    function batchExecute(address[] calldata targets, bytes[] calldata datas, uint256[] calldata values) external;
}
