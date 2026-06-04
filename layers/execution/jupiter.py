"""
Layer 5 – Execution: Jupiter v6 swap integration.

In DRY_RUN mode only the quote is fetched (read-only); no transaction is built
or signed, so no wallet is required.
"""

import base64
import requests
from typing import Optional

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6
SOL_DECIMALS = 9
DEFAULT_SLIPPAGE_BPS = 50  # 0.5%


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
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": amount_atomic,
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
                "quoteResponse": quote,
                "userPublicKey": user_pubkey,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("swapTransaction")
    except Exception as exc:
        print(f"[Jupiter] _get_swap_transaction error: {exc}")
        return None


def _sign_and_send(
    swap_tx_b64: str,
    keypair,
    rpc_url: str,
) -> Optional[str]:
    """Sign a VersionedTransaction with our keypair and broadcast to RPC."""
    try:
        from solders.transaction import VersionedTransaction  # type: ignore

        raw = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(raw)

        # sign_message signs the serialised message bytes (includes blockhash)
        sig = keypair.sign_message(bytes(tx.message))
        signed_tx = VersionedTransaction([sig], tx.message)
        signed_bytes = bytes(signed_tx)

        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    base64.b64encode(signed_bytes).decode(),
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                        "maxRetries": 3,
                    },
                ],
            },
            timeout=30,
        )
        result = resp.json()
        if "error" in result:
            print(f"[Jupiter] RPC sendTransaction error: {result['error']}")
            return None
        return result.get("result")  # transaction signature
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
    """Swap USDC → SOL via Jupiter."""
    amount_atomic = int(usdc_amount * 10 ** USDC_DECIMALS)
    quote = get_quote(USDC_MINT, SOL_MINT, amount_atomic)
    if not quote:
        return {"success": False, "error": "Quote unavailable"}

    out_sol = int(quote.get("outAmount", 0)) / 10 ** SOL_DECIMALS
    price_impact = float(quote.get("priceImpactPct", 0))

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "input_usdc": usdc_amount,
            "output_sol": out_sol,
            "price_impact_pct": price_impact,
            "tx_signature": "DRY_RUN",
        }

    swap_tx = _get_swap_transaction(quote, str(keypair.pubkey()))
    if not swap_tx:
        return {"success": False, "error": "Failed to build swap transaction"}

    sig = _sign_and_send(swap_tx, keypair, rpc_url)
    if not sig:
        return {"success": False, "error": "Transaction broadcast failed"}

    return {
        "success": True,
        "dry_run": False,
        "input_usdc": usdc_amount,
        "output_sol": out_sol,
        "price_impact_pct": price_impact,
        "tx_signature": sig,
    }


def sell_sol_for_usdc(
    sol_amount: float,
    keypair,
    rpc_url: str,
    dry_run: bool = True,
) -> dict:
    """Swap SOL → USDC via Jupiter."""
    amount_atomic = int(sol_amount * 10 ** SOL_DECIMALS)
    quote = get_quote(SOL_MINT, USDC_MINT, amount_atomic)
    if not quote:
        return {"success": False, "error": "Quote unavailable"}

    out_usdc = int(quote.get("outAmount", 0)) / 10 ** USDC_DECIMALS
    price_impact = float(quote.get("priceImpactPct", 0))

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "input_sol": sol_amount,
            "output_usdc": out_usdc,
            "price_impact_pct": price_impact,
            "tx_signature": "DRY_RUN",
        }

    swap_tx = _get_swap_transaction(quote, str(keypair.pubkey()))
    if not swap_tx:
        return {"success": False, "error": "Failed to build swap transaction"}

    sig = _sign_and_send(swap_tx, keypair, rpc_url)
    if not sig:
        return {"success": False, "error": "Transaction broadcast failed"}

    return {
        "success": True,
        "dry_run": False,
        "input_sol": sol_amount,
        "output_usdc": out_usdc,
        "price_impact_pct": price_impact,
        "tx_signature": sig,
    }
