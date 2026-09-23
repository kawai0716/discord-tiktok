import argparse
import json
import logging
import os
from pathlib import Path

from .collector import BrowserCollector
from .discord import DiscordNotifier
from .engine import run
from .rules import parse_config
from .state import GitHubStore, LocalStore


def main():
    parser = argparse.ArgumentParser(description='TikTok → Discord hashtag monitor')
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--state', default='state.json')
    parser.add_argument('--github-state', action='store_true')
    parser.add_argument('--initialize', action='store_true', help='状態がない場合だけ初期化を許可')
    parser.add_argument('--dry-run', action='store_true', help='取得・判定のみ。通知・状態保存なし')
    parser.add_argument('--validate-config', action='store_true')
    parser.add_argument('--headed', action='store_true', help='ローカル診断用にブラウザを表示')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = parse_config(json.loads(Path(args.config).read_text(encoding='utf-8')))
        if args.validate_config:
            print('設定OK / 監視タグ: ' + ', '.join(config.watch_tags))
            return 0
        store = (GitHubStore(os.environ.get('GITHUB_REPOSITORY', ''), os.environ.get('GH_TOKEN', ''))
                 if args.github_state else LocalStore(args.state))
        notifier = None if args.dry_run else DiscordNotifier(os.environ.get('DISCORD_WEBHOOK_URL', ''))
        return run(config, BrowserCollector(config.scrolls, config.wait_seconds, args.headed),
                   notifier, store, initialize=args.initialize, dry_run=args.dry_run)
    except Exception as error:
        # Error messages from browser/HTTP libraries may contain credentials; our own errors do not.
        from .models import FetchError, DeliveryError
        from .http import HTTPFailure
        message = str(error) if isinstance(error, (ValueError, FetchError, DeliveryError, HTTPFailure)) else type(error).__name__
        logging.error('実行失敗: %s', message)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
