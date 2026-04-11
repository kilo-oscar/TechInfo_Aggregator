#!/bin/bash
set -eu

PROJECT_DIR="$HOME/ドキュメント/TechInfo_Aggregator"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_crawlers.log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') START =====" >> "$LOG_FILE"

export CRAWL_BATCH_ID="daily-$(date '+%Y%m%d%H%M%S')"

run_step() {
  local label="$1"
  shift

  echo "[STEP] ${label} START" >> "$LOG_FILE"
  if "$@" >> "$LOG_FILE" 2>&1; then
    echo "[STEP] ${label} OK" >> "$LOG_FILE"
  else
    local exit_code=$?
    echo "[STEP] ${label} FAIL exit=${exit_code}" >> "$LOG_FILE"
  fi
}

# 対話シェル経由で bashrc を読み込み、Gmail 用の環境変数だけ取り込む
if [ -f "$HOME/.bashrc" ]; then
  eval "$(bash -ic 'declare -px GMAIL_SENDER GMAIL_APP_PASSWORD GMAIL_RECIPIENT 2>/dev/null | sed "s/^declare -x /export /"' 2>/dev/null)"
fi

# 仮想環境を有効化
source "$PROJECT_DIR/.venv/bin/activate"

# 必要なら Python パス確認
python3 --version >> "$LOG_FILE" 2>&1

# 既存データをリセット
run_step "reset_raw_items" python3 reset_raw_items.py

# 各クローラを順番に実行
run_step "arxiv_crawler" python3 -m crawlers.arxiv_crawler
run_step "google_news_crawler" python3 -m crawlers.google_news_crawler
run_step "exhibition_crawler" python3 -m crawlers.exhibition_crawler
run_step "real_haptics_crawler" python3 -m crawlers.real_haptics_crawler
run_step "thinktank_crawler" python3 -m crawlers.thinktank_crawler
run_step "government_policy_crawler" python3 -m crawlers.government_policy_crawler
run_step "cleanup_raw_item_duplicates" python3 cleanup_raw_item_duplicates.py
run_step "send_new_items_gmail" python3 send_new_items_gmail.py

echo "===== $(date '+%Y-%m-%d %H:%M:%S') END =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
