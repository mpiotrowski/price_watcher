"""Price history chart rendering — headless Agg backend, no display required."""
from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from db import PriceSnapshot

_COLOR = "#1976D2"


def render_price_chart(
    snapshots: list[PriceSnapshot],
    product_name: str,
    store_name: str,
    days: int,
) -> bytes:
    times = [s.checked_at for s in snapshots]
    prices = [s.price for s in snapshots]
    in_stock_flags = [s.in_stock for s in snapshots]

    fig, ax = plt.subplots(figsize=(10, 4))

    # Draw solid segments when in stock, dotted when out of stock.
    # Each segment extends one point into the next segment for visual continuity.
    i = 0
    n = len(snapshots)
    while i < n:
        status = in_stock_flags[i]
        j = i + 1
        while j < n and in_stock_flags[j] == status:
            j += 1
        overlap = 1 if j < n else 0
        seg_t = times[i : j + overlap]
        seg_p = prices[i : j + overlap]
        valid = [(t, p) for t, p in zip(seg_t, seg_p) if p is not None]
        if len(valid) >= 2:
            vt, vp = zip(*valid)
            ax.plot(vt, vp, "-" if status else ":", color=_COLOR, linewidth=2)
        i = j

    # Label the first priced snapshot and each point where price changes.
    prev_price: float | None = None
    for snap in snapshots:
        if snap.price is None:
            continue
        if prev_price is None or snap.price != prev_price:
            ax.annotate(
                f"${snap.price:.2f}",
                xy=(snap.checked_at, snap.price),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color="#333333",
            )
            ax.plot(snap.checked_at, snap.price, "o", color=_COLOR, markersize=5)
            prev_price = snap.price

    ax.legend(
        handles=[
            Line2D([0], [0], color=_COLOR, linewidth=2, linestyle="-", label="In stock"),
            Line2D([0], [0], color=_COLOR, linewidth=2, linestyle=":", label="Out of stock"),
        ],
        fontsize=8,
        loc="upper right",
    )

    ax.set_title(
        f"{product_name}  ·  {store_name}  ·  last {days} day{'s' if days != 1 else ''}",
        fontsize=10,
    )
    ax.set_ylabel("Price (USD)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.2f}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3, linestyle="--")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
