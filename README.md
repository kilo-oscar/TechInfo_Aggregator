# TechInfo_Aggregator

Physical AI / Robotics 関連の情報を収集して、Flask で一覧表示するアプリです。

この README では、次の流れを順番に説明します。

1. プロジェクトフォルダに移動する
2. 仮想環境に入る
3. `requirements.txt` から必要なパッケージをインストールする
4. クローラを実行してデータを収集する
5. クローラを実行してデータを収集する
6. Flask アプリを起動する
7. ブラウザで確認する

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

## 7. ブラウザで確認する

一覧画面:

```text
http://127.0.0.1:5000
```

個別詳細画面は、一覧から開けます。

## 8. よく使う一連のコマンド

毎回の起動手順をまとめると次の通りです。

```bash
cd ~/ドキュメント/TechInfo_Aggregator
source .venv/bin/activate
pip install -r requirements.txt
python3 -m crawlers.exhibition_crawler
python3 app.py
```

## 9. DB ファイルについて

SQLite の DB は次に作成されます。

```text
instance/techinfo.db
```

クローラを実行すると、ここに収集結果が保存されます。

## 10. 仮想環境を抜ける

作業が終わったら、仮想環境は次のコマンドで抜けられます。

```bash
deactivate
```

## 11. エラーが出たとき

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

## 12. 補足

- 依存関係を追加したら、`requirements.txt` も更新してください。
- Remote SSH で作業している場合も、コマンドは基本的に同じです。
- 展示会クローラを実行してから `app.py` を起動すると、一覧画面にデータが出やすいです。
