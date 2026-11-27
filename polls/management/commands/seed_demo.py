import hashlib
import random
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from polls.models import Option, Poll, Vote

# Demo accounts never log in: a password in this public repo would let anyone take them over
# on the live site and delete their polls. They get an unusable password instead.
DEMO_EMAIL_DOMAIN = "@demo.kararsizim.test"

DEMO_USERS = [
    ("ayse_k", "ayse@demo.kararsizim.test"),
    ("mert42", "mert@demo.kararsizim.test"),
    ("deniz_ok", "deniz@demo.kararsizim.test"),
]

DEMO_POLLS = [
    ("Bugün sinemaya mı gitsem, restorana mı?", "", ["Sinema", "Restoran"]),
    ("Hafta sonu kamp mı, şehirde dinlenmek mi?", "Hava güzel görünüyor ama yorgunum.", ["Kamp", "Şehirde dinlenmek"]),
    ("İlk programlama dili olarak hangisini öğreneyim?", "", ["Python", "JavaScript", "Go", "C#"]),
    ("Kahvaltıda simit mi, poğaça mı?", "", ["Simit", "Poğaça", "İkisi de"]),
    ("Yeni telefon alayım mı, eskisini tamir ettireyim mi?", "Ekran çatlak, pil idare ediyor.", ["Yeni al", "Tamir ettir"]),
    ("Tatil için deniz mi, dağ mı?", "", ["Deniz", "Dağ", "Şehir turu"]),
    ("Akşam hangi diziye başlayayım?", "Bilim kurgu ya da gerilim seviyorum.", ["Yeni çıkan", "Eski klasik", "Belgesel", "Mini dizi", "Hiçbiri, kitap oku"]),
    ("Spor salonu sabah mı, akşam mı?", "", ["Sabah", "Akşam"]),
    ("Saçımı kısa mı kestireyim, uzatayım mı?", "", ["Kısa kestir", "Uzat"]),
    ("Kedi mi sahiplensem, köpek mi?", "Evim küçük, gün içinde dışarıdayım.", ["Kedi", "Köpek", "Şimdilik hiçbiri"]),
    ("Doğum günü hediyesi: kitap mı, deneyim mi?", "", ["Kitap", "Deneyim", "El yapımı bir şey"]),
    ("Yazın staj mı yapayım, kendi projemi mi geliştireyim?", "", ["Staj", "Kendi projem", "İkisini birden dene"]),
]

CLOSED_POLL_INDEXES = {4, 8}


def random_voter_key():
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


class Command(BaseCommand):
    help = "Demo kullanıcıları, anketleri ve rastgele oyları oluşturur (tekrar çalıştırılabilir)."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        now = timezone.now()

        users = []
        for username, email in DEMO_USERS:
            user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
            if not user.email.endswith(DEMO_EMAIL_DOMAIN):
                # A real person registered this name first; never touch their account or polls.
                raise CommandError(f"@{username} gerçek bir hesap, demo verisi oluşturulmadı.")
            if user.has_usable_password():
                user.set_unusable_password()
                user.save(update_fields=["password"])
            users.append(user)

        deleted, _ = Poll.objects.filter(author__in=users).delete()
        if deleted:
            self.stdout.write(f"Eski demo verisi silindi ({deleted} kayıt).")

        for index, (question, description, option_texts) in enumerate(DEMO_POLLS):
            author = users[index % len(users)]
            poll = Poll.objects.create(
                question=question,
                description=description,
                author=author,
                status=Poll.Status.CLOSED if index in CLOSED_POLL_INDEXES else Poll.Status.ACTIVE,
            )
            created_at = now - timedelta(days=random.randint(0, 13), hours=random.randint(0, 23))
            Poll.objects.filter(pk=poll.pk).update(created_at=created_at)

            poll_options = Option.objects.bulk_create(
                Option(poll=poll, text=text, position=position) for position, text in enumerate(option_texts)
            )

            weights = [random.randint(1, 10) for _ in poll_options]
            votes = []
            for voter in users:
                if random.random() < 0.6:
                    votes.append(Vote(poll=poll, user=voter, voter_key=random_voter_key(),
                                      option=random.choices(poll_options, weights)[0]))
            for _ in range(random.randint(0, 40)):
                votes.append(Vote(poll=poll, voter_key=random_voter_key(),
                                  option=random.choices(poll_options, weights)[0]))
            Vote.objects.bulk_create(votes)

            age = now - created_at
            for vote in votes:
                vote.created_at = created_at + age * random.random()
            Vote.objects.bulk_update(votes, ["created_at"])

            for option in poll_options:
                option.vote_count = sum(1 for vote in votes if vote.option_id == option.pk)
            Option.objects.bulk_update(poll_options, ["vote_count"])
            Poll.objects.filter(pk=poll.pk).update(total_votes=len(votes))

        self.stdout.write(self.style.SUCCESS(
            f"{len(users)} kullanıcı, {len(DEMO_POLLS)} anket ve {Vote.objects.filter(poll__author__in=users).count()} oy hazır. "
            f"Demo kullanıcı adları: {', '.join(u.username for u in users)}"
        ))
