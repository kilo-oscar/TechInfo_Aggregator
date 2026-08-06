# TechInfo_Aggregator

Physical AI / Robotics 関連の情報を収集して、Flask で一覧表示するアプリです。

この README では、次の流れを順番に説明します。

1. プロジェクトフォルダに移動する
2. 仮想環境に入る
3. `requirements.txt` から必要なパッケージをインストールする
4. クローラを実行してデータを収集する
5. Flask アプリを起動する
6. ブラウザで確認する
7. 日次実行やリセット方法を確認する

## 1. 前提

Ubuntu / Linux を想定しています。

必要なもの:

- Python 3
- `python3-venv` が使える環境
- インターネット接続

Python 3 の確認:

```bash
python3 --version
```

`venv` が入っていない場合:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

## 2. プロジェクトフォルダへ移動

```bash
cd ~/ドキュメント/TechInfo_Aggregator
```

## 3. 仮想環境に入る

このプロジェクトには `.venv` がある前提です。まずは有効化します。

```bash
source .venv/bin/activate
```

有効化できると、ターミナルの先頭に `(.venv)` のような表示が出ます。

例:

```bash
(.venv) kenji@kenji-Default-string:~/ドキュメント/TechInfo_Aggregator$
```

### うまく入れない場合

`.venv` が無い、または壊れている場合は作り直します。

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4. `requirements.txt` から必要なパッケージをインストール

このプロジェクトは `requirements.txt` を使います。

```bash
pip install -r requirements.txt
```

入る主なパッケージ:

- Flask
- Flask-SQLAlchemy
- requests
- feedparser
- beautifulsoup4

インストール確認をしたい場合:

```bash
pip list
```

### APIキー・認証情報を設定する

このプロジェクトで使うAPIキーと認証情報は、プロジェクト直下の `.env` で管理します。

```bash
cp .env.example .env
chmod 600 .env
```

`.env` を開いて必要な値を設定します。

```dotenv
GOOGLE_TRANSLATE_API_KEY="your-google-cloud-api-key"
GOOGLE_TRANSLATE_MONTHLY_CHARACTER_LIMIT="450000"
GMAIL_SENDER="your-address@gmail.com"
GMAIL_APP_PASSWORD="your-gmail-app-password"
GMAIL_RECIPIENT="recipient@example.com"
```

Pythonアプリ、各クローラ、日次実行スクリプトは `.env` を自動的に読み込みます。すでにシェルに設定されている同名の環境変数は、Python側では `.env` で上書きしません。

`.env` は `.gitignore` に登録されているためGitには含まれません。`.env.example` にはキー名だけを記載し、実際の値を入れないでください。

## 5. 展示会クローラを実行する

展示会情報を収集するクローラは次のコマンドで実行できます。

```bash
python3 -m crawlers.exhibition_crawler
```

検索語を自分で指定したい場合:

```bash
python3 -m crawlers.exhibition_crawler --queries "robotics exhibition" "physical AI expo" "humanoid robot exhibition"
```

### 他のクローラ例

リアルハプティクス専用クローラ:

```bash
python3 -m crawlers.real_haptics_crawler
```

Google News クローラ:

```bash
python3 -m crawlers.google_news_crawler
```

arXiv クローラ:

```bash
python3 -m crawlers.arxiv_crawler
```

シンクタンク横断クローラ:

```bash
python3 -m crawlers.thinktank_crawler
```

個別シンクタンククローラ:

```bash
python3 -m crawlers.mri_crawler
python3 -m crawlers.jri_crawler
python3 -m crawlers.nri_crawler
python3 -m crawlers.dir_crawler
python3 -m crawlers.mizuho_rt_crawler
python3 -m crawlers.murc_crawler
```

政府系政策クローラ:

```bash
python3 -m crawlers.government_policy_crawler
```

### 収集される主な種別

保存される `source_type` には主に次の値があります。

- `news`
- `paper`
- `event`
- `policy`
- `thinktank`
- `company`

### クローラ実行時の保存先

各クローラは取得したデータを SQLite に保存します。

保存先:

```text
instance/techinfo.db
```

重複判定は基本的に URL 単位で行われ、同じ URL のデータは再登録されません。

現在は保存時に次の重複も回避します。

- `http` / `https` 違いを吸収した URL 重複
- 追跡パラメータ付き URL の重複
- 同じ `source_name + title + published_at` の重複

### みずほリサーチ&テクノロジーズ向けクローラについて

`crawlers.mizuho_rt_crawler` は、みずほ公開サイトで直接アクセス時に `403 Forbidden` が返ることがあるため、みずほ向けだけ取得方法を少し変えています。

主な特徴:

- `DuckDuckGo` 検索
- `Google News RSS`
- `r.jina.ai` 経由の本文取得
- `https://www.mizuhobank.co.jp/corporate/industry/` 配下の収集
- `industry/pdf` 配下の PDF 資料収集

そのため、通常の HTML 記事だけでなく、業界調査資料や PDF も収集対象に含まれます。

### 日本総合研究所向けクローラについて

`crawlers.jri_crawler` は、日本総研サイト内の `先端技術リサーチ` 系コンテンツを重点的に収集するよう調整しています。

主な特徴:

- `先端技術リサーチ` の一覧・詳細ページを seed URL に追加
- `Physical AI`、`フィジカルAI`、`ロボット`、`embodied AI` などを重視
- 日本総研固有のノイズページを除外
- `Physical AI / ロボット` に関係する記事だけを後段で再フィルタ

このため、単純なサイトトップ巡回よりも `Physical AI` 関連記事の精度を優先した挙動になっています。

### 民間企業主催の Physical AI イベントについて

展示会クローラは、展示会専用サイトに加え、AWS、Microsoft、Google Cloud、NVIDIA、トヨタ、Honda、ソニー、富士通、NEC、日立、三菱電機、FANUC、安川電機、川崎重工、オムロン、SoftBank、NTT DATAなどの公式サイトも検索します。

企業公式ドメインのページのうち、次の条件を満たすものを `event` として保存します。

- Physical AI、ロボティクス、ヒューマノイド、自律移動などに関連する
- 主催、共催、参加登録、公式イベントなどの記載がある
- 展示、サミット、カンファレンス、勉強会、ハンズオンなどのイベントである
- 開催終了日または開催日が実行日以降である

企業が他社の展示会に出展するだけの告知は、従来どおり原則として除外します。保存した企業主催イベントの `source_name` は `Corporate Event / <domain>` となります。

## 6. Flask アプリを起動する

データ収集後、次のコマンドでアプリを起動します。

```bash
python3 app.py
```

起動に成功すると、次のような表示が出ます。

```text
 * Running on http://127.0.0.1:5000
```

このプロジェクトの `app.py` では `0.0.0.0:5000` で起動するので、同じPCから開く場合は通常次の URL で見られます。

- `http://127.0.0.1:5000`
- `http://localhost:5000`

### 同一 LAN 内の別 PC からアクセスする

このプロジェクトは `0.0.0.0:5000` で待ち受けるため、同じ LAN に接続された別の PC からもアクセスできます。

まず、Flask アプリを実行する PC で LAN 内 IP アドレスを確認します。

```bash
hostname -I
```

例として `192.168.1.100` と表示された場合、別 PC のブラウザーで次の URL を開きます。

```text
http://192.168.1.100:5000
```

IP アドレスが複数表示された場合は、別 PC と同じ LAN に接続している有線 LAN または Wi-Fi インターフェースの IP アドレスを使います。

接続できない場合は、Flask アプリを実行する PC のファイアウォールで TCP ポート `5000` を許可します。Ubuntu で `ufw` を使っている場合の例:

```bash
sudo ufw allow 5000/tcp
sudo ufw status
```

また、両方の PC が同じ LAN または SSID に接続されていることと、ルーターの AP isolation（プライバシーセパレーター）が有効になっていないことを確認してください。

`app.py` は現在 `debug=True` で起動するため、信頼できる LAN 内でのみ使用し、ルーターでインターネットからポート `5000` を開放しないでください。

### DB テーブルの自動作成

`app.py` 起動時に `db.create_all()` が呼ばれるため、初回起動時は必要なテーブルが自動作成されます。

注意:

- クローラを実行しても Flask アプリは自動起動しません
- 一覧画面を開きたい場合は、別途 `python3 app.py` の実行が必要です

## 7. ブラウザで確認する

一覧画面:

```text
http://127.0.0.1:5000
```

個別詳細画面は、一覧から開けます。

### 一覧画面でできること

- キーワード検索
- `source_name` での絞り込み
- `source_type` での絞り込み
- 最新クローラ実行で取得した記事の `NEW` 表示
- `published_at` / `fetched_at` などでの並び替え
- 各レコードの詳細表示

上部の集計カードからもナビゲーションできます。

- `イベント` カード: 国別ナビゲーションをホバーまたはクリックで表示
- `ニュース` カード: 小カテゴリナビゲーションをホバーまたはクリックで表示

`source_type=event` のときは、`ニュース` 一覧と別に開催国で絞り込めます。

`source_type=news` のときは、次のような小分類で絞り込めます。

- `Physical AI`
- `Robot Makers`
- `Real Haptics`
- `Startup`
- `Google News`
- `その他`

詳細画面では、`raw_summary` と `raw_text` の保存内容を確認できます。

記事詳細では、保存済みの公開日とは別に、実際のページから取得した公開日も確認できます。両者がずれている場合は警告表示されます。

### 月次分析レポート

次の URL から、公開月ごとの分野別件数と国内・海外の Physical AI 動向を確認できます。

```text
http://127.0.0.1:5000/reports
```

各レポートでは次の内容を表示します。

- 月間の収集件数と前月比
- Physical AI、Robot Makers、論文、展示会、政策などの分野別件数
- 国内・海外の Physical AI 関連件数
- 国内・海外で頻出したテーマと代表記事
- キーワード出現に基づく動向の自動要約
- 分野別の横棒グラフ、前月比較、国内・海外比率の円グラフ
- Physical AI、Robot Makers、Startup、論文、展示会、政策などの分野ごとの動向説明

画面から Markdown の表示とダウンロードもできます。Markdown にはSVGグラフを画像として埋め込み、Mermaid版も併記します。コマンドで Markdown ファイルを生成する場合:

```bash
python3 generate_monthly_report.py 2026-08
```

出力先は `reports/2026-08.md` です。グラフ画像は `reports/assets/2026-08/` に生成されます。任意の出力先も指定できます。

```bash
python3 generate_monthly_report.py 2026-08 --output /tmp/techinfo-2026-08.md
```

集計月は `published_at` を使用します。国内・海外の判定はソース名、地名、媒体名、言語に基づく推定のため、重要なレポートでは代表記事も確認してください。

### 海外記事・論文の日本語翻訳

海外ニュースと、日本語で記載されていない論文の見出し・概要は、Google Cloud Translationで日本語に翻訳してDBへ保存できます。原文は上書きされず、一覧画面の「原文を表示」から記事ごとに切り替えられます。

#### Google Cloud Translation APIキーの取得方法

Google公式の[Cloud Translationセットアップ手順](https://docs.cloud.google.com/translate/docs/setup)に沿って設定します。Google Cloud Translationの利用にはGoogle Cloudプロジェクトと請求先アカウントが必要です。

1. [Google Cloud Console](https://console.cloud.google.com/) にGoogleアカウントでログインします。
2. 画面上部のプロジェクト選択から、このアプリ用のプロジェクトを新規作成します。例: `techinfo-aggregator`
3. [Google Cloudのお支払い](https://console.cloud.google.com/billing) を開き、作成したプロジェクトに請求先アカウントを関連付けます。
4. 対象プロジェクトを選択した状態で、[Cloud Translation API](https://console.cloud.google.com/apis/library/translate.googleapis.com) を開き、「有効にする」を押します。
5. [APIとサービス → 認証情報](https://console.cloud.google.com/apis/credentials) を開きます。
6. 「認証情報を作成」→「APIキー」を選びます。
7. 生成されたAPIキーを一度だけコピーし、「APIキーを編集」へ進みます。

#### APIキーに制限を設定する

APIキーが他のGoogle Cloud APIに使われないよう、Google公式の[APIキー管理手順](https://docs.cloud.google.com/docs/authentication/api-keys)を参考に次の制限を設定します。

1. 「APIの制限」で「キーを制限」を選びます。
2. 利用可能なAPIは「Cloud Translation API」だけを選びます。
3. 「保存」を押します。反映に数分かかる場合があります。

このプロジェクトはPythonサーバーからCloud Translation APIを呼び出すため、ブラウザー用のHTTPリファラー制限は使いません。実行PCが固定のグローバルIPアドレスを持つ場合は、追加で「アプリケーションの制限 → IPアドレス」を設定できます。`192.168.x.x`、`10.x.x.x`、`localhost` などのローカルアドレスはGoogle CloudのIP制限に使用できません。固定グローバルIPがない場合でも、Cloud Translation APIのAPI制限は必ず設定してください。

#### `.env` にAPIキーを設定する

プロジェクト直下の `.env` に、コピーしたAPIキーを設定します。

```dotenv
GOOGLE_TRANSLATE_API_KEY="your-google-cloud-api-key"
GOOGLE_TRANSLATE_MONTHLY_CHARACTER_LIMIT="450000"
```

`.env` の権限とGit除外状態を確認します。

```bash
chmod 600 .env
git check-ignore .env
```

`git check-ignore .env` で `.env` が表示されれば、Gitの除外対象です。APIキーをREADME、`.env.example`、ソースコードに直接書かないでください。

#### APIの接続を確認する

次のコマンドは `.env` からAPIキーを読み、`Physical AI` だけを日本語に翻訳します。APIキー自体は表示しません。

```bash
python3 - <<'PY'
from env_loader import load_project_env
from translation_service import GoogleCloudTranslator

load_project_env()
translator = GoogleCloudTranslator()
translated, source_language = translator.translate(["Physical AI"])
print("source_language:", source_language)
print("translated:", translated[0])
PY
```

成功時は次のように表示されます。

```text
source_language: en
translated: フィジカル AI
```

#### 既存データを少量で試す

この環境変数が設定されている場合、新規収集される `news` と `paper` は保存時に自動翻訳されます。APIエラー時も原文の保存は継続します。

既存データの対象数を確認する場合:

```bash
python3 backfill_japanese_translations.py --dry-run --limit 0
```

論文をすべて翻訳する場合:

```bash
python3 backfill_japanese_translations.py --source-type paper --limit 0
```

海外ニュースを含む全対象を翻訳する場合:

```bash
python3 backfill_japanese_translations.py --limit 0
```

大量の翻訳にはGoogle Cloud Translationの利用料金が発生する可能性があるため、最初は `--limit 100` などで翻訳品質と課金量を確認してください。

```bash
python3 backfill_japanese_translations.py --source-type paper --limit 10
```

#### 無料利用範囲に抑える

2026年8月時点のGoogle公式料金表では、Cloud Translation BasicとAdvancedのNMTテキスト翻訳に対し、毎月最初の50万文字分に相当する10 USDのクレジットが適用されます。料金や条件は変更される可能性があるため、必ず[Cloud Translation料金表](https://cloud.google.com/translate/pricing)も確認してください。

このプロジェクトでは無料分に余裕を持たせるため、既定の月間上限を45万文字にしています。

```dotenv
GOOGLE_TRANSLATE_MONTHLY_CHARACTER_LIMIT="450000"
```

翻訳に成功した入力文字数は `instance/translation_usage.json` に月別で記録されます。今月の使用量と残り文字数は次のコマンドで確認できます。

```bash
python3 backfill_japanese_translations.py --show-usage
```

上限を超える翻訳リクエストはAPI送信前に停止します。新規クロール時は翻訳だけをスキップし、原文の保存は継続します。

ただし、このローカル記録で把握できるのはこのアプリからの利用量だけです。同じGoogle CloudプロジェクトやAPIキーを他のアプリで使うと、Google側の合計利用量と一致しません。翻訳専用のGoogle CloudプロジェクトとAPIキーを使い、Google Cloud Console側でも割り当て量、請求額、予算アラートを設定してください。予算アラートは通知であり、課金を自動停止する機能ではありません。

#### トラブルシューティング

- `GOOGLE_TRANSLATE_API_KEY is not configured`: `.env` の値が空でないか確認します。
- `403 Forbidden` / `PERMISSION_DENIED`: 対象プロジェクト、請求先設定、Cloud Translation APIの有効化、APIキーのAPI制限を確認します。
- `400 Bad Request` / `API key not valid`: APIキーのコピーミス、余分な空白、引用符の対応を確認します。
- `429 Too Many Requests` / `RESOURCE_EXHAUSTED`: APIの割り当て量と請求額を確認し、`--limit` で処理数を小さくして再実行します。

### Physical AI Google Trends

Physical AI関連キーワードの過去12か月のGoogle検索関心度を、日本と世界に分けて収集できます。

```bash
python3 -m crawlers.google_trends_crawler
```

任意のキーワードを指定する場合:

```bash
python3 -m crawlers.google_trends_crawler --keywords "Physical AI" "フィジカルAI" "Humanoid Robot"
```

収集結果は次の画面で表示します。

```text
http://127.0.0.1:5000/trends
```

日本と世界のトレンド推移、最新値、平均値、最高値、Google Trends公式Explore画面へのリンクをキーワードごとに確認できます。値は各期間・地域内の最高点を100とする相対値です。

グラフの横軸は日付（左が開始日、右が終了日）で、取得データから日次・週次・月次の間隔を自動判定して表示します。縦軸は検索関心度の相対値（0〜100）です。

Google Trendsの公式APIは現在申請制アルファのため、取得仕様の変更や一時的なレート制限によりデータ取得に失敗する可能性があります。失敗時でも日次処理は継続し、公式Exploreリンクは表示されます。

## 8. よく使う一連のコマンド

毎回の起動手順をまとめると次の通りです。

```bash
cd ~/ドキュメント/TechInfo_Aggregator
source .venv/bin/activate
pip install -r requirements.txt
python3 -m crawlers.exhibition_crawler
python3 app.py
```

展示会以外もまとめて収集したい場合の例:

```bash
cd ~/ドキュメント/TechInfo_Aggregator
source .venv/bin/activate
python3 -m crawlers.arxiv_crawler
python3 -m crawlers.google_news_crawler
python3 -m crawlers.google_trends_crawler
python3 -m crawlers.exhibition_crawler
python3 -m crawlers.real_haptics_crawler
python3 -m crawlers.thinktank_crawler
python3 -m crawlers.government_policy_crawler
python3 app.py
```

## 9. 日次実行スクリプト

まとめてクローラを実行するためのスクリプトがあります。

```bash
./run_daily_crwalers.sh
```

実行権限が無い場合:

```bash
chmod +x run_daily_crwalers.sh
./run_daily_crwalers.sh
```

このスクリプトは次を順番に実行します。

- `reset_raw_items.py`
- `crawlers.arxiv_crawler`
- `crawlers.google_news_crawler`
- `crawlers.google_trends_crawler`
- `crawlers.exhibition_crawler`
- `crawlers.real_haptics_crawler`
- `crawlers.thinktank_crawler`
- `crawlers.government_policy_crawler`
- `cleanup_raw_item_duplicates.py`
- `send_new_items_gmail.py`

このとき 1 回の実行全体に同じ `crawl_batch_id` が付きます。UI の `NEW` ラベルは、この最新 `crawl_batch_id` に属する記事に対して付きます。

ログ出力先:

```text
logs/daily_crawlers.log
```

## 10. DB ファイルについて

SQLite の DB は次に作成されます。

```text
instance/techinfo.db
```

クローラを実行すると、ここに収集結果が保存されます。

中身をすべて消して最初から取り直したい場合は、次のリセット用スクリプトを使えます。

```bash
python3 reset_raw_items.py
```

これは `raw_items` テーブルの内容を削除します。

### 重複データを整理したい場合

既存 DB に入ってしまった重複データを整理したい場合は、次のスクリプトを使えます。

```bash
python3 cleanup_raw_item_duplicates.py
```

このスクリプトは次の重複を削除します。

- 正規化 URL が同じレコード
- `source_name + title + published_at` が同じレコード

日次実行スクリプトの最後でも自動実行されます。

### 新規記事だけを Gmail 送信したい場合

日次実行の最後に `send_new_items_gmail.py` を実行すると、その回の収集結果のうち「まだ一度も通知していない記事」だけを Gmail 送信できます。

このプロジェクトでは毎回 `reset_raw_items.py` を実行して DB を作り直しても差分通知できるように、通知済み状態を別ファイルに保存します。

保存先:

```text
instance/notified_items.json
```

必要な値を `.env` に設定します。

```dotenv
GMAIL_SENDER="your-address@gmail.com"
GMAIL_APP_PASSWORD="your-app-password"
GMAIL_RECIPIENT="your-address@gmail.com"
```

複数宛先に送りたい場合:

```dotenv
GMAIL_RECIPIENT="a@example.com,b@example.com"
```

Gmail は通常のログインパスワードではなく、Google アカウントのアプリパスワードを使ってください。

単体で動作確認したい場合:

```bash
python3 send_new_items_gmail.py --dry-run
```

件数を絞ってテストしたい場合:

```bash
python3 send_new_items_gmail.py --dry-run --limit 5
python3 send_new_items_gmail.py --limit 5
```

実際に送信する場合:

```bash
python3 send_new_items_gmail.py
```

## 11. 仮想環境を抜ける

作業が終わったら、仮想環境は次のコマンドで抜けられます。

```bash
deactivate
```

## 12. エラーが出たとき

### `ModuleNotFoundError: No module named 'bs4'`

仮想環境に入っていないか、パッケージ未インストールです。

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `ModuleNotFoundError: No module named 'feedparser'`

同じく、依存関係の未インストールです。

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `Address already in use`

5000 番ポートがすでに使われています。別の Python プロセスが起動中の可能性があります。

確認:

```bash
ss -ltnp | grep 5000
```

停止してから再実行するか、`app.py` のポート番号を変更してください。

### ブラウザで開けない

同じPCからの確認なら、まずこれを試してください。

```text
http://127.0.0.1:5000
```

別PCからアクセスする場合は、サーバー側のIP、ファイアウォール、バインドアドレスの確認が必要です。

### クローラ実行時にタイムアウトや取得失敗が出る

外部サイト側の応答遅延や一時的なブロックで失敗することがあります。

対処:

- 少し時間をおいて再実行する
- まず単体クローラで試す
- `logs/daily_crawlers.log` を確認する

### Google News にノイズ記事が混ざる

`Google News / Robot Makers` では、`UR` を `Universal Robots` の意味で集めています。`UR都市機構` や `URBAN RESEARCH` のような曖昧一致は除外するように調整済みです。

ノイズが残る場合は、まず次を単体で再実行してください。

```bash
python3 -m crawlers.google_news_crawler
```

### `403 Forbidden` や `429 Too Many Requests` が出る

一部サイト、特にみずほ系ページではアクセス制限がかかることがあります。

このプロジェクトでは、みずほ向けで `r.jina.ai` を使った回避経路を入れていますが、それでも短時間に連続アクセスすると `429 Too Many Requests` が出ることがあります。

対処:

- 少し時間をおいて再実行する
- まず `python3 -m crawlers.mizuho_rt_crawler` を単体で試す
- 必要なら日次実行の間隔を見直す

### Gmail が送れない

`send_new_items_gmail.py` 実行時に Gmail 送信がスキップされる場合は、環境変数が足りていない可能性があります。

確認項目:

- `GMAIL_SENDER`
- `GMAIL_APP_PASSWORD`
- `GMAIL_RECIPIENT`

`--dry-run` で本文が出るかを先に確認すると切り分けしやすいです。

## 13. 補足

- 依存関係を追加したら、`requirements.txt` も更新してください。
- Remote SSH で作業している場合も、コマンドは基本的に同じです。
- 展示会クローラを実行してから `app.py` を起動すると、一覧画面にデータが出やすいです。
