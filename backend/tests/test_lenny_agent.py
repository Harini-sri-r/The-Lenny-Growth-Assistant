import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.lenny_agent import format_search_results, ship30_system_prompt
from app.rag.retrieval import Passage
from app.agents.lenny_agent import ClaudeResearchAgent


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
    assert "approximately 1,250 words" in prompt
    assert "search_transcripts" in prompt
    assert "Do not invent" in prompt
    assert "strong opening hook" in prompt
    assert "narrative progression" in prompt
    assert "skimmable headings" in prompt
    assert "bullets" in prompt
    assert "bold emphasis sparingly" in prompt
    assert "concise takeaway" in prompt
    assert "each citation next to the claim it supports" in prompt


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
    result = ClaudeResearchAgent(OnePassageRetriever()).answer("Write an evidence-based response")
    assert "Use interviews to test assumptions." in state["tool_result"]["content"][0]["text"]
    assert state["tools"][0].tool_name == "search_transcripts"
    assert result.grounded is True
    assert result.sources[0].source_id == "S1"
