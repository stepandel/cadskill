#!/bin/sh
# Installs CadSkill: the `cadskill` command and its Claude or Codex skill.
#
#   curl -LsSf https://raw.githubusercontent.com/stepandel/cadskill/main/install.sh | sh
#
# Options after `sh -s --` go to `cadskill install`, for example:
#
#   curl -LsSf https://raw.githubusercontent.com/stepandel/cadskill/main/install.sh | sh -s -- --desktop
#   curl -LsSf https://raw.githubusercontent.com/stepandel/cadskill/main/install.sh | sh -s -- --agent codex
#
# Run it again to update. It uses uv (https://docs.astral.sh/uv/) to fetch Python
# and the CAD libraries into a folder of their own, and installs uv first if it
# is missing. Set CADSKILL_PACKAGE to install something other than the latest
# release from PyPI: a version ("cadskill==0.1.1"), a wheel, or a git URL.
set -eu

say() { printf '%s\n' "$*"; }
fail() { printf 'cadskill installer: %s\n' "$*" >&2; exit 1; }

find_uv() {
    for candidate in "$(command -v uv 2>/dev/null || true)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

main() {
    case "$(uname -s)" in
        Darwin | Linux) ;;
        *) fail "only macOS and Linux are supported for now." ;;
    esac
    command -v curl >/dev/null 2>&1 || fail "curl is needed but was not found."

    if ! uv=$(find_uv); then
        say "Installing uv, which fetches Python and the CAD libraries for CadSkill..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        uv=$(find_uv) || fail "uv was installed but could not be found. Open a new terminal and run this again."
    fi

    package="${CADSKILL_PACKAGE:-cadskill}"
    bin=$("$uv" tool dir --bin)

    # A background process left running from an earlier install would keep serving the old code.
    if [ -x "$bin/cadskill" ]; then
        "$bin/cadskill" stop >/dev/null 2>&1 || true
    fi
    # Before it was on PyPI, CadSkill was installed from a copy of the repository as `cadskill-mcp`.
    if "$uv" tool list 2>/dev/null | grep -q '^cadskill-mcp '; then
        say "Removing the earlier install from a copy of the repository (cadskill-mcp)..."
        "$uv" tool uninstall cadskill-mcp
    fi

    say "Installing CadSkill (about 1.3 GB the first time: CadQuery, OpenCASCADE and VTK)..."
    # Python 3.12 is what server/pyproject.toml requires. Naming it lets a rerun keep the existing
    # environment; without it uv starts from the default Python and rebuilds everything.
    "$uv" tool install --force --upgrade --python 3.12 "$package"

    # Run the new command directly: this shell's PATH may not have uv's tool folder on it yet.
    PATH="$bin:$PATH" "$bin/cadskill" install "$@"

    case ":${PATH}:" in
        *":$bin:"*) ;;
        *)
            "$uv" tool update-shell >/dev/null 2>&1 || true
            say ""
            say "Open a new terminal so that \`cadskill\` is on your PATH ($bin)."
            ;;
    esac
}

main "$@"
