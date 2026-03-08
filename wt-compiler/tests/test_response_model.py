"""Tests for the generalized ResponseModel and dispatch template changes."""

from __future__ import annotations

import json
import pathlib
import traceback
from typing import Any

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "wt_compiler" / "templates"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_template(name: str) -> str:
    """Render a pkg/ template with an empty file_header."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template(f"pkg/{name}")
    return tmpl.render(file_header="# auto-generated")


class ResponseModel(BaseModel):
    """Mirror of the rendered response.jinja2 — used for behavioural tests."""

    result: Any = None
    error: str | None = None
    trace: str | None = None


# ---------------------------------------------------------------------------
# Template rendering tests
# ---------------------------------------------------------------------------


class TestTemplateRendering:
    """Verify rendered templates have the expected imports / no ecoscope."""

    def test_response_template_no_ecoscope_import(self) -> None:
        rendered = _render_template("response.jinja2")
        assert "ecoscope_workflows_core" not in rendered

    def test_dispatch_template_no_basemodel_import(self) -> None:
        rendered = _render_template("dispatch.jinja2")
        assert "from pydantic import BaseModel" not in rendered


# ---------------------------------------------------------------------------
# ResponseModel serialization tests
# ---------------------------------------------------------------------------


class TestResponseModelSerialization:
    """Verify ResponseModel accepts various result types."""

    def test_response_model_with_int_result(self) -> None:
        data = json.loads(ResponseModel(result=42).model_dump_json())
        assert data["result"] == 42

    def test_response_model_with_string_result(self) -> None:
        data = json.loads(ResponseModel(result="hello").model_dump_json())
        assert data["result"] == "hello"

    def test_response_model_with_dict_result(self) -> None:
        data = json.loads(ResponseModel(result={"key": "val"}).model_dump_json())
        assert data["result"] == {"key": "val"}

    def test_response_model_with_basemodel_result(self) -> None:
        """Backward compat: BaseModel subclass result serializes as nested dict."""

        class Inner(BaseModel):
            x: int = 1
            y: str = "two"

        data = json.loads(ResponseModel(result=Inner()).model_dump_json())
        assert data["result"] == {"x": 1, "y": "two"}

    def test_response_model_error_response(self) -> None:
        resp = ResponseModel(error="something broke", trace="Traceback ...")
        data = json.loads(resp.model_dump_json())
        assert data["error"] == "something broke"
        assert data["trace"] == "Traceback ..."
        assert data["result"] is None


# ---------------------------------------------------------------------------
# Dispatch behavior tests
# ---------------------------------------------------------------------------


class TestDispatchBehavior:
    """Test dispatch logic with different result types."""

    @staticmethod
    def _build_dispatch(dispatcher_fn):
        """Build a minimal dispatch function mirroring the rendered template logic."""

        def dispatch(params):
            try:
                result = dispatcher_fn(params=params)
                response = ResponseModel(result=result)
                response.model_dump_json()  # eagerly validate JSON-serializability
            except Exception as e:
                trace = traceback.format_exc()
                response = ResponseModel(error=str(e), trace=trace)
            return response

        return dispatch

    def test_dispatch_primitive_result_serializes(self) -> None:
        dispatch = self._build_dispatch(lambda params: 42)
        resp = dispatch(params={})
        data = json.loads(resp.model_dump_json())
        assert data == {"result": 42, "error": None, "trace": None}

    def test_dispatch_basemodel_result_serializes(self) -> None:
        class MyModel(BaseModel):
            value: str = "ok"

        dispatch = self._build_dispatch(lambda params: MyModel())
        resp = dispatch(params={})
        data = json.loads(resp.model_dump_json())
        assert data["result"] == {"value": "ok"}
        assert data["error"] is None

    def test_dispatch_non_serializable_returns_error(self) -> None:
        dispatch = self._build_dispatch(lambda params: object())
        resp = dispatch(params={})
        data = json.loads(resp.model_dump_json())
        assert data["result"] is None
        assert data["error"] is not None
        assert data["trace"] is not None
