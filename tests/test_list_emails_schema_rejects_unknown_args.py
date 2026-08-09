"""Regression: list_emails' MCP inputSchema had no `additionalProperties: false`
and no `query` property, so a model that invented a `query` argument (trying
to smuggle search intent into the wrong tool) got it silently accepted and
ignored — the call "succeeded" by luck of falling inside the default recency
window rather than because anything resembling search happened. This masked
the model's actual tool-choice failure rate.

The MCP SDK (`Server.call_tool(validate_input=True)`, the default) runs
`jsonschema.validate(instance=arguments, schema=tool.inputSchema)` on every
real call BEFORE `call_tool()` (the handler in this module) ever executes —
confirmed by reading `mcp.server.lowlevel.server.Server.call_tool`. That
means the schema returned by `list_tools()` — not the copy in
src/tool_schemas.py, which is presentational only — is what's actually
enforced. This test exercises that exact validation step directly.

Adding `additionalProperties: false` alone would have broken every real
call: the agent runtime injects a caller-identity argument
(`_MCP_OWNER_ARG` / "_odysseus_owner") into every dispatched call (see
tool_execution.py), and the MCP `limit` alias the handler already accepts
was never declared either — both had to be added to the schema's properties
or the fix would have turned "silently ignores an invalid arg" into
"rejects every real call, valid or not". Confirmed live against the running
container before landing this test.
"""
import asyncio

import jsonschema
import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es


def _list_emails_schema() -> dict:
    tools = asyncio.run(es.list_tools())
    return next(t for t in tools if t.name == "list_emails").inputSchema


def test_schema_declares_additional_properties_false():
    schema = _list_emails_schema()
    assert schema.get("additionalProperties") is False


def test_invented_query_argument_is_rejected():
    schema = _list_emails_schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={"query": "saber"}, schema=schema)


def test_real_owner_arg_and_known_properties_still_validate():
    """The fix must not reject legitimate calls — every real dispatch injects
    the owner arg, and `limit` is a documented backward-compatible alias."""
    schema = _list_emails_schema()
    jsonschema.validate(
        instance={
            "unread_only": True,
            "limit": 5,
            "account": "work",
            es._MCP_OWNER_ARG: "tester",
        },
        schema=schema,
    )
    jsonschema.validate(instance={}, schema=schema)


def test_query_alongside_valid_args_still_rejected():
    schema = _list_emails_schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"unread_only": True, "query": "saber", es._MCP_OWNER_ARG: "tester"},
            schema=schema,
        )
