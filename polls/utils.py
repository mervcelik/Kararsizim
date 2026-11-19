import secrets
import string

BASE62_ALPHABET = string.ascii_letters + string.digits
PUBLIC_ID_LENGTH = 10


def generate_public_id():
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(PUBLIC_ID_LENGTH))


def compute_percentages(counts):
    """Rounded percentages that always sum to 100; the rounding drift goes to the largest option."""
    total = sum(counts)
    if total == 0:
        return [0] * len(counts)
    percents = [round(count * 100 / total) for count in counts]
    drift = 100 - sum(percents)
    if drift:
        largest = max(range(len(counts)), key=lambda i: counts[i])
        percents[largest] += drift
    return percents


def decision_badge(percents, total_votes):
    """Returns (kind, text) for the indecision badge based on the gap between the top two options."""
    if total_votes == 0:
        return "first", "İlk oyu sen ver"
    top = sorted(percents, reverse=True)
    gap = top[0] - (top[1] if len(top) > 1 else 0)
    if gap <= 5:
        return "tie", "Kalabalık da kararsız"
    if gap <= 20:
        return "lead", "Az farkla önde"
    return "clear", "Karar net"
