# note 記事 自動作成・投稿

Claude に話す → 記事の下書きができる → 自分で確認・修正 → note に投稿、までを行う仕組み。

## 使い方

1. このリポジトリで Claude Code のセッションを開き、記事にしたいことを普通に話す
   (例:「せどりで最初の月に3万円稼いだ話を記事にしたい。やったことは…」)
2. Claude が `articles/drafts/` に下書きを作って見せてくれるので、直したいところを伝える
3. OK を出すと note に**下書き**として保存され、エディタの URL がもらえる
   (アイキャッチ画像の追加などはここで)
4. 「公開して」と言うと公開される

## 初回だけ必要な設定

### 1. note のログイン情報(Cookie)

1. PC のブラウザで note.com にログイン
2. 開発者ツール(F12)→「Application」→「Cookies」→ `https://note.com`
3. `_note_session_v5` の値をコピー
4. Claude Code のクラウド環境の設定(Edit)で、環境変数 `NOTE_SESSION=コピーした値` を追加

※ この値はパスワードと同じ扱い。チャットやリポジトリには絶対に貼らない。
  ログアウトすると無効になるので、その時は取り直す。

### 2. ネットワーク

クラウド環境の設定の Network access で、Allowed domains に `note.com` を追加する。

## 注意

- note には公式の投稿 API が無いため、note のエディタ内部の API を使っている。
  note 側の仕様変更で動かなくなることがある。
- 有料記事は frontmatter の `price` に金額を入れ、無料で見せる部分の最後に
  `<!-- paywall -->` の行を入れる。

## ファイル

- `articles/TEMPLATE.md` — 記事のひな形
- `articles/drafts/` — 下書き
- `articles/published/` — 公開済み
- `scripts/note_post.py` — note への送信スクリプト(`--dry-run` / 下書き保存 / `--publish`)
