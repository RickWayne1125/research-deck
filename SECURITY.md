# Security

Research Deck runs on your machine, listens on 127.0.0.1 only and drives AI agents inside your project folders, so
problems that let a page, another program or an agent do more than it should matter most: reading or writing outside
a project's `.research/` folder, getting past the origin and CSRF checks, an agent acting with the researcher's
permissions, or anything reaching the network or a credential.

## Reporting

Please report a security problem privately: on the repository's **Security** tab, choose **Report a vulnerability**.
Do not open a public issue. Say what an attacker could do, how to reproduce it, and which version (commit) you used.
You will get an answer within a week.

## Supported versions

Fixes go into the latest version on `main`.
