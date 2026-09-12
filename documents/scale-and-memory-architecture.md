# Prompt Tower — scale and memory

Telegram sessions stay in the existing SQLite/Postgres session store.
Reverse intake is stateless per step (await URL → hook → twist → model).

Do not put Prompt Tower user memory through an LLM replay. Structured
session keys only (`prompt_await_url`, hook, twist, model).

Deploy still lives on the ThinkPad. One poller process is enough until
Ashok says otherwise.
