#!/usr/bin/env python3
"""Markdown の下書きを note.com に送る。

使い方:
  python3 scripts/note_post.py articles/drafts/xxx.md --dry-run   # 送信せず変換結果だけ表示
  python3 scripts/note_post.py articles/drafts/xxx.md             # note に「下書き」として保存
  python3 scripts/note_post.py articles/drafts/xxx.md --publish   # note に公開

認証: 環境変数 NOTE_SESSION にブラウザの Cookie `_note_session_v5` の値を入れる。
note には公式の投稿 API がないため、エディタが内部で使っている API を呼んでいる。
仕様変更で動かなくなることがある。
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://note.com/api"
PAYWALL_MARKER = "<!-- paywall -->"


# ---------- frontmatter ----------

def parse_frontmatter(text):
    """先頭の --- で囲まれた key: value を読む。リストは [a, b] 形式のみ。"""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value.strip("\"'")
    body = text[end + 4:].lstrip("\n")
    return meta, body


def write_frontmatter(path, updates):
    """frontmatter の値を書き換える(無ければ追加)。"""
    text = path.read_text(encoding="utf-8")
    end = text.find("\n---", 4)
    head, rest = text[4:end], text[end:]
    lines = head.splitlines()
    for key, value in updates.items():
        new = f"{key}: {value}"
        for i, line in enumerate(lines):
            if line.split(":", 1)[0].strip() == key:
                lines[i] = new
                break
        else:
            lines.append(new)
    path.write_text("---\n" + "\n".join(lines) + rest, encoding="utf-8")


# ---------- markdown -> note HTML ----------

def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return text


def block(tag, inner, ids):
    uid = str(uuid.uuid4())
    ids.append(uid)
    return f'<{tag} name="{uid}" id="{uid}">{inner}</{tag}>'


def markdown_to_note_html(md):
    """note のエディタが扱える範囲の HTML に変換する。

    戻り値: (html, 有料ラインの直前ブロックの id か None)
    """
    ids, out = [], []
    separator = None
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s == PAYWALL_MARKER:
            separator = ids[-1] if ids else None
            i += 1
            continue
        if s.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(block("pre", "<code>" + html.escape("\n".join(code)) + "</code>", ids))
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            # note の見出しは大(h2)と小(h3)のみ
            out.append(block("h2" if len(m.group(1)) <= 2 else "h3", inline(m.group(2)), ids))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            out.append(block("hr", "", ids).replace("></hr>", ">"))
            i += 1
            continue
        if s.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(inline(lines[i].strip()[1:].strip()))
                i += 1
            out.append(block("blockquote", "<br>".join(quote), ids))
            continue
        if re.match(r"^([-*]|\d+\.)\s+", s):
            ordered = bool(re.match(r"^\d+\.", s))
            items = []
            while i < len(lines) and re.match(r"^([-*]|\d+\.)\s+", lines[i].strip()):
                items.append("<li>" + inline(re.sub(r"^([-*]|\d+\.)\s+", "", lines[i].strip())) + "</li>")
                i += 1
            out.append(block("ol" if ordered else "ul", "".join(items), ids))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,3}\s|```|>|[-*]\s|\d+\.\s|-{3,}$|\*{3,}$)", lines[i].strip()
        ) and lines[i].strip() != PAYWALL_MARKER:
            para.append(inline(lines[i].strip()))
            i += 1
        out.append(block("p", "<br>".join(para), ids))
    return "".join(out), separator


# ---------- note API ----------

def request(method, path, session, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Content-Type": "application/json",
        "Cookie": f"_note_session_v5={session}",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://editor.note.com",
        "Referer": "https://editor.note.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"note API エラー {e.code} ({method} {path}): {e.read().decode()[:500]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--publish", action="store_true", help="下書きではなく公開する")
    ap.add_argument("--dry-run", action="store_true", help="送信せず変換結果を表示する")
    args = ap.parse_args()

    meta, md = parse_frontmatter(args.file.read_text(encoding="utf-8"))
    title = meta.get("title", "").strip()
    if not title:
        sys.exit("frontmatter に title がありません")
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    price = int(meta.get("price", 0) or 0)

    body, separator = markdown_to_note_html(md)
    if price > 0 and not separator:
        sys.exit(f"有料記事(price: {price})には本文中に {PAYWALL_MARKER} の行が必要です")

    if args.dry_run:
        print(json.dumps({"title": title, "tags": tags, "price": price, "separator": separator,
                          "body_length": len(body)}, ensure_ascii=False, indent=2))
        print(body)
        return

    session = os.environ.get("NOTE_SESSION")
    if not session:
        sys.exit("環境変数 NOTE_SESSION(Cookie `_note_session_v5` の値)が設定されていません")

    note_id, note_key = meta.get("note_id"), meta.get("note_key")
    if not note_id:
        created = request("POST", "/v1/text_notes", session, {"template_key": None})["data"]
        note_id, note_key = str(created["id"]), created["key"]
        write_frontmatter(args.file, {"note_id": note_id, "note_key": note_key})

    request("POST", f"/v1/text_notes/draft_save?id={note_id}&is_temp_saved=true", session, {
        "name": title, "body": body, "body_length": len(body), "index": False, "is_lead_form": False,
    })

    if not args.publish:
        print(f"下書き保存しました: https://editor.note.com/notes/{note_key}/edit/")
        return

    request("PUT", f"/v1/text_notes/{note_id}", session, {
        "name": title,
        "body": body,
        "body_length": len(body),
        "status": "published",
        "hashtags": [t if t.startswith("#") else "#" + t for t in tags],
        "price": price,
        "separator": separator if price > 0 else None,
        "index": False,
        "is_refund": False,
        "limited": False,
        "magazine_ids": [],
        "magazine_keys": [],
        "slug": f"slug-{note_key}",
        "free_body": None,
        "lead_form": {"is_active": False, "consent_url": ""},
    })
    url = f"https://note.com/{meta.get('author', 'me')}/n/{note_key}" if meta.get("author") else f"https://note.com/n/{note_key}"
    write_frontmatter(args.file, {"status": "published", "note_url": url})
    print(f"公開しました: {url}")


if __name__ == "__main__":
    main()
