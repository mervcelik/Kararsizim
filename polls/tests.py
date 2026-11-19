from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Option, Poll, Vote
from .utils import BASE62_ALPHABET, generate_public_id


class VoteConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tester", "tester@example.com", "parola-12345")
        cls.poll = Poll.objects.create(question="Hangisini seçeyim acaba?", author=cls.user)
        cls.option_a = Option.objects.create(poll=cls.poll, text="A", position=0)
        cls.option_b = Option.objects.create(poll=cls.poll, text="B", position=1)

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


class PublicIdTests(TestCase):
    def test_public_id_is_base62(self):
        public_id = generate_public_id()
        self.assertEqual(len(public_id), 10)
        self.assertTrue(set(public_id) <= set(BASE62_ALPHABET))
