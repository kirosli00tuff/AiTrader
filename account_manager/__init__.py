"""Account / venue credential handling (Python side).

The C++ `account_manager` owns the per-venue runtime state machine; this Python
package owns the encrypted-at-rest credential store + the single runtime
resolver (in-app saved credential first, then environment / .env fallback).
"""
