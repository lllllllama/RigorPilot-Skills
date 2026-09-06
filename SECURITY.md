# Security policy

## Execution boundary

RigorPilot executes programs on the local host. It is not an operating-system
sandbox: an approved command can access files, processes, and the network with
the permissions of the user running it. Use trusted repositories and review
commands, dependency installation, and task files before execution. Use an
independently configured isolated environment for untrusted code.

The model-driven runner restricts its tools to reviewed command IDs, but this
does not restrict what those programs can do. Credential environment filtering
is a defense in depth, not a guarantee that a program cannot find credentials
elsewhere on the host. Timeouts and between-action output checks are not hard
disk, memory, CPU, or network isolation.

## Credentials and evidence

- Keep credentials in the documented environment variables, never in task or
  model-profile JSON, source files, command arguments, or submitted examples.
- Review logs, prompts, model responses, repository snapshots, and trajectories
  before sharing them. They may contain private code, personal paths, dataset
  contents, or secrets emitted by a program; automatic complete redaction is
  not provided.
- If a credential is exposed, revoke or rotate it with its provider. Removing a
  file or commit does not invalidate a credential or remove existing copies.
- Do not submit private repositories or unreviewed evidence bundles in public
  issues or pull requests. Prefer a minimal sanitized reproducer.

## Reporting a vulnerability

If private vulnerability reporting is enabled for this repository, use
**Report a vulnerability** on its [GitHub Security page](https://github.com/lllllllama/RigorPilot-Skills/security).
If that option is unavailable, open a minimal issue requesting a private
reporting channel, without exploit details, sensitive data, or credentials.
No private email address or response-time guarantee is currently published.

Include the affected commit, installation method, platform/Python version,
security impact, and the smallest safe reproduction. Distinguish a failure of
a documented boundary from the expected host access of explicitly approved
programs. Do not test against other people's systems or data.
