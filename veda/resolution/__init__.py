"""Engineering-aware activity resolution helpers.

The resolution layer is intentionally separate from retrieval and from schedule
mutation.  Retrieval finds plausible activities; this package interprets field
events, injects hierarchy/time/network context, estimates risk, and tells the
agent which tools are worth invoking next.
"""
