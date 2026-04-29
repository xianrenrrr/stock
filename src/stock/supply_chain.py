"""stock.supply_chain -- AI industry supply chain knowledge base."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

CHAIN_PATH: str = "data/ai_supply_chain.yaml"


class Player(BaseModel):
    """One company entry in a supply-chain sublayer."""

    ticker: str
    name: str
    country: str = ""
    role: str = ""
    notes: str = ""


class Sublayer(BaseModel):
    """A named slice inside a top-level supply-chain layer."""

    name: str
    function: str = ""
    notes: str = ""
    materials: list[str] = []
    players: list[Player] = []


class Layer(BaseModel):
    """A top-level layer of the AI supply chain (raw_materials, equipment, ...)."""

    layer: str
    function: str = ""
    sublayers: list[Sublayer] = []

    @property
    def all_players(self) -> list[Player]:
        """Return every player across every sublayer in this layer."""
        out: list[Player] = []
        for sub in self.sublayers:
            out.extend(sub.players)
        return out


class SupplyChain(BaseModel):
    """Whole AI supply-chain map."""

    layers: list[Layer]

    def find_layer(self, name: str) -> Layer | None:
        """Return the first layer whose `layer` field matches name, case-insensitive."""
        target = name.strip().lower()
        for layer in self.layers:
            if layer.layer.lower() == target:
                return layer
        return None

    def find_player(self, ticker: str) -> tuple[Layer, Sublayer, Player] | None:
        """Reverse-lookup a ticker. Returns (layer, sublayer, player) or None."""
        target = ticker.strip().upper()
        for layer in self.layers:
            for sub in layer.sublayers:
                for p in sub.players:
                    if p.ticker.upper() == target:
                        return layer, sub, p
        return None

    def search(self, query: str) -> list[tuple[Layer, Sublayer, Player]]:
        """Free-text search across player names, roles, and notes."""
        q = query.strip().lower()
        if not q:
            return []
        matches: list[tuple[Layer, Sublayer, Player]] = []
        for layer in self.layers:
            for sub in layer.sublayers:
                for p in sub.players:
                    haystack = " ".join([p.name, p.role, p.notes, sub.name, sub.function]).lower()
                    if q in haystack:
                        matches.append((layer, sub, p))
        return matches


@lru_cache(maxsize=1)
def load_chain(path: str | None = None) -> SupplyChain:
    """Load and cache the supply chain map from YAML."""
    chain_path = Path(path or CHAIN_PATH)
    if not chain_path.exists():
        raise FileNotFoundError(f"Supply chain map not found at {chain_path}")

    raw: dict[str, Any] = yaml.safe_load(chain_path.read_text(encoding="utf-8")) or {}
    layers_raw = raw.get("layers") or []

    # Hand-validate so unknown YAML keys don't blow up the pydantic strict path
    layers: list[Layer] = []
    for layer_raw in layers_raw:
        sublayers: list[Sublayer] = []
        for sub_raw in layer_raw.get("sublayers") or []:
            players_raw = sub_raw.get("players") or []
            players = [Player(**p) for p in players_raw if isinstance(p, dict)]
            sublayers.append(
                Sublayer(
                    name=str(sub_raw.get("name", "")),
                    function=str(sub_raw.get("function", "")),
                    notes=str(sub_raw.get("notes", "")),
                    materials=[str(m) for m in (sub_raw.get("materials") or [])],
                    players=players,
                )
            )
        layers.append(
            Layer(
                layer=str(layer_raw.get("layer", "")),
                function=str(layer_raw.get("function", "")),
                sublayers=sublayers,
            )
        )
    return SupplyChain(layers=layers)


def pick_focus_layer(chain: SupplyChain, *, seed_iso: str | None = None) -> Layer:
    """Rotate deterministically through layers based on day-of-year.

    Each calendar day picks the same layer, so morning + evening pushes stay coherent.
    """
    if not chain.layers:
        raise RuntimeError("Supply chain has no layers")

    now = datetime.fromisoformat(seed_iso) if seed_iso else datetime.now(timezone.utc)
    doy = now.timetuple().tm_yday
    idx = (doy - 1) % len(chain.layers)
    return chain.layers[idx]


def format_layer_players(layer: Layer, *, limit_per_sublayer: int = 4) -> str:
    """Render a layer's sublayers + players as a compact text block for prompts."""
    if not layer.sublayers:
        return f"(layer {layer.layer} has no sublayers)"

    lines: list[str] = []
    for sub in layer.sublayers:
        header = f"### {sub.name} — {sub.function}"
        lines.append(header)
        if sub.notes:
            lines.append(f"  note: {sub.notes}")
        if not sub.players:
            lines.append("  (no players catalogued)")
            continue
        for p in sub.players[:limit_per_sublayer]:
            country = f" ({p.country})" if p.country else ""
            lines.append(f"  - {p.ticker}{country} — {p.name}: {p.role}")
        if len(sub.players) > limit_per_sublayer:
            lines.append(f"  ...and {len(sub.players) - limit_per_sublayer} more")
    return "\n".join(lines)


def format_cross_layer_sample(
    chain: SupplyChain, *, exclude_layer: str | None = None, per_layer: int = 2
) -> str:
    """Pick a small cross-layer sample so the model sees the whole chain context."""
    lines: list[str] = []
    for layer in chain.layers:
        if exclude_layer and layer.layer == exclude_layer:
            continue
        sample: list[str] = []
        for sub in layer.sublayers:
            for p in sub.players[:1]:
                sample.append(f"{p.ticker} ({sub.name})")
                if len(sample) >= per_layer:
                    break
            if len(sample) >= per_layer:
                break
        if sample:
            lines.append(f"- **{layer.layer}**: {', '.join(sample)} -- {layer.function}")
    return "\n".join(lines) if lines else "(no cross-layer sample)"


def gather_chain_context(
    chain: SupplyChain,
    *,
    topic: str,
) -> str:
    """Build a chain-context block for a deep-dive on a topic.

    Topic can match a layer name, a sublayer name, a ticker, or a free-text query.
    """
    target = topic.strip()

    # Direct layer hit
    layer = chain.find_layer(target)
    if layer is not None:
        return f"## Layer: {layer.layer}\nfunction: {layer.function}\n\n{format_layer_players(layer)}"

    # Direct ticker hit
    if len(target) <= 12:
        hit = chain.find_player(target.upper())
        if hit is not None:
            layer_obj, sub, _ = hit
            return (
                f"## Player match — layer {layer_obj.layer} / sublayer {sub.name}\n"
                f"{format_layer_players(layer_obj)}"
            )

    # Sublayer hit — search by sublayer name
    target_lower = target.lower()
    for layer_obj in chain.layers:
        for sub in layer_obj.sublayers:
            if sub.name.lower() == target_lower or target_lower in sub.name.lower():
                return (
                    f"## Sublayer match — layer {layer_obj.layer} / sublayer {sub.name}\n"
                    f"function: {sub.function}\n"
                    f"notes: {sub.notes}\n\n"
                    + "\n".join(
                        f"- {p.ticker} ({p.country}) — {p.name}: {p.role}"
                        for p in sub.players
                    )
                )

    # Fall back to free-text search across all players
    matches = chain.search(target)
    if not matches:
        return f"(no supply-chain entries matched topic '{topic}')"
    lines: list[str] = [f"## Free-text matches for '{topic}'"]
    for layer_obj, sub, p in matches[:25]:
        lines.append(
            f"- {p.ticker} ({p.country}) — {p.name}: {p.role}"
            f"  [layer={layer_obj.layer}, sublayer={sub.name}]"
        )
    return "\n".join(lines)


def list_layer_names(chain: SupplyChain) -> list[str]:
    """Return the ordered list of top-level layer names."""
    return [layer.layer for layer in chain.layers]


def chain_summary_for_log(chain: SupplyChain) -> dict[str, int]:
    """Diagnostic counts (used by `stock chain` CLI)."""
    layer_count = len(chain.layers)
    sublayer_count = sum(len(layer.sublayers) for layer in chain.layers)
    player_count = sum(len(layer.all_players) for layer in chain.layers)
    return {
        "layers": layer_count,
        "sublayers": sublayer_count,
        "players": player_count,
    }


def get_chain_for_request(_conn: sqlite3.Connection | None = None) -> SupplyChain:
    """Wrapper that exists so callers can pass a connection in the future without API churn."""
    return load_chain()
