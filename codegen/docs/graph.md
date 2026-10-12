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
	extract_rule(extract_rule)
	validate_domain(validate_domain)
	reject_rule(reject_rule)
	code_generation(code_generation)
	persist_response(persist_response)
	extract_code(extract_code)
	dispatch_execution(dispatch_execution)
	await_execution(await_execution)
	decision(decision)
	suggest_adaptation(suggest_adaptation)
	search_sales_target(search_sales_target)
	publish_sales_target(publish_sales_target)
	__end__([<p>__end__</p>]):::last
	__start__ -.-> extract_rule;
	__start__ -.-> load_rule;
	await_execution -.-> decision;
	await_execution -.-> search_sales_target;
	code_generation --> persist_response;
	decision -.-> __end__;
	decision -.-> search_sales_target;
	decision -.-> suggest_adaptation;
	dispatch_execution -.-> __end__;
	dispatch_execution -.-> await_execution;
	extract_code --> dispatch_execution;
	load_rule --> validate_domain;
	persist_response --> extract_code;
	search_sales_target -.-> dispatch_execution;
	search_sales_target -.-> publish_sales_target;
	validate_domain -.-> code_generation;
	validate_domain -.-> reject_rule;
	extract_rule --> __end__;
	publish_sales_target --> __end__;
	reject_rule --> __end__;
	suggest_adaptation --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
