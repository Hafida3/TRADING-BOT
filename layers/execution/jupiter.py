"""
Layer 5 – Execution: Jupiter v6 swap integration.

Modes:
  DRY_RUN=true           — quote fetched, no transaction built
  SOLANA_NETWORK=devnet  — real signed self-transfer (0.001 SOL) on Devnet;
                           proves the signing/broadcast pipeline end-to-end
                           without touching real funds
  live                   — full Jupiter swap on mainnet
"""

import base64
import json
import struct
import requests
from pathlib import Path
from typing import Optional

import config

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL  = "https://quote-api.jup.ag/v6/swap"

SOL_MINT       = "So11111111111111111111111111111111111111112"
USDC_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS  = 6
SOL_DECIMALS   = 9
DEFAULT_SLIPPAGE_BPS = 50  # 0.5%


# ── Devnet keypair loader ─────────────────────────────────────────────────────

def _load_devnet_keypair():
    """Load keypair from devnet-wallet.json (raw 64-byte secret key array)."""
    from solders.keypair import Keypair
    path = Path(config.DEVNET_WALLET_PATH).expanduser()
    secret = bytes(json.loads(path.read_text()))
    return Keypair.from_bytes(secret)


# ── Devnet self-transfer ──────────────────────────────────────────────────────

def _devnet_self_transfer(label: str) -> dict:
    """
    Send 0.001 SOL to self on Devnet — real on-chain transaction that proves
    the full sign → broadcast pipeline without touching real funds or Jupiter.
    Returns the transaction signature.
    """
    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.hash import Hash
        from solders.transaction import Transaction
        from solders.system_program import transfer, TransferParams
        from solders.message import Message

        kp = _load_devnet_keypair()
        pubkey = kp.pubkey()
        rpc = config.SOLANA_RPC_URL

        # 1. Check balance
        bal_resp = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance",
            "params": [str(pubkey)],
        }, timeout=10).json()
        balance_lamports = bal_resp.get("result", {}).get("value", 0)
        if balance_lamports < 10_000:
            return {
                "success": False,
                "error": (
                    f"Devnet wallet unfunded ({balance_lamports} lamports). "
                    f"Visit https://faucet.solana.com and airdrop to {pubkey}"
                ),
            }

        # 2. Get recent blockhash
        bh_resp = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "confirmed"}],
        }, timeout=10).json()
        blockhash_str = bh_resp["result"]["value"]["blockhash"]
        blockhash = Hash.from_string(blockhash_str)

        # 3. Build self-transfer instruction (0.001 SOL)
        lamports = 1_000  # 0.000001 SOL — tiny, just proves signing works
        ix = transfer(TransferParams(
            from_pubkey=pubkey,
            to_pubkey=pubkey,
            lamports=lamports,
        ))

        msg = Message.new_with_blockhash([ix], pubkey, blockhash)
        tx  = Transaction([kp], msg, blockhash)
        tx_bytes = bytes(tx)

        # 4. Broadcast
        send_resp = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(tx_bytes).decode(),
                {"encoding": "base64", "preflightCommitment": "confirmed"},
            ],
        }, timeout=30).json()

        if "error" in send_resp:
            return {"success": False, "error": str(send_resp["error"])}

        sig = send_resp["result"]
        explorer = f"https://explorer.solana.com/tx/{sig}?cluster=devnet"
        print(f"[Devnet] {label} — tx: {sig}")
        print(f"[Devnet] Explorer: {explorer}")
        return {
            "success":      True,
            "devnet":       True,
            "tx_signature": sig,
            "explorer_url": explorer,
            "label":        label,
        }

    except Exception as exc:
        print(f"[Devnet] _devnet_self_transfer error: {exc}")
        return {"success": False, "error": str(exc)}


# ── Quote ─────────────────────────────────────────────────────────────────────

def get_quote(
    input_mint: str,
    output_mint: str,
    amount_atomic: int,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
) -> Optional[dict]:
    try:
        resp = requests.get(
            JUPITER_QUOTE_URL,
            params={
                "inputMint":   input_mint,
                "outputMint":  output_mint,
                "amount":      amount_atomic,
                "slippageBps": slippage_bps,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[Jupiter] get_quote error: {exc}")
        return None


# ── Transaction helpers ───────────────────────────────────────────────────────

def _get_swap_transaction(quote: dict, user_pubkey: str) -> Optional[str]:
    """Return base64-encoded unsigned VersionedTransaction from Jupiter."""
    try:
        resp = requests.post(
            JUPITER_SWAP_URL,
            json={
                "quoteResponse":              quote,
                "userPublicKey":              user_pubkey,
                "wrapAndUnwrapSol":           True,
                "dynamicComputeUnitLimit":    True,
                "prioritizationFeeLamports":  "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("swapTransaction")
    except Exception as exc:
        print(f"[Jupiter] _get_swap_transaction error: {exc}")
        return None


def _sign_and_send(swap_tx_b64: str, keypair, rpc_url: str) -> Optional[str]:
    """Sign a VersionedTransaction with our keypair and broadcast to RPC."""
    try:
        from solders.transaction import VersionedTransaction

        raw    = base64.b64decode(swap_tx_b64)
        tx     = VersionedTransaction.from_bytes(raw)
        sig    = keypair.sign_message(bytes(tx.message))
        signed = VersionedTransaction([sig], tx.message)

        resp = requests.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method":  "sendTransaction",
            "params":  [
                base64.b64encode(bytes(signed)).decode(),
                {
                    "encoding":             "base64",
                    "skipPreflight":        False,
                    "preflightCommitment":  "confirmed",
                    "maxRetries":           3,
                },
            ],
        }, timeout=30)
        result = resp.json()
        if "error" in result:
            print(f"[Jupiter] RPC sendTransaction error: {result['error']}")
            return None
        return result.get("result")
    except Exception as exc:
        print(f"[Jupiter] _sign_and_send error: {exc}")
        return None


# ── Public swap functions ─────────────────────────────────────────────────────

def buy_sol_with_usdc(
    usdc_amount: float,
    keypair,
    rpc_url: str,
    dry_run: bool = True,
) -> dict:
    """Swap USDC → SOL. On devnet: simulated via self-transfer."""
    if config.SOLANA_NETWORK == "devnet":
        return _devnet_self_transfer(f"BUY {usdc_amount:.2f} USDC→SOL")

    amount_atomic = int(usdc_amount * 10 ** USDC_DECIMALS)
    quote = get_quote(USDC_MINT, SOL_MINT, amount_atomic)
    if not quote:
        return {"success": False, "error": "Quote unavailable"}

    out_sol      = int(quote.get("outAmount", 0)) / 10 ** SOL_DECIMALS
    price_impact = float(quote.get("priceImpactPct", 0))

    if dry_run:
        return {
            "success":          True,
            "dry_run":          True,
            "input_usdc":       usdc_amount,
            "output_sol":       out_sol,
            "price_impact_pct": price_impact,
            "tx_signature":     "DRY_RUN",
        }

    swap_tx = _get_swap_transaction(quote, str(keypair.pubkey()))
    if not swap_tx:
        return {"success": False, "error": "Failed to build swap transaction"}

    sig = _sign_and_send(swap_tx, keypair, rpc_url)
    if not sig:
        return {"success": False, "error": "Transaction broadcast failed"}

    return {
        "success":          True,
        "dry_run":          False,
        "input_usdc":       usdc_amount,
        "output_sol":       out_sol,
        "price_impact_pct": price_impact,
        "tx_signature":     sig,
    }


def sell_sol_for_usdc(
    sol_amount: float,
    keypair,
    rpc_url: str,
    dry_run: bool = True,
) -> dict:
    """Swap SOL → USDC. On devnet: simulated via self-transfer."""
    if config.SOLANA_NETWORK == "devnet":
        return _devnet_self_transfer(f"SELL {sol_amount:.6f} SOL→USDC")

    amount_atomic = int(sol_amount * 10 ** SOL_DECIMALS)
    quote = get_quote(SOL_MINT, USDC_MINT, amount_atomic)
    if not quote:
        return {"success": False, "error": "Quote unavailable"}

    out_usdc     = int(quote.get("outAmount", 0)) / 10 ** USDC_DECIMALS
    price_impact = float(quote.get("priceImpactPct", 0))

    if dry_run:
        return {
            "success":          True,
            "dry_run":          True,
            "input_sol":        sol_amount,
            "output_usdc":      out_usdc,
            "price_impact_pct": price_impact,
            "tx_signature":     "DRY_RUN",
        }

    swap_tx = _get_swap_transaction(quote, str(keypair.pubkey()))
    if not swap_tx:
        return {"success": False, "error": "Failed to build swap transaction"}

    sig = _sign_and_send(swap_tx, keypair, rpc_url)
    if not sig:
        return {"success": False, "error": "Transaction broadcast failed"}

    return {
        "success":          True,
        "dry_run":          False,
        "input_sol":        sol_amount,
        "output_usdc":      out_usdc,
        "price_impact_pct": price_impact,
        "tx_signature":     sig,
    }
