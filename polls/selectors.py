from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.timesince import timesince

from .models import Poll, Vote
from .utils import compute_percentages, decision_badge

PAGE_SIZE = 20
POPULAR_WINDOW = timedelta(days=7)
DAILY_POLL_LIMIT = 10

FEED_TABS = {
    "yeni": "Yeni",
    "populer": "Popüler",
    "kapanan": "Kapananlar",
}
DEFAULT_TAB = "yeni"


@dataclass
class OptionView:
    id: int
    text: str
    position: int
    count: int
    percent: int
    is_voted: bool


@dataclass
class PollView:
    poll: Poll
    options: list
    show_results: bool
    badge_kind: str
    badge_text: str
    relative_time: str
    voted_option_id: int | None
    is_owner: bool
    can_vote: bool


def _open_q(now):
    return Q(status=Poll.Status.ACTIVE) & (Q(closes_at__isnull=True) | Q(closes_at__gt=now))


def _base_queryset():
    return Poll.objects.select_related("author").prefetch_related("options")


def feed_queryset(tab):
    now = timezone.now()
    qs = _base_queryset()
    if tab == "kapanan":
        return qs.exclude(_open_q(now)).order_by("-created_at")
    qs = qs.filter(_open_q(now))
    if tab == "populer":
        return qs.annotate(
            recent_votes=Count("votes", filter=Q(votes__created_at__gte=now - POPULAR_WINDOW))
        ).order_by("-recent_votes", "-created_at")
    return qs.order_by("-created_at")


def paginate(queryset, page_number):
    return Paginator(queryset, PAGE_SIZE).get_page(page_number)


def get_poll(public_id):
    return _base_queryset().filter(public_id=public_id).first()


def get_profile_user(username):
    return get_user_model().objects.filter(username__iexact=username).first()


def profile_queryset(user):
    return _base_queryset().filter(author=user).order_by("-created_at")


def profile_stats(user):
    return Poll.objects.filter(author=user).aggregate(poll_count=Count("id"), vote_count=Sum("total_votes"))


def polls_created_today(user):
    start_of_day = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return Poll.objects.filter(author=user, created_at__gte=start_of_day).count()


def voted_options(request, polls):
    """Maps poll id → option id the current visitor voted for (logged-in user or anonymous voter_key)."""
    poll_ids = [poll.pk for poll in polls]
    if not poll_ids:
        return {}
    voter_key = request.session.get("voter_key")
    who = Q()
    if request.user.is_authenticated:
        who |= Q(user=request.user)
    if voter_key:
        who |= Q(voter_key=voter_key, user__isnull=True)
    if not who:
        return {}
    return dict(Vote.objects.filter(who, poll_id__in=poll_ids).values_list("poll_id", "option_id"))


def relative_time(value):
    if timezone.now() - value < timedelta(minutes=1):
        return "az önce"
    return f"{timesince(value, depth=1)} önce"


def build_poll_view(poll, request, voted_option_id=None):
    options = list(poll.options.all())
    counts = [option.vote_count for option in options]
    percents = compute_percentages(counts)
    is_owner = request.user.is_authenticated and poll.author_id == request.user.pk
    show_results = voted_option_id is not None or not poll.is_open or is_owner
    badge_kind, badge_text = decision_badge(percents, poll.total_votes)
    if not show_results and poll.total_votes > 0:
        badge_kind, badge_text = "hidden", "Oy ver, sonucu gör"
    return PollView(
        poll=poll,
        options=[
            OptionView(
                id=option.pk,
                text=option.text,
                position=option.position,
                count=option.vote_count,
                percent=percent,
                is_voted=option.pk == voted_option_id,
            )
            for option, percent in zip(options, percents)
        ],
        show_results=show_results,
        badge_kind=badge_kind,
        badge_text=badge_text,
        relative_time=relative_time(poll.created_at),
        voted_option_id=voted_option_id,
        is_owner=is_owner,
        can_vote=poll.is_open and voted_option_id is None,
    )


def results_payload(view):
    """JSON for the results endpoint. Counts stay hidden until the visitor may see results."""
    visible = view.show_results
    return {
        "total": view.poll.total_votes,
        "results_visible": visible,
        "options": [
            {
                "id": option.id,
                "text": option.text,
                "position": option.position,
                "count": option.count if visible else None,
                "percent": option.percent if visible else None,
            }
            for option in view.options
        ],
        "voted_option_id": view.voted_option_id,
        "is_open": view.poll.is_open,
        "badge": {"kind": view.badge_kind, "text": view.badge_text},
    }


def build_poll_views(polls, request):
    polls = list(polls)
    voted = voted_options(request, polls)
    return [build_poll_view(poll, request, voted.get(poll.pk)) for poll in polls]
