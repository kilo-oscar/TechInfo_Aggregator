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

### DB テーブルの自動作成

`app.py` 起動時に `db.create_all()` が呼ばれるため、初回起動時は必要なテーブルが自動作成されます。

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
- `published_at` / `fetched_at` などでの並び替え
- 各レコードの詳細表示

詳細画面では、`raw_summary` と `raw_text` の保存内容を確認できます。

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
- `crawlers.exhibition_crawler`
- `crawlers.real_haptics_crawler`
- `crawlers.thinktank_crawler`
- `crawlers.government_policy_crawler`
- `cleanup_raw_item_duplicates.py`

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

### `403 Forbidden` や `429 Too Many Requests` が出る

一部サイト、特にみずほ系ページではアクセス制限がかかることがあります。

このプロジェクトでは、みずほ向けで `r.jina.ai` を使った回避経路を入れていますが、それでも短時間に連続アクセスすると `429 Too Many Requests` が出ることがあります。

対処:

- 少し時間をおいて再実行する
- まず `python3 -m crawlers.mizuho_rt_crawler` を単体で試す
- 必要なら日次実行の間隔を見直す

## 13. 補足

- 依存関係を追加したら、`requirements.txt` も更新してください。
- Remote SSH で作業している場合も、コマンドは基本的に同じです。
- 展示会クローラを実行してから `app.py` を起動すると、一覧画面にデータが出やすいです。
