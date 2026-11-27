from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from throttle import limits

from .forms import LoginForm, RegisterForm

CREATE_POLL_PATH = "/anket/olustur/"


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("polls:index")

    if request.method == "POST" and limits.over_limit(request, limits.REGISTER_IP):
        form = RegisterForm(initial={"username": request.POST.get("username", "")})
        return render(
            request,
            "accounts/register.html",
            {"form": form, "throttle_message": limits.REGISTER_IP.message},
            status=429,
        )

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Hoş geldin, @{user.username}")
        return redirect("polls:index")

    return render(request, "accounts/register.html", {"form": form})


class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _rules(self):
        username = self.request.POST.get("username", "").strip()
        return ((limits.LOGIN_IP, ()), (limits.LOGIN_USER, (username,)))

    def post(self, request, *args, **kwargs):
        # Count first, then decide: the atomic increment means parallel requests cannot all
        # slip past a check before any of them is recorded. Blocked requests are rejected
        # before authenticating, so they give no signal about the password.
        over = [rule for rule, parts in self._rules() if limits.over_limit(request, rule, *parts)]
        if over:
            form = self.get_form_class()(request, initial={"username": request.POST.get("username", "")})
            context = self.get_context_data(form=form, throttle_message=over[0].message)
            return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        # Only failed attempts should count; give this one back.
        for rule, parts in self._rules():
            limits.undo(self.request, rule, *parts)
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["needs_login_to_create"] = self.get_redirect_url().startswith(CREATE_POLL_PATH)
        return context
