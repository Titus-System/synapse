# Graph

Generated from `app/graph/core/engine.py`; do not edit by hand. Regenerate with `make graph`.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	load_rule(load_rule)
	code_generation(code_generation)
	persist_response(persist_response)
	extract_code(extract_code)
	dispatch_execution(dispatch_execution)
	await_execution(await_execution)
	__end__([<p>__end__</p>]):::last
	__start__ --> load_rule;
	code_generation --> persist_response;
	dispatch_execution --> await_execution;
	extract_code --> dispatch_execution;
	load_rule --> code_generation;
	persist_response --> extract_code;
	await_execution --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
