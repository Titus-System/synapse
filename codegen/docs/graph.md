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
	reextract_rule(reextract_rule)
	validate_domain(validate_domain)
	report_conflicts(report_conflicts)
	derive_code(derive_code)
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
	__start__ -.-> reextract_rule;
	await_execution -.-> decision;
	await_execution -.-> search_sales_target;
	code_generation --> persist_response;
	decision -.-> __end__;
	decision -.-> code_generation;
	decision -.-> search_sales_target;
	decision -.-> suggest_adaptation;
	derive_code -.-> code_generation;
	derive_code -.-> dispatch_execution;
	dispatch_execution -.-> __end__;
	dispatch_execution -.-> await_execution;
	extract_code --> dispatch_execution;
	load_rule --> validate_domain;
	persist_response --> extract_code;
	search_sales_target -.-> dispatch_execution;
	search_sales_target -.-> publish_sales_target;
	validate_domain -.-> derive_code;
	validate_domain -.-> report_conflicts;
	extract_rule --> __end__;
	publish_sales_target --> __end__;
	reextract_rule --> __end__;
	report_conflicts --> __end__;
	suggest_adaptation --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
