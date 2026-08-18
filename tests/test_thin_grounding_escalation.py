"""Coverage for the zero-grounding escalation reroute.

The feature reroutes a single turn to a larger model when an explicit web
search came back with too little to ground an answer on. It survived the
origin/dev merge, but the surrounding routing code was replaced wholesale by
the explicit foreground route-descriptor system, so these tests pin the
behaviour that merge had to preserve:

  * when the reroute fires (and, just as importantly, when it must not),
  * that the candidate list and the parallel descriptor list are built from
    the SAME model, so index 0 of each describes the same route,
  * that requested-vs-actual stays two distinct values in saved metadata,
  * that the partial-save path taken on an early client disconnect still
    records the model that actually ran.
"""

import json
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.foreground_model_routing as foreground_model_routing


SELECTED_MODEL = "selected-model"
SELECTED_URL = "https://selected.example/v1"
SELECTED_HEADERS = {"Authorization": "Bearer selected"}
# Mirrors the _ESCALATION_MODEL literal inside chat_routes' stream closure.
# It is a function-local constant, so it cannot be imported; the guard test
# below fails loudly if the literal is ever renamed out from under these tests.
ESCALATION_MODEL = "gemma4:12b-it-q4_K_M"


def test_escalation_model_literal_still_matches_chat_routes_source():
    import inspect

    source = inspect.getsource(chat_routes)
    assert f'_ESCALATION_MODEL = "{ESCALATION_MODEL}"' in source
    assert "_MIN_GROUNDED_RESULTS = 2" in source


class _EmptyQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _EmptyDb:
    def query(self, *args, **kwargs):
        return _EmptyQuery()

    def close(self):
        return None


class _RouteRequest:
    def __init__(self, mode, use_web, privileges=None):
        self.headers = {}
        auth_manager = None
        if privileges is not None:
            auth_manager = SimpleNamespace(get_privileges=lambda user: privileges)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=auth_manager))
        self.state = SimpleNamespace(current_user="alice")
        self._form = {
            "message": "hello",
            "session": "session-1",
            "mode": mode,
        }
        if use_web:
            self._form["use_web"] = "true"

    async def form(self):
        return self._form


def _endpoint(
    monkeypatch,
    mode,
    captured,
    *,
    use_web=True,
    web_sources=(),
    session_model=SELECTED_MODEL,
    agent_chunks=None,
    chat_chunks=None,
):
    """Build the /api/chat_stream endpoint with everything below it stubbed.

    Mirrors the harness in test_foreground_model_routing.py, adding the two
    knobs this feature actually keys on: use_web and how many web sources the
    pre-fetch came back with.
    """

    def add_message(message):
        captured.setdefault("added_messages", []).append(message)

    session = SimpleNamespace(
        endpoint_url=SELECTED_URL,
        model=session_model,
        headers=dict(SELECTED_HEADERS),
        name="test",
        history=[],
        add_message=add_message,
    )
    session_manager = SimpleNamespace(
        get_session=lambda session_id: session,
        save_sessions=lambda: None,
    )
    context = SimpleNamespace(
        user="alice",
        messages=[{"role": "user", "content": "hello"}],
        route_messages=[{"role": "user", "content": "hello"}],
        preprocessed=SimpleNamespace(attachment_meta=[]),
        auto_opened_docs=[],
        rag_sources=[],
        web_sources=list(web_sources),
        used_memories=[],
        uploaded_files=[],
        uprefs={},
        was_compacted=False,
        context_trimmed=False,
        context_length=4096,
        context_messages_before_trim=1,
        context_messages_after_trim=1,
        context_tokens_before_trim=10,
        context_tokens_after_trim=10,
        preset=SimpleNamespace(temperature=0.2, max_tokens=128, character_name=None),
    )

    async def fake_build_context(*args, **kwargs):
        return context

    # Record the model each builder was handed. The alignment invariant is
    # exactly "these two agree", so capture them independently.
    real_candidates = chat_routes.build_foreground_model_candidates
    real_descriptors = chat_routes.build_foreground_route_descriptors

    def spy_candidates(endpoint_url, model, headers=None, **kwargs):
        captured.setdefault("builder_models", {})["candidates"] = model
        return real_candidates(endpoint_url, model, headers, **kwargs)

    def spy_descriptors(endpoint_url, model, headers=None, **kwargs):
        captured.setdefault("builder_models", {})["descriptors"] = model
        return real_descriptors(endpoint_url, model, headers, **kwargs)

    async def fake_chat_stream(candidates, messages, **kwargs):
        captured["chat_candidates"] = list(candidates)
        captured["chat_descriptors"] = kwargs.get("candidate_route_descriptors")
        if chat_chunks is not None:
            for chunk in chat_chunks:
                if isinstance(chunk, BaseException):
                    raise chunk
                yield chunk
            return
        yield f'data: {json.dumps({"delta": "done"})}\n\n'
        yield f'data: {json.dumps({"type": "metrics", "data": {}})}\n\n'
        yield "data: [DONE]\n\n"

    async def fake_agent_stream(endpoint_url, model, messages, **kwargs):
        captured["agent"] = {
            "primary_model": model,
            "requested_model": kwargs.get("requested_model"),
            "route_descriptors": kwargs.get("route_descriptors"),
            "fallbacks": kwargs.get("fallbacks"),
        }
        if agent_chunks is not None:
            for chunk in agent_chunks:
                if isinstance(chunk, BaseException):
                    raise chunk
                yield chunk
            return
        yield f'data: {json.dumps({"delta": "done"})}\n\n'
        yield f'data: {json.dumps({"type": "metrics", "data": {}})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "coerce_message_and_session", lambda *a, **k: ("hello", "session-1"))
    monkeypatch.setattr(chat_routes, "_verify_session_owner", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "effective_user", lambda request: "alice")
    monkeypatch.setattr(chat_routes, "_clear_orphaned_session_endpoint", lambda *a, **k: False)
    monkeypatch.setattr(chat_routes, "_recover_empty_session_model", lambda *a, **k: False)
    monkeypatch.setattr(chat_routes, "_enforce_chat_privileges", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "resolve_session_auth", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "get_session_mode", lambda session_id: mode)
    monkeypatch.setattr(chat_routes, "set_session_mode", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "build_chat_context", fake_build_context)
    monkeypatch.setattr(chat_routes, "SessionLocal", _EmptyDb)
    monkeypatch.setattr(chat_routes, "_is_image_generation_session", lambda *a, **k: False)
    monkeypatch.setattr(chat_routes, "build_foreground_model_candidates", spy_candidates)
    monkeypatch.setattr(chat_routes, "build_foreground_route_descriptors", spy_descriptors)
    monkeypatch.setattr(chat_routes, "stream_llm_with_fallback", fake_chat_stream)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", fake_agent_stream)
    monkeypatch.setattr(
        chat_routes,
        "save_assistant_response",
        lambda *a, **k: captured.setdefault("saved", []).append((a, k)) or "msg-1",
    )
    monkeypatch.setattr(chat_routes, "run_post_response_tasks", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "estimate_tokens", lambda messages: 10)
    monkeypatch.setattr(chat_routes, "accumulate_token_usage", lambda *a, **k: None)
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences", lambda owner=None: {})

    import src.settings as settings

    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(
        settings,
        "get_user_setting",
        lambda key, owner="", default=None: default,
    )

    router = chat_routes.setup_chat_routes(
        session_manager,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    return next(route.endpoint for route in router.routes if route.path == "/api/chat_stream")


def _privileges_for(mode, use_web):
    """Privileges needed to actually reach `mode` for this turn.

    A chat-mode turn with web search enabled is auto-escalated to agent mode
    (chat_routes.py: `elif chat_mode == "chat" and _search_enabled`). The only
    way a real chat-mode turn coexists with use_web is a user who may not use
    agent mode, which forces chat_mode back to 'chat'. Without this, a
    "chat mode + escalation" test silently exercises the agent branch instead.
    """
    if mode == "chat" and use_web:
        return {"can_use_agent": False}
    return None


async def _drain(endpoint, mode, use_web):
    request = _RouteRequest(mode, use_web, _privileges_for(mode, use_web))
    response = await endpoint(request)
    chunks = []
    # A client disconnect surfaces as the stream simply ending here; the
    # CancelledError raised inside the LLM stream is absorbed at the
    # StreamingResponse boundary rather than propagating to the caller.
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return chunks


def _events(chunks):
    out = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                continue
    return out


def _model_info(chunks):
    return next(e for e in _events(chunks) if e.get("type") == "model_info")


# ── (a) trigger boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
@pytest.mark.parametrize(
    ("use_web", "sources", "should_escalate"),
    [
        (True, 0, True),    # nothing to ground on
        (True, 1, True),    # below the floor
        (True, 2, False),   # exactly at the floor -> no reroute
        (True, 3, False),
        (False, 0, False),  # no explicit web search this turn
    ],
)
async def test_escalation_trigger_boundary(monkeypatch, mode, use_web, sources, should_escalate):
    captured = {}
    endpoint = _endpoint(
        monkeypatch,
        mode,
        captured,
        use_web=use_web,
        web_sources=[{"url": f"https://e/{i}"} for i in range(sources)],
    )

    chunks = await _drain(endpoint, mode, use_web)

    expected = ESCALATION_MODEL if should_escalate else SELECTED_MODEL
    assert _model_info(chunks)["model"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_no_escalation_when_already_on_escalation_model(monkeypatch, mode):
    """Never reroute a session that already selected the escalation model."""
    captured = {}
    endpoint = _endpoint(
        monkeypatch,
        mode,
        captured,
        use_web=True,
        web_sources=[],
        session_model=ESCALATION_MODEL,
    )

    chunks = await _drain(endpoint, mode, True)

    assert _model_info(chunks)["model"] == ESCALATION_MODEL
    assert captured["builder_models"]["candidates"] == ESCALATION_MODEL


# ── (b) descriptor / candidate alignment ────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_builders_receive_the_running_model_under_escalation(monkeypatch, mode):
    """candidate[0] and descriptor[0] must describe the model that runs.

    Regression guard for the original defect: the escalation model was handed
    to the agent loop while both lists were still built from sess.model, so
    descriptor[0] described a route that was not the one executing.
    """
    captured = {}
    endpoint = _endpoint(monkeypatch, mode, captured, use_web=True, web_sources=[])

    await _drain(endpoint, mode, True)

    builders = captured["builder_models"]
    assert builders["candidates"] == ESCALATION_MODEL
    assert builders["descriptors"] == ESCALATION_MODEL
    # The invariant itself: both lists are built from one model.
    assert builders["candidates"] == builders["descriptors"]

    if mode == "chat":
        assert captured["chat_candidates"][0] == (
            SELECTED_URL,
            ESCALATION_MODEL,
            SELECTED_HEADERS,
        )
        assert len(captured["chat_descriptors"]) == len(captured["chat_candidates"])
    else:
        assert captured["agent"]["primary_model"] == ESCALATION_MODEL
        assert len(captured["agent"]["route_descriptors"]) == 1 + len(
            captured["agent"]["fallbacks"] or []
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_builders_receive_selected_model_without_escalation(monkeypatch, mode):
    captured = {}
    endpoint = _endpoint(monkeypatch, mode, captured, use_web=False, web_sources=[])

    await _drain(endpoint, mode, False)

    builders = captured["builder_models"]
    assert builders["candidates"] == SELECTED_MODEL
    assert builders["descriptors"] == SELECTED_MODEL


# ── (c) requested vs actual in saved metadata ───────────────────────────────

@pytest.mark.asyncio
async def test_agent_turn_passes_requested_model_separately_under_escalation(monkeypatch):
    """stream_agent_loop must be told what ran AND what was asked for."""
    captured = {}
    endpoint = _endpoint(monkeypatch, "agent", captured, use_web=True, web_sources=[])

    await _drain(endpoint, "agent", True)

    agent = captured["agent"]
    assert agent["primary_model"] == ESCALATION_MODEL
    assert agent["requested_model"] == SELECTED_MODEL
    assert agent["primary_model"] != agent["requested_model"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_saved_metadata_keeps_requested_and_actual_distinct(monkeypatch, mode):
    captured = {}
    endpoint = _endpoint(monkeypatch, mode, captured, use_web=True, web_sources=[])

    await _drain(endpoint, mode, True)

    metrics = captured["saved"][0][0][4]
    assert metrics["model"] == ESCALATION_MODEL
    assert metrics["requested_model"] == SELECTED_MODEL
    assert metrics["model"] != metrics["requested_model"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_saved_metadata_collapses_when_escalation_does_not_fire(monkeypatch, mode):
    """Non-escalated turns must stay byte-identical to upstream behaviour."""
    captured = {}
    endpoint = _endpoint(monkeypatch, mode, captured, use_web=False, web_sources=[])

    await _drain(endpoint, mode, False)

    metrics = captured["saved"][0][0][4]
    assert metrics["model"] == SELECTED_MODEL
    assert metrics["requested_model"] == SELECTED_MODEL
    assert metrics["model"] == metrics["requested_model"]


# ── (d) partial save on an early disconnect ─────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_partial_save_on_early_disconnect_records_escalated_model(monkeypatch, mode):
    """The seed is the only thing standing in for a model_actual event here.

    The client disconnects after real text but before any model_actual/metrics
    event, so nothing has corrected the actual-model bookkeeping yet. Without
    the escalation seed the partial save would attribute the answer to the
    pre-escalation session model.
    """
    import asyncio as _asyncio

    disconnect = [
        f'data: {json.dumps({"delta": "partial answer"})}\n\n',
        _asyncio.CancelledError(),
    ]
    captured = {}
    kwargs = {"agent_chunks": disconnect} if mode == "agent" else {"chat_chunks": disconnect}
    endpoint = _endpoint(
        monkeypatch, mode, captured, use_web=True, web_sources=[], **kwargs
    )

    await _drain(endpoint, mode, True)

    saved = captured["added_messages"]
    assert saved, "expected a partial assistant message to be saved"
    metadata = saved[-1].metadata
    assert metadata["stopped"] is True
    assert metadata["model"] == ESCALATION_MODEL
    assert metadata["requested_model"] == SELECTED_MODEL
    if mode == "agent":
        # Round 1 ran the escalation model, so the per-round ACTUAL map must
        # say so -- seeding it from the requested model would mislabel it.
        assert metadata["round_models"][0] == ESCALATION_MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "agent"])
async def test_partial_save_on_early_disconnect_without_escalation(monkeypatch, mode):
    import asyncio as _asyncio

    disconnect = [
        f'data: {json.dumps({"delta": "partial answer"})}\n\n',
        _asyncio.CancelledError(),
    ]
    captured = {}
    kwargs = {"agent_chunks": disconnect} if mode == "agent" else {"chat_chunks": disconnect}
    endpoint = _endpoint(
        monkeypatch, mode, captured, use_web=False, web_sources=[], **kwargs
    )

    await _drain(endpoint, mode, False)

    metadata = captured["added_messages"][-1].metadata
    assert metadata["model"] == SELECTED_MODEL
    assert metadata["requested_model"] == SELECTED_MODEL
