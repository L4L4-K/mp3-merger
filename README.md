# MP3 Merger

ブラウザにドラッグ＆ドロップした MP3 ファイルを、指定した順番で 1 つの MP3 に結合する Docker 対応 Web アプリです。

## 機能

- 複数 MP3 のドラッグ＆ドロップ
- 一覧上でのドラッグ並べ替え
- ↑ ↓ ボタンによる順番変更
- 不要ファイルの削除
- FFmpeg による再エンコード結合
- 結合後の `merged.mp3` 自動ダウンロード

## 起動方法

```bash
docker compose up --build
```

ブラウザで次を開きます。

```text
http://localhost:8000
```

Docker Compose を使わない場合は次で起動できます。

```bash
docker build -t mp3-merger .
docker run --rm -p 8000:8000 mp3-merger
```

## 設定

`docker-compose.yml` の environment で変更できます。

| 変数 | 既定値 | 説明 |
|---|---:|---|
| `MAX_FILES` | `100` | 一度に結合できる最大ファイル数 |
| `MAX_TOTAL_BYTES` | `1073741824` | アップロード合計サイズ上限。既定は 1 GiB |
| `MP3_QUALITY` | `2` | FFmpeg libmp3lame の VBR 品質。小さいほど高品質 |
| `OUTPUT_SAMPLE_RATE` | `44100` | 出力サンプルレート |
| `OUTPUT_CHANNEL_LAYOUT` | `stereo` | 出力チャンネル。例: `stereo`, `mono` |

## 実装メモ

MP3 ファイルを単純にバイト列として連結すると壊れたファイルになる可能性があります。このアプリでは FFmpeg で各入力を同じサンプルレート、同じチャンネルに正規化し、concat filter で結合してから MP3 に再エンコードします。

## ディレクトリ構成

```text
.
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app
│   └── main.py
└── static
    ├── index.html
    ├── styles.css
    └── app.js
```
