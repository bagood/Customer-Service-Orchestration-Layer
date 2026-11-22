# CSOL Workflow Configuration Refactor Plan

A workflow will live under `workflow/<workflow_id>/` and own one `workflow.yaml`, its step modules, and its SQL helpers. Adding a workflow should require its own files and, when an existing workflow routes into it, an explicit change to that caller. The engine and conversation model should support the addition without edits. The six current steps, PostgreSQL transaction semantics, and Hermes tool contract are the baseline for acceptance.

## Workflow manifest

Use the workflow directory name as the persisted state ID and each step directory name as its persisted step ID. A step alias is a workflow-local name for code and configuration. For example, `preferences` can refer to the existing `package_preference_identification` directory and its `main.py`. Python imports use the derived, fully qualified module path. MCP tool names continue to come from the step's exported handlers.

The following excerpt shows the proposed shape of `workflow/buy_package/workflow.yaml`.

```yaml
version: 1
context:
  offer:
    type: object
    nullable: true
    default: null
    fields:
      package_id: {type: string}
      name: {type: string}
      benefits: {type: string}
      quota_gb: {type: integer, minimum: 0}
      price: {type: integer, minimum: 1}
  offer_presented_turn: {type: string, nullable: true, default: null}
  shortfall: {type: integer, nullable: true, default: null}
reset_on_return_to_menu: [offer, offer_presented_turn, shortfall]
steps:
  preferences: {directory: package_preference_identification}
  confirm: {directory: user_confirmation}
  credit_detour: {directory: buy_credits_confirmation}
destinations:
  menu: {workflow: landing, step: menu}
  preferences: {workflow: buy_package, step: preferences}
  credit_detour: {workflow: buy_package, step: credit_detour}
  top_up: {workflow: buy_credits, step: amount}
```

Place `start_at: identification` in the start manifest and `return_to_menu_at: menu` in the landing manifest. These point to aliases in their respective manifests. Require exactly one of each across the registry. Each caller declares the destinations it uses, including the landing menu's package and credit routes and the credit step's return to package confirmation. Resolve destination aliases to immutable `(state, step)` pairs at startup. The former constants such as `MENU` and `PREFERENCES` are tuples of IDs. The resolved destinations serve the same purpose.

Keep input schemas, instruction text, conditional transitions, and action handlers in the existing Python and Markdown files. A handler chooses a destination after examining the action result. YAML declares where that destination points. Each step's `main.py` still exports one `Step` so the same definition drives tool listing, instruction selection, and dispatch.

## Parsing and registration

1. Add a pinned YAML parser to the project and lockfile. Use safe parsing for a single document per file. Reject duplicate mapping keys before schema validation and reject custom tags, aliases, and merge keys so every value is explicit.
2. Validate manifests with strict Pydantic models. Support a bounded vocabulary of string, integer, boolean, and typed object declarations with explicit nullability and validated defaults. Object schemas require their declared fields unless a field defines a default and reject extra fields. Reject unknown manifest keys, unsupported schema versions, invalid IDs, incompatible type constraints, and incorrectly typed defaults. Keep type declarations declarative and defaults JSON-compatible.
3. Discover manifests in a deterministic order from the packaged workflow root. For each declared step, derive `workflow.<workflow_id>.<directory>.main` and import it using Python's standard import machinery. Restrict IDs and directories to Python identifiers and keep resolved paths under the workflow root. Report step directories that contain `main.py` but lack a declaration. Validate each `Step` export, its instruction file, and its tool schema. Reject duplicate step directories, unresolved destinations, and duplicate or incompatible MCP tool names, including collisions with global tools and names after Hermes prefixing or shortening.
4. Build one immutable registry during the FastAPI lifespan, before serving requests. Pass it to the engine and store. Use it for the stable MCP catalog, the signed `/scope` endpoint, instruction lookup, and action dispatch. Keep the instruction tool first, the action second, and both global tools available on every step. Fail startup with the manifest path and the offending key or module when validation fails. Import discovery runs again on deployment restart.

## Conversation state and instruction context

- Keep customer binding, conversation instance, current state and step, revision, pending return question, and in-flight reservation in the conversation envelope. Add a storage format version and a `context` mapping keyed by workflow ID.
- Move `display_name` to `start.context` and the offer, offer presentation turn, and shortfall to `buy_package.context`. Provide a validated workflow context accessor and resolve defaults when a namespace is first accessed. Copy defaults per conversation. Declare and validate cross-workflow context dependencies in the consuming manifest. For example, the credit workflow declares `context_dependencies: {buy_package: [offer, offer_presented_turn, shortfall]}`. Validate the referenced fields at startup and enforce access through the workflow context accessor. Read and update the retained offer in its original namespace during the detour.
- Give workflows control over which values are included in the instruction context. Move the current projection out of the engine into workflow exports, preserving its existing keys and omission rules. Keep `display_name` available throughout the existing journey, expose the offer when present and the shortfall when set, and keep the presentation turn internal. The engine still projects its own recovery arguments and return question. New context fields are private until explicitly exported.
- Let the purchase workflow clear its own offer fields on the existing exits. On a confirmed global return, reset the fields marked by each manifest and preserve the display name. On a declined return, preserve workflow context. Keep confirmation revisions and the later-turn check for purchases following a top-up.

## PostgreSQL helpers

| Location | Responsibility |
| --- | --- |
| `workflow/start/helper.py` | Update the bound customer's name. |
| `workflow/buy_package/helper.py` | Match catalog preferences, lock and revalidate a quoted package, check funds, and construct the purchase result. |
| `workflow/buy_credits/helper.py` | Enforce the balance limit and construct the top-up result. |
| `app/database.py` | Own the shared transaction wrapper, customer row lock, recorded-operation lookup, balance update primitive, and operation recording. |

Replace the current operation-kind branch with explicit workflow helper calls. Pass the workflow callback the transaction connection and locked balance. Keep the prior-operation lookup, callback, and receipt insert inside the same PostgreSQL transaction. Preserve operation IDs, operation kinds, receipt payloads, lock order, missing-account handling, and the Redis update after commit. The external PostgreSQL schema requires no migration for this refactor.

## Redis compatibility and deployment

1. Add a decoder for the current flat records and the new versioned envelope. Move legacy values into their corresponding namespaces while preserving the Redis key, exact state and step, customer binding, instance ID, revision, pending return question, and in-flight tool, arguments, and turn. Reject unsupported record versions, invalid values, or unknown active steps without resetting the chat.
2. Capture the original stored value when decoding and compare it with the value under Redis `WATCH` before a write. Comparing a reserialized migrated conversation with a legacy record would otherwise make the first update conflict. Write the new envelope on the next successful reservation or transition. Reads of existing records leave the stored representation intact, and a format conversion alone leaves the workflow revision intact.
3. First deploy a compatibility release that reads both formats and writes the legacy shape for the six existing steps. After verifying that release, switch all writers to versioned writes together. Keep the compatibility release as the rollback target while both readers understand both shapes. During rollback, turn off versioned writes and retain the ability to read already converted records. Enable workflows with context or states the compatibility release cannot represent only after retiring that rollback target. Keep old state IDs and tool names stable while any persisted chats or pending operations refer to them.

## Implementation sequence and acceptance

| Milestone | Work | Acceptance |
| --- | --- | --- |
| 1. Register the existing steps from YAML | Add the parser, validated registry, manifests, and aliases. Wire up the three consumers of the registry. | The stable MCP catalog still contains 14 tools. Each legacy state and step pair exposes its original four tools in order. Malformed manifests fail at startup. A fixture workflow with a new alias, context field, and step registers and executes without editing the engine or conversation model. |
| 2. Move context and enable compatibility reads | Introduce the workflow context accessor, move instruction projection and reset ownership into workflows, and implement the legacy decoder. | Seed flat records at all six steps, plus pending return and in-flight cases. Verify valid actions and restarts, rejection of invalid values, isolation of defaults, and correct Redis conflict handling between concurrent writers. Test the compatibility deployment and rollback against both stored formats. Verify that a workflow with state or context outside the legacy schema cannot be enabled while legacy writes are active. |
| 3. Move SQL into workflow helpers | Extract the workflow operations and reuse the shared transaction wrapper. | Against isolated PostgreSQL and Redis, verify purchase and top-up receipts, duplicate delivery, simultaneous purchases from one account, changed quotes, and recovery after PostgreSQL commits but Redis fails. Include replay of an operation reserved before upgrading. |
| 4. Run container and Hermes acceptance | Update the README with the manifest rules and workflow authoring example. Build the locked image, deploy it with isolated services, and run the existing MCP and Hermes acceptance paths. | Two interleaved chats keep independent state. Inspect the model-facing tools and reject stale calls. Recreate CSOL and resume the same chat. Starting with 20 credits, add 30 in the detour, require a fresh purchase confirmation, then verify one purchase, a zero balance, and a return to the menu. Confirm both accepted and declined menu returns and a standalone top-up. |
