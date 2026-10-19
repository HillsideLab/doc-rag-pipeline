# アーキテクチャ

全体設計は `SPEC.md` を参照。このファイルでは各ファイルの役割を 1 行ずつ説明する。

## ファイル一覧

- `SPEC.md`: プロジェクトの仕様書。範囲・構成・マイルストーンの正とする文書。
- `CLAUDE.md`: Claude Code 向けの作業ルール (手順、禁止事項、コマンド)。
- `README.md`: 英語の概要とセットアップ手順。
- `pyproject.toml`: uv のプロジェクト定義。依存関係と ruff / pytest の設定をまとめる。
- `uv.lock`: 依存バージョンの固定。CI でも同じバージョンを使うためにコミットする。
- `.python-version`: uv が使う Python のバージョン (3.12)。
- `.gitignore`: `.env`、仮想環境、PDF、Terraform の state と plan ファイル、Lambda のビルド結果 (`build/`) などをコミット対象から外す。
- `.env.example`: 環境変数の雛形。値は空かダミーのみで、実際の値は git 管理外の `.env` に書く。
- `.github/workflows/ci.yml`: GitHub Actions。AWS 認証情報なしで ruff と pytest、Lambda の zip の作成と `terraform fmt -check` / `validate`、`docs/openapi.json` がコードと一致するかの確認を実行する。
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
- `src/providers/textract.py`: Extractor の Textract 実装。S3 へのアップロード、sha256 による生 JSON キャッシュ、非同期ジョブのポーリング (指数バックオフ、NextToken のページング)。Step Functions 用に、1 回だけの状態確認 (`job_status`) と、完了済みジョブの結果の取得 (`fetch_result`) も持つ。
- `src/providers/textract_parse.py`: Textract の生 JSON を `ExtractedDocument` に変換する純粋関数 (boto3 に依存しない)。
- `scripts/extract_pdf.py`: ローカルの PDF 1 本を Textract で処理し、`data/extracted/<doc_id>.json` に保存する CLI。課金前に確認を求める。
- `tests/fixtures/textract_layout_sample.json`: 手作りの小さな Textract 応答 (合成テキスト、2 段組・ヘッダ・フッタ・空ページを含む 3 ページ)。
- `tests/test_textract_parse.py`: 変換規則のテスト。
- `tests/test_textract_extractor.py`: キャッシュ判定、ポーリング、ページング、失敗時の扱いのテスト。S3 と Textract は自作のフェイク。
- `tests/test_textract_integration.py`: 本物の S3 と Textract を呼ぶテスト (`-m integration` のときだけ実行)。
- `src/indexing.py`: 埋め込む文字列の組み立て (section + 本文)、1 文書の登録 (入れ直し)、質問での検索。どの Embedder / VectorStore でも動く。
- `src/providers/pinecone.py`: Embedder と Reranker の Pinecone Inference API 実装と、VectorStore の Pinecone 実装 (dense インデックス)。埋め込みとリランクのモデル名はどちらも環境変数で必須 (コードに既定値なし)。
- `scripts/index_documents.py`: `data/extracted/` の抽出結果をチャンクに分け、Pinecone に登録する CLI。書き込み前に確認を求める。Textract は呼ばない。
- `scripts/search.py`: 質問を投げ、上位のチャンク (chunk_id、ページ、section、スコア) を表示する CLI。読み取りのみ。
- `tests/test_indexing.py`: 埋め込む文字列の規則、入れ直しで古いチャンクが残らないこと、doc_id での絞り込みのテスト (フェイクのみ)。
- `tests/test_pinecone_provider.py`: Pinecone 実装のテスト。SDK のオブジェクトは自作のフェイクで、通信しない。
- `tests/test_pinecone_integration.py`: 本物の Pinecone を呼ぶテスト。専用の namespace を使い、最後に消す (`-m integration` のときだけ実行)。
- `eval/retrieval_questions.json`: 検索の評価用の質問 5 問と、上位に出てほしい chunk_id。
- `src/evaluation.py`: 評価の質問の読み込みと、hit@k / recall@k の計算 (純粋関数)。
- `scripts/eval_retrieval.py`: 評価の質問を本物の Pinecone で検索し、hit@k と recall@k を表示する CLI (`--rerank` でリランクあり)。読み取りのみ。
- `tests/test_evaluation.py`: hit@k / recall@k の計算と、質問ファイルの形式のテスト。
- `src/citations.py`: チャンクから出典 (chunk_id、ファイル、製品名、section、ページ、種類) と、回答やプロンプトに出す 1 行の表示を作る。すべての Generator が使う。
- `src/answering.py`: 質問応答の本体 `answer_question` (検索 → 生成 → 免責の文を付ける)。CLI、API (M5)、Lambda (M6) から同じ関数を呼ぶ。
- `src/providers/factory.py`: 環境変数 `EMBEDDER` / `VECTOR_STORE` / `RERANKER` / `GENERATOR` から実装を選ぶ。既定はすべてフェイク。API 用に、選んだ名前だけを返す `selected()` と、`PINECONE_NAMESPACE` を読む `pinecone_namespace()` (必須、`__default__` は default namespace) も持つ。
- `src/providers/bedrock.py`: Generator の Bedrock Claude 実装 (Converse API、推論プロファイル ID)。**未検証** (アカウントの制限で Bedrock を呼べないため、フェイクのクライアントでのみテスト)。
- `scripts/ask.py`: 質問 1 つに答え、回答・出典・免責の文を表示する CLI。実装は環境変数で選ぶ。読み取りのみ。
- `scripts/eval_answers.py`: 評価セットの 5 問に答え、出典に正解のチャンクが含まれるかを数え、使った量を表示する CLI。読み取りのみ。
- `tests/test_answering.py`: 出典の項目、免責の文、0 件、doc_id での絞り込み、リランクの順序のテスト。
- `tests/test_factory.py`: 既定値がフェイクであること、知らない値や禁止の組み合わせ、必須の変数がないときのテスト。本物のクライアントは作らない。
- `tests/test_bedrock_generator.py`: Bedrock 実装のテスト。bedrock-runtime は自作のフェイクで、通信しない。
- `src/pipeline/__init__.py`: `pipeline` をパッケージにする (中身は空)。
- `src/pipeline/steps.py`: Step Functions の工程ごとの関数 (登録、Textract の開始・確認・保存、チャンク化と登録)。クライアントは引数で受け取る。再試行させる例外 `TransientError` もここで定める。
- `src/pipeline/handlers.py`: Lambda のハンドラ 5 つ。環境変数を読み、クライアントを作り (コンテナが温かい間は再利用)、`steps.py` を呼ぶだけ。Pinecone のキーは Secrets Manager から読む。
- `src/pipeline/logging_json.py`: Lambda と API のログを 1 行 1 JSON にする。Lambda は `document_id`、`execution_arn`、`step`、`status`、API は `request_id`、`method`、`path`、`status_code`、`duration_ms` と起動時の provider 名を付ける。質問文、本文、キーは出さない。
- `scripts/build_lambda.sh`: Lambda 用の zip (`build/lambda.zip`) を作る。`src/` と、Linux x86_64 / Python 3.12 用の依存関係。boto3 と numpy は入れない。
- `scripts/cleanup.sh`: M6 で作ったものを片付ける (Pinecone の `pipeline` namespace、`incoming/` のファイル、`terraform destroy`)。段階ごとに確認を取る。最後に、deployer ポリシーを root で外す手作業の手順を表示する。
- `infra/versions.tf`: Terraform と AWS provider のバージョン、ローカル state、全リソースのタグ `Project=doc-rag-mock`。リージョンと認証情報は環境変数から読む。
- `infra/variables.tf`: Terraform の変数 (バケット名、Pinecone のインデックス・namespace・モデル、テスト用の `force_fail_step`)。`force_fail_step` 以外は既定値なし。
- `infra/dynamodb.tf`: 文書の処理状態のテーブル (`doc_id` のみのキー、オンデマンド)。
- `infra/secrets.tf`: Pinecone の API キーを入れる Secrets Manager の入れ物。値は手で入れる。
- `infra/lambda.tf`: Lambda 関数 5 つと、関数ごとのロール (最小権限) とロググループ (7 日保持)。
- `infra/stepfunctions.tf`: ステートマシンとそのロール。
- `infra/statemachine.asl.json`: ステートマシンの定義 (状態の流れ、再試行、失敗時の経路)。
- `infra/events.tf`: 既存バケットの EventBridge 通知の有効化、`incoming/` だけを拾うルール、ステートマシンを起動するロール。
- `infra/outputs.tf`: ステートマシンの ARN、テーブル名、シークレットの ARN などの出力。
- `infra/.terraform.lock.hcl`: AWS provider のバージョンとハッシュの固定。CI でも同じものを使うためにコミットする。
- `infra/deployer-policy.json`: `terraform apply` のために `rag-mock` ユーザーへ追加する IAM ポリシー。リソース名 `doc-rag-mock-*` に限定。
- `tests/aws_fakes.py`: S3 / Textract / DynamoDB / Secrets Manager の小さなフェイク。複数のテストで共有する。
- `tests/test_pipeline_steps.py`: 工程ごとの関数のテスト (キャッシュの有無、ジョブの状態、タイムアウト、DynamoDB に書く内容)。
- `tests/test_pipeline_handlers.py`: ハンドラのテスト (別のバケットの拒否、`FORCE_FAIL_STEP`、ログが JSON で本文やキーを含まないこと、キーの読み込みが 1 回だけなこと)。
- `tests/test_state_machine.py`: ステートマシンの定義のテスト (再試行は計 3 回、失敗時は必ず MarkFailed、キャッシュがあれば Textract を飛ばす、遷移先が存在する)。
- `src/api/__init__.py`: `api` をパッケージにする (中身は空)。
- `src/api/schemas.py`: API の入力 (`AskRequest`: 質問は 1〜1000 文字、`top_k` は 1〜20、Swagger の例の質問)、エラー (`ErrorResponse`)、`/health` の応答。`/ask` の応答はコアの `Answer` をそのまま使う。
- `src/api/main.py`: FastAPI のアプリ。`POST /ask` (`answer_question` を呼ぶだけ) と `GET /health`。provider は起動時に 1 回だけ組み立てる。外部サービスの失敗は 502 で、内部情報を返さない。リクエストごとに JSON のログを 1 行出す。
- `src/api/__main__.py`: `python -m src.api` で API を起動する。認証がないので `127.0.0.1` だけで待ち受ける。
- `scripts/export_openapi.py`: OpenAPI の定義を `docs/openapi.json` に書き出す。`--check` で、コミット済みのものとコードが一致するかを確かめる (CI で使う)。
- `docs/openapi.json`: コードから生成した OpenAPI の定義。手で編集しない。
- `tests/test_api.py`: API のテスト (TestClient とフェイクのみ)。正常系、入力の検証 (422)、外部エラー (502 で内部情報を出さない)、ログに質問文が出ないこと、起動ログ、`/health`、`docs/openapi.json` との一致。

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

### 埋め込みと Pinecone への登録
1. インデックス `doc-rag-mock` は普通の dense インデックス (1024 次元、cosine、serverless aws us-east-1、組み込みの埋め込みモデルなし)。`describe_index` の `embed` が None であることで確認した。埋め込みは Pinecone Inference API で作り、ベクトルとして upsert する。
2. 埋め込みモデルは `llama-text-embed-v2` (dimension=1024)。1 入力 2,048 トークンまで。`multilingual-e5-large` は 507 トークンまでで、500 語のチャンクの末尾が切れるため使わない。1 リクエスト 96 件まで (`inference.get_model` で確認)。
3. 登録時は `input_type=passage`、質問は `input_type=query`。Embedder の `embed_documents` と `embed_query` にそのまま対応する。
4. 埋め込む文字列は `製品名 | section: 本文` (例: `Cablivi | 6.1 List of excipients: Trisodium citrate ...`)。6.1 の続きのページのように、本文に節の名前も製品名もないチャンクがあり、質問の側にはふつう製品名が入るため。本文の先頭 200 文字以内に section があれば二重にしない (先頭に上の階層の見出しが付く場合があるため、先頭一致では判定しない)。元の本文はメタデータの `text` に残し、引用と回答にはこちらを使う。
   - 製品名は EMA のファイル名 `<製品名>-epar-product-information_en.pdf` の先頭から取る (cablivi → Cablivi)。この形でないファイルには製品名を付けない (推測しない)。EMA の命名規則に頼っている点は既知の制約。
   - Pinecone は 1 リクエストの全入力を、その中で一番長い入力の長さで数える (実測: 9 トークンと 826 トークンを一緒に送ると 1,652)。そのため長さ順に並べてからバッチにし、ベクトルは元の順に戻す。1 回の全件登録は 159,155 → 67,073 トークンに減った。登録前に出す見積もりは上限 (実測の約 1.9 倍)。
5. レコードの ID は chunk_id。メタデータは `doc_id`、`source_file`、`page`、`chunk_type`、`section`、`text` (切らない。最大 3,400 文字で、上限の 40 KB に収まる)、`embedder`。Pinecone はメタデータの数値を float で返すので、`page` は int に戻す。
6. 入れ直し (`replace_document`): (1) ID の前方一致 `<doc_id>:` で今ある ID を一覧 (2) 新しいチャンクを upsert (3) 新しい ID に含まれない古い ID を削除。先に upsert するので、文書が検索から消える時間がない。メタデータの絞り込みによる削除は、直後に書いた新しいチャンクまで消すので使わない。
7. 検索の doc_id での絞り込みは、メタデータの filter `{"doc_id": {"$eq": ...}}`。
8. `PINECONE_INDEX` に既定値は置かず、未設定ならエラーで止める (M2 の `S3_BUCKET` と同じ方針)。API キーは `from_env` で読むだけで、保存もログ出力もしない。
9. 1 つのインデックスには 1 つの埋め込みモデルだけ。モデルを変えたら全件を入れ直す。
10. リランク (任意): `search(..., reranker=...)` を渡すと、ベクトル検索の上位 50 件を `bge-reranker-v2-m3` で並べ替えて上位 k 件を返す。リランカーは質問とチャンクを一緒に読むので、ベクトルの近さより精度が高い。渡さなければベクトル検索だけ。無料プランは月 500 リクエスト、1 分 60 リクエストで、質問 1 つにつき 1 リクエスト。モデルの既定は `truncate=NONE` (1,024 トークンを超えると失敗) なので `END` を指定する。Cohere のリランクは無料プランでは使えない。

### 検索の評価 (hit@5)
`eval/retrieval_questions.json` の 5 問で、上位 5 件に正解のチャンクが 1 つでも入れば hit。recall@5 は正解のうち上位 5 件に入った割合。正解は SmPC の該当の節 (妊娠だけは患者向け説明書の節も含む) で、箱の表示 (`3. LIST OF EXCIPIENTS`) や説明書の同じ内容は正解に数えていない。問題数が少なく、正解も開発者が決めたので、数字は傾向を見るためのもの。

| 段階 | hit@5 | 平均 recall@5 |
|---|---|---|
| section を付けた状態 (M3 の最初) | 1/5 | 0.15 |
| 見出しの二重を直し、長さ順のバッチに変更 | 1/5 | 0.15 |
| 製品名を付けた | 4/5 | 0.45 |
| 製品名 + リランク (上位 50 件) | 5/5 | 0.85 |

目次のチャンク (`What is in this leaflet`) を除く対策はまだ行っていない。

### 質問応答と出典 (M4)
1. 流れは `answer_question`: 質問を埋め込み → 検索 (任意でリランク) → Generator が回答を作る → `disclaimer` を付ける。業務ロジックは `src/` にあり、CLI・API・Lambda は呼ぶだけ。
2. 出典はチャンク 1 つにつき 1 件で、`chunk_id`、`file`、`product`、`section`、`page`、`chunk_type` を持つ。同じページの 2 チャンクも別の出典にする。製品名は埋め込みと同じく EMA のファイル名から取り、合わなければ空にする (推測しない)。
3. `Answer.generator` に回答を作った実装の名前 (`stub` など) を入れる。生成モデルを使ったかどうかを、本文を読まずに判定できるようにするため。Bedrock は `bedrock` とだけ書く。推論プロファイルの ARN にはアカウント ID が入るため。
4. 免責の文 (医療上の助言ではない) は本文に混ぜず、`Answer.disclaimer` に毎回入れる。`answer_question` で付けるので、どの Generator でも同じ文になり、モデルの出力にも頼らない。評価や本文も汚れない。

### StubGenerator (既定)
1. 生成モデルを使わない。先頭に「No generative model was used.」と書き、受け取ったチャンクをすべて、スコアの高い順に `[n] 製品名, section, page P (chunk ID)` と本文の先頭 400 文字で並べる。出典の n 番目は `[n]` と同じチャンク。
2. 件数を切らないのは、回答の出典と検索の上位 k 件を一致させ、回答の評価と hit@k をそろえるため。件数は `top_k` で決める。
3. 限界: 内容が質問に合うかは判断できない。「見つからない」と答えるのは検索結果が 0 件のときだけ。

### 実装の切り替え
1. `EMBEDDER` (fake|pinecone)、`VECTOR_STORE` (memory|pinecone)、`RERANKER` (none|pinecone)、`GENERATOR` (stub|bedrock)。未設定なら最初の値 (フェイク) で、ネットワークもキーも使わない。知らない値はエラーで止める。
2. 本物の実装は選ばれたときだけ import し、インデックス名やキーはそれぞれの `from_env` が環境変数から読む。コードには外部の名前もキーも書かない。
3. `VECTOR_STORE=pinecone` のときは `EMBEDDER=pinecone` が必須。インデックスは Pinecone の埋め込みで作ったので、別の埋め込みで検索すると結果が意味をなさない (1 つのインデックスに 1 つの埋め込みモデル)。
4. M3 のスクリプト (`index_documents`、`search`、`eval_retrieval`) は Pinecone 専用のまま残し、切り替えは使わない。

### Bedrock の生成 (未検証)
1. Converse API を推論プロファイル ID (`BEDROCK_INFERENCE_PROFILE_ID`、既定値なし) で呼ぶ。Converse はモデルによらず同じ形なので短く書ける。`temperature=0`。
2. system プロンプトの規則: 渡した番号付きの文章だけを根拠にする / 根拠がなければ決まった文 `I don't know based on the provided documents.` で答える / 文ごとに `[n]` で出典を示す。
3. 回答の `[n]` から出典を決める (範囲外の番号は無視)。番号が 1 つもなければ渡した全チャンクを出典にする (出典を必ず付けるため)。「わからない」の回答は出典なし。検索結果が 0 件ならモデルを呼ばない。
4. 本物では一度も呼んでいない。README でも verified にしない。

### 回答の評価 (StubGenerator、本物の Pinecone + リランク、top_k=5)
`scripts/eval_answers.py` で、評価セットの 5 問に答えた。出典に正解のチャンクが 1 つでも入った質問は 5/5、正解のうち出典に入った割合の平均は 0.85。Stub は上位 5 件をすべて出典にするので、M3 のリランクありの hit@5 (5/5、0.85) と一致する。1 回の実行で、埋め込み 66 トークン、リランク 5 リクエスト。

### イベント駆動のパイプライン (M6)
1. 流れ: S3 の `incoming/` に PDF → EventBridge → Step Functions (Standard) → Lambda。状態は DynamoDB の `doc-rag-mock-documents` に RECEIVED → INDEXED / FAILED で記録する。
2. 工程: RegisterDocument (sha256 を計算し RECEIVED、キャッシュの有無を返す) → キャッシュがなければ StartExtraction → Wait 10 秒 → CheckExtraction → 未完了なら Wait に戻る → SaveExtraction (結果をキャッシュに保存) → IndexDocument (チャンク化と Pinecone への登録) → MarkIndexed。
3. Textract の完了待ちは Lambda の中ではなく、Step Functions の Wait と Choice で行う。Lambda の中で待つと待ち時間も課金され、15 分の上限にも当たるため。600 秒を超えたら CheckExtraction が TimeoutError を出す。
4. 状態の間で渡すのは ID とフラグと件数だけ (Step Functions の上限は 256 KB)。Textract の結果は既存の S3 キャッシュ (`textract-cache/<sha256>.json`) を通して渡す。キャッシュは受け渡しと二重課金の防止を兼ねる。同じ理由で、チャンク化と埋め込み・登録は 1 つの Lambda にまとめた。
5. 再試行は一時的なエラー (Lambda 側の障害とスロットリング、`TransientError`) だけで、最大計 3 回 (`MaxAttempts: 2`、間隔 2 秒から倍)。Textract の失敗、タイムアウト、入力の誤りは再試行せずにすぐ FAILED にする。同じ入力で再実行しても同じ結果になるため。
6. MarkIndexed と MarkFailed は Lambda を使わず、Step Functions から DynamoDB を直接更新する。Lambda のパッケージが壊れていても FAILED の記録は残る。RegisterDocument の失敗だけは、`doc_id` がまだないので DynamoDB に書かず、実行の失敗として残る。
7. EventBridge のルールは、このバケットの `incoming/` の Object Created だけを拾う。パイプラインが書くのは `textract-cache/` だけで、どの Lambda のロールにも `incoming/` への書き込み権限はない。パイプラインが自分自身を起動することはない。
8. Pinecone には `pipeline` namespace で書く。M3 で手で登録した default namespace のデータには触れない。
9. Lambda は 1 つの zip を 5 関数で共有する (handler 名だけが違う)。Python 3.12、x86_64、VPC なし。boto3 はランタイムに入っているものを使う。
10. Pinecone の API キーは Secrets Manager から、コンテナごとに 1 回だけ読む。Terraform が作るのは入れ物だけなので、キーは tfvars にも state にも入らない。
11. テスト用に、環境変数 `FORCE_FAIL_STEP` で指定した工程が `TransientError` を出す。再試行と FAILED の経路を本物で確かめるため。普段は空。
12. 設定の値はコードに既定値を置かない。Pinecone の埋め込みモデル名 (`PINECONE_EMBED_MODEL`) も必須にした。最初の本番実行で、`.env` にこの変数がなく、Lambda の環境変数が空のまま作られて失敗したため (CLI はコード内の既定値で動いていたので気づかなかった)。Terraform の必須の変数にも、空の値を plan で止める検証を入れた。
13. メモリは実測で決めた。128 MB の関数は boto3 だけで 104 MB を使ったので、すべて 256 MB 以上にした。IndexDocument は 1024 MB で 158 MB しか使わないが、メモリを増やすと CPU も増えるので、大きな文書のために余裕を残している。
14. `updated_at` は、Lambda が書く値も Step Functions (`$$.State.EnteredTime`) と同じ形 (`2026-10-19T04:55:34.746Z`、ミリ秒、末尾 `Z`) にそろえた。
15. MarkFailed は前回の `page_count` / `chunk_count` を消す。INDEXED の後に FAILED になった項目で、古い件数が今回の結果に見えないようにするため。
16. Lambda のログ形式は JSON (`logging_config`)。本番で確認済み (2026-10-19): ロググループの全行が JSON で、START / REPORT も `platform.start` / `platform.report` の JSON になる (メモリは `record.metrics.maxMemoryUsedMB`)。ハンドラの行は `logging_json.py` の形のままで、`step` / `status` / `document_id` / `execution_arn` が `message` の中の文字列ではなく最上位の項目として入る。自前の行には時刻と requestId がない (時刻は CloudWatch の `@timestamp` で並べる)。`status` は工程の状態 (STARTED / SUCCEEDED / FAILED) で、文書の `INDEXED` は DynamoDB にだけある (MarkIndexed は Lambda を通らない)。Logs Insights でのクエリは、権限を付けていないため試していない。
17. 本番で確かめたこと: キャッシュあり / なしの経路、一時的なエラーの再試行 (計 3 回、待ち 2 秒・4 秒)、再試行しない失敗 (設定の不足、Textract の `INVALID_IMAGE_TYPE`)。Wait に戻るループ (IN_PROGRESS) は、Textract が最初の 10 秒で終わったため本番では通っていない。
18. API (M5) は `answer_question` を包むだけの薄い層にした。入力は API 用の `AskRequest`、応答はコアの `Answer` (もともと Pydantic) をそのまま使う。コアのモデルを変えると API の契約も変わるが、`docs/openapi.json` の一致チェックで CI が気づく。
19. API には認証がないので、`127.0.0.1` だけで待ち受ける。手元のデモ専用で、本番向けではない。
20. API の provider は起動時に組み立てる。設定の不足 (キー、namespace、モデル名) は最初のリクエストではなく起動時に、変数名入りのエラーで止まる。生成は `GENERATOR` の切り替えだけで差し替えられる (API は `factory.build_generator()` を呼ぶだけ)。
21. 外部サービスのエラーは 502 にし、決まった文と `request_id` だけを返す。SDK の例外の文にはインデックス名やリクエストの中身が入ることがあるので、ログにもクラス名だけを出す。`/health` は外部サービスを呼ばない (リランクの無料枠と費用を使わないため)。
22. Pinecone の namespace は `PINECONE_NAMESPACE` で決める (必須)。default namespace は空文字だと「未設定」と区別できないので、Pinecone のコンソールの表記に合わせて `__default__` と書く。
23. 本物で確認したこと (2026-10-19): Swagger UI から `/ask` を 1 回 (200、3.9 秒、出典に Cablivi の 6.1 List of excipients の 10 ページと 11 ページ)。ログに質問文は出ていない。上位 3 件はラベル表示の「3. LIST OF EXCIPIENTS」のほぼ同じ文で、重複の除去はまだしていない。
