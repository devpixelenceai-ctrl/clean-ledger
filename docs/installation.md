# Installation guide

This guide covers everything you need to install Clean Ledger in Claude Code, from a computer with nothing installed through to a working, verified plugin. It also covers team setup, updating, removing, and fixing install problems.

The install commands were tested against this public repository: adding the marketplace, installing (version 1.4.0), the Guard hook blocking a push, uninstalling, and removing the marketplace. Details about installing Claude Code itself come from Anthropic's official documentation, linked in each section.

## Checklist

| # | Step | Needed? |
|---|---|---|
| 1 | [Check your account and operating system](#1-check-your-account-and-operating-system) | Yes |
| 2 | [Install Claude Code](#2-install-claude-code) | Yes |
| 3 | [Sign in](#3-sign-in) | Yes |
| 4 | [Install Git, Python 3 and Node.js](#4-install-git-python-3-and-nodejs) | Yes |
| 5 | [Install the analysis tools](#5-install-the-analysis-tools) | Yes (Semgrep is optional) |
| 6 | [Install the Clean Ledger plugin](#6-install-the-clean-ledger-plugin) | Yes |
| 7 | [Verify the installation](#7-verify-the-installation) | Strongly recommended |
| 8 | [Set it up for a team](#8-optional-set-it-up-for-a-team) | Optional |
| 9 | [Get the settings templates for unattended runs](#9-optional-get-the-settings-templates) | Optional |
| 10 | [Update, disable or uninstall](#10-update-disable-or-uninstall) | Later |
| 11 | [Fix install problems](#11-troubleshooting-the-installation) | If needed |

## What it costs

- **The plugin is free** (MIT licence), and so are the analysis tools and the CI gate.
- **Running Clean Ledger uses Claude.** Every run, including `/clean-ledger:status`, is processed by Claude Code. That counts against your Claude plan or API account like any other Claude Code use.

## 1. Check your account and operating system

**Account.** You need one that includes Claude Code:
- Claude **Pro** or **Max**;
- Claude for **Teams** or **Enterprise**;
- a Claude **Console** (API) account.

The free claude.ai plan does not include Claude Code. ([Authentication](https://code.claude.com/docs/en/authentication))

**Operating system:**

| System | Supported for Clean Ledger |
|---|---|
| macOS 13 or later | Yes (tested) |
| Linux: Ubuntu 20.04+, Debian 10+ | Yes (tested in containers) |
| Windows 10 1809+ **with WSL** | Yes. Install and run everything **inside WSL**, and follow the Linux instructions there |
| Windows without WSL | Not tested and not recommended. The Guard hook runs `python3`, which is often missing on native Windows, and Semgrep needs WSL |

## 2. Install Claude Code

Choose one method. ([Setup](https://code.claude.com/docs/en/setup))

**Native installer (recommended; updates itself):**

```bash
# macOS, Linux and WSL
curl -fsSL https://claude.ai/install.sh | bash
```

**Homebrew (macOS):**

```bash
brew install --cask claude-code      # update later with: brew upgrade claude-code
```

**npm** (needs Node.js 22 or later; never use `sudo`):

```bash
npm install -g @anthropic-ai/claude-code
```

Check the installation:

```bash
claude --version
claude doctor
```

## 3. Sign in

```bash
claude
```

Follow the browser prompt. Inside a session you can also use `/login`, and `/logout` to sign out. ([Authentication](https://code.claude.com/docs/en/authentication))

## 4. Install Git, Python 3 and Node.js

Clean Ledger needs:
- **Git**;
- **Python 3.9 or later**, available as **`python3`**;
- **Node.js 18 or later**, for jscpd. Use 22 or later if you installed Claude Code with npm.

**macOS** (with [Homebrew](https://brew.sh)):

```bash
brew install git python node
```

**Ubuntu, Debian or WSL:**

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip
# Node.js: use your preferred method, e.g. https://nodejs.org or nvm
```

Check all three. Every command must work, and `python3` must be found **by that exact name**, because the Guard hook calls it:

```bash
git --version
python3 --version      # 3.9 or later
node --version         # 18 or later
```

## 5. Install the analysis tools

Clean Ledger measures your code with three free tools:

| Tool | What it measures | Required |
|---|---|---|
| lizard | Complexity of each function | Yes |
| jscpd | Duplicated code | Yes |
| Semgrep (Community Edition) | Security and code-smell findings | Optional |

**Simplest install:**

```bash
pip install lizard semgrep
npm install -g jscpd
```

**Recommended: a user-level install** that touches no system folders:

```bash
python3 -m venv ~/.clean-ledger-tools
~/.clean-ledger-tools/bin/pip install lizard semgrep
npm install --prefix ~/.clean-ledger-tools jscpd
```

If you used the user-level install, either add the tool folders to your `PATH`, for example in `~/.zshrc` or `~/.bashrc`:

```bash
export PATH="$HOME/.clean-ledger-tools/bin:$HOME/.clean-ledger-tools/node_modules/.bin:$PATH"
```

…or leave `PATH` alone and tell Clean Ledger where the tools are when a run starts. Phase 0 passes the folders to `ledger.py init --tool-dir`.

Check:

```bash
lizard --version
jscpd --version
semgrep --version      # optional
```

## 6. Install the Clean Ledger plugin

Choose **A** (inside Claude Code) or **B** (from your terminal). They do the same thing.

### A. Inside Claude Code

1. Start Claude Code in any folder:
   ```bash
   claude
   ```
2. Add this repository as a plugin marketplace:
   ```
   /plugin marketplace add devpixelenceai-ctrl/clean-ledger
   ```
   You should see `Successfully added marketplace: clean-ledger-marketplace`.
3. Install the plugin:
   ```
   /plugin install clean-ledger@clean-ledger-marketplace
   ```
   A details pane opens. Read the trust warning and choose where to install. See "Which scope?" below.
4. If Claude Code says `Run /reload-plugins to apply`, run:
   ```
   /reload-plugins
   ```

You can do the same through the menu: type `/plugin`, open **Marketplaces** to add the marketplace, then **Discover** to install.

### B. From your terminal

```bash
claude plugin marketplace add devpixelenceai-ctrl/clean-ledger
claude plugin install clean-ledger@clean-ledger-marketplace
```

Both commands take `--scope user|project|local`; the default is `user`. Restart any running Claude Code session, or run `/reload-plugins` in it.

### Which scope?

| Scope | Where it is saved | Who gets the plugin |
|---|---|---|
| `user` (default) | `~/.claude/settings.json` | You, in every project on this computer |
| `project` | `.claude/settings.json` in the repository (commit it) | Everyone who works in that repository. See [step 8](#8-optional-set-it-up-for-a-team) |
| `local` | `.claude/settings.local.json` in the repository (not committed) | Only you, only in that repository |

To try Clean Ledger on one repository first, run the terminal commands **inside that repository** with `--scope local`.

### A word on trust

The plugin includes a hook, the Guard, that runs `python3 hooks/guard.py` with **your user privileges** before every command Claude Code runs. It only blocks commands; it never runs anything else. Plugins can do anything a hook can, though, so read [hooks/guard.py](../hooks/guard.py) and [SECURITY.md](../SECURITY.md) before installing it on an important machine.

## 7. Verify the installation

Run each check. This doesn't use any Claude usage.

1. **The plugin is installed and enabled:**
   ```bash
   claude plugin list
   ```
   Look for `clean-ledger@clean-ledger-marketplace` with `Status: ✔ enabled` and the latest version (see the [changelog](../CHANGELOG.md)).
2. **Its parts are present.** In recent Claude Code versions:
   ```bash
   claude plugin details clean-ledger
   ```
   If your version says `unknown command 'details'`, open `/plugin` → **Installed** → **clean-ledger** in Claude Code instead. The component list should include:
   - the commands `run`, `status` and `review`;
   - the skill `clean-ledger`;
   - the agent `ledger-auditor`;
   - a `PreToolUse` hook.
3. **The commands appear.** In Claude Code, type `/clean-ledger` and you should see `/clean-ledger:run`, `/clean-ledger:status` and `/clean-ledger:review`.
4. **The Guard hook is active.** In Claude Code, run `/hooks`, choose **PreToolUse**, and look for an entry from the **plugin** source running `python3 ".../hooks/guard.py"`.
5. **The tools are found.** Re-run the version checks from steps 4 and 5.

You are ready. Continue with [Getting started](getting-started.md), step 4.

## 8. (Optional) Set it up for a team

To have everyone who works on a repository use Clean Ledger, commit this as `.claude/settings.json` in that repository, or merge it into the existing file:

```json
{
  "extraKnownMarketplaces": {
    "clean-ledger-marketplace": {
      "source": { "source": "github", "repo": "devpixelenceai-ctrl/clean-ledger" }
    }
  },
  "enabledPlugins": {
    "clean-ledger@clean-ledger-marketplace": true
  }
}
```

The quickest way to create it is to run this inside the repository, then commit `.claude/settings.json`:

```bash
claude plugin marketplace add devpixelenceai-ctrl/clean-ledger --scope project
claude plugin install clean-ledger@clean-ledger-marketplace --scope project
```

**What teammates need to do:**
1. Open the repository in Claude Code and **accept the workspace trust prompt**. Until a folder is trusted, its marketplace settings are ignored without any message.
2. If the plugin does not appear, run `/plugin`, check the **Errors** tab, and install it:
   ```bash
   claude plugin install clean-ledger@clean-ledger-marketplace --scope project
   ```
3. They still need the tools from steps 4 and 5 on their own computer.

## 9. (Optional) Get the settings templates

For runs without permission prompts, Clean Ledger ships two settings templates. Copy one into the repository you want to clean, and keep it out of git:

| Template | What it does |
|---|---|
| `settings.json` | Allow-list: common commands run without prompting; dangerous ones are denied |
| `settings.sandboxed.json` | The allow-list **plus** Claude Code's Bash sandbox: writes stay in the repository, network access is limited, credential folders can't be read. Recommended for unattended runs |

```bash
mkdir -p .claude
curl -fsSL https://raw.githubusercontent.com/devpixelenceai-ctrl/clean-ledger/main/skills/clean-ledger/assets/settings.sandboxed.json \
  -o .claude/settings.local.json
echo ".claude/settings.local.json" >> .git/info/exclude
```

[Getting started](getting-started.md), step 5, explains the options. [Safety](safety.md) explains what each layer protects.

## 10. Update, disable or uninstall

Third-party marketplaces **do not update automatically** unless you switch it on (`/plugin` → **Marketplaces** → this marketplace).

| To | Inside Claude Code | From the terminal |
|---|---|---|
| Update | `/plugin` → **Marketplaces** → `clean-ledger-marketplace` → **Update marketplace**, then `/reload-plugins` | `claude plugin marketplace update clean-ledger-marketplace` then `claude plugin update clean-ledger@clean-ledger-marketplace` |
| Disable for now | `/plugin` → **Installed** → select it → **Disable** | `claude plugin disable clean-ledger@clean-ledger-marketplace --scope <scope>` |
| Uninstall | `/plugin` → **Installed** → select it → **Uninstall** | `claude plugin uninstall clean-ledger@clean-ledger-marketplace --scope <scope>` |
| Remove the marketplace | `/plugin marketplace remove clean-ledger-marketplace` | `claude plugin marketplace remove clean-ledger-marketplace` (no `--scope`; it also uninstalls its plugins) |

Uninstalling the plugin does not touch repositories you already ran it on. Their `clean-ledger` branches, `.ledger/` folders and reports stay until you delete them.

## 11. Troubleshooting the installation

| Problem | Fix |
|---|---|
| `claude: command not found` | Open a new terminal, or follow the PATH hint the installer printed. Then run `claude doctor` |
| `marketplace add` fails to clone | Check your network, and that `git` works: `git ls-remote https://github.com/devpixelenceai-ctrl/clean-ledger`. The repository is public, so no sign-in is needed |
| "is blocked by enterprise policy" or "is not in the allowed marketplace list" | Your organization restricts plugins. Run `/status` and look for "Enterprise managed settings". Ask your admin to allow `{"source": "github", "repo": "devpixelenceai-ctrl/clean-ledger"}` in `strictKnownMarketplaces`. Hooks can also be disabled by `allowManagedHooksOnly` |
| `claude plugin list` shows an older version | Update the marketplace and the plugin (step 10). If several folders have their own installs, the list can show another folder's entry first; check `/plugin` → **Installed** (or `claude plugin details clean-ledger` in recent versions) |
| `/clean-ledger:...` commands don't appear | Run `/reload-plugins`, or restart Claude Code. Check `/plugin` → **Errors** |
| The Guard hook isn't listed in `/hooks` | Check that `python3 --version` works in the same terminal. On Windows, use WSL. Make sure your organization hasn't set `allowManagedHooksOnly` |
| Team members don't get the plugin | They must accept the workspace trust prompt for the repository, then install with `--scope project` (step 8) |
| lizard, jscpd or Semgrep "not found" during a run | Add their folders to `PATH`, or pass them with `--tool-dir`. See [Troubleshooting](troubleshooting.md) |

Still stuck? Open an issue on GitHub. For anything security-related, use the private process in [SECURITY.md](../SECURITY.md) instead.
