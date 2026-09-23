"""Failure kinds shared across layers."""


class NonRetryableError(RuntimeError):
    """A failure that retrying cannot fix.

    The job runner attempts these once and shows the message to the user, so
    the message must say what to change: widen the selection, raise the budget,
    fix the key. Contrast `VendorError`, which is presumed transient.
    """
