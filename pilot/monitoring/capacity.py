"""Explicit sustained-paging policy for the pilot's bounded capacity test."""

SWAP_RATE_BYTES = 64 * 1024
SUSTAINED_SECONDS = 60
MAX_SAMPLE_GAP = 45


def swapping(samples):
    """Fail on >=64 KiB/s of swap traffic continuously for >=60 seconds.

    An isolated page-in or reclaim burst is reported but is not sustained paging.
    Missing, reset, non-monotonic or widely spaced samples fail closed.
    """
    if len(samples) < 2:
        return {"valid": False, "no_sustained_swap": False}
    streak = longest = peak = 0.0
    total = 0
    valid = True
    for before, after in zip(samples, samples[1:]):
        elapsed = after["time"] - before["time"]
        deltas = [after["swap"][k] - before["swap"][k] for k in ["pswpin", "pswpout"]]
        page_size = after.get("page_size")
        if (
            elapsed <= 0
            or elapsed > MAX_SAMPLE_GAP
            or min(deltas) < 0
            or not page_size
            or page_size != before.get("page_size")
        ):
            valid = False
            continue
        traffic = sum(deltas) * page_size
        total += traffic
        rate = traffic / elapsed
        peak = max(peak, rate)
        streak = streak + elapsed if rate >= SWAP_RATE_BYTES else 0.0
        longest = max(longest, streak)
    return {
        "valid": valid,
        "no_sustained_swap": valid and longest < SUSTAINED_SECONDS,
        "total_bytes": total,
        "peak_bytes_per_second": peak,
        "longest_sustained_seconds": longest,
        "policy": {
            "bytes_per_second": SWAP_RATE_BYTES,
            "seconds": SUSTAINED_SECONDS,
            "max_sample_gap_seconds": MAX_SAMPLE_GAP,
        },
    }
