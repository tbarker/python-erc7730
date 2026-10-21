// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.30;

/// @title Encrypted Token Example
interface EncryptedToken {
    /// @custom:clearsig-intent Send encrypted tokens
    /// @custom:clearsig-encryption-scheme amount=fhevm
    /// @custom:clearsig-plaintext-type amount=uint64
    /// @custom:clearsig-fallback-label amount=[Encrypted amount]
    /// @custom:clearsig-label amount=Amount
    /// @custom:clearsig-format amount=tokenAmount
    /// @custom:clearsig-token-path amount=@.to
    /// @custom:clearsig-example params=(0x1212121212121212121212121212121212121212121212121212121212121212) intent="Send encrypted tokens" fields={"Amount":"[Encrypted amount]"}
    function transferEncrypted(bytes32 amount) external;
}
