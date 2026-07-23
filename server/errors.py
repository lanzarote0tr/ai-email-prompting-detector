class AiFilterError(Exception):
    def __init__(self, message: str, status_code: int = 502, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        # True when re-asking the model could plausibly succeed (bad/truncated output),
        # False when the problem is the connection or the configuration.
        self.retryable = retryable
