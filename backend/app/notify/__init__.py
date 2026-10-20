"""Notifications (C2; G4 adds the in-app bell on the same pieces).

    email.py   the email interface (`EmailSender`), the fake provider that
               only writes to the outbox table, and the address book
    digest.py  the owner's digest: news queued as it happens, sent at most
               every 10 minutes as one email
"""
