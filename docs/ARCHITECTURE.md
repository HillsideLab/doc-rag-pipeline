# アーキテクチャ

全体設計は `SPEC.md` を参照。このファイルでは各ファイルの役割を 1 行ずつ説明する。

## ファイル一覧

- `SPEC.md`: プロジェクトの仕様書。範囲・構成・マイルストーンの正とする文書。
- `CLAUDE.md`: Claude Code 向けの作業ルール (手順、禁止事項、コマンド)。
- `README.md`: 英語の概要とセットアップ手順。
- `pyproject.toml`: uv のプロジェクト定義。依存関係と ruff / pytest の設定をまとめる。
- `uv.lock`: 依存バージョンの固定。CI でも同じバージョンを使うためにコミットする。
- `.python-version`: uv が使う Python のバージョン (3.12)。
- `.gitignore`: `.env`、仮想環境、PDF、Terraform state などをコミット対象から外す。
- `.env.example`: 環境変数の雛形。値は空かダミーのみで、実際の値は git 管理外の `.env` に書く。
- `.github/workflows/ci.yml`: GitHub Actions。AWS 認証情報なしで ruff と pytest を実行する。
- `src/__init__.py`: `src` をパッケージとして import できるようにする (中身は空)。
- `tests/__init__.py`: テストディレクトリをパッケージにする (中身は空)。
- `tests/test_smoke.py`: テストが 0 件で pytest が失敗しないための最小テスト。
- `src/models.py`: 全工程で共有する Pydantic モデル (抽出結果、チャンク、検索結果、回答と引用、処理ステータス)。
- `src/providers/__init__.py`: `providers` をパッケージにする (中身は空)。
- `src/providers/base.py`: 外部サービスのインターフェース (Extractor / Embedder / VectorStore / Generator) を Protocol で定義。埋め込み次元 1024 もここで定める。
- `src/providers/fakes.py`: ネットワーク不要のフェイク実装。テストとローカル実行の既定値。
- `src/chunking.py`: 抽出結果をチャンクに分割する。ルールは下記。
- `tests/conftest.py`: テスト共通の fixture (サンプル文書の読み込み)。
- `tests/fixtures/extracted_sample.json`: 自作の合成サンプル (実在の文書ではない)。SmPC 風の見出し・段落・表を含む 2 ページ。
- `tests/test_models.py`: モデルの入力検証のテスト。
- `tests/test_chunking.py`: チャンキング規則のテスト。
- `tests/test_fakes.py`: フェイク実装がインターフェースを満たし、正しく動くことのテスト。
- `tests/test_offline_pipeline.py`: 抽出から引用付き回答までをフェイクだけで通す結合テスト。

## 設計メモ

### プロバイダのインターフェース
外部サービス (Textract、Bedrock、Pinecone) はすべて `src/providers/base.py` の Protocol 越しに呼ぶ。Protocol は継承不要で、同じメソッドを持つクラスなら差し替えられる。Bedrock が使えなくても、フェイクで全体を動かせる。

Extractor は Textract の生 JSON ではなく、自前の `ExtractedDocument` を返す。チャンキングを Textract に依存させないため。

### チャンキングの規則
1. チャンクはページをまたがない。引用のページ番号を正確にするため。
2. 行の縦の隙間が行の高さの半分より大きければ、新しい段落とみなす。
3. `4.8 Undesirable effects` のような番号付き見出し (番号の後が大文字、80 文字以内) で新しいチャンクを始め、`section` に記録する。`section` は次の見出しまでページをまたいで引き継ぐ。
4. 段落を最大 500 語まで 1 チャンクに詰め、次のチャンクの先頭に前のチャンクの末尾 50 語を重ねる。トークン数は空白区切りの単語数で近似する (特定の tokenizer に依存しないため)。
5. 表は分割せず 1 表 = 1 チャンクで、Markdown 表にする。表の `section` は、表より上にある最後の見出しから決める。
6. `chunk_id` は `{doc_id}:p{ページ}:c{連番}` で決定的に決まる。再実行しても同じ ID になり、上書き (upsert) が重複を作らない。

既知の制約: 2 段組のページは行の順序が崩れると段落判定が不正確になる。
