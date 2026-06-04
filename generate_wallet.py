#!/usr/bin/env python3
"""
Standalone wallet generator — run this once before starting the bot in LIVE mode.

Usage:
    python generate_wallet.py

Copies the two env vars to stdout. Paste them into your .env file.
"""

from layers.execution.wallet import generate_wallet

if __name__ == "__main__":
    pub, enc, key = generate_wallet()
    print(f"\nNew Solana wallet generated.")
    print(f"Public key : {pub}")
    print(f"\nPaste into .env:")
    print(f"WALLET_PUBLIC_KEY={pub}")
    print(f"WALLET_PRIVATE_KEY_ENCRYPTED={enc}")
    print(f"WALLET_ENCRYPTION_KEY={key}")
    print(f"\n⚠  Back up WALLET_ENCRYPTION_KEY securely. Loss = unrecoverable funds.")
