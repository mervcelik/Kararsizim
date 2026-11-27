import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings

from polls.services import create_poll
from polls.models import Vote

from . import limits
from .models import Hit

User = get_user_model()
PASSWORD = "kararsiz-Test-2026"


def vercel_client(ip):
    return Client(HTTP_X_VERCEL_FORWARDED_FOR=ip)


class LimitsUnitTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/", REMOTE_ADDR="203.0.113.7")

    def test_counts_per_key_and_never_stores_raw_ip(self):
        self.assertEqual(limits.hit(self.request, limits.LOGIN_USER, "Ayse_K"), 1)
        self.assertEqual(limits.hit(self.request, limits.LOGIN_USER, "ayse_k"), 2)  # case-insensitive
        self.assertEqual(limits.hit(self.request, limits.LOGIN_USER, "mert42"), 1)
        keys = list(Hit.objects.values_list("key", flat=True))
        self.assertTrue(all(len(key) == 64 and "203.0.113.7" not in key for key in keys))

    def test_vercel_header_wins_over_socket_address(self):
        request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_VERCEL_FORWARDED_FOR="198.51.100.9, 10.0.0.1")
        self.assertEqual(limits.client_ip(request), "198.51.100.9")

    def test_window_resets(self):
        rule = limits.Rule("t", 2, 60, "")
        with mock.patch("throttle.limits.time.time", return_value=1_000_020):
            limits.hit(self.request, rule)
            limits.hit(self.request, rule)
            self.assertTrue(limits.is_limited(self.request, rule))
        with mock.patch("throttle.limits.time.time", return_value=1_000_080):
            self.assertFalse(limits.is_limited(self.request, rule))

    def test_cleanup_keeps_current_windows_of_every_period(self):
        for rule in (limits.LOGIN_IP, limits.VOTE_GLOBAL):
            limits.hit(self.request, rule)
        Hit.objects.create(key="eski", window=int(time.time()) - 2 * 24 * 3600, count=5)
        limits._cleanup()
        self.assertEqual(sorted(Hit.objects.values_list("count", flat=True)), [1, 1])

    @override_settings(RATE_LIMITS_ENABLED=False)
    def test_can_be_disabled(self):
        self.assertEqual(limits.hit(self.request, limits.LOGIN_IP), 0)
        self.assertFalse(Hit.objects.exists())


class AnonymousVoteLimitTests(TestCase):
    def setUp(self):
        author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        self.poll = create_poll(author=author, question="Hangisini seçeyim acaba?", description="", options=["A", "B"])
        self.url = f"/anket/{self.poll.public_id}/oy/"
        self.option_id = self.poll.options.first().pk

    def vote(self, client):
        return client.post(self.url, {"option_id": self.option_id}, HTTP_ACCEPT="application/json")

    def test_fresh_cookies_from_one_network_are_capped(self):
        statuses = [self.vote(vercel_client("198.51.100.1")).status_code for _ in range(limits.VOTE_PER_POLL.limit + 2)]
        self.assertEqual(statuses.count(200), limits.VOTE_PER_POLL.limit)
        self.assertEqual(statuses[-1], 429)
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.total_votes, limits.VOTE_PER_POLL.limit)
        self.assertEqual(Vote.objects.count(), limits.VOTE_PER_POLL.limit)

    def test_429_message_and_other_networks_unaffected(self):
        for _ in range(limits.VOTE_PER_POLL.limit):
            self.vote(vercel_client("198.51.100.1"))
        blocked = self.vote(vercel_client("198.51.100.1"))
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("çok fazla oy", blocked.json()["message"])
        self.assertEqual(self.vote(vercel_client("198.51.100.2")).status_code, 200)

    def test_logged_in_users_are_not_counted(self):
        for index in range(limits.VOTE_PER_POLL.limit + 1):
            user = User.objects.create_user(f"uye{index}", f"uye{index}@example.com", PASSWORD)
            client = vercel_client("198.51.100.1")
            client.force_login(user)
            self.assertEqual(self.vote(client).status_code, 200)
        self.assertFalse(Hit.objects.exists())

    def test_without_js_shows_message(self):
        for _ in range(limits.VOTE_PER_POLL.limit):
            vercel_client("198.51.100.1").post(self.url, {"option_id": self.option_id})
        response = vercel_client("198.51.100.1").post(self.url, {"option_id": self.option_id}, follow=True)
        self.assertContains(response, "çok fazla oy")


class LoginLimitTests(TestCase):
    def setUp(self):
        User.objects.create_user("ayse_k", "ayse@example.com", PASSWORD)

    def test_blocks_after_failed_attempts_even_with_correct_password(self):
        client = vercel_client("198.51.100.5")
        for i in range(limits.LOGIN_USER.limit):
            self.assertEqual(client.post("/giris/", {"username": "ayse_k", "password": f"yanlis{i}"}).status_code, 200)
        response = client.post("/giris/", {"username": "Ayse_K", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "çok fazla hatalı deneme", status_code=429)
        self.assertNotIn("_auth_user_id", client.session)

    def test_successful_logins_are_not_counted(self):
        client = vercel_client("198.51.100.5")
        for _ in range(limits.LOGIN_USER.limit + 2):
            self.assertEqual(client.post("/giris/", {"username": "ayse_k", "password": PASSWORD}).status_code, 302)
            client.post("/cikis/")
        self.assertFalse(Hit.objects.filter(count__gt=0).exists())

    def test_username_limit_is_shared_across_networks(self):
        statuses = []
        for ip_n in range(3):
            client = vercel_client(f"198.51.100.{20 + ip_n}")
            for i in range(5):
                statuses.append(client.post("/giris/", {"username": "ayse_k", "password": f"x{ip_n}{i}"}).status_code)
        self.assertEqual(statuses.count(200), limits.LOGIN_USER.limit)
        self.assertEqual(statuses[limits.LOGIN_USER.limit:], [429] * (15 - limits.LOGIN_USER.limit))

    def test_attempt_is_counted_before_authenticating(self):
        # Parallel requests must not all pass a check before any of them is recorded.
        seen = []

        def fake_authenticate(request=None, **credentials):
            seen.append(limits.count(request, limits.LOGIN_USER, "ayse_k"))
            return None

        with mock.patch("django.contrib.auth.forms.authenticate", side_effect=fake_authenticate):
            vercel_client("198.51.100.30").post("/giris/", {"username": "ayse_k", "password": "yanlis"})
        self.assertEqual(seen, [1])

    def test_other_account_from_other_network_still_works(self):
        attacker = vercel_client("198.51.100.5")
        for i in range(limits.LOGIN_USER.limit):
            attacker.post("/giris/", {"username": "ayse_k", "password": f"yanlis{i}"})
        User.objects.create_user("mert42", "mert@example.com", PASSWORD)
        other = vercel_client("198.51.100.6")
        self.assertEqual(other.post("/giris/", {"username": "mert42", "password": PASSWORD}).status_code, 302)


class RegisterLimitTests(TestCase):
    def data(self, n, **extra):
        return {"username": f"yeni{n}", "email": f"yeni{n}@example.com",
                "password1": PASSWORD, "password2": PASSWORD, **extra}

    def test_registrations_per_network_are_capped(self):
        statuses = [vercel_client("198.51.100.8").post("/kayit/", self.data(n)).status_code
                    for n in range(limits.REGISTER_IP.limit + 1)]
        self.assertEqual(statuses[:-1], [302] * limits.REGISTER_IP.limit)
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(User.objects.count(), limits.REGISTER_IP.limit)

    def test_honeypot_blocks_bots_and_is_hidden(self):
        client = vercel_client("198.51.100.9")
        response = client.post("/kayit/", self.data(1, website="http://spam.example"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kayıt tamamlanamadı.")
        self.assertFalse(User.objects.exists())
        page = client.get("/kayit/").content.decode()
        self.assertIn('class="visually-hidden" aria-hidden="true"', page)
        self.assertIn('tabindex="-1"', page)
