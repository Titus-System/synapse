# components

Components with no feature owner: UI primitives used by more than one part of the app.

## Naming convention

- `Base*` — reusable primitive. Domain-free, doesn't call the API, doesn't read a store. Receives props, emits events. Ex.: `BaseButton`.
- `The*` — unique on screen, usually structural. Ex.: `TheSidebar`.

Component names are always multi-word PascalCase — ESLint rejects a single-word name (`vue/multi-word-component-names`).

## Do

```vue
<!-- BaseButton.vue -->
<script setup lang="ts">
defineProps<{ variant?: 'primary' | 'secondary' }>()
</script>
```

Receives by prop, emits by event, nothing else.

## Don't

```vue
<!-- ❌ a component in src/components/ doesn't do this -->
<script setup lang="ts">
import { useRoute } from 'vue-router'
import { getExample } from '@/features/example/services/example.api'
</script>
```

If a component needs the route or API data, it doesn't belong here — it's probably a view inside a feature.

Don't create a component here anticipating reuse. It's born in `features/<feature>/components/` and is only promoted here by the rule of two: once a **second** feature needs it.

Before creating a new component, search here and in the feature itself — duplication is the most common mistake in this project.
