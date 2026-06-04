"""
Layer 5 – Execution: Solana hot-wallet generation and balance queries.

Private key is stored Fernet-encrypted in .env so plaintext never touches disk.
"""

import base64
import requests
from typing import Optional

from cryptography.fernet import Fernet

try:
    from solders.keypair import Keypair  # type: ignore
    _SOLDERS = True
except ImportError:
    _SOLDERS = False


# ── Key generation ────────────────────────────────────────────────────────────

def generate_wallet() -> tuple[str, str, str]:
    """
    Create a fresh Solana keypair and encrypt the private key.

    Returns
    -------
    (public_key_str, encrypted_private_key_b64, encryption_key_str)
    """
    if not _SOLDERS:
        raise RuntimeError("Install 'solders' to use wallet features.")

    kp = Keypair()
    pub = str(kp.pubkey())

    fernet_key = Fernet.generate_key()
    fernet = Fernet(fernet_key)
    encrypted = fernet.encrypt(bytes(kp))

    enc_b64 = base64.b64encode(encrypted).decode()
    fernet_key_str = fernet_key.decode()
    return pub, enc_b64, fernet_key_str


def load_keypair(encrypted_b64: str, encryption_key: str) -> Optional["Keypair"]:
    """Decrypt and reconstruct a Keypair from .env values."""
    if not _SOLDERS:
        raise RuntimeError("Install 'solders' to use wallet features.")
    try:
        fernet = Fernet(encryption_key.encode())
        raw = fernet.decrypt(base64.b64decode(encrypted_b64))
        return Keypair.from_bytes(raw)
    except Exception as exc:
        print(f"[Wallet] load_keypair error: {exc}")
        return None


# ── On-chain balance queries ──────────────────────────────────────────────────

def get_sol_balance(public_key: str, rpc_url: str) -> float:
    """SOL balance in SOL (not lamports)."""
    try:
        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [public_key, {"commitment": "confirmed"}],
            },
            timeout=10,
        )
        lamports = resp.json()["result"]["value"]
        return lamports / 1e9
    except Exception as exc:
        print(f"[Wallet] get_sol_balance error: {exc}")
        return 0.0


def get_usdc_balance(public_key: str, rpc_url: str, usdc_mint: str) -> float:
    """USDC token account balance."""
    try:
        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    public_key,
                    {"mint": usdc_mint},
                    {"encoding": "jsonParsed"},
                ],
            },
            timeout=10,
        )
        accounts = resp.json()["result"]["value"]
        if not accounts:
            return 0.0
        ui_amount = (
            accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
        )
        return float(ui_amount or 0.0)
    except Exception as exc:
        print(f"[Wallet] get_usdc_balance error: {exc}")
        return 0.0
