from app.tools.consistency_check import ConsistencyCheckTool


def test_consistency_check_keeps_full_ui_issues_but_compacts_model_content():
    tool = ConsistencyCheckTool()
    issues = [
        {
            "severity": "notice",
            "title": f"提示 {index}",
            "path": f"world/{index}.md",
            "detail": "很长的问题说明" * 40,
            "snippet": "片段",
            "score": 0.5,
            "collection": "world",
        }
        for index in range(5)
    ]

    result = tool._result(issues, "", related_count=8, mode="rules")

    assert result.metadata["issue_count"] == 5
    assert result.metadata["model_issue_count"] == 3
    assert result.ui_hint is not None
    assert result.ui_hint["type"] == "list:issues"
    assert len(result.ui_hint["data"]) == 5
    assert "发现 5 条提示" in result.content
    assert "提示 0" in result.content
    assert "提示 3" not in result.content
    assert "完整问题列表已放入 ui_hint" in result.content
