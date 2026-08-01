from app.core.prompt_pack_examples import prompt_pack_create_from_example, prompt_pack_examples
from app.workflows.templates import workflow_template, workflow_templates


def test_prompt_pack_examples_include_semi_classical_style():
    examples = prompt_pack_examples()
    semi = next(item for item in examples if item["id"] == "style_semi_classical")

    assert semi["name"] == "半文半白叙事"
    assert "半文半白" in str(semi["content"])
    assert "chapter_draft" in semi["stages"]
    assert prompt_pack_create_from_example("style_semi_classical") is not None


def test_workflow_templates_include_draft_to_formal_flow():
    templates = workflow_templates()
    template = workflow_template("chapter_draft_to_formal")

    assert template is not None
    assert template in templates
    kinds = [step["kind"] for step in template["steps"]]
    assert kinds == ["context", "plan", "user_confirm", "draft", "user_confirm", "write_file"]
    write_step = template["steps"][-1]
    assert write_step["input"]["target_path"].startswith("chapters/")
