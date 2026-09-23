from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class Post:
    id: str
    url: str
    username: str
    caption: str
    hashtags: tuple[str, ...]
    created_at: int

    def to_dict(self):
        data = asdict(self)
        data['hashtags'] = list(self.hashtags)
        return data


class FetchError(RuntimeError):
    pass


class DeliveryError(RuntimeError):
    pass


class Collector(Protocol):
    def collect(self, tags: list[str]) -> dict[str, list[Post]]: ...


class Notifier(Protocol):
    def send(self, post: Post, rules: list[str]) -> None: ...


class Store(Protocol):
    def load(self) -> dict | None: ...
    def save(self, state: dict) -> None: ...
