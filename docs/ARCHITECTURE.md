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
- `src/providers/textract.py`: Extractor の Textract 実装。S3 へのアップロード、sha256 による生 JSON キャッシュ、非同期ジョブのポーリング (指数バックオフ、NextToken のページング)。
- `src/providers/textract_parse.py`: Textract の生 JSON を `ExtractedDocument` に変換する純粋関数 (boto3 に依存しない)。
- `scripts/extract_pdf.py`: ローカルの PDF 1 本を Textract で処理し、`data/extracted/<doc_id>.json` に保存する CLI。課金前に確認を求める。
- `tests/fixtures/textract_layout_sample.json`: 手作りの小さな Textract 応答 (合成テキスト、2 段組・ヘッダ・フッタ・空ページを含む 3 ページ)。
- `tests/test_textract_parse.py`: 変換規則のテスト。
- `tests/test_textract_extractor.py`: キャッシュ判定、ポーリング、ページング、失敗時の扱いのテスト。S3 と Textract は自作のフェイク。
- `tests/test_textract_integration.py`: 本物の S3 と Textract を呼ぶテスト (`-m integration` のときだけ実行)。

## 設計メモ

### プロバイダのインターフェース
外部サービス (Textract、Bedrock、Pinecone) はすべて `src/providers/base.py` の Protocol 越しに呼ぶ。Protocol は継承不要で、同じメソッドを持つクラスなら差し替えられる。Bedrock が使えなくても、フェイクで全体を動かせる。

Extractor は Textract の生 JSON ではなく、自前の `ExtractedDocument` を返す。チャンキングを Textract に依存させないため。

### チャンキングの規則
1. チャンクはページをまたがない。引用のページ番号を正確にするため (例外は規則 6 の見出しだけ)。
2. 行の縦の隙間が行の高さの半分より大きければ、新しい段落とみなす。
3. `4.8 Undesirable effects` のような番号付き見出し (番号の後が大文字、80 文字以内) で新しいチャンクを始め、`section` に記録する。`section` は次の見出しまでページをまたいで引き継ぐ。
4. 段落を最大 500 語まで 1 チャンクに詰め、次のチャンクの先頭に前のチャンクの末尾 50 語を重ねる。トークン数は空白区切りの単語数で近似する (特定の tokenizer に依存しないため)。
5. 表は分割せず 1 表 = 1 チャンクで、Markdown 表にする。表の `section` は、表より上にある最後の見出しから決める。
6. 見出しだけのチャンク (例: `4. CLINICAL PARTICULARS` の直後に `4.1 ...` が来る場合) は作らず、すぐ次のチャンクの先頭に付ける。次のチャンクが別のページでも付け、ページと `section` は次のチャンクのものを使う (本文がある側のページを引用するため)。規則 1 の唯一の例外。見出しと短い本文がそろったチャンクはそのまま残す。文書の最後の見出しは付け先がないので単独で残る。ただし扉のページ (行がすべて見出しのページ) はまたがない。扉の見出しが来た時点で、普通のページから待っていた見出しは元のページに単独のチャンクとして残す。前の部の最後の見出しが、次の部の先頭として引用されるのを防ぐため (Aubagio の `3. To encourage ...` と `5. OTHER` で確認)。
7. `chunk_id` は `{doc_id}:p{ページ}:c{連番}` で決定的に決まる。再実行しても同じ ID になり、上書き (upsert) が重複を作らない。

既知の制約:
- 2 段組のページは行の順序が崩れると段落判定が不正確になる (Textract LAYOUT の読み順で緩和、下記)。
- 番号付きの箇条書き (例: Aubagio の `3. To encourage the patients to read the PIL thoroughly`) が、規則 3 の正規表現で見出しと誤判定されることがある。
- 部の単位 (`A. LABELLING` など) は `section` には残らない (本文には残るので検索はできる)。必要なら M3 以降に別の項目として追加する。

規則 3 の見出しには、抽出側が見出しと判定した行 (`Line.is_heading`) も含む。番号のない見出しも拾える。

### Textract 抽出とキャッシュ
1. PDF は `s3://<S3_BUCKET>/raw/` に置く。M6 で EventBridge が監視する `incoming/` とは分け、M2 の作業でパイプラインが動かないようにする。
2. PDF の sha256 をキーに、生 JSON を `textract-cache/<sha256>.json` に保存する。キャッシュがあれば Textract を呼ばない (同じ PDF に二度課金しない)。ファイル名ではなく中身で判定するので、名前を変えても再実行されない。
3. キャッシュの読み込みで AccessDenied が出たら「ミス」とみなさず例外にする。権限不足のまま課金が発生するのを防ぐため。
4. 非同期 API (StartDocumentAnalysis / GetDocumentAnalysis) を使う。PDF の複数ページを扱えるのは非同期 API だけだから。待ち時間は 2 秒から倍々、上限 30 秒、合計 600 秒でタイムアウト。
5. 結果は 1 回の応答に収まらないので、`NextToken` がなくなるまで取得して Blocks を連結する。
6. FAILED と PARTIAL_SUCCESS は例外にし、キャッシュに書かない (不完全な結果を再利用しないため)。
7. `doc_id` は sha256 の先頭 16 文字。同じ PDF なら常に同じ ID になり、chunk_id も安定する。
8. FeatureTypes は LAYOUT のみ。表のセル内容は取らず (`tables` は空)、表内の文字は通常の行になる。TABLES との比較は Tier 3。

### Textract JSON の変換規則
1. 行の順序は LAYOUT ブロックの返却順 (Textract の読み順) に従う。2 段組でも左の段を読み終えてから右の段に進む。
2. どの LAYOUT にも属さない行は、ページの最後に縦位置順で足す。
3. LAYOUT_TITLE と LAYOUT_SECTION_HEADER は、1 ブロックの中の行を空白でつないで 1 本の行にし、`is_heading=True` にする。Textract は `4.8 Undesirable effects` を `4.8` と `Undesirable effects` の 2 行で返すことが多い。つながないと、番号だけのチャンクができ、`section` も `4.8` だけになる (実文書の Cablivi で確認した)。
4. 捨てるのは LAYOUT_PAGE_NUMBER の行だけ。LAYOUT_HEADER / LAYOUT_FOOTER の行は残す。Cablivi では HEADER / FOOTER の 8 箇所がすべて本文の誤分類だった (17・28 ページの扉、16 ページの ANNEX III の扉、10・11 ページの 6.1 の添加物、21〜23 ページの箱の表示)。繰り返しヘッダのある文書を追加するときは、同じ文字列が複数ページに出るときだけ捨てる方式に切り替える。
5. ページ番号を除いた行が 2 行以下のページは扉とみなし、その行を見出し (`is_heading=True`) にする。`A. LABELLING` などの扉は Textract がフッタに分類し、番号付き見出しの正規表現にも合わないため。見出しになれば、チャンキング規則 6 で次のチャンクの先頭に付き、`section` も切り替わる。本文が 2 行以下しかないページも見出し扱いになる点は既知の制約。
6. 空のページも `Page` として残し、ページ番号がずれないようにする。
