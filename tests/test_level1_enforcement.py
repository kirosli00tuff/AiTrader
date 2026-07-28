"""Every Level 1 key must be enforced, and the loss brake must be releasable.

WHY THIS EXISTS. Six Level 1 keys have now been found that were parsed,
range-validated, printed in the startup banner, and enforced NOWHERE:
`whale_position_scale_cap` and `dnn_position_scale_cap` (removed 2026-07-18),
`max_trade_notional_cap_pct` and `default_position_sizing_method` (removed
2026-07-27), and the `in_cooldown` / `cooldown_until_ts` pair, which had a
declaration and a read and no assignment anywhere in the tree.

The defect recurs because a key that reads plausibly in config and prints at
startup looks enforced from every angle except the one that matters. **A
configuration key claiming a safety property must be enforced or removed, never
printed as though live.** The guard below makes that structural rather than a
habit: a seventh unenforced key fails the suite instead of shipping quietly.

The second half covers the consecutive-loss brake's RESET. The brake cleared
only on a win, and it refuses the entries that could produce one, so once
tripped it was an ABSORBING STATE. The record: 1,578 of 1,912 blocked_trades
rows, 82.5 percent of every RiskGate refusal ever recorded, read
max_consecutive_losses. The offline replay could NOT exercise the fix, so it is
exercised here against a real engine run instead.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_HPP = os.path.join(REPO, "config", "config.hpp")
ENGINE = os.path.join(REPO, "build", "mal_engine")

# Where a Level 1 value may legitimately be enforced. `learning/adaptive.cpp` is
# deliberately EXCLUDED: it compares proposed values against hard limits to
# forbid weakening, which is the invariant, not a gate on an order.
ENFORCEMENT_SITES = (
    "risk/risk_gate.cpp",
    "core/engine.cpp",
    "core/backtest_main.cpp",
    "account_manager/account_manager.cpp",
    "execution/execution.cpp",
    "signal_engine/factor_engine.cpp",
)


def _struct_fields(name: str) -> list[str]:
    body = re.search(rf"struct {name} \{{(.*?)\n\}};",
                     open(CFG_HPP).read(), re.S)
    assert body, f"{name} not found in config.hpp"
    return re.findall(r"^\s*(?:double|int|bool|std::string)\s+(\w+)\s*=",
                      body.group(1), re.M)


def _enforcement_sites(key: str) -> list[str]:
    hits = []
    for rel in ENFORCEMENT_SITES:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if key in line:
                hits.append(f"{rel}:{i}")
    return hits


# ---- the guard --------------------------------------------------------------

def test_every_level1_key_is_enforced_somewhere():
    """THE GUARD. A key in RiskConfig or SizingConfig that no enforcement site
    references is claiming a safety property the code does not provide. Six
    such keys have shipped. This is how a seventh gets caught."""
    unenforced = []
    for struct in ("RiskConfig", "SizingConfig"):
        for key in _struct_fields(struct):
            if not _enforcement_sites(key):
                unenforced.append(f"{struct}.{key}")
    assert not unenforced, (
        "Level 1 keys parsed but enforced NOWHERE: " + ", ".join(unenforced) +
        ". Enforce it or remove it. A key that has never fired protects "
        "nothing, and printing it at startup tells the operator a limit "
        "exists that does not.")


def test_the_removed_keys_stay_removed():
    """MUTATION GUARD. Re-adding either removed key without wiring it
    reintroduces the exact defect."""
    hpp = open(CFG_HPP).read()
    body = re.search(r"struct RiskConfig \{(.*?)\n\};", hpp, re.S).group(1)
    assert "max_trade_notional_cap_pct" not in re.sub(r"//.*", "", body), (
        "max_trade_notional_cap_pct is back in RiskConfig; it was removed "
        "2026-07-27 for being enforced nowhere")
    sizing = re.search(r"struct SizingConfig \{(.*?)\n\};", hpp, re.S).group(1)
    assert "default_position_sizing_method" not in re.sub(r"//.*", "", sizing)


def test_no_removed_key_still_prints_at_startup():
    """Whatever is removed must leave the banner too, so the operator is not
    told a limit exists that does not."""
    main = open(os.path.join(REPO, "core", "main.cpp")).read()
    for gone in ("max_trade_notional_cap_pct", "default_position_sizing_method",
                 "whale_position_scale_cap", "dnn_position_scale_cap"):
        assert gone not in main, f"{gone} still reaches the startup banner"


# ---- the brake reset --------------------------------------------------------

def test_the_loss_brake_has_a_release_path():
    """The brake cleared only on a win, and it refuses the entries that could
    produce one. Without a release it is an absorbing state."""
    src = open(os.path.join(REPO, "core", "engine.cpp")).read()
    assert "release_loss_brake_if_due" in src
    assert "note_loss_brake" in src
    entry = src.index("---------- ENTRY path")
    release = src.index("release_loss_brake_if_due(now_epoch)")
    assert release < entry, (
        "the brake release moved below the entry marker; a released brake "
        "would take effect one bar late")


def test_the_release_uses_the_same_key_the_harness_uses():
    """THE DIVERGENCE THIS CLOSES. backtest_main.cpp applies
    cooldown_minutes_after_loss_breach as this reset and its comment asserts
    the live engine does the same. It did not, so every backtest ran under a
    laxer brake than live."""
    engine = open(os.path.join(REPO, "core", "engine.cpp")).read()
    harness = open(os.path.join(REPO, "core", "backtest_main.cpp")).read()
    key = "cooldown_minutes_after_loss_breach"
    assert key in engine, "the live engine does not use the harness's key"
    assert key in harness


@pytest.mark.skipif(not os.path.exists(ENGINE), reason="engine not built")
def test_the_brake_actually_releases_in_a_real_run(tmp_path):
    """BEHAVIOURAL, and it exists because the REPLAY COULD NOT EXERCISE THIS.

    A default-config synthetic run produces 5 closed losses against a cap of 6,
    one short of tripping, so nothing releases and the replay proves nothing.
    Rather than assert the change is safe on that basis, which is the mistake
    the sizing session was criticised for, this tightens the cap in a temp
    config so the brake genuinely trips, and asserts it then releases.
    """
    cfg = str(tmp_path / "tight.yaml")
    src = open(os.path.join(REPO, "config", "default_config.yaml")).read()
    src = re.sub(r"^  max_consecutive_losses: \d+",
                 "  max_consecutive_losses: 2", src, count=1, flags=re.M)
    src = re.sub(r"^  cooldown_minutes_after_loss_breach: \d+",
                 "  cooldown_minutes_after_loss_breach: 5", src, count=1,
                 flags=re.M)
    open(cfg, "w").write(src)
    db = str(tmp_path / "brake.db")
    subprocess.run(
        [ENGINE, "--db", db, "--config", cfg, "--iterations", "6000",
         "--feed-mode", "synthetic_regimes", "--clock-mode", "simulated"],
        capture_output=True, text=True, cwd=REPO, timeout=900)
    conn = sqlite3.connect(db)
    released = conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind='loss_brake_released'"
    ).fetchone()[0]
    assert released > 0, (
        "the brake tripped but never released: it is still an absorbing state")
