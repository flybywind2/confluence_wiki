import pytest

from app.core.config import Settings
from app.demo_seed import seed_demo_content
from app.services.wiki_qa import WikiQAService


class FakeTextClient:
    def answer_question(self, question: str, contexts: list[dict[str, str]]) -> str:
        joined_titles = ", ".join(item["title"] for item in contexts)
        return f"질문: {question}\n근거: {joined_titles}"


def test_wiki_qa_limits_answers_to_selected_space(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())
    result = service.answer(question="운영 대시보드와 런북 요약", scope="space", selected_space="DEMO")

    assert result["scope"] == "space"
    assert result["selected_space"] == "DEMO"
    assert result["sources"]
    assert all("DEMO" in source["space_key"] for source in result["sources"])
    assert "운영 대시보드" in result["answer"]


def test_wiki_qa_can_search_across_global_wiki(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())
    result = service.answer(question="아키텍처 메모가 무엇을 설명해?", scope="global", selected_space="DEMO")

    assert result["scope"] == "global"
    assert any("ARCH" in source["space_key"] for source in result["sources"])
    assert "아키텍처 메모" in result["answer"]


def test_wiki_qa_requires_concrete_space_for_space_scope(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())

    with pytest.raises(ValueError):
        service.answer(question="질문", scope="space", selected_space="all")


def test_wiki_qa_excerpts_strip_markdown_and_html_noise(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())
    result = service.answer(question="이미지와 graph cache는 어디에서 서빙돼?", scope="global", selected_space="DEMO")

    assert result["sources"]
    assert "<td" not in result["sources"][0]["excerpt"]
    assert "](" not in result["sources"][0]["excerpt"]


def test_wiki_qa_can_persist_analysis_and_reuse_it_as_source(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())
    answer = service.answer(question="운영 대시보드와 런북 요약", scope="space", selected_space="DEMO")

    saved = service.save_answer(
        space_key="DEMO",
        question="운영 대시보드와 런북 요약",
        scope=answer["scope"],
        answer=answer["answer"],
        sources=answer["sources"],
    )

    assert saved["kind"] == "analysis"
    assert saved["href"].startswith("/knowledge/analyses/")

    follow_up = service.answer(question="대시보드와 런북 요약 분석 문서", scope="space", selected_space="DEMO")
    assert any(source["kind"] == "analysis" for source in follow_up["sources"])
