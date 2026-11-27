from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from throttle import limits

from . import selectors, services
from .forms import PollForm
from .models import MAX_OPTIONS, MIN_OPTIONS
from .utils import get_voter_key, remember_vote


def _get_poll_or_404(public_id):
    poll = selectors.get_poll(public_id)
    if poll is None:
        raise Http404("Anket bulunamadı.")
    return poll


def _wants_json(request):
    return (
        "application/json" in request.headers.get("Accept", "")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _poll_view(request, poll):
    return selectors.build_poll_views([poll], request)[0]


def index(request):
    tab = request.GET.get("sekme", selectors.DEFAULT_TAB)
    if tab not in selectors.FEED_TABS:
        tab = selectors.DEFAULT_TAB
    page = selectors.paginate(selectors.feed_queryset(tab), request.GET.get("page"))
    return render(request, "polls/index.html", {
        "tabs": selectors.FEED_TABS,
        "active_tab": tab,
        "page": page,
        "cards": selectors.build_poll_views(page.object_list, request),
    })


def detail(request, public_id):
    poll = _get_poll_or_404(public_id)
    return render(request, "polls/detail.html", {"card": _poll_view(request, poll), "poll": poll})


def _check_anonymous_vote_limits(request, poll):
    # A fresh cookie is a fresh anonymous voter, so the network is the only brake on
    # ballot stuffing. Logged-in users are already limited by the per-user constraint.
    for rule, parts in ((limits.VOTE_PER_POLL, (poll.pk,)), (limits.VOTE_GLOBAL, ())):
        if limits.over_limit(request, rule, *parts):
            raise services.RateLimited(rule.message)


@require_POST
def vote(request, public_id):
    poll = _get_poll_or_404(public_id)
    user = request.user if request.user.is_authenticated else None
    try:
        if user is None:
            _check_anonymous_vote_limits(request, poll)
        services.cast_vote(
            poll=poll,
            option_id=request.POST.get("option_id"),
            user=user,
            voter_key=get_voter_key(request),
        )
    except services.VoteError as error:
        status, message, ok = error.status, error.message, False
    else:
        remember_vote(request, poll.pk)
        status, message, ok = 200, "Oyun kaydedildi.", True

    if _wants_json(request):
        # The owner may delete the poll mid-request; fall back to the copy we already have.
        fresh = selectors.get_poll(public_id) or poll
        return JsonResponse(
            {"ok": ok, "message": message, "results": selectors.results_payload(_poll_view(request, fresh))},
            status=status,
        )
    (messages.success if ok else messages.error)(request, message)
    return redirect(poll)


@require_GET
def results(request, public_id):
    poll = _get_poll_or_404(public_id)
    return JsonResponse(selectors.results_payload(_poll_view(request, poll)))


@login_required
@require_POST
def close(request, public_id):
    poll = _get_poll_or_404(public_id)
    if poll.author_id != request.user.pk:
        return HttpResponseForbidden("Bu anketi sadece sahibi kapatabilir.")
    services.close_poll(poll)
    messages.success(request, "Anket kapatıldı. Sonuçlar artık herkese açık.")
    return redirect(poll)


@login_required
@require_http_methods(["GET", "POST"])
def delete(request, public_id):
    poll = _get_poll_or_404(public_id)
    if poll.author_id != request.user.pk:
        return HttpResponseForbidden("Bu anketi sadece sahibi silebilir.")
    if request.method == "POST":
        services.delete_poll(poll)
        messages.success(request, "Anket silindi.")
        return redirect("polls:profile", username=request.user.username)
    return render(request, "polls/delete_confirm.html", {"poll": poll})


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = PollForm(
        request.POST or None,
        daily_count=selectors.polls_created_today(request.user) if request.method == "POST" else 0,
        daily_limit=selectors.DAILY_POLL_LIMIT,
    )
    if request.method == "POST" and form.is_valid():
        poll = services.create_poll(
            author=request.user,
            question=form.cleaned_data["question"],
            description=form.cleaned_data["description"],
            options=form.cleaned_data["options"],
        )
        messages.success(request, "Anketin yayında.")
        return redirect(poll)
    return render(request, "polls/create.html", {
        "form": form,
        "min_options": MIN_OPTIONS,
        "max_options": MAX_OPTIONS,
    })


def profile(request, username):
    profile_user = selectors.get_profile_user(username)
    if profile_user is None:
        raise Http404("Kullanıcı bulunamadı.")
    page = selectors.paginate(selectors.profile_queryset(profile_user), request.GET.get("page"))
    stats = selectors.profile_stats(profile_user)
    return render(request, "polls/profile.html", {
        "profile_username": profile_user.username,
        "poll_count": stats["poll_count"] or 0,
        "vote_count": stats["vote_count"] or 0,
        "page": page,
        "cards": selectors.build_poll_views(page.object_list, request),
    })
