"""The experiment's own credential and its own exhaustion-latch identity.

WHY THIS EXISTS (Open Question 9, 2026-07-28). Amendment 3 chose
`claude-haiku-4-5` because it is already approved under CLAUDE.md, and recorded
the residual that choice introduced: the experiment would run on
`ANTHROPIC_API_KEY`, the same key behind the council's base-check gate and one
council provider. `llm_consensus.provider_health` latches exhaustion by
provider LABEL because the quota belongs to the API key, so under one shared
key a credit exhaustion caused by any of the three dries all three. A council
run could stop the collector mid-collection and the reverse, and neither would
say why.

THE SEPARATION IS TWO INDEPENDENT THINGS AND BOTH ARE NEEDED.

  1. A DIFFERENT CREDENTIAL. `EXPERIMENT_ANTHROPIC_API_KEY`, resolved through
     the same keystore-then-env precedence every other secret uses. A separate
     key means a separate account balance, which is the only thing that
     actually stops one workload draining the other.

  2. A DIFFERENT LATCH LABEL. `anthropic_experiment`, never `anthropic`. The
     latch is a dict keyed by the lower-cased label, so two labels are two
     entries and `mark_exhausted` on one leaves the other callable. This half
     works even before the operator creates a second key, which is why it is
     not folded into the first.

THERE IS NO SILENT FALLBACK, and that is deliberate. Falling back to
`ANTHROPIC_API_KEY` when the experiment key is absent would restore the exact
coupling this module removes, invisibly. The collector REFUSES to run without
its own key unless the operator passes `--allow-shared-key`, which is loud, is
recorded on every row as `credential_shared = 1`, and leaves the evidence in
the data rather than in a log nobody reads.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # pragma: no cover - the absence branch is exercised by tests
    from account_manager import credentials as _keystore
except Exception:  # noqa: BLE001 - the package must import with no keystore
    _keystore = None  # type: ignore[assignment]

# The latch identity. Distinct from the council's "anthropic" so
# `provider_health.mark_exhausted` records two entries rather than one.
EXPERIMENT_PROVIDER_LABEL = "anthropic_experiment"
COUNCIL_PROVIDER_LABEL = "anthropic"

EXPERIMENT_CREDENTIAL_NAME = "anthropic_experiment_key"
EXPERIMENT_ENV_VAR = "EXPERIMENT_ANTHROPIC_API_KEY"
COUNCIL_ENV_VAR = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class KeyResolution:
    """A resolved key plus how it was resolved. `key` is never logged."""
    key: str | None
    source: str          # "experiment" | "shared_council" | "missing"
    shared: bool         # True only when the council key is being reused
    label: str           # the latch label to use for this key

    @property
    def ok(self) -> bool:
        return bool(self.key)

    def describe(self) -> str:
        """One line for the startup block. Carries no secret."""
        if not self.key:
            return (f"NO KEY: neither {EXPERIMENT_ENV_VAR} nor an in-app "
                    f"{EXPERIMENT_CREDENTIAL_NAME} resolves. The collector "
                    f"refuses to run.")
        if self.shared:
            return (f"SHARED KEY IN USE: fell back to {COUNCIL_ENV_VAR}. A "
                    f"credit exhaustion caused by the council will stop this "
                    f"collector and the reverse. The latch label is still "
                    f"'{self.label}', so the two are counted separately even "
                    f"though the balance is not. Recorded on every row as "
                    f"credential_shared=1.")
        return (f"OWN KEY: resolved {EXPERIMENT_CREDENTIAL_NAME} "
                f"(source {self.source}), latch label '{self.label}'. "
                f"Independent of the council balance.")


def _from_keystore(name: str) -> str | None:
    if _keystore is None:
        return None
    try:
        return _keystore.get_credential(name) or None
    except Exception:  # noqa: BLE001 - a keystore fault must not crash a probe
        return None


def resolve_experiment_key(*, allow_shared: bool = False) -> KeyResolution:
    """Resolve the experiment's key, keystore first then environment.

    `allow_shared` is the ONLY route to the council's key. It is off by default
    so the coupling cannot return by accident.
    """
    own = (_from_keystore(EXPERIMENT_CREDENTIAL_NAME)
           or os.environ.get(EXPERIMENT_ENV_VAR))
    if own:
        return KeyResolution(key=own, source="experiment", shared=False,
                             label=EXPERIMENT_PROVIDER_LABEL)
    if not allow_shared:
        return KeyResolution(key=None, source="missing", shared=False,
                             label=EXPERIMENT_PROVIDER_LABEL)
    council = _from_keystore("anthropic_key") or os.environ.get(COUNCIL_ENV_VAR)
    if council:
        # The LABEL stays the experiment's even on the shared key, so the latch
        # still separates "the collector saw an exhaustion" from "the council
        # saw one". That is the diagnosis a shared balance destroys.
        return KeyResolution(key=council, source="shared_council", shared=True,
                             label=EXPERIMENT_PROVIDER_LABEL)
    return KeyResolution(key=None, source="missing", shared=False,
                         label=EXPERIMENT_PROVIDER_LABEL)


def latch_is_separate() -> bool:
    """Whether the latch treats the experiment and the council as two providers.

    Called by the startup block so the claim is CHECKED at run time rather than
    asserted in a docstring. It latches the experiment label in a scratch
    state, reads both labels back, then restores whatever was there: the latch
    is process state, so a probe must leave it as it found it.
    """
    from llm_consensus import provider_health

    before = provider_health.exhausted_providers()
    try:
        provider_health.reset_exhaustion()
        provider_health.mark_exhausted(EXPERIMENT_PROVIDER_LABEL,
                                       model_id="probe",
                                       detail="separation probe")
        return (provider_health.is_exhausted(EXPERIMENT_PROVIDER_LABEL)
                and not provider_health.is_exhausted(COUNCIL_PROVIDER_LABEL))
    finally:
        provider_health.reset_exhaustion()
        for entry in before.values():
            provider_health.mark_exhausted(entry["label"],
                                           model_id=entry.get("model_id", ""),
                                           detail=entry.get("detail", ""))
