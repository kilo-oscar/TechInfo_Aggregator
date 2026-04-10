#!/bin/bash
set -eu

PROJECT_DIR="$HOME/ドキュメント/TechInfo_Aggregator"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_crawlers.log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') START =====" >> "$LOG_FILE"

export CRAWL_BATCH_ID="daily-$(date '+%Y%m%d%H%M%S')"

# 対話シェル経由で bashrc を読み込み、Gmail 用の環境変数だけ取り込む
if [ -f "$HOME/.bashrc" ]; then
  eval "$(bash -ic 'declare -px GMAIL_SENDER GMAIL_APP_PASSWORD GMAIL_RECIPIENT 2>/dev/null | sed "s/^declare -x /export /"' 2>/dev/null)"
fi

# 仮想環境を有効化
source "$PROJECT_DIR/.venv/bin/activate"

# 必要なら Python パス確認
python3 --version >> "$LOG_FILE" 2>&1

# 既存データをリセット
python3 reset_raw_items.py >> "$LOG_FILE" 2>&1

# 各クローラを順番に実行
python3 -m crawlers.arxiv_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.google_news_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.exhibition_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.real_haptics_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.thinktank_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.government_policy_crawler >> "$LOG_FILE" 2>&1
python3 cleanup_raw_item_duplicates.py >> "$LOG_FILE" 2>&1
python3 send_new_items_gmail.py >> "$LOG_FILE" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') END =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
