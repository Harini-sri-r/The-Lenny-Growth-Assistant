import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.lenny_agent import _deduplicate_essay, _filter_specific_claims, _merge_pi_essay, _normalize_citations, _trim_essay_to_word_limit, format_search_results, ship30_system_prompt
from app.rag.retrieval import Passage
from app.agents.lenny_agent import ClaudeResearchAgent, PiCodingAgent, _pi_essay_word_count
from app.services.rag import INSUFFICIENT_EVIDENCE


def test_pi_adapter_uses_json_final_message_and_preserves_valid_citation(monkeypatch):
    import json
    from types import SimpleNamespace

    events = [
        {"type": "session", "version": 3},
        {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Interview customers to test assumptions. [S1]"}] }},
    ]
    captured = {}
    monkeypatch.setattr("app.agents.lenny_agent.shutil.which", lambda command: "pi.exe")
    def fake_run(args, **kwargs):
        prompt_arg = args[-1]
        assert prompt_arg.startswith("@")
        prompt_path = prompt_arg[1:]
        captured.update(args=args, kwargs=kwargs, prompt_path=prompt_path)
        captured["prompt"] = Path(prompt_path).read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(e) for e in events), stderr="")
    monkeypatch.setattr("app.agents.lenny_agent.subprocess.run", fake_run)
    agent = PiCodingAgent(OnePassageRetriever(), model="gemini-test", provider="gemini", ship30_minimum_words=1)
    answer = agent.answer("customer research")
    assert answer.grounded
    assert answer.sources[0].source_id == "S1"
    args = captured["args"]
    assert args[1:6] == ["--mode", "json", "--print", "--no-session", "--no-tools"]
    assert args[6:10] == ["--provider", "gemini", "--model", "gemini-test"]
    assert args[-1].startswith("@")
    assert len(args[-1]) < 300
    assert captured["prompt"].startswith("You are the Lenny Growth research agent.")
    assert not Path(captured["prompt_path"]).exists()
    assert captured["kwargs"]["timeout"] == 240
    assert answer.answer.endswith("[S1]")


def test_pi_adapter_bounds_subprocess_and_reports_timeout(monkeypatch):
    from subprocess import TimeoutExpired
    from types import SimpleNamespace
    captured = {}
    monkeypatch.setattr("app.agents.lenny_agent.shutil.which", lambda _command: "pi.exe")
    def fake_run(args, **_kwargs):
        captured["prompt_path"] = args[-1][1:]
        assert Path(captured["prompt_path"]).is_file()
        raise TimeoutExpired("pi", 1)
    monkeypatch.setattr("app.agents.lenny_agent.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="Pi Coding Agent did not finish within"):
        PiCodingAgent(OnePassageRetriever(), model="llama3:latest", provider="ollama", timeout=1).answer("customer research")
    assert not Path(captured["prompt_path"]).exists()


def test_pi_adapter_logs_sanitized_stderr_on_nonzero_exit(monkeypatch, caplog):
    import logging
    from types import SimpleNamespace
    caplog.set_level(logging.ERROR, logger="app.agents.lenny_agent")
    secret = "test-gemini-api-secret-value"
    monkeypatch.setattr("app.agents.lenny_agent.shutil.which", lambda _command: "pi.exe")
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    stderr = f"provider rejected request with GEMINI_API_KEY={secret}; retry later"
    captured = {}
    def fake_run(args, **_kwargs):
        captured["prompt_path"] = args[-1][1:]
        assert Path(captured["prompt_path"]).read_text(encoding="utf-8").startswith("You are the Lenny Growth research agent.")
        return SimpleNamespace(returncode=1, stdout="", stderr=stderr)
    monkeypatch.setattr("app.agents.lenny_agent.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="Pi Coding Agent returned an error"):
        PiCodingAgent(OnePassageRetriever(), model="gemini-test", provider="gemini", api_key=secret).answer("customer research")
    assert secret not in caplog.text
    record = next(record for record in caplog.records if getattr(record, "event", None) == "pi_agent_request_failed")
    assert record.failure_category == "process_error"
    assert record.exit_code == 1
    assert "stderr_excerpt" in record.__dict__
    assert "retry later" in record.stderr_excerpt
    assert secret not in record.stderr_excerpt
    assert not Path(captured["prompt_path"]).exists()


def test_pi_adapter_deletes_prompt_file_when_process_cannot_launch(monkeypatch):
    captured = {}
    monkeypatch.setattr("app.agents.lenny_agent.shutil.which", lambda _command: "pi.exe")
    def fake_run(args, **_kwargs):
        captured["prompt_path"] = args[-1][1:]
        assert Path(captured["prompt_path"]).is_file()
        raise OSError("simulated process launch error")
    monkeypatch.setattr("app.agents.lenny_agent.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="Pi Coding Agent could not be started"):
        PiCodingAgent(OnePassageRetriever(), model="llama3:latest", provider="ollama").answer("customer research")
    assert not Path(captured["prompt_path"]).exists()


def test_pi_adapter_ignores_non_json_stderr_on_success_and_parses_json(monkeypatch):
    import json
    from types import SimpleNamespace
    event = {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Interview customers to test assumptions. [S1]"}]}}
    monkeypatch.setattr("app.agents.lenny_agent.shutil.which", lambda _command: "pi.exe")
    monkeypatch.setattr("app.agents.lenny_agent.subprocess.run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr="harmless progress"))
    answer = PiCodingAgent(OnePassageRetriever(), model="llama3:latest", provider="ollama", ship30_minimum_words=1).answer("customer research")
    assert answer.grounded
    assert answer.sources[0].source_id == "S1"


def test_pi_adapter_rejects_unknown_citation(monkeypatch):
    import json
    from types import SimpleNamespace
    event = {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Interview customers to test assumptions. [S99]"}]}}
    monkeypatch.setattr("app.agents.lenny_agent.shutil.which", lambda _command: "pi.exe")
    monkeypatch.setattr("app.agents.lenny_agent.subprocess.run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr=""))
    answer = PiCodingAgent(OnePassageRetriever(), model="llama3:latest", provider="ollama").answer("customer research")
    assert not answer.grounded
    assert answer.refusal_reason == "unknown_citation"


class OnePassageRetriever:
    def retrieve(self, query):
        assert query == "customer research"
        return [Passage("Use interviews to test assumptions.", {"source_path": "podcasts/example.md", "chunk_id": "c1", "title": "An episode", "document_type": "podcast"}, .91)]


def test_sdk_retrieval_tool_formats_actual_sources_and_passage():
    collected = []
    result = format_search_results("customer research", OnePassageRetriever(), collected)
    assert "[S1]" in result
    assert "podcasts/example.md" in result
    assert "Use interviews to test assumptions." in result
    assert len(collected) == 1


def test_ship30_skill_sets_grounded_1250_word_contract():
    prompt = ship30_system_prompt()
    assert "1,150–1,350 words" in prompt
    assert "search_transcripts" in prompt
    assert "Do not invent" in prompt
    assert "strong opening hook" in prompt
    assert "narrative progression" in prompt
    assert "skimmable headings" in prompt
    assert "bullets" in prompt
    assert "bold emphasis sparingly" in prompt
    assert "concise takeaway" in prompt
    assert "each citation next to the claim it supports" in prompt
    assert "Do not repeat a title, paragraph, section, or complete draft" in prompt


def test_agent_sdk_orchestration_calls_the_retrieval_tool(monkeypatch):
    sdk = ModuleType("claude_agent_sdk")
    state = {}

    def tool(name, description, schema):
        def decorate(function):
            function.tool_name = name
            return function
        return decorate

    def create_server(name, version, tools):
        state["tools"] = tools
        return SimpleNamespace(name=name, tools=tools)

    class Options:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeClient:
        def __init__(self, options):
            self.options = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def query(self, prompt):
            state["prompt"] = prompt
            state["system_prompt"] = self.options.system_prompt
            state["sdk_env"] = self.options.env
            state["tool_result"] = await self.options.mcp_servers["lenny_knowledge"].tools[0]({"query": "customer research"})

        async def receive_response(self):
            yield sdk.AssistantMessage([sdk.TextBlock("Interview customers to test assumptions. [S1]")])

    sdk.tool = tool
    sdk.create_sdk_mcp_server = create_server
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = FakeClient
    class TextBlock:
        def __init__(self, text):
            self.text = text

    class AssistantMessage:
        def __init__(self, content):
            self.content = content

    sdk.TextBlock = TextBlock
    sdk.AssistantMessage = AssistantMessage
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
    fake_key = "test-only-fake-key"
    result = ClaudeResearchAgent(OnePassageRetriever(), anthropic_api_key=fake_key).answer(
        "Write an evidence-based response", system_prompt=ship30_system_prompt()
    )
    assert "Use interviews to test assumptions." in state["tool_result"]["content"][0]["text"]
    assert state["tools"][0].tool_name == "search_transcripts"
    assert "MUST call search_transcripts" in state["system_prompt"]
    assert "1,150–1,350 words" in state["system_prompt"]
    assert state["sdk_env"] == {"ANTHROPIC_API_KEY": fake_key}
    assert result.grounded is True
    assert result.sources[0].source_id == "S1"


def test_agent_does_not_override_inherited_sdk_auth_with_an_empty_key(monkeypatch):
    sdk = ModuleType("claude_agent_sdk")
    state = {}

    def tool(_name, _description, _schema):
        return lambda function: function

    class Options:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class FakeClient:
        def __init__(self, options): self.options = options
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def query(self, _prompt):
            state["sdk_env"] = self.options.env
            search_tool = self.options.mcp_servers["lenny_knowledge"].tools[0]
            await search_tool({"query": "customer research"})
        async def receive_response(self):
            yield sdk.AssistantMessage([sdk.TextBlock("A useful answer [S1]")])

    sdk.tool = tool
    sdk.create_sdk_mcp_server = lambda **kwargs: type("Server", (), kwargs)()
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = FakeClient
    sdk.TextBlock = type("TextBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    sdk.AssistantMessage = type("AssistantMessage", (), {"__init__": lambda self, content: setattr(self, "content", content)})
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)

    result = ClaudeResearchAgent(OnePassageRetriever()).answer("customer research")

    assert state["sdk_env"] == {}
    assert result.grounded is True


def test_sdk_failure_log_redacts_configured_key_and_summarizes_stderr(caplog):
    from app.agents.lenny_agent import _log_sdk_failure

    fake_key = "sk-ant-test-fake-secret-123456"

    class FakeProcessError(RuntimeError):
        exit_code = 1
        api_error_status = 401
        terminal_reason = "api_error"
        stderr = f"Invalid x-api-key: {fake_key}"

    error = FakeProcessError(f"CLI request failed using {fake_key}")
    error.stderr = f"Invalid x-api-key: {fake_key}"
    _log_sdk_failure("initial_response", error, secrets=(fake_key,))

    record = next(record for record in caplog.records if getattr(record, "event", None) == "claude_agent_request_failed")
    assert fake_key not in caplog.text
    assert record.failure_message == "Claude authentication was rejected."
    assert record.stderr_category == "authentication"
    assert record.api_error_status == 401
    assert record.exit_code == 1
    assert "Invalid x-api-key" not in caplog.text


@pytest.mark.parametrize(
    ("status", "category", "failure_message", "has_sdk_errors", "result_kind"),
    [
        (400, "invalid_request", "Claude API rejected an invalid request (HTTP 400).", False, "invalid_request"),
        (400, "request_error", "Claude API returned HTTP 400; request details were suppressed for safety.", False, "unknown"),
        (None, "unclassified", "Claude Agent SDK raised _ClaudeSdkResultError; details were suppressed for safety.", False, "unknown"),
        (401, "authentication", "Claude authentication was rejected.", True, "unknown"),
        (503, "service_error", "Claude API returned HTTP 503 (service error).", True, "unknown"),
    ],
)
def test_sdk_error_result_logs_safe_category_and_suppresses_error_content(
    monkeypatch, caplog, status, category, failure_message, has_sdk_errors, result_kind
):
    import logging

    from app.agents.lenny_agent import ClaudeResearchAgent

    caplog.set_level(logging.ERROR, logger="app.agents.lenny_agent")
    sdk = ModuleType("claude_agent_sdk")
    fake_key = "sk-ant-test-error-result-secret-987654"
    private_prompt = "PRIVATE ESSAY DRAFT MUST NOT APPEAR"
    result_text = (
        f"API Error: HTTP 400 invalid_request_error: authorization bearer {fake_key}; {private_prompt}"
        if result_kind == "invalid_request"
        else f"unrecognized provider prose {fake_key}; {private_prompt}"
    )
    sdk_errors = [f"API Error: HTTP {status}; authorization token {fake_key}", private_prompt] if has_sdk_errors else []

    class Options:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class ResultMessage:
        result = result_text
        is_error = True
        errors = sdk_errors
        api_error_status = status
        subtype = "success"
        terminal_reason = "api_error"

    class Client:
        def __init__(self, options): self.options = options
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def query(self, _prompt): pass
        async def receive_response(self):
            yield ResultMessage()

    sdk.AssistantMessage = type("AssistantMessage", (), {})
    sdk.TextBlock = type("TextBlock", (), {})
    sdk.ResultMessage = ResultMessage
    sdk.tool = lambda *_args: lambda function: function
    sdk.create_sdk_mcp_server = lambda **kwargs: type("Server", (), kwargs)()
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = Client
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)

    with pytest.raises(RuntimeError, match="Claude Agent SDK request failed"):
        ClaudeResearchAgent(OnePassageRetriever(), anthropic_api_key=fake_key).answer("customer research")
    record = next(record for record in caplog.records if getattr(record, "event", None) == "claude_agent_request_failed")
    assert record.failure_category == category
    assert record.sdk_error_category == (category if has_sdk_errors or result_text else None)
    assert record.failure_message == failure_message
    assert record.sdk_error_count == (2 if has_sdk_errors else 0)
    assert getattr(record, "api_error_status", None) == status
    assert record.stderr_category is None
    assert record.terminal_reason == "api_error"
    assert fake_key not in caplog.text
    assert private_prompt not in caplog.text
    assert result_text not in caplog.text
    assert fake_key not in record.failure_message
    assert "Invalid x-api-key" not in caplog.text


def test_agent_rejects_unknown_citation_and_logs_only_citation_diagnostics(monkeypatch, caplog):
    sdk = ModuleType("claude_agent_sdk")

    def tool(_name, _description, _schema):
        return lambda function: function

    class FakeClient:
        def __init__(self, options): self.options = options
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def query(self, _prompt):
            await self.options.mcp_servers["lenny_knowledge"].tools[0]({"query": "customer research"})
        async def receive_response(self):
            yield sdk.AssistantMessage([sdk.TextBlock("An essay claim [S99].")])

    class Options:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    sdk.tool = tool
    sdk.create_sdk_mcp_server = lambda **kwargs: type("Server", (), kwargs)()
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = FakeClient
    sdk.TextBlock = type("TextBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    sdk.AssistantMessage = type("AssistantMessage", (), {"__init__": lambda self, content: setattr(self, "content", content)})
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)

    result = ClaudeResearchAgent(OnePassageRetriever()).answer("Write an essay")

    assert result.answer == "I couldn't find enough relevant, traceable evidence in the indexed Lenny library to answer that question. The retrieved passages do not support a specific answer."
    assert result.grounded is False
    assert result.sources == []
    assert result.refusal_reason == "unknown_citation"
    rejection = next(record for record in caplog.records if getattr(record, "event", None) == "claude_citation_validation_rejected")
    assert rejection.citation_count == 1
    assert rejection.recognized_labels == []
    assert rejection.unrecognized_labels == ["[S99]"]
    assert not hasattr(rejection, "response_text")


def test_citation_normalizer_accepts_bare_and_grouped_ids_only_when_sources_exist():
    passages = [
        Passage("First evidence.", {"source_path": "one.md", "chunk_id": "c1"}, .8),
        Passage("Second evidence.", {"source_path": "two.md", "chunk_id": "c2"}, .7),
    ]
    from app.services.rag import source_references
    refs = source_references(passages)

    normalized, recognized, unknown, count = _normalize_citations("Useful claim S1 and [S1, S2].", refs)

    assert normalized == "Useful claim [S1] and [S1] [S2]."
    assert recognized == ["S1", "S2"]
    assert unknown == []
    assert count == 2

    invalid, recognized, unknown, count = _normalize_citations("Made-up citation [S99].", refs)
    assert invalid == "Made-up citation [S99]."
    assert recognized == []
    assert unknown == ["S99"]
    assert count == 1


def test_ship30_deduplicates_repeated_paragraphs_and_caps_length():
    paragraph = "Teams should interview users before choosing a solution. [S1]"
    repeated = f"# Useful essay\n\n{paragraph}\n\n{paragraph}"
    assert _deduplicate_essay(repeated).count(paragraph) == 1
    oversized = "# Useful essay\n\n" + "\n\n".join(
        f"## Section {index}\n\n{paragraph.replace('interview users', f'learn from cohort {index}') }"
        for index in range(1, 81)
    )
    bounded = _trim_essay_to_word_limit(oversized)
    assert _pi_essay_word_count(bounded) <= 1350


def test_pi_ship30_merge_deduplicates_a_continuation_that_echoes_the_entire_draft():
    draft = "# Retention begins with first use\n\n## Find early friction\n\nTeams should sign up as a new customer. [S1]"
    continuation = draft + "\n\n## Turn evidence into action\n\nTeams can remove the friction they observe. [S1]"

    merged = _merge_pi_essay(draft, continuation)

    assert merged.count("# Retention begins with first use") == 1
    assert merged.count("## Find early friction") == 1
    assert merged.count("Teams should sign up as a new customer.") == 1
    assert "## Turn evidence into action" in merged


def test_ship30_drops_person_company_and_metric_claims_without_matching_cited_evidence():
    essay = (
        "Maya Chen grew Acme by 40% in one quarter. [S1]\n"
        "Teams should track D7 retention. [S2]"
    )
    filtered = _filter_specific_claims(essay, {
        "S1": "Maya Chen led Acme's launch. The company grew 4% in one quarter.",
        "S2": "Track D7 retention to understand continued use.",
    })
    assert "40%" not in filtered
    assert "D7 retention" in filtered


def test_ship30_prefetches_topic_evidence_and_supplies_it_to_the_agent(monkeypatch):
    sdk = ModuleType("claude_agent_sdk")
    state = {}
    passage = Passage(
        "Track D7 retention and sign up as a new user to find first-use friction.",
        {"source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast"},
        .67,
    )
    second_passage = Passage(
        "Measure whether customers continue using the product.",
        {"source_path": "podcasts/retention-metrics.md", "chunk_id": "retention-2", "title": "Retention metrics", "document_type": "podcast"},
        .66,
    )

    class TopicRetriever:
        def retrieve(self, query):
            state.setdefault("queries", []).append(query)
            return [passage, second_passage]

    def tool(_name, _description, _schema):
        return lambda function: function

    class Options:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class FakeClient:
        def __init__(self, options): self.options = options
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def query(self, prompt): state["prompt"] = prompt
        async def receive_response(self):
            # Claude sometimes emits the supplied source ID without square brackets.
            yield sdk.AssistantMessage([sdk.TextBlock("Measure continued use over time. S2")])

    sdk.tool = tool
    sdk.create_sdk_mcp_server = lambda **kwargs: type("Server", (), kwargs)()
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = FakeClient
    sdk.TextBlock = type("TextBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    sdk.AssistantMessage = type("AssistantMessage", (), {"__init__": lambda self, content: setattr(self, "content", content)})
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)

    topic = "How startups can improve user retention by building products people love"
    result = ClaudeResearchAgent(TopicRetriever()).answer(
        "Write an essay for product managers", system_prompt=ship30_system_prompt(), retrieval_query=topic
    )

    assert state["queries"] == [topic]
    assert '[S1] Retention\nMetadata: {"chunk_id": "retention-1", "document_type": "podcast"' in state["prompt"]
    assert '[S2] Retention metrics\nMetadata: {"chunk_id": "retention-2", "document_type": "podcast"' in state["prompt"]
    assert passage.text in state["prompt"]
    assert result.grounded is True
    assert [source.chunk_id for source in result.sources] == ["retention-2"]
    assert result.sources[0].source_path == "podcasts/retention-metrics.md"
    assert result.answer.endswith("[S2]")


def test_agent_uses_terminal_sdk_result_instead_of_intermediate_assistant_text(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="app.agents.lenny_agent")
    sdk = ModuleType("claude_agent_sdk")
    state = {"client_count": 0}
    sdk.TextBlock = type("TextBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    sdk.AssistantMessage = type("AssistantMessage", (), {"__init__": lambda self, content: setattr(self, "content", content)})
    sdk.ResultMessage = type("ResultMessage", (), {
        "__init__": lambda self, result, is_error=False: (setattr(self, "result", result), setattr(self, "is_error", is_error)) and None
    })

    class Options:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class Client:
        def __init__(self, options):
            self.options = options
            state["client_count"] += 1
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def query(self, prompt): state["prompt"] = prompt
        async def receive_response(self):
            yield sdk.AssistantMessage([sdk.TextBlock(INSUFFICIENT_EVIDENCE)])
            yield sdk.ResultMessage("# Retention starts with first use\n\nTrack D7 retention and remove first-use friction. [S1]")

    sdk.tool = lambda *_args: lambda function: function
    sdk.create_sdk_mcp_server = lambda **kwargs: type("Server", (), kwargs)()
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = Client
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)

    result = ClaudeResearchAgent(OnePassageRetriever()).answer(
        "Write an essay", system_prompt=ship30_system_prompt(), retrieval_query="customer research"
    )

    assert state["client_count"] == 1
    assert "exact citation format is [S1]" in state["prompt"]
    assert '"chunk_id": "c1"' in state["prompt"]
    assert result.grounded is True
    assert result.answer.startswith("# Retention starts")
    assert result.sources == []
    assert "[S1]" not in result.answer
    parsed = next(record for record in caplog.records if getattr(record, "event", None) == "claude_agent_response_parsed")
    assert parsed.response_source == "result_message"
    assert parsed.result_message_count == 1
    assert parsed.response_kind == "substantive_text"
    assert not hasattr(parsed, "response_text")


def test_ship30_retries_once_on_terminal_insufficiency_using_same_evidence(monkeypatch):
    sdk = ModuleType("claude_agent_sdk")
    state = {"client_count": 0, "allowed_tools": [], "system_prompts": []}
    passage = Passage(
        "Track D7 retention and sign up as a new user to find first-use friction.",
        {"source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast"},
        .67,
    )

    class TopicRetriever:
        def __init__(self): self.queries = []
        def retrieve(self, query):
            self.queries.append(query)
            return [passage]

    class Options:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class Client:
        def __init__(self, options):
            self.options = options
            state["client_count"] += 1
            state["allowed_tools"].append(options.allowed_tools)
            state["system_prompts"].append(options.system_prompt)
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def query(self, prompt): state[f"prompt_{state['client_count']}"] = prompt
        async def receive_response(self):
            if state["client_count"] == 1:
                yield sdk.ResultMessage(INSUFFICIENT_EVIDENCE)
            else:
                yield sdk.ResultMessage("# Retention is learned in the first week\n\nTrack D7 and test first use. [S1]")

    sdk.TextBlock = type("TextBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    sdk.AssistantMessage = type("AssistantMessage", (), {"__init__": lambda self, content: setattr(self, "content", content)})
    sdk.ResultMessage = type("ResultMessage", (), {
        "__init__": lambda self, result, is_error=False: (setattr(self, "result", result), setattr(self, "is_error", is_error)) and None
    })
    sdk.tool = lambda *_args: lambda function: function
    sdk.create_sdk_mcp_server = lambda **kwargs: type("Server", (), kwargs)()
    sdk.ClaudeAgentOptions = Options
    sdk.ClaudeSDKClient = Client
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)

    topic = "How startups can improve user retention by building products people love"
    retriever = TopicRetriever()
    result = ClaudeResearchAgent(retriever).answer(
        "Write a Ship 30 essay", system_prompt=ship30_system_prompt(), retrieval_query=topic
    )

    assert state["client_count"] == 2
    assert state["allowed_tools"][1] == []
    assert "The requested topic has already been searched" in state["system_prompts"][1]
    assert "Use the read-only `search_transcripts` tool before drafting" not in state["system_prompts"][1]
    assert "exact citation format is [S1]" in state["prompt_2"]
    assert "Do not search for or introduce other sources" in state["prompt_2"]
    assert retriever.queries == [topic]
    assert result.grounded is True
    assert result.sources[0].chunk_id == "retention-1"


def test_ship30_rejects_when_topic_prefetch_finds_no_relevant_passages():
    class EmptyRetriever:
        def __init__(self): self.queries = []
        def retrieve(self, query):
            self.queries.append(query)
            return []

    retriever = EmptyRetriever()
    result = ClaudeResearchAgent(retriever).answer(
        "Write an essay", system_prompt=ship30_system_prompt(), retrieval_query="a topic absent from the corpus"
    )

    assert retriever.queries == ["a topic absent from the corpus"]
    assert result.grounded is False
    assert result.sources == []
