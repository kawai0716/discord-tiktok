import hashlib
import json
import unicodedata
from dataclasses import dataclass


def tag_char(char: str) -> bool:
    return char == '_' or unicodedata.category(char)[0] in 'LNM'


def normalize(tag: str) -> str:
    if not isinstance(tag, str):
        raise ValueError('タグは文字列で指定してください')
    tag = unicodedata.normalize('NFKC', tag).strip().removeprefix('#').casefold()
    if not tag or not all(tag_char(c) for c in tag):
        raise ValueError(f'無効なタグ: {tag!r}')
    return tag


def extract_hashtags(caption: str) -> set[str]:
    text = unicodedata.normalize('NFKC', caption)
    found = set()
    for part in text.split('#')[1:]:
        end = 0
        while end < len(part) and tag_char(part[end]):
            end += 1
        if end:
            found.add(normalize(part[:end]))
    return found


@dataclass(frozen=True)
class Rule:
    name: str
    all_of: frozenset[str]
    any_of: frozenset[str]
    tags: frozenset[str]
    minimum: int

    def matches(self, hashtags: set[str]) -> bool:
        return (self.all_of <= hashtags
                and (not self.any_of or bool(self.any_of & hashtags))
                and len(self.tags & hashtags) >= self.minimum)


@dataclass(frozen=True)
class Config:
    rules: tuple[Rule, ...]
    max_notifications: int = 20
    scrolls: int = 3
    wait_seconds: int = 5

    @property
    def watch_tags(self):
        return sorted(set().union(*(r.all_of | r.any_of | r.tags for r in self.rules)))

    @property
    def fingerprint(self):
        data = sorted((sorted(r.all_of), sorted(r.any_of), sorted(r.tags), r.minimum)
                      for r in self.rules)
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()

    def matching_names(self, hashtags):
        return [r.name for r in self.rules if r.matches(hashtags)]


def parse_config(data: dict) -> Config:
    if not isinstance(data, dict) or set(data) - {'rules', 'maxNotificationsPerRun', 'collector'}:
        raise ValueError('設定のキーが不正です')
    raw = data.get('rules')
    if not isinstance(raw, list) or not raw:
        raise ValueError('rules は空でない配列にしてください')
    rules = []
    for row in raw:
        if not isinstance(row, dict) or set(row) - {'name', 'allOf', 'anyOf', 'tags', 'minMatches'}:
            raise ValueError('ルールのキーが不正です')
        name = row.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('ルール名は1〜100文字にしてください')
        groups = []
        for key in ('allOf', 'anyOf', 'tags'):
            values = row.get(key, [])
            if not isinstance(values, list):
                raise ValueError(f'{key} は配列にしてください')
            groups.append(frozenset(normalize(x) for x in values))
        minimum = row.get('minMatches', 0)
        if bool(groups[2]) != ('minMatches' in row):
            raise ValueError('tags と minMatches はセットで指定してください')
        if type(minimum) is not int or (groups[2] and not 1 <= minimum <= len(groups[2])) or minimum < 0:
            raise ValueError('minMatches は重複を除いたタグ数以内の正の整数です')
        if not any(groups):
            raise ValueError('条件が空のルールは使えません')
        rules.append(Rule(name, *groups, minimum))
    if len({r.name for r in rules}) != len(rules):
        raise ValueError('ルール名は一意にしてください')
    collector = data.get('collector', {})
    if not isinstance(collector, dict) or set(collector) - {'scrolls', 'waitSeconds'}:
        raise ValueError('collector のキーが不正です')
    values = [data.get('maxNotificationsPerRun', 20), collector.get('scrolls', 3), collector.get('waitSeconds', 5)]
    for value, lower, upper in zip(values, (1, 0, 1), (100, 20, 30)):
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError('通知上限/scrolls/waitSeconds が許容範囲外です')
    return Config(tuple(rules), *values)
