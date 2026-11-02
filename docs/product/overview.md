# Product Overview

Supervisor Telegram helps teams operating Telegram communities keep
conversations healthy and operations visible while retaining human control over
high-impact decisions.

## Target Users

| Persona | Primary Need |
| --- | --- |
| Community operator | Keep one or more Telegram communities useful, safe, and manageable as activity grows |
| Moderator or administrator | Resolve reports, enforce rules, and handle edge cases quickly and consistently |
| Operations owner | Understand managed chats, members, and public catalog state from authenticated operating surfaces |
| Community member | Participate in a healthier community; this is a beneficiary persona, not the primary operator |

## Jobs To Be Done

- When a Telegram community creates more moderation work than admins can handle
  manually, help operators enforce policy consistently while keeping the
  decisions that remove a person with a human.
- When a community is targeted by bot farms or drive-by advertising, help
  operators keep them out and clean up after them without watching the chat
  continuously.
- When admins need to run day-to-day community operations, help them do it from
  familiar control surfaces instead of stitching together ad hoc tools.
- When operators expose a public catalog, help anonymous visitors browse the
  intended public projection without granting administrative authority.

## Business Outcomes

- Reduce repetitive moderation effort without removing human authority from
  decisions that remove a person.
- Improve consistency of enforcement across managed chats.
- Reduce operational friction for admins managing several communities at once.
- Make public catalog exposure deliberate and inspectable.

## Product Promises

| Promise | What must stay true |
| --- | --- |
| Humans retain control where judgment matters | Removing a person is confirmed by an administrator, never carried out by automation on its own verdict |
| Routine work becomes easier to operate | The platform reduces repeated manual steps instead of only moving them elsewhere |
| Public visibility does not imply admin authority | Public read access and authenticated administrative actions remain separate |
| A chat is managed only once an operator says so | Nothing acts publicly in a chat the operator has not approved |

## Product Capabilities

| Capability Group | Business Meaning |
| --- | --- |
| Community safety | Keep chats healthier with less repetitive administrator effort |
| Entry control | Decide who gets in before they are in, rather than cleaning up afterwards |
| Operator control | Let a small team run the supported workflows coherently from Telegram and a web surface |
| Public projection | Expose a curated read-only view of the community catalog without admin authority |
| Enquiry intake | Let somebody who wants to reach these communities see the size of the offer and find the operator who can price it |

Individual features are not listed here on purpose: the list rots, and the code
and its tests are the answer.

## Technical Enablers

These matter to delivery, but they are not product promises on their own.

| Enabler | Role |
| --- | --- |
| Telegram API separation | Split bot and client-level responsibilities safely |
| Persistence of observed activity | Give operators the record a decision needs |
| Automated verification | Keep the system maintainable as behavior changes |

## In Scope

- Telegram communities managed by platform operators.
- Moderation workflows, including reports, spam handling, a cross-chat
  blacklist, and entry checks on join requests.
- Administrator workflows exposed through Telegram commands and an
  authenticated web surface.
- Public read-only views only where they are intentionally exposed.

## Out Of Scope

- General-purpose social media management outside Telegram.
- Content generation, editorial workflows, publishing, and scheduling.
- Automated advertising sales: rate cards, self-serve booking, payment, and
  delivery reporting. The public surface states reach and hands the enquiry to
  an operator; everything after that conversation happens outside the product.
- Autonomous removal of a community member without administrator confirmation.
- Replacing operator ownership of community policy or judgment.
- Member-facing customer support or general chat assistance unrelated to the
  supported moderation workflows.

## Boundary With Rules The Code Cannot State

This document defines product intent, not executable behaviour. Behaviour is
pinned by tests. The rules a test cannot state — those spanning processes,
living in deployment, or recording why a design is shaped the way it is — live
in [invariants](../invariants.md).

## Wording Risks

- **"AI moderation"** does not describe this system. No model decides anything
  here; the moderation paths are deterministic, and the judgement calls belong
  to an administrator.
- **"Automatic ban"** overstates what happens. Only an administrator removes
  someone: by a command, on the console, or by putting them on the blacklist.
- **"General-purpose platform"** overstates the current evidence unless we can
  name supported audiences and workflows beyond the present operating model.
- Database choices, Telegram client details, and the number of bot identities
  are enablers, not customer outcomes. Keep them out of high-level product
  promises.
