# Security policy

## Supported versions

Security fixes are made for the latest released minor version (see [`CHANGELOG.md`](CHANGELOG.md)).
Older versions are not patched; update with `hermes plugins update pixel-hq` and restart the gateway.

| Version | Supported |
|---|---|
| 1.3.x | Yes |
| < 1.3 | No |

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
[GitHub's private vulnerability reporting](https://github.com/W4-NERF/pixel-hq/security/advisories/new)
(*Security → Report a vulnerability* in this repository).

Include the Pixel HQ and Hermes versions, the platform, the steps to reproduce and the impact you expect.
Leave out real tokens, private paths and bot data; synthetic examples are enough. You can expect a first
answer within a week; fixes are released as a patch version and noted in the changelog.

## Scope

Pixel HQ runs inside the Hermes gateway and the Hermes Desktop app. Relevant reports include, for example:

- escaping problems that let bot, card, comment or SOUL text run script in the Pixel HQ page;
- messages from the sandboxed page that make the Desktop bridge call anything beyond its fixed operations;
- path handling that reads or writes outside the documented files (see
  [What it reads and writes](README.md#what-it-reads-and-writes-disclosure));
- Kanban actions, reviews, roster or SOUL writes that happen without the documented confirmation.

Vulnerabilities in Hermes itself belong to the [Hermes Agent](https://github.com/NousResearch/hermes-agent) project.
