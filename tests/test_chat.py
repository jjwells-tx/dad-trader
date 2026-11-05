"""Chat: context building, Gemini request/response handling, and the /chat endpoint. Gemini is faked."""
import json, threading, urllib.error, urllib.request
import pytest
from http.server import ThreadingHTTPServer
from trader import chat
from trader.db import connect
from trader.server import make_handler


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    con = connect(path)
    con.execute("INSERT INTO positions VALUES ('Randol IRA','GOOGL',18,5000,200,'system',NULL,'2026-10-30')")
    con.execute("INSERT INTO positions VALUES ('Randol IRA','AGX',42,5000,200,'hold','One block buy',NULL)")
    con.execute("INSERT INTO stocks (ticker, grade, zacks, buy_below, newsletters) VALUES ('GOOGL','B','3',340,?)",
                (json.dumps([dict(name="Innovation Investor", bucket=None, date="2022-10-18", price=100.77)]),))
    con.execute("INSERT INTO prices VALUES ('GOOGL','2026-11-05',280.48,'yahoo')")
    con.execute("INSERT INTO prices VALUES ('AGX','2026-11-05',357.15,'yahoo')")
    con.execute("INSERT INTO meta VALUES ('positions_source','Google Sheets')")
    con.commit()
    return path


def test_context_has_positions_orders_and_sheet_details(db):
    ctx = chat.build_context(db)
    assert "Randol IRA | GOOGL | 18 sh | 280.48 (2026-11-05, yahoo)" in ctx
    assert "SELL 1 @ 288.89" in ctx and "BUY 1 @ 266.66" in ctx
    assert "AGX" in ctx and "hold" in ctx
    assert "GOOGL | B | 3 | 340.0" in ctx and "Innovation Investor" in ctx
    assert "Google Sheets" in ctx


def test_history_is_validated():
    assert chat.clean_history([{"role": "model", "text": "hi"}, {"role": "user", "text": " q "}]) == [{"role": "user", "text": "q"}]
    for bad in ([], None, [{"role": "system", "text": "x"}], [{"role": "user", "text": "a"}, {"role": "model", "text": "b"}],
                [{"role": "user", "text": "x" * (chat.MAX_CHARS + 1)}]):
        with pytest.raises(chat.ChatError) as e:
            chat.clean_history(bad)
        assert e.value.status == 400


def test_ask_sends_context_and_search_tool_and_parses_sources():
    seen = {}

    def post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": "GOOGL sells at **$288.89**."}]},
                                "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://a.example", "title": "A"}},
                                                                          {"web": {"uri": "https://a.example", "title": "A"}}]}}]}

    out = chat.ask([{"role": "user", "text": "next GOOGL sell?"}], "CONTEXT-123", api_key="k", model="m", post=post)
    assert out == {"reply": "GOOGL sells at **$288.89**.", "sources": [{"title": "A", "uri": "https://a.example"}]}
    assert seen["url"].endswith("/models/m:generateContent") and seen["headers"]["x-goog-api-key"] == "k"
    assert "CONTEXT-123" in seen["body"]["system_instruction"]["parts"][0]["text"]
    assert seen["body"]["tools"] == [{"google_search": {}}]
    assert seen["body"]["contents"] == [{"role": "user", "parts": [{"text": "next GOOGL sell?"}]}]


def test_missing_key_and_blocked_answers_are_clear(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(chat.ChatError, match="GEMINI_API_KEY") as e:
        chat.ask([{"role": "user", "text": "q"}], "")
    assert e.value.status == 503
    with pytest.raises(chat.ChatError, match="SAFETY"):
        chat.ask([{"role": "user", "text": "q"}], "", api_key="k", post=lambda *a: {"promptFeedback": {"blockReason": "SAFETY"}})


@pytest.fixture
def server(db):
    calls = []

    def fake_ask(messages, context):
        calls.append((messages, context))
        return {"reply": f"you asked: {messages[-1]['text']}", "sources": []}

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db, ask=fake_ask))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", calls
    httpd.shutdown()


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_page_has_the_chat_panel(server):
    base, _ = server
    page = urllib.request.urlopen(base + "/").read().decode()
    assert "Rung Sheet" in page and 'id="ask-btn"' in page and "GOOGL" in page


def test_chat_endpoint(server):
    base, calls = server
    code, data = _post(base + "/chat", {"messages": [{"role": "user", "text": "hello"}]})
    assert code == 200 and data["reply"] == "you asked: hello"
    assert "GOOGL" in calls[0][1]                                  # the ledger went along as context


def test_chat_rejects_cross_origin_and_non_json(server):
    base, calls = server
    code, _ = _post(base + "/chat", {"messages": [{"role": "user", "text": "x"}]}, {"Origin": "https://evil.example"})
    assert code == 403
    req = urllib.request.Request(base + "/chat", data=b"messages=x", method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 415 and not calls
