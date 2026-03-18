import React, { createElement, Fragment, useState } from "react";
import { createRoot } from "react-dom/client";
import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";

function RjsfWidget({ schema, uiSchema }) {
  const [formData, setFormData] = useState(undefined);

  return createElement(
    "div",
    { className: "rjsf-widget" },
    createElement(
      Form,
      {
        schema,
        uiSchema,
        validator,
        formData,
        onChange: (e) => setFormData(e.formData),
        children: createElement(Fragment),
      },
    ),
    createElement(
      "details",
      { className: "rjsf-output", open: true },
      createElement("summary", null, "formData"),
      createElement(
        "pre",
        null,
        JSON.stringify(formData, null, 2) ?? "{}",
      ),
    ),
  );
}

function parseSchema(raw) {
  const { uiSchema, ...schema } = raw;
  return {
    schema: { type: "object", ...schema },
    uiSchema: uiSchema ?? {},
  };
}

function initForms() {
  document.querySelectorAll("div.rjsf-form").forEach(async (el) => {
    if (el.dataset.rendered) return;
    el.dataset.rendered = "true";

    let raw;
    if (el.dataset.schema) {
      raw = JSON.parse(el.dataset.schema);
    } else if (el.dataset.schemaUrl) {
      const resp = await fetch(el.dataset.schemaUrl);
      raw = await resp.json();
    } else {
      el.textContent = "Error: rjsf-form needs data-schema or data-schema-url";
      return;
    }

    const { schema, uiSchema } = parseSchema(raw);
    const root = createRoot(el);
    root.render(createElement(RjsfWidget, { schema, uiSchema }));
  });
}

// Initial load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initForms);
} else {
  initForms();
}

// Material for MkDocs instant loading (SPA navigation)
if (typeof document$ !== "undefined") {
  document$.subscribe(() => initForms());
}
