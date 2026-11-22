# Customer Service Orchestration Layer development plan

Implement all CSOL application code in Python. FastAPI hosts the MCP server, and Docker Compose runs CSOL as a single application container. CSOL owns the customer service procedure and a Redis-backed finite state machine (FSM) that remembers where each conversation stopped. Hermes owns the persona, interprets the customer's words, calls CSOL, and presents the result. The proof of concept covers the package purchase and credit top-up journeys shown in the diagram. [CSOL diagram](CSOL.html)

## Proof of concept and success criteria

The goal is to prove that Hermes can follow a customer service procedure when CSOL gives it only the instructions and tools appropriate to the current step. **Keep the logic as simple as possible.** In `app/`, use an explicit Python mapping from each of the six `(state, step)` pairs to its handlers. Express each transition as a direct decision in the step's `main.py`. Extract a function into `helper/` when that makes the handler easier to read. The workflow table below is the full scope of the demo.

**The proof succeeds when** a test customer can complete a package purchase through Hermes, including a detour to add credits. At each turn, check that the Redis state and step predict the instruction and tools Hermes sees, that both return-to-menu tools stay available, and that CSOL rejects a call from a previous step. After the top-up, Hermes must ask again before buying. Verify the final balance in PostgreSQL and the return to the menu in Redis.

## External data services

Redis and PostgreSQL are already deployed as separate services. This repository consumes both through configured client connections. Deployment and administration of each database belong to its service owner.

| Service | Data it owns | How CSOL uses it |
| --- | --- | --- |
| Redis | Each conversation's FSM state, step, revision, and temporary workflow context | `app/` reads the current state and step to select the tools for Hermes. It persists transitions so the next call resumes at the correct step. |
| PostgreSQL | Customer records, including name and balance, and the available packages with their benefits, quota, and price | Identification uses the customer record. Package matching reads the catalog. Purchases and top-ups update the customer's balance through the existing PostgreSQL service. |

## The Hermes and CSOL contract

Keep the persona in the customer service profile's `$HERMES_HOME/SOUL.md` and register `csol` under `mcp_servers` in its `config.yaml`. Set the server URL to the container's reachable `/mcp` endpoint and use MCP Streamable HTTP. Give Hermes one procedural instruction.

> **“For every customer turn, consult CSOL and follow its current instruction before replying or taking action.”**

The greeting, service menu, questions, and completion criteria belong to CSOL so that a workflow change requires no persona edit. [Hermes configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) · [Hermes MCP integration](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)

Expose one read-only instruction tool and one action tool for the current step, plus these **two tools in every state**. All names below are proposed.

| Always available | Behavior |
| --- | --- |
| `request_return_to_landing` | Return the instruction to ask whether the customer wants to leave the current procedure. Record which step and revision the question refers to. |
| `resolve_return_to_landing` | Apply the customer's answer to that pending question. Yes clears the pending package and sets the FSM to `landing / intent_classification`. No resumes the interrupted step. An unsolicited or stale confirmation has no effect. |

On a new or resumed turn, Hermes calls the visible instruction tool. It returns the question to ask, the context needed to answer it, and the action that becomes appropriate once the customer supplies the input. If the current message already supplies that input, Hermes may act in the same turn. An ambiguous answer calls for clarification. A pending return-to-menu question takes precedence over the underlying step, so a “yes” to leaving cannot also authorize a purchase.

For every action, CSOL returns the committed state and step, a revision, the outcome, and the next instruction. Purchase and balance-update messages come from confirmed transaction results. Hermes renders those facts in its persona. If the transaction outcome is uncertain, stop the action and check the recorded result before attempting another balance change.

## Directory architecture

```text
├── Dockerfile
├── compose.yaml
├── pyproject.toml
├── app/
│   └── main.py
├── global/
│   ├── instructions/
│   │   └── *.md
│   ├── main.py
│   └── helper/
│       └── *.py
├── tests/
│   ├── start/
│   │   └── identification/
│   │       └── test_scripts/test_record_name.py
│   ├── landing/
│   │   └── intent_classification/
│   │       └── test_scripts/test_select_service.py
│   ├── buy_package/
│   │   ├── package_preference_identification/
│   │   │   └── test_scripts/test_match_package.py
│   │   ├── user_confirmation/
│   │   │   └── test_scripts/test_confirm_package.py
│   │   └── buy_credits_confirmation/
│   │       └── test_scripts/test_confirm_credit_detour.py
│   └── buy_credits/
│       └── amount_of_balance/
│           └── test_scripts/test_add_credits.py
└── workflow/
    ├── start/
    │   └── identification/
    │       ├── instruction.md
    │       ├── main.py
    │       └── helper/*.py
    ├── landing/
    │   └── intent_classification/
    │       ├── instruction.md
    │       ├── main.py
    │       └── helper/*.py
    ├── buy_package/
    │   ├── package_preference_identification/
    │   │   ├── instruction.md
    │   │   ├── main.py
    │   │   └── helper/*.py
    │   ├── user_confirmation/
    │   │   ├── instruction.md
    │   │   ├── main.py
    │   │   └── helper/*.py
    │   └── buy_credits_confirmation/
    │       ├── instruction.md
    │       ├── main.py
    │       └── helper/*.py
    └── buy_credits/
        └── amount_of_balance/
            ├── instruction.md
            ├── main.py
            └── helper/*.py
```

- **`app/`** implements the MCP server. Before selecting tools for Hermes, it reads the current `state` and `step` from external Redis using the trusted conversation ID. It maps that pair to `workflow/<state>/<step>/` and includes the two tools from `global/`. On invocation it rechecks the Redis state, step, and revision before dispatching the handler.
- **`global/`** owns the two return-to-landing tools. Its `main.py` defines their handlers, `instructions/` holds the Markdown wording Hermes uses to ask for confirmation, and `helper/` holds supporting Python functions.
- **`workflow/<state>/<step>/`** owns one row of the transition table below. Its `main.py` exposes the read-only instruction tool and the step's action tool. The instruction tool reads the adjacent `instruction.md`. The action handler implements the transition and uses functions in its local `helper/` directory as needed.
- **`tests/<state>/<step>/test_scripts/`** holds the Python tests for the corresponding workflow step. Use the step's row in the transition table to check its instruction, action, and resulting state. For example, `test_confirm_package.py` covers a confirmed purchase, a declined offer, and insufficient funds.

For example, when Redis holds `buy_package / user_confirmation`, Hermes receives the two global tools and the pair defined in `workflow/buy_package/user_confirmation/main.py`. The instruction comes from that directory's `instruction.md`, and `confirm_package` handles the customer's answer.

## FastAPI runtime and Docker Compose deployment

- **Application entry point.** Define the FastAPI application in `app/main.py`. Mount the MCP Python SDK's Streamable HTTP application so Hermes reaches it at exactly `/mcp`. Use FastAPI's lifespan to start the MCP session manager and open the Redis and PostgreSQL clients, then close them on shutdown. [MCP Python SDK guide to mounting an HTTP server](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/asgi.md)
- **Container image.** Declare the Python dependencies in `pyproject.toml` and pin them for the build. The root `Dockerfile` installs those dependencies, copies the Python modules and Markdown instructions, and starts Uvicorn with `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- **Compose configuration.** Define one service named `csol` in `compose.yaml`. Supply `REDIS_URL` and `DATABASE_URL` at runtime using addresses reachable from inside the container. For Hermes running on the Docker host, publish port 8000 on loopback and configure `http://127.0.0.1:8000/mcp`. For Hermes on a shared Docker network, use `http://csol:8000/mcp`.
- **Deployment check.** With both connection URLs supplied, run `docker compose config --quiet` and `docker compose up --build -d`. Connect an MCP client to the same URL Hermes will use, request the current step's instruction, and verify the returned tool result. After recording a name, recreate the application container and verify the same conversation resumes at `landing / intent_classification`.

## Workflow and transition table

The instruction column describes what each step's read-only MCP tool returns. The action column names its paired tool. The same credit step handles both routes into a top-up.

| State and step | Instruction for Hermes | Action and transition owned by CSOL |
| --- | --- | --- |
| `start / identification` | Ask for the customer's name. | `record_name` records the supplied name for the bound customer in PostgreSQL. After that succeeds, CSOL saves the display name in the conversation context and enters `landing / intent_classification` in Redis. |
| `landing / intent_classification` | Explain **buy a package** and **buy credits**. Ask which service the customer wants. | `select_service` routes a package request to `buy_package / package_preference_identification` and a credit request to `buy_credits / amount_of_balance`. An unclear selection stays here. |
| `buy_package / package_preference_identification` | Ask what the customer wants in a package. | `match_package` matches preferences against package benefits, quota, and price in PostgreSQL, saves the selected offer and quote in Redis, and enters `user_confirmation`. If there is no match, ask for revised preferences. |
| `buy_package / user_confirmation` | Present the selected package and price. Ask whether to buy it. | `confirm_package` handles both answers. No clears the offer and returns to preferences. Yes checks the customer's PostgreSQL balance and debits it if sufficient. Success returns a receipt and enters `landing / intent_classification`. Insufficient funds retain the offer and enter `buy_credits_confirmation`. |
| `buy_package / buy_credits_confirmation` | Explain the shortfall and ask whether the customer wants to buy credits. | `confirm_credit_detour` enters `buy_credits / amount_of_balance` on yes, retaining the offer. No clears the offer and returns to `landing / intent_classification`. |
| `buy_credits / amount_of_balance` | Ask how many credits to add. | `add_credits` validates the amount, credits the customer's balance in PostgreSQL, and returns the posted result. A direct top-up ends at `landing / intent_classification`. A retained offer returns to package confirmation, where Hermes asks again before any debit. |

**Diagram interpretations.** The service-menu box pairs `intent_classification` with the label `start`. The name-recording action sends the customer to `landing`, so this plan assigns `intent_classification` to `landing`. The direct credits branch repeats the package condition, and the declined credit detour points to the name box although its action specifies `landing`. Use the service and destination named by the actions. Treat `package_preference_identification` as a step within `buy_package`. Keep the customer's name across returns to the menu. For the otherwise unspecified case of a confirmed menu request during onboarding, allow the customer to enter the menu without a display name. Wallet operations still require a bound customer account.

## State, tools, and transaction boundaries

- **Conversation identity.** Bind the conversation to a trusted Hermes conversation identifier and the wallet to a customer identifier supplied by the channel or test fixture. Two conversations with the same display name must have independent FSMs. Two conversations for one account must still spend from one balance.
- **Redis state.** Initialize a new conversation at `start / identification`. Persist the state and step together on every transition. Keep the customer reference, display name for this conversation, selected offer and quote, pending confirmation, and revision with the FSM. Read the current balance and catalog from PostgreSQL whenever an action depends on them. Define each step once with its instruction, action schema, and transition rules. Use that definition for tool selection and execution. Reject a stale revision or out-of-step call before applying any effect, and return the current instruction for recovery.
- **Tool visibility.** Use a stable MCP catalog and a thin Hermes integration that presents only the two global tools and the current step's pair to the model. Resolve the allowed names from CSOL for the trusted conversation before model calls, including after an action in the same turn. CSOL independently enforces the same rules on invocation. This design accounts for MCP revisions that prohibit varying a shared server's tool list as a side effect of preceding calls on one connection. Verify the filtering path, including tool search, against the chosen Hermes release. [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) · [Hermes middleware](https://hermes-agent.nousresearch.com/docs/developer-guide/middleware)
- **Purchases and top-ups.** Use a test account. Check the confirmed offer, price, and balance and record the debit and receipt in one PostgreSQL transaction. Record a top-up and its receipt the same way. Advance Redis after the database confirms the outcome. If the write outcome is uncertain or Redis fails after commit, pause that operation and reconcile it against the PostgreSQL record before resuming. For the demo, this check can be manual.

## Implementation milestones

| Milestone | Work | Acceptance check |
| --- | --- | --- |
| 1. Prove the containerized Hermes integration | Pin Hermes and the Python MCP SDK. Build the FastAPI image and run it with Docker Compose against external Redis and PostgreSQL. Connect Hermes over Streamable HTTP. Implement name collection, landing, the two global tools, and conversation identity binding. | Run two interleaved Hermes chats. Start both at `start / identification` and record a name in one. Verify that only that chat advances to `landing / intent_classification` and exposes the service-selection tools. The other still exposes the name tools. Both see the two return tools. Inspect the model-facing tools after a transition and reject a direct call to an old tool. |
| 2. Build the Redis FSM | Implement the transition table, scoped instruction and action tools, revision checks, and confirmation handling. | Exercise every row and both answers to each confirmation. Restart CSOL midway and verify that `app/` reads the saved state and step from Redis and exposes the matching tools. From each state, confirm a return to the menu and assert the stored pair is `landing / intent_classification`. Declining must preserve the interrupted pair. |
| 3. Complete the purchase and credit journeys | Use a test customer and package from the external PostgreSQL service. Implement insufficient funds, declined offers, top-up receipts, and package reconfirmation. | Start with 20 credits and a 50-credit offer. Accept, top up 30, and verify a balance of 50. Confirm the package again and verify one purchase and a balance of zero. A standalone top-up must end at the menu. |

The proof of concept is complete after milestone 3 passes the success criteria above. Before using live customer balances, verify duplicate deliveries, concurrent purchases, and recovery from a PostgreSQL commit followed by a failed Redis update. Use a stable operation ID to recover the recorded outcome without repeating the balance change. Confirm support for that lookup with the external PostgreSQL service owner.
