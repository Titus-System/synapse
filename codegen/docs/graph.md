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
	__end__([<p>__end__</p>]):::last
	__start__ --> load_rule;
	load_rule --> code_generation;
	code_generation --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
