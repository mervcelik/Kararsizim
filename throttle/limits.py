"""Fixed-window rate limits stored in the database.

Vercel may serve every request from a different instance, so an in-memory counter would
not be shared. Keys are HMACs of (scope, IP, extra parts); raw IPs are never stored.
"""

import ipaddress
import random
import time
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils.crypto import salted_hmac

from .models import Hit

CLEANUP_PROBABILITY = 0.01
CLEANUP_AGE_SECONDS = 24 * 3600


@dataclass(frozen=True)
class Rule:
    scope: str
    limit: int  # IPv4: one address is often shared (mobile CGNAT, school Wi-Fi), so keep it loose
    period: int  # seconds
    message: str
    per_ip: bool = True  # False: one shared counter for the parts, whatever the network
    limit_v6: int | None = None  # IPv6 /64: usually one home or device, so it can be tighter


VOTE_PER_POLL = Rule(
    "vote-poll", 50, 3600, "Bu ağdan bu ankete çok fazla oy geldi. Biraz sonra tekrar dene.", limit_v6=10
)
VOTE_GLOBAL = Rule("vote", 300, 3600, "Çok hızlı oy veriyorsun. Biraz sonra tekrar dene.", limit_v6=100)
LOGIN_IP = Rule("login-ip", 100, 900, "Çok fazla hatalı giriş denemesi. 15 dakika sonra tekrar dene.", limit_v6=30)
# Not per IP: otherwise a botnet gets 10 guesses per address against the same account.
# The cost is that anyone can lock an account's logins for 15 minutes.
LOGIN_USER = Rule(
    "login-user", 10, 900, "Bu hesap için çok fazla hatalı deneme yapıldı. 15 dakika sonra tekrar dene.", per_ip=False
)
REGISTER_IP = Rule(
    "register", 30, 3600, "Bu ağdan çok fazla kayıt denemesi yapıldı. Bir saat sonra tekrar dene.", limit_v6=10
)


def client_ip(request):
    # Vercel sets x-vercel-forwarded-for itself and drops client-supplied values, so it
    # cannot be spoofed there. Anywhere else, fall back to the socket address.
    forwarded = request.headers.get("x-vercel-forwarded-for", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


def client_network(request):
    """(network id, is_ipv6). IPv6 is grouped by /64, since one subscriber can rotate freely inside it."""
    raw = client_ip(request)
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return raw, False
    if address.version == 6 and address.ipv4_mapped:
        return str(address.ipv4_mapped), False
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False)), True
    return str(address), False


def limit_for(request, rule):
    if not rule.per_ip:
        return rule.limit
    _, is_v6 = client_network(request)
    return rule.limit_v6 if is_v6 and rule.limit_v6 is not None else rule.limit


def _key(request, rule, parts):
    network = client_network(request)[0] if rule.per_ip else "*"
    value = "|".join([rule.scope, network, *(str(part).lower() for part in parts)])
    return salted_hmac("throttle", value, algorithm="sha256").hexdigest()


def _window(rule):
    """Start of the current window as a Unix timestamp, comparable across rules."""
    now = int(time.time())
    return now - now % rule.period


def _enabled():
    return getattr(settings, "RATE_LIMITS_ENABLED", True)


def count(request, rule, *parts):
    if not _enabled():
        return 0
    hit = Hit.objects.filter(key=_key(request, rule, parts), window=_window(rule)).only("count").first()
    return hit.count if hit else 0


def is_limited(request, rule, *parts):
    return _enabled() and count(request, rule, *parts) >= limit_for(request, rule)


def over_limit(request, rule, *parts):
    """Counts this attempt first, then reports whether it went over the limit.

    Counting before deciding keeps parallel requests from all slipping past the check.
    """
    return _enabled() and hit(request, rule, *parts) > limit_for(request, rule)


def hit(request, rule, *parts):
    """Records one attempt and returns the count in the current window, including this one."""
    if not _enabled():
        return 0
    key, window = _key(request, rule, parts), _window(rule)
    with transaction.atomic():
        Hit.objects.get_or_create(key=key, window=window)
        Hit.objects.filter(key=key, window=window).update(count=F("count") + 1)
    if random.random() < CLEANUP_PROBABILITY:
        _cleanup()
    return Hit.objects.filter(key=key, window=window).values_list("count", flat=True).first() or 0


def undo(request, rule, *parts):
    """Takes back one attempt in the current window, e.g. after a successful login."""
    if not _enabled():
        return
    Hit.objects.filter(key=_key(request, rule, parts), window=_window(rule), count__gt=0).update(
        count=F("count") - 1
    )


def _cleanup():
    Hit.objects.filter(window__lt=int(time.time()) - CLEANUP_AGE_SECONDS).delete()
