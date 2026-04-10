#!/bin/bash
set -eu

PROJECT_DIR="$HOME/ドキュメント/TechInfo_Aggregator"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_crawlers.log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') START =====" >> "$LOG_FILE"

# 仮想環境を有効化
source "$PROJECT_DIR/.venv/bin/activate"

# 必要なら Python パス確認
python3 --version >> "$LOG_FILE" 2>&1

# 各クローラを順番に実行
python3 -m crawlers.arxiv_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.google_news_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.exhibition_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.real_haptics_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.thinktank_crawler >> "$LOG_FILE" 2>&1
python3 -m crawlers.government_policy_crawler >> "$LOG_FILE" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') END =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"