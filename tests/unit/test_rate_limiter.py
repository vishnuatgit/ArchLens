from app.services.rate_limiter import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_reports_wait_time():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=3, window_seconds=600, clock=clock)

    assert [limiter.hit("1.2.3.4") for _ in range(3)] == [None, None, None]

    clock.now += 100
    assert limiter.hit("1.2.3.4") == 500  # the oldest event expires in 500s


def test_window_slides_and_clients_are_independent():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60, clock=clock)

    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None
    assert limiter.hit("b") is None

    clock.now += 60
    assert limiter.hit("a") is None


def test_refused_requests_do_not_extend_the_wait():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60, clock=clock)
    limiter.hit("a")

    for _ in range(5):
        limiter.hit("a")
    clock.now += 60
    assert limiter.hit("a") is None


def test_non_positive_limit_disables_limiting():
    limiter = SlidingWindowRateLimiter(max_events=0, window_seconds=60)
    assert all(limiter.hit("a") is None for _ in range(100))
