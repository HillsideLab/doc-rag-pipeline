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
