from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import selectors
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
