from django.contrib import admin
from django.http import HttpResponsePermanentRedirect
from django.templatetags.static import static
from django.urls import include, path


def favicon(request):
    # Browsers and crawlers ask for /favicon.ico regardless of <link rel="icon">.
    # Resolved per request so a hashed static storage can be enabled later.
    return HttpResponsePermanentRedirect(static("img/favicon.svg"))


urlpatterns = [
    path("admin/", admin.site.urls),
    path("favicon.ico", favicon),
    path("", include("accounts.urls")),
    path("", include("polls.urls")),
]
