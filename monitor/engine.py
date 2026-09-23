import logging
import time

from .models import DeliveryError, FetchError, Post

log = logging.getLogger(__name__)


def run(config, collector, notifier, store, *, initialize=False, dry_run=False, now=None):
    state = store.load()
    if state is None and not (initialize or dry_run):
        raise ValueError('状態がありません。初回のみ --initialize を指定してください')
    started = int(time.time()) if now is None else now
    tags = config.watch_tags
    log.info('watch_tags=%d tags=%s', len(tags), ','.join(tags))
    batches = collector.collect(tags)
    if set(batches) != set(tags) or any(not posts for posts in batches.values()):
        raise FetchError('一部の監視タグを取得できませんでした。状態を変更せず停止')
    posts = {}
    for batch in batches.values():
        for post in batch:
            # Never merge tag sets of conflicting snapshots: this could invent an AND match.
            if post.id not in posts or len(post.caption) > len(posts[post.id].caption):
                posts[post.id] = post
    matches = {key: config.matching_names(set(post.hashtags)) for key, post in posts.items()}
    log.info('deduplicated=%d matching=%d', len(posts), sum(bool(x) for x in matches.values()))
    for key, names in matches.items():
        if names:
            log.info('matched video=%s rules=%s', key, ', '.join(names))
    if state is None or state['fingerprint'] != config.fingerprint:
        if dry_run:
            log.info('dry_run: 初回/条件変更のため実行時は通知なしで基準を保存')
            return 0
        old = state or {'known': [], 'pending': {}}
        pending = {k: v for k, v in old['pending'].items()
                   if config.matching_names(set(v['hashtags']))}
        state = {'version': 1, 'initialized': True, 'fingerprint': config.fingerprint,
                 'cutoff': started, 'known': sorted((set(old['known']) | set(posts)) - set(pending)),
                 'pending': pending}
        store.save(state)
        log.info('baseline_saved=%d pending=%d notifications=0 (初回または条件変更)', len(posts), len(pending))
        return 0
    known = set(state['known'])
    new = 0
    for key, post in posts.items():
        if key in known or key in state['pending'] or post.created_at <= state['cutoff']:
            continue
        new += 1
        if matches[key]:
            state['pending'][key] = post.to_dict()
    # Re-evaluate queued posts under the current rules as well.
    state['pending'] = {k: v for k, v in state['pending'].items()
                        if config.matching_names(set(v['hashtags']))}
    log.info('new_videos=%d pending=%d', new, len(state['pending']))
    if dry_run:
        log.info('dry_run: 送信・保存なし would_notify=%d', min(len(state['pending']), config.max_notifications))
        return 0
    store.save(state)  # Persist the outbox before making any external delivery.
    successes = failures = 0
    queue = sorted(state['pending'].values(), key=lambda x: (x['created_at'], x['id']))
    for raw in queue[:config.max_notifications]:
        post = Post(**raw)
        names = config.matching_names(set(post.hashtags))
        try:
            notifier.send(post, names)
        except DeliveryError as error:
            failures += 1
            log.error('delivery_failed video=%s reason=%s', post.id, error)
            # Avoid hammering a deleted webhook / rate limit. All remaining posts stay pending.
            break
        known.add(post.id)
        del state['pending'][post.id]
        state['known'] = sorted(known)
        store.save(state)  # Fail closed if durable acknowledgement cannot be written.
        successes += 1
    log.info('discord_success=%d discord_failure=%d remaining_pending=%d', successes, failures, len(state['pending']))
    return 1 if failures else 0
