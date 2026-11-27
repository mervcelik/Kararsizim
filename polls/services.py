from django.db import IntegrityError, transaction
from django.db.models import F, Q

from .models import Option, Poll, Vote


class VoteError(Exception):
    status = 400
    message = "Oy kaydedilemedi."

    def __init__(self, message=None):
        super().__init__(message or self.message)
        if message:
            self.message = message


class PollClosed(VoteError):
    status = 403
    message = "Bu anket kapandı, artık oy verilemez."


class InvalidOption(VoteError):
    status = 400
    message = "Bu seçenek bu ankete ait değil."


class AlreadyVoted(VoteError):
    status = 409
    message = "Bu ankete zaten oy verdin."


class RateLimited(VoteError):
    status = 429
    message = "Çok hızlı oy veriyorsun. Biraz sonra tekrar dene."


@transaction.atomic
def create_poll(*, author, question, description, options):
    poll = Poll.objects.create(author=author, question=question, description=description)
    Option.objects.bulk_create(
        Option(poll=poll, text=text, position=position) for position, text in enumerate(options)
    )
    return poll


def has_voted(*, poll, user, voter_key):
    who = Q(voter_key=voter_key, user__isnull=True)
    if user is not None:
        who |= Q(user=user)
    return Vote.objects.filter(who, poll=poll).exists()


def cast_vote(*, poll, option_id, user, voter_key):
    """Records one vote. Raises PollClosed, InvalidOption or AlreadyVoted."""
    if not poll.is_open:
        raise PollClosed
    try:
        option = poll.options.get(pk=int(option_id))
    except (TypeError, ValueError, Option.DoesNotExist):
        raise InvalidOption from None
    if has_voted(poll=poll, user=user, voter_key=voter_key):
        raise AlreadyVoted

    try:
        with transaction.atomic():
            vote = Vote.objects.create(poll=poll, option=option, user=user, voter_key=voter_key)
            Option.objects.filter(pk=option.pk).update(vote_count=F("vote_count") + 1)
            Poll.objects.filter(pk=poll.pk).update(total_votes=F("total_votes") + 1)
    except IntegrityError:
        # Two concurrent requests passed has_voted(); the unique constraint decides.
        raise AlreadyVoted from None
    return vote


def close_poll(poll):
    Poll.objects.filter(pk=poll.pk).update(status=Poll.Status.CLOSED)


def delete_poll(poll):
    poll.delete()
