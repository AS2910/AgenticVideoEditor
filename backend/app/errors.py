"""Failure kinds shared across layers."""


class NonRetryableError(RuntimeError):
    """A failure that retrying cannot fix.

    The job runner attempts these once and shows the message to the user, so
    the message must say what to change: widen the selection, raise the budget,
    fix the key. Contrast `VendorError`, which is presumed transient.
    """


class SafetyRefused(NonRetryableError):
    """Run 5 item 1: a vendor's safety filter refused the content itself.

    Retrying the same words cannot help, so it is not retried; the person is
    told which line it was (`line_text`, and `at` in seconds when known) and
    to reword it. `detail` is the vendor's own text, for the log only.
    """

    def __init__(self, vendor: str, line_text: str | None = None, at: float | None = None, detail: str = "") -> None:
        self.vendor, self.line_text, self.at, self.detail = vendor, line_text, at, detail
        super().__init__(f"{vendor} safety filter refused the content")

    def on_line(self, line_text: str | None, at: float | None) -> "SafetyRefused":
        """The same refusal, naming the line it was about (a known line is kept)."""
        if self.line_text:
            return self
        return SafetyRefused(self.vendor, line_text, at, self.detail)
