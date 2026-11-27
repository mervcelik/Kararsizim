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

    if request.method == "POST" and limits.hit(request, limits.REGISTER_IP) > limits.REGISTER_IP.limit:
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
        # Checked before authenticating, so a blocked attacker gets no password signal at all.
        for rule, parts in self._rules():
            if limits.is_limited(request, rule, *parts):
                form = self.get_form_class()(request, initial={"username": request.POST.get("username", "")})
                context = self.get_context_data(form=form, throttle_message=rule.message)
                return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        for rule, parts in self._rules():
            limits.hit(self.request, rule, *parts)
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["needs_login_to_create"] = self.get_redirect_url().startswith(CREATE_POLL_PATH)
        return context
