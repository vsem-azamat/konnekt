# Product Documentation

This section is the canonical product and business reference for Supervisor
Telegram.

Use it to answer:

- who the product is for;
- which jobs it exists to help with;
- which business outcomes matter;
- what is explicitly in scope and out of scope;
- which statements are product promises versus technical enablers.

## Documents

- [Product Overview](overview.md) - target users, jobs-to-be-done, outcomes,
  promises, enablers, and scope boundaries.
- [Articles](articles.md) - how an article on konnekt.cz is sourced, written
  and reviewed before it is published.

## Relationship To Other Docs

- Product docs define business intent and scope.
- [Invariants](../invariants.md) hold the rules code cannot state for itself.
- Current behaviour is defined by the code and pinned by its tests, not by prose
  anywhere in `docs/`.

When business intent changes, update the product docs first. When current
behavior changes, change the test before the implementation.
