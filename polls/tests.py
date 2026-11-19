import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import selectors, services
from .models import Option, Poll, Vote
from .services import create_poll
from .utils import BASE62_ALPHABET, compute_percentages, decision_badge, generate_public_id

User = get_user_model()
PASSWORD = "kararsiz-Test-2026"
CREATE_URL = "/anket/olustur/"


def make_poll(author, question="Hangisini seçeyim acaba?", options=("A", "B"), **fields):
    poll = create_poll(author=author, question=question, description="", options=list(options))
    if fields:
        Poll.objects.filter(pk=poll.pk).update(**fields)
        poll.refresh_from_db()
    return poll


class VoteConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tester", "tester@example.com", PASSWORD)
        cls.poll = make_poll(cls.user)
        cls.option_a, cls.option_b = cls.poll.options.all()

    def test_same_user_cannot_vote_twice(self):
        Vote.objects.create(poll=self.poll, option=self.option_a, user=self.user, voter_key="k1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vote.objects.create(poll=self.poll, option=self.option_b, user=self.user, voter_key="k2")

    def test_same_anonymous_key_cannot_vote_twice(self):
        Vote.objects.create(poll=self.poll, option=self.option_a, voter_key="anon")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vote.objects.create(poll=self.poll, option=self.option_b, voter_key="anon")

    def test_option_position_unique_per_poll(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Option.objects.create(poll=self.poll, text="C", position=0)


class UtilsTests(TestCase):
    def test_public_id_is_base62(self):
        public_id = generate_public_id()
        self.assertEqual(len(public_id), 10)
        self.assertTrue(set(public_id) <= set(BASE62_ALPHABET))

    def test_percentages_always_sum_to_100(self):
        for counts in ([1, 1, 1], [1, 2, 4], [3, 3, 1], [2, 2, 2, 1], [1, 1, 1, 1, 3], [0, 7], [5, 0, 0]):
            with self.subTest(counts=counts):
                self.assertEqual(sum(compute_percentages(counts)), 100)

    def test_percentages_zero_votes(self):
        self.assertEqual(compute_percentages([0, 0, 0]), [0, 0, 0])

    def test_decision_badge_thresholds(self):
        self.assertEqual(decision_badge([0, 0], 0)[0], "first")
        self.assertEqual(decision_badge([52, 48], 25)[0], "tie")
        self.assertEqual(decision_badge([55, 45], 20)[0], "lead")
        self.assertEqual(decision_badge([60, 40], 10)[0], "lead")
        self.assertEqual(decision_badge([61, 39], 10)[0], "clear")


class CreatePollTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, options, question="Bugün sinemaya mı gitsem?"):
        return self.client.post(CREATE_URL, {"question": question, "description": "", "options": options})

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(CREATE_URL)
        self.assertRedirects(response, f"/giris/?next={CREATE_URL}", fetch_redirect_response=False)

    def test_single_option_rejected(self):
        response = self.post(["Sinema", "", ""])
        self.assertContains(response, "En az 2 seçenek gerekli.")
        self.assertFalse(Poll.objects.exists())

    def test_six_options_rejected(self):
        response = self.post(["A", "B", "C", "D", "E", "F"])
        self.assertContains(response, "En fazla 5 seçenek ekleyebilirsin.")
        self.assertFalse(Poll.objects.exists())

    def test_duplicate_options_rejected(self):
        response = self.post(["Sinema", "sinema"])
        self.assertContains(response, "Aynı seçeneği iki kez yazmışsın.")
        self.assertFalse(Poll.objects.exists())

    def test_short_question_rejected(self):
        response = self.post(["A", "B"], question="Kısa")
        self.assertContains(response, "Soru en az 10 karakter olmalı.")

    def test_valid_poll_created_with_blank_rows_ignored(self):
        response = self.post(["Sinema", "", "Restoran", "", ""])
        poll = Poll.objects.get()
        self.assertRedirects(response, poll.get_absolute_url())
        self.assertEqual(list(poll.options.values_list("text", "position")), [("Sinema", 0), ("Restoran", 1)])
        self.assertEqual(poll.author, self.user)

    def test_daily_limit(self):
        for i in range(selectors.DAILY_POLL_LIMIT):
            make_poll(self.user, question=f"Bugünkü anket numarası {i}")
        response = self.post(["A", "B"])
        self.assertContains(response, "Bugün en fazla 10 anket açabilirsin.")
        self.assertEqual(Poll.objects.count(), selectors.DAILY_POLL_LIMIT)


class FeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)

    def test_tabs_split_open_and_closed(self):
        open_poll = make_poll(self.user, question="Açık olan anket sorusu")
        make_poll(self.user, question="Kapalı olan anket sorusu", status=Poll.Status.CLOSED)
        make_poll(self.user, question="Süresi dolmuş anket sorusu", closes_at=timezone.now() - timedelta(hours=1))

        response = self.client.get("/")
        self.assertEqual([c.poll.pk for c in response.context["cards"]], [open_poll.pk])
        response = self.client.get("/?sekme=kapanan")
        self.assertEqual(len(response.context["cards"]), 2)

    def test_popular_orders_by_votes_in_last_seven_days(self):
        old_favourite = make_poll(self.user, question="Eskiden çok oy alan anket")
        trending = make_poll(self.user, question="Bu hafta oy alan anket")
        for i in range(5):
            Vote.objects.create(poll=old_favourite, option=old_favourite.options.first(), voter_key=f"o{i}")
        Vote.objects.filter(poll=old_favourite).update(created_at=timezone.now() - timedelta(days=10))
        for i in range(2):
            Vote.objects.create(poll=trending, option=trending.options.first(), voter_key=f"t{i}")

        cards = self.client.get("/?sekme=populer").context["cards"]
        self.assertEqual(cards[0].poll.pk, trending.pk)

    def test_pagination_twenty_per_page(self):
        for i in range(25):
            make_poll(self.user, question=f"Sayfalama test anketi {i}")
        first = self.client.get("/")
        self.assertEqual(len(first.context["cards"]), 20)
        self.assertContains(first, "Daha fazla göster")
        second = self.client.get("/?sekme=yeni&page=2")
        self.assertEqual(len(second.context["cards"]), 5)
        self.assertNotContains(second, "Daha fazla göster")

    def test_query_count_constant(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get("/")
            return len(ctx)

        for i in range(3):
            make_poll(self.user, question=f"Sorgu sayısı anketi {i}", options=("A", "B", "C"))
        few = count_queries()
        for i in range(12):
            make_poll(self.user, question=f"Sorgu sayısı ek anketi {i}", options=("A", "B", "C", "D"))
        many = count_queries()
        self.assertEqual(few, many)

    def test_empty_state(self):
        self.assertContains(self.client.get("/"), "Henüz anket yok. İlk kararsızlığını sen paylaş.")


class ResultVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.visitor = User.objects.create_user("ziyaretci", "ziyaretci@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, options=("Sinema", "Restoran"))
        option = cls.poll.options.first()
        Option.objects.filter(pk=option.pk).update(vote_count=3)
        Poll.objects.filter(pk=cls.poll.pk).update(total_votes=3)

    def card(self):
        return self.client.get(self.poll.get_absolute_url()).context["card"]

    def test_results_hidden_before_voting(self):
        self.client.force_login(self.visitor)
        card = self.card()
        self.assertFalse(card.show_results)
        self.assertEqual(card.badge_text, "Oy ver, sonucu gör")

    def test_owner_sees_results(self):
        self.client.force_login(self.author)
        card = self.card()
        self.assertTrue(card.show_results)
        self.assertEqual(card.badge_text, "Karar net")

    def test_closed_poll_shows_results(self):
        Poll.objects.filter(pk=self.poll.pk).update(status=Poll.Status.CLOSED)
        self.assertTrue(self.card().show_results)

    def test_voter_sees_results_and_own_vote(self):
        option = self.poll.options.last()
        Vote.objects.create(poll=self.poll, option=option, user=self.visitor, voter_key="v")
        self.client.force_login(self.visitor)
        card = self.card()
        self.assertTrue(card.show_results)
        self.assertEqual(card.voted_option_id, option.pk)

    def test_unknown_poll_404(self):
        self.assertEqual(self.client.get("/anket/yokboyle12/").status_code, 404)


class ProfileTests(TestCase):
    def test_profile_lists_polls_without_email(self):
        user = User.objects.create_user("gizli_kisi", "gizli.adres@example.com", PASSWORD)
        make_poll(user, question="Profilde görünen anket sorusu")
        Poll.objects.update(total_votes=7)
        response = self.client.get("/kullanici/Gizli_Kisi/")
        self.assertContains(response, "Profilde görünen anket sorusu")
        self.assertContains(response, "@gizli_kisi")
        self.assertEqual(response.context["vote_count"], 7)
        self.assertNotContains(response, "gizli.adres")

    def test_detail_page_has_no_author_email(self):
        user = User.objects.create_user("gizli_kisi", "gizli.adres@example.com", PASSWORD)
        poll = make_poll(user)
        self.assertNotContains(self.client.get(poll.get_absolute_url()), "gizli.adres")

    def test_unknown_profile_404(self):
        self.assertEqual(self.client.get("/kullanici/yok_boyle/").status_code, 404)


JSON = {"HTTP_ACCEPT": "application/json"}


class VotingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.voter = User.objects.create_user("secmen", "secmen.gizli@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, options=("Sinema", "Restoran", "Evde kal"))
        cls.option = cls.poll.options.first()
        cls.other_poll = make_poll(cls.author, question="Başka bir anket sorusu")

    def vote_url(self, poll=None):
        return reverse("polls:vote", args=[(poll or self.poll).public_id])

    def vote(self, option_id=None, poll=None, **extra):
        return self.client.post(self.vote_url(poll), {"option_id": option_id or self.option.pk}, **extra)

    def counters(self):
        self.poll.refresh_from_db()
        self.option.refresh_from_db()
        return self.poll.total_votes, self.option.vote_count

    def test_anonymous_vote_succeeds_and_increments_counters(self):
        response = self.vote(**JSON)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["results"]["voted_option_id"], self.option.pk)
        self.assertEqual(self.counters(), (1, 1))
        vote = Vote.objects.get()
        self.assertIsNone(vote.user)
        self.assertEqual(len(vote.voter_key), 64)

    def test_same_session_second_vote_409_and_counters_unchanged(self):
        self.vote(**JSON)
        other = self.poll.options.last()
        response = self.vote(other.pk, **JSON)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "Bu ankete zaten oy verdin.")
        self.assertTrue(response.json()["results"]["results_visible"])
        self.assertEqual(self.counters(), (1, 1))

    def test_same_user_second_vote_409(self):
        self.client.force_login(self.voter)
        self.vote(**JSON)
        second = self.client_class()
        second.force_login(self.voter)
        response = second.post(self.vote_url(), {"option_id": self.option.pk}, **JSON)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Vote.objects.count(), 1)

    def test_anonymous_vote_then_login_still_counts_as_voted(self):
        self.vote(**JSON)
        self.client.post(reverse("accounts:login"), {"username": "secmen", "password": PASSWORD})
        response = self.vote(**JSON)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Vote.objects.count(), 1)

    def test_option_from_another_poll_400(self):
        response = self.vote(self.other_poll.options.first().pk, **JSON)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Vote.objects.count(), 0)

    def test_garbage_option_id_400(self):
        self.assertEqual(self.vote("abc", **JSON).status_code, 400)

    def test_closed_poll_vote_403(self):
        Poll.objects.filter(pk=self.poll.pk).update(status=Poll.Status.CLOSED)
        response = self.vote(**JSON)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Vote.objects.count(), 0)

    def test_expired_poll_vote_403(self):
        Poll.objects.filter(pk=self.poll.pk).update(closes_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.vote(**JSON).status_code, 403)

    def test_author_may_vote_on_own_poll(self):
        self.client.force_login(self.author)
        self.assertEqual(self.vote(**JSON).status_code, 200)

    def test_concurrent_double_vote_caught_by_constraint(self):
        self.client.force_login(self.voter)
        self.vote(**JSON)
        # Simulate a second tab that passed the pre-check at the same moment.
        with mock.patch.object(services, "has_voted", return_value=False):
            second = self.client_class()
            second.force_login(self.voter)
            response = second.post(self.vote_url(), {"option_id": self.option.pk}, **JSON)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.counters(), (1, 1))

    def test_vote_without_js_redirects_to_detail(self):
        response = self.vote(follow=True)
        self.assertRedirects(response, self.poll.get_absolute_url())
        self.assertContains(response, "Oyun kaydedildi.")
        card = response.context["card"]
        self.assertTrue(card.show_results)
        self.assertFalse(card.can_vote)
        self.assertContains(response, "option-row--voted")

    def test_vote_requires_post(self):
        self.assertEqual(self.client.get(self.vote_url()).status_code, 405)

    def test_voted_poll_remembered_in_session(self):
        self.vote(**JSON)
        self.assertIn(self.poll.pk, self.client.session["voted_polls"])

    def test_closed_poll_detail_has_no_vote_buttons(self):
        Poll.objects.filter(pk=self.poll.pk).update(status=Poll.Status.CLOSED)
        response = self.client.get(self.poll.get_absolute_url())
        self.assertNotContains(response, 'name="option_id"')
        self.assertContains(response, "Bu anket kapandı, artık oy verilemez.")


class ResultsEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("gizli_yazar", "yazar.gizli@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, options=("A", "B", "C"))

    def results(self):
        return self.client.get(reverse("polls:results", args=[self.poll.public_id]))

    def test_percentages_hidden_before_voting(self):
        data = self.results().json()
        self.assertFalse(data["results_visible"])
        self.assertTrue(all(o["percent"] is None and o["count"] is None for o in data["options"]))

    def test_percentages_sum_to_100_with_uneven_counts(self):
        for counts in ([1, 1, 1], [3, 2, 2], [1, 2, 4]):
            with self.subTest(counts=counts):
                Vote.objects.all().delete()
                for option, count in zip(self.poll.options.all(), counts):
                    Option.objects.filter(pk=option.pk).update(vote_count=count)
                Poll.objects.filter(pk=self.poll.pk).update(total_votes=sum(counts), status=Poll.Status.CLOSED)
                data = self.results().json()
                self.assertEqual(sum(o["percent"] for o in data["options"]), 100)

    def test_results_json_leaks_no_email_or_user_id(self):
        voter = User.objects.create_user("secmen", "secmen.gizli@example.com", PASSWORD)
        self.client.force_login(voter)
        self.client.post(reverse("polls:vote", args=[self.poll.public_id]),
                         {"option_id": self.poll.options.first().pk}, **JSON)
        raw = self.results().content.decode()
        data = json.loads(raw)
        self.assertNotIn("@example.com", raw)
        self.assertNotIn("gizli", raw)
        self.assertNotIn("user", json.dumps(list(data.keys())))
        self.assertNotIn("author", raw)
        for key in ("user_id", "author_id"):
            self.assertNotIn(key, raw)


class OwnerActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.stranger = User.objects.create_user("yabanci", "yabanci@example.com", PASSWORD)

    def setUp(self):
        self.poll = make_poll(self.author)

    def test_owner_can_close(self):
        self.client.force_login(self.author)
        self.client.post(reverse("polls:close", args=[self.poll.public_id]))
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.status, Poll.Status.CLOSED)

    def test_stranger_cannot_close_or_delete(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(reverse("polls:close", args=[self.poll.public_id])).status_code, 403)
        self.assertEqual(self.client.post(reverse("polls:delete", args=[self.poll.public_id])).status_code, 403)
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.status, Poll.Status.ACTIVE)

    def test_anonymous_close_redirects_to_login(self):
        response = self.client.post(reverse("polls:close", args=[self.poll.public_id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/giris/"))

    def test_delete_shows_confirmation_then_deletes(self):
        self.client.force_login(self.author)
        url = reverse("polls:delete", args=[self.poll.public_id])
        response = self.client.get(url)
        self.assertContains(response, "Evet, anketi sil")
        self.assertTrue(Poll.objects.filter(pk=self.poll.pk).exists())
        response = self.client.post(url)
        self.assertRedirects(response, reverse("polls:profile", args=["yazar"]))
        self.assertFalse(Poll.objects.filter(pk=self.poll.pk).exists())

    def test_close_requires_post(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("polls:close", args=[self.poll.public_id])).status_code, 405)


class UiShellTests(TestCase):
    """Faz 5: error pages, share metadata and the no-raw-hex rule."""

    def test_unknown_url_uses_branded_404(self):
        response = self.client.get("/boyle-bir-sayfa-yok/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Burada bir şey yok.", status_code=404)

    def test_missing_poll_uses_branded_404(self):
        response = self.client.get("/anket/YOKYOKYOK1/")
        self.assertTemplateUsed(response, "404.html")

    def test_500_page_renders_without_request_context(self):
        from django.template.loader import render_to_string

        html = render_to_string("500.html")
        self.assertIn("Bir şeyler ters gitti.", html)
        self.assertNotIn('property="og:url"', html)

    def test_detail_shares_question_in_og_tags(self):
        author = User.objects.create_user("paylasan", "p@example.com", PASSWORD)
        poll = make_poll(author, question="Kırmızı mı mavi mi?")
        response = self.client.get(poll.get_absolute_url())
        self.assertContains(response, '<meta property="og:title" content="Kırmızı mı mavi mi?">', html=False)
        self.assertContains(response, 'property="og:image" content="http://testserver/static/img/og.png"')
        self.assertContains(response, 'rel="icon"')
        self.assertNotContains(response, "p@example.com")

    def test_favicon_ico_redirects_to_svg(self):
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].endswith("img/favicon.svg"))

    def test_no_raw_hex_outside_tokens(self):
        import re
        from pathlib import Path

        from django.conf import settings

        hex_color = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
        offenders = []
        css_dir = Path(settings.BASE_DIR) / "static" / "css"
        for path in css_dir.glob("*.css"):
            if path.name != "tokens.css" and hex_color.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        for path in (Path(settings.BASE_DIR) / "templates").rglob("*.html"):
            text = re.sub(r'href="#[^"]*"', "", path.read_text(encoding="utf-8"))
            if hex_color.search(text):
                offenders.append(str(path))
        self.assertEqual(offenders, [])