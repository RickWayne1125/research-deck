#!/usr/bin/env python3
"""A stand-in for the Coder CLI (`coder --global-config <folder> whoami|login|ssh`), for tests. Standard library only.

It behaves as Coder v2.35's CLI does with --global-config (file storage): the session is <folder>/session (mode 0600)
and the deployment <folder>/url. `login <url>` refuses a CODER_SESSION_TOKEN in the environment, says where the token
page is, reads the token from its prompt on stdin (GOOD is accepted, anything else is "not a valid token", then EOF
fails), and writes the session. `whoami -o json` answers for a good session, else prints the CLI's sign-out message.
`ssh --stdio <host>` fails the same way when signed out. Every call is appended to <folder>/calls.jsonl (argv and PATH)
so tests can check what the CLI was given.
"""
import json
import os
import sys
from pathlib import Path

GOOD = "good-token"
SIGNED_OUT = ("error: You are signed out or your session has expired. Please sign in again to continue.\n"
              "Suggestion: Try logging in using 'coder login'.\n")


def main() -> int:
    args = sys.argv[1:]
    if args == ["--version"]:
        print("Coder v2.35.3 [stand-in]")
        return 0
    folder = Path(args[args.index("--global-config") + 1]) if "--global-config" in args else Path.home() / ".coder-stand-in"
    rest = [a for i, a in enumerate(args) if a != "--global-config" and (i == 0 or args[i - 1] != "--global-config")]
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "path": os.environ.get("PATH", "")}) + "\n")
    session = (folder / "session").read_text().strip() if (folder / "session").exists() else ""
    url = (folder / "url").read_text().strip() if (folder / "url").exists() else ""
    cmd = rest[0] if rest else ""
    if cmd == "whoami":
        if session != GOOD:
            sys.stderr.write(SIGNED_OUT)
            return 1
        print(json.dumps([{"url": url, "username": "tester", "user_id": "u-1", "organization_ids": [], "roles": {}}]))
        return 0
    if cmd == "login":
        if os.environ.get("CODER_SESSION_TOKEN"):
            print("To log in, unset the environment variable and re-run this command:\n\n\tunset CODER_SESSION_TOKEN")
            return 1
        target = rest[1].rstrip("/") if len(rest) > 1 else url
        print(f"Open the following in your browser:\n\n\t{target}/cli-auth\n")
        for line in sys.stdin:
            sys.stdout.write("> Paste your token here: ")
            if line.strip() == GOOD:
                (folder / "session").write_text(GOOD)
                os.chmod(folder / "session", 0o600)
                (folder / "url").write_text(target)
                print("Welcome to Coder, tester! You're authenticated.")
                return 0
            print("That's not a valid token!")
        sys.stderr.write("error: paste token prompt: EOF\n")
        return 1
    if cmd == "ssh":
        if session != GOOD:
            sys.stderr.write('Encountered an error running "coder ssh", see "coder ssh --help" for more information\n' + SIGNED_OUT)
            return 1
        return 0
    sys.stderr.write(f"stand-in: no {cmd!r}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
