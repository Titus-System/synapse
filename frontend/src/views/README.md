# views

Views with no feature owner: only what's genuinely cross-cutting to the whole app, like a "page not found" screen.

## Do

```
src/views/NotFoundView.vue    // catch-all route, doesn't belong to any domain
```

## Don't

```
src/views/LoginView.vue        // ❌ has an owner — belongs to an auth feature
src/views/RuleDetailView.vue   // ❌ has an owner — belongs to the domain feature
```

Every view with a domain owner goes in `features/<feature>/views/`. Before adding a view here, ask: is there (or should there be) a feature that owns it? If so, it goes there, not here.
