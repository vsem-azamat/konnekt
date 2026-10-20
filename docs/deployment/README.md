# Deployment

This section covers production runtime operations and deployment contracts.

- [Production Credentials](production-credentials.md) - where production
  credentials live, which values must be real production values, and how to
  rotate or audit them without printing secrets.
- [Agent Runtime MCP](agent-runtime-mcp.md) - configuring the MCP endpoint, why
  it is not published to the internet, and client setup.
- [The Database](database.md) - it runs beside this stack rather than in it,
  what that costs, and the one-time sequence that brought a database older than
  the migration squash under the current history.
- [Telegram Accounts](telegram-accounts.md) - the personal and working accounts,
  why their sessions are kept apart, and how to sign each in.
- [The admin site](admin-site.md) - the console in a browser: what switches it
  on, what has to exist outside this repository, and what to check after the
  first deploy.
