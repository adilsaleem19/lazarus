"""Per-job token budget so a runaway repair loop can't drain the free tier."""


class BudgetExceeded(Exception):
    pass


class TokenBudget:
    def __init__(self, limit: int):
        self.limit = limit
        self.spent = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def can_afford(self, tokens: int) -> bool:
        return self.spent + tokens <= self.limit

    def charge(self, tokens: int) -> None:
        if self.spent + tokens > self.limit:
            raise BudgetExceeded(
                f"token budget exhausted: {self.spent}+{tokens} exceeds limit {self.limit}"
            )
        self.spent += tokens
