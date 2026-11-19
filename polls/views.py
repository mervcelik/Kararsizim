from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import selectors, services
from .forms import PollForm
from .models import MAX_OPTIONS, MIN_OPTIONS


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
    poll = selectors.get_poll(public_id)
    if poll is None:
        raise Http404("Anket bulunamadı.")
    view = selectors.build_poll_views([poll], request)[0]
    return render(request, "polls/detail.html", {"card": view, "poll": poll})


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
